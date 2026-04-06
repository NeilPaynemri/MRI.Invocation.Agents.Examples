"""
LangGraph calculator agent with AG-UI protocol event streaming.

Runs the same LangGraph workflow as invoketest1_mcp_approval (plan → llm → tools
with interrupt_before for approval) but translates the LangGraph stream into
AG-UI protocol events (https://docs.ag-ui.com).

AG-UI event flow for a typical tool-calling run:

    RUN_STARTED
    STEP_STARTED (plan_node)
    TEXT_MESSAGE_START / TEXT_MESSAGE_CONTENT* / TEXT_MESSAGE_END
    STEP_FINISHED (plan_node)
    STEP_STARTED (llm_call)
    TOOL_CALL_START / TOOL_CALL_ARGS* / TOOL_CALL_END
    CUSTOM (approval_required)          ← graph interrupt
    RUN_FINISHED
    --- client sends approve=true ---
    RUN_STARTED
    STEP_STARTED (tools)
    TOOL_CALL_RESULT
    STEP_FINISHED (tools)
    STEP_STARTED (llm_call)
    TEXT_MESSAGE_START / TEXT_MESSAGE_CONTENT* / TEXT_MESSAGE_END
    STEP_FINISHED (llm_call)
    RUN_FINISHED

Local usage:
    python main.py

    curl -N -X POST http://localhost:8088/invocations \\
         -H 'Content-Type: application/json' \\
         -d '{"message": "What is (12 + 8) * 3?"}'
"""

import asyncio
import json
import logging
import sys
import time
import uuid
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from azure.ai.agentserver.core import AgentHost
from azure.ai.agentserver.invocations import InvocationHandler

from langchain_core.messages import AIMessageChunk, AIMessage, ToolMessage, HumanMessage
from langchain_core.messages import ToolMessage as LCToolMessage

from graph import build_graph, init_mcp_tools

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("azure.ai.agentserver.user_agent")

# ---------------------------------------------------------------------------
# Graph instance (lazily initialized on first request to stay on the
# server's event loop so MCP async sessions work correctly)
# ---------------------------------------------------------------------------
_graph = None


async def get_graph():
    global _graph
    if _graph is None:
        logger.info("Initializing MCP tools and building graph...")
        await init_mcp_tools()
        _graph = build_graph()
        logger.info("Graph ready.")
    return _graph

# ---------------------------------------------------------------------------
# SDK server + invocations handler
# ---------------------------------------------------------------------------
server = AgentHost()
invocations = InvocationHandler(server)

# ---------------------------------------------------------------------------
# In-memory store for completed invocation results (for GET polling)
# ---------------------------------------------------------------------------
_results: dict[str, dict[str, Any]] = {}
_cancel_events: dict[str, asyncio.Event] = {}


# ---------------------------------------------------------------------------
# AG-UI SSE helper
# ---------------------------------------------------------------------------


def agui(event_type: str, **fields) -> str:
    """Format one AG-UI event as an SSE data line.

    AG-UI events use ``type`` as the discriminator, e.g.:
        data: {"type":"RUN_STARTED","threadId":"...","runId":"..."}
    """
    return f"data: {json.dumps({'type': event_type, **fields})}\n\n"


# ---------------------------------------------------------------------------
# Route handlers (wired via SDK decorators)
# ---------------------------------------------------------------------------


@invocations.invoke_handler
async def handle_invoke(request: Request) -> Response:
    """POST /invocations — run the graph and stream AG-UI events back."""
    invocation_id = request.state.invocation_id
    session_id = request.state.session_id

    data = await request.json()

    message = data.get("message", "")
    approve = data.get("approve")  # True/False/None — for tool approval flow
    if not message and approve is None:
        return JSONResponse(
            {"error": "Missing required field 'message' or 'approve'"}, status_code=400
        )

    user_id = data.get("user_id", "")

    # Use session_id as the LangGraph thread for multi-turn
    thread_id = data.get("thread_id") or session_id or invocation_id
    run_id = str(uuid.uuid4())

    logger.info(
        "POST /invocations  inv_id=%s  session=%s  thread=%s  run=%s  user=%r  "
        "message=%r  approve=%s",
        invocation_id, session_id, thread_id, run_id,
        user_id, message[:80] if message else "", approve,
    )

    # Set up cancellation
    cancel_event = asyncio.Event()
    _cancel_events[invocation_id] = cancel_event
    _results[invocation_id] = {"status": "in_progress", "result": None}

    config = {"configurable": {"thread_id": thread_id}}
    collected_content: list[str] = []

    # ── AG-UI translation state ───────────────────────────────────────
    current_msg_id: str | None = None      # open TEXT_MESSAGE
    current_node: str | None = None        # open STEP
    active_tool_calls: dict[int, str] = {} # chunk index → toolCallId

    async def sse_stream():
        nonlocal current_msg_id, current_node, active_tool_calls

        # ── Lifecycle: run begins ─────────────────────────────────────
        yield agui("RUN_STARTED", threadId=thread_id, runId=run_id)

        try:
            g = await get_graph()

            # Determine graph input: new message vs approval resume
            if approve is not None:
                logger.info("Approval response: approve=%s thread=%s", approve, thread_id)
                if not approve:
                    # Denial: inject ToolMessage for each pending tool call
                    state = await g.aget_state(config)
                    last_msg = state.values["messages"][-1]
                    deny_msgs = [
                        LCToolMessage(content="Tool call denied by user.", tool_call_id=tc["id"])
                        for tc in last_msg.tool_calls
                    ]
                    await g.aupdate_state(config, {"messages": deny_msgs}, as_node="tools")
                graph_input = None  # resume from interrupt
            else:
                graph_input = {"messages": [HumanMessage(content=message)], "user_id": user_id}
                logger.info("graph_input user_id=%r, message=%r", user_id, message[:80])

            async for chunk in g.astream(
                graph_input,
                config=config,
                stream_mode=["messages", "updates", "custom"],
                version="v2",
            ):
                if cancel_event.is_set():
                    yield agui("RUN_ERROR", message="Cancelled by user", code="cancelled")
                    _results[invocation_id] = {"status": "cancelled", "result": None}
                    return

                chunk_type = chunk[0] if isinstance(chunk, tuple) else chunk.get("type", "")

                # ══════════════════════════════════════════════════════
                # custom stream — get_stream_writer() events from nodes
                # ══════════════════════════════════════════════════════
                if chunk_type == "custom":
                    custom_data = chunk[1] if isinstance(chunk, tuple) else chunk.get("data")
                    yield agui("CUSTOM",
                               name="node_status",
                               value=custom_data if isinstance(custom_data, dict) else {"raw": custom_data})
                    continue

                # ══════════════════════════════════════════════════════
                # messages stream — token-level chunks
                # ══════════════════════════════════════════════════════
                if chunk_type == "messages":
                    msg_data = chunk[1] if isinstance(chunk, tuple) else chunk.get("data")
                    if not (isinstance(msg_data, tuple) and len(msg_data) == 2):
                        continue
                    msg, metadata = msg_data
                    node = metadata.get("langgraph_node", "")

                    # ── Step tracking (node transitions) ──────────────
                    if node and node != current_node:
                        if current_node:
                            yield agui("STEP_FINISHED", stepName=current_node)
                        current_node = node
                        yield agui("STEP_STARTED", stepName=node)

                    if not isinstance(msg, AIMessageChunk):
                        continue

                    tool_chunks = getattr(msg, "tool_call_chunks", None) or []

                    # ── Text content (no tool call chunks) ────────────
                    if msg.content and not tool_chunks:
                        if current_msg_id is None:
                            current_msg_id = msg.id or str(uuid.uuid4())
                            yield agui("TEXT_MESSAGE_START",
                                       messageId=current_msg_id, role="assistant")
                        yield agui("TEXT_MESSAGE_CONTENT",
                                   messageId=current_msg_id, delta=msg.content)
                        collected_content.append(msg.content)

                    # ── Tool call chunks (streaming args) ─────────────
                    for tc in tool_chunks:
                        idx = tc.get("index", 0)

                        if tc.get("name"):
                            # First chunk of a new tool call — has name + id
                            tc_id = tc.get("id") or str(uuid.uuid4())
                            active_tool_calls[idx] = tc_id
                            yield agui("TOOL_CALL_START",
                                       toolCallId=tc_id,
                                       toolCallName=tc["name"])

                        if tc.get("args"):
                            tc_id = active_tool_calls.get(idx, tc.get("id", ""))
                            if tc_id:
                                yield agui("TOOL_CALL_ARGS",
                                           toolCallId=tc_id, delta=tc["args"])

                # ══════════════════════════════════════════════════════
                # updates stream — full messages per node completion
                # ══════════════════════════════════════════════════════
                elif chunk_type == "updates":
                    update_data = chunk[1] if isinstance(chunk, tuple) else chunk.get("data")
                    if not isinstance(update_data, dict):
                        continue

                    for node_name, output in update_data.items():
                        if not isinstance(output, dict):
                            continue  # skip __interrupt__ tuples etc.

                        for msg in output.get("messages", []):
                            # Full AIMessage — close open text + tool calls
                            if isinstance(msg, AIMessage):
                                if current_msg_id:
                                    yield agui("TEXT_MESSAGE_END",
                                               messageId=current_msg_id)
                                    current_msg_id = None

                                # Close each streaming tool call
                                if msg.tool_calls:
                                    for tc in msg.tool_calls:
                                        yield agui("TOOL_CALL_END",
                                                   toolCallId=tc["id"])
                                    active_tool_calls.clear()

                            # ToolMessage — tool execution result
                            if isinstance(msg, ToolMessage):
                                yield agui("TOOL_CALL_RESULT",
                                           toolCallId=msg.tool_call_id,
                                           content=str(msg.content),
                                           role="tool")

        except Exception as e:
            logger.exception("Error during graph execution")
            yield agui("RUN_ERROR", message=str(e), code="internal_error")
            _results[invocation_id] = {"status": "failed", "error": str(e)}
            return

        # ── Close any remaining open step ─────────────────────────────
        if current_node:
            yield agui("STEP_FINISHED", stepName=current_node)

        # ── Check for interrupt (pending tool approval) ───────────────
        state = await g.aget_state(config)
        if state.next:
            last_msg = state.values["messages"][-1]
            pending_tool_calls = [
                {"id": tc["id"], "name": tc["name"], "args": tc["args"]}
                for tc in getattr(last_msg, "tool_calls", [])
            ]
            logger.info("Interrupt: awaiting approval for %s",
                        [tc["name"] for tc in pending_tool_calls])

            # AG-UI CUSTOM event for approval (no native interrupt event yet)
            yield agui("CUSTOM",
                        name="approval_required",
                        value={"tool_calls": pending_tool_calls,
                               "thread_id": thread_id})

            _results[invocation_id] = {"status": "awaiting_approval", "result": None}
            _cancel_events.pop(invocation_id, None)

            # Close the run — client will POST again with approve=true/false
            yield agui("RUN_FINISHED", threadId=thread_id, runId=run_id)
            return

        # ── Store final result for GET polling ────────────────────────
        final_text = "".join(collected_content)
        _results[invocation_id] = {
            "status": "completed",
            "result": {
                "reply": final_text,
                "invocation_id": invocation_id,
                "thread_id": thread_id,
                "timestamp": int(time.time()),
            },
        }
        _cancel_events.pop(invocation_id, None)

        # ── Lifecycle: run ends ───────────────────────────────────────
        yield agui("RUN_FINISHED", threadId=thread_id, runId=run_id)

    # Always stream — AG-UI is inherently an event stream protocol
    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@invocations.get_invocation_handler
async def handle_get_invocation(request: Request) -> Response:
    """GET /invocations/{id} — retrieve a previous invocation result."""
    invocation_id = request.state.invocation_id
    logger.info("GET /invocations/%s", invocation_id)

    if invocation_id in _results:
        return JSONResponse(_results[invocation_id])

    return JSONResponse(
        {"error": "not found", "invocation_id": invocation_id},
        status_code=404,
    )


@invocations.cancel_invocation_handler
async def handle_cancel_invocation(request: Request) -> Response:
    """POST /invocations/{id}/cancel — cancel an in-progress invocation."""
    invocation_id = request.state.invocation_id
    logger.info("POST /invocations/%s/cancel", invocation_id)

    cancel_event = _cancel_events.get(invocation_id)
    if cancel_event:
        cancel_event.set()
        return JSONResponse({"invocation_id": invocation_id, "status": "cancelling"})

    if invocation_id in _results:
        _results[invocation_id]["status"] = "cancelled"
        return JSONResponse({"invocation_id": invocation_id, "status": "cancelled"})

    return JSONResponse(
        {"error": "not found", "invocation_id": invocation_id},
        status_code=404,
    )

if __name__ == "__main__":
    logger.info("=== invoketest1 calculator agent (AG-UI) starting ===")
    sys.stdout.flush()
    server.run()
