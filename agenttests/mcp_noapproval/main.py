"""
LangGraph calculator agent exposed via the Foundry Invocations protocol (v0.0.1).

Uses the azure-ai-agentserver-invocations SDK for route wiring and health
endpoints. Streams LangGraph output as SSE events.

Local usage:
    python main.py

    curl -N -X POST http://localhost:8088/invocations \
         -H 'Content-Type: application/json' \
         -d '{"message": "What is (12 + 8) * 3?"}'

    # Poll result (use the invocation_id from the SSE stream)
    curl http://localhost:8088/invocations/<invocation_id>

    # Cancel
    curl -X POST http://localhost:8088/invocations/<invocation_id>/cancel
"""

import asyncio
import json
import logging
import sys
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from azure.ai.agentserver.core import AgentHost
from azure.ai.agentserver.invocations import InvocationHandler

from langchain_core.messages import AIMessageChunk, AIMessage, ToolMessage, HumanMessage

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
# SSE serialization helpers
# ---------------------------------------------------------------------------


def _serialize_message_event(msg, metadata: dict) -> dict | None:
    """Convert a LangChain message chunk + metadata into a JSON-serializable SSE event."""
    node = metadata.get("langgraph_node", "")

    if isinstance(msg, AIMessageChunk):
        event = {
            "event": "message_chunk",
            "node": node,
            "content": msg.content or "",
            "tool_calls": [],
        }
        for tc in msg.tool_calls:
            event["tool_calls"].append({
                "id": tc.get("id", ""),
                "name": tc.get("name", ""),
                "args": tc.get("args", {}),
            })
        return event

    if isinstance(msg, ToolMessage):
        return {
            "event": "tool_result",
            "node": node,
            "content": str(msg.content),
            "tool_call_id": msg.tool_call_id,
        }

    if isinstance(msg, AIMessage):
        return {
            "event": "message",
            "node": node,
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.get("id", ""), "name": tc.get("name", ""), "args": tc.get("args", {})}
                for tc in (msg.tool_calls or [])
            ],
        }

    return {
        "event": "unknown_message",
        "node": node,
        "type": type(msg).__name__,
        "content": str(msg.content) if hasattr(msg, "content") else str(msg),
    }


def _serialize_update_event(data: dict) -> list[dict]:
    """Convert an updates-mode chunk into JSON-serializable SSE events."""
    events = []
    for node_name, state_delta in data.items():
        if not isinstance(state_delta, dict):
            continue  # skip __interrupt__ tuples etc.
        event = {"event": "node_update", "node": node_name}
        msgs = state_delta.get("messages", [])
        summaries = []
        for m in msgs:
            summary = {"type": type(m).__name__}
            if hasattr(m, "content") and m.content:
                summary["content_preview"] = str(m.content)[:200]
            if hasattr(m, "tool_calls") and m.tool_calls:
                summary["tool_calls"] = [
                    {"name": tc.get("name", ""), "args": tc.get("args", {})}
                    for tc in m.tool_calls
                ]
            if hasattr(m, "tool_call_id"):
                summary["tool_call_id"] = m.tool_call_id
            summaries.append(summary)
        event["messages"] = summaries
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# Route handlers (wired via SDK decorators)
# ---------------------------------------------------------------------------


@invocations.invoke_handler
async def handle_invoke(request: Request) -> Response:
    """POST /invocations — run the graph and stream SSE events back."""
    invocation_id = request.state.invocation_id
    session_id = request.state.session_id

    data = await request.json()

    message = data.get("message", "")
    if not message:
        return JSONResponse(
            {"error": "Missing required field 'message'"}, status_code=400
        )

    user_id = data.get("user_id", "")

    # Use session_id as the LangGraph thread for multi-turn
    thread_id = data.get("thread_id") or session_id or invocation_id

    logger.info(
        "POST /invocations  inv_id=%s  session=%s  thread=%s  user=%r  message=%r",
        invocation_id, session_id, thread_id, user_id, message[:80],
    )

    # Client can opt out of streaming
    stream = data.get("stream", True)

    # Set up cancellation
    cancel_event = asyncio.Event()
    _cancel_events[invocation_id] = cancel_event
    _results[invocation_id] = {"status": "in_progress", "result": None}

    config = {"configurable": {"thread_id": thread_id}}
    collected_content: list[str] = []
    total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    async def sse_stream():
        # Opening event with IDs
        yield f"data: {json.dumps({'event': 'session', 'invocation_id': invocation_id, 'thread_id': thread_id})}\n\n"

        try:
            g = await get_graph()
            graph_input = {"messages": [HumanMessage(content=message)], "user_id": user_id}
            logger.info("graph_input user_id=%r, message=%r", user_id, message[:80])

            async for chunk in g.astream(
                graph_input,
                config=config,
                stream_mode=["messages", "updates", "custom"],
                version="v2",
            ):
                if cancel_event.is_set():
                    yield f"data: {json.dumps({'event': 'cancelled', 'invocation_id': invocation_id})}\n\n"
                    _results[invocation_id] = {"status": "cancelled", "result": None}
                    return

                chunk_type = chunk.get("type", "") if isinstance(chunk, dict) else (chunk[0] if isinstance(chunk, tuple) else "")
                chunk_data = chunk.get("data") if isinstance(chunk, dict) else (chunk[1] if isinstance(chunk, tuple) else chunk)

                # ── custom stream — get_stream_writer() events ──
                if chunk_type == "custom":
                    yield f"data: {json.dumps({'event': 'custom', **(chunk_data if isinstance(chunk_data, dict) else {'raw': chunk_data})})}\n\n"
                    continue

                if chunk_type == "messages":
                    msg_data = chunk[1] if isinstance(chunk, tuple) else chunk.get("data")
                    if isinstance(msg_data, tuple) and len(msg_data) == 2:
                        msg, metadata = msg_data
                    else:
                        continue
                    # Track token usage from message metadata
                    usage = getattr(msg, "usage_metadata", None)
                    if usage:
                        total_usage["input_tokens"] += usage.get("input_tokens", 0)
                        total_usage["output_tokens"] += usage.get("output_tokens", 0)
                        total_usage["total_tokens"] += usage.get("total_tokens", 0)

                    event = _serialize_message_event(msg, metadata)
                    if event:
                        if event.get("content"):
                            collected_content.append(event["content"])
                        yield f"data: {json.dumps(event)}\n\n"

                elif chunk_type == "updates":
                    update_data = chunk_data
                    if isinstance(update_data, dict):
                        for event in _serialize_update_event(update_data):
                            yield f"data: {json.dumps(event)}\n\n"

        except Exception as e:
            logger.exception("Error during graph execution")
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
            _results[invocation_id] = {"status": "failed", "error": str(e)}
            return

        # Emit token usage summary
        if total_usage["total_tokens"] > 0:
            yield f"data: {json.dumps({'event': 'usage', **total_usage})}\n\n"

        # Store final result for GET polling
        final_text = "".join(collected_content)
        result = {
            "reply": final_text,
            "invocation_id": invocation_id,
            "thread_id": thread_id,
            "agent": "invoketest1-calculator",
            "protocol": "invocations/v0.0.1",
            "timestamp": int(time.time()),
            "usage": total_usage,
        }
        _results[invocation_id] = {"status": "completed", "result": result}

        yield f"data: {json.dumps({'event': 'done', 'invocation_id': invocation_id})}\n\n"

        # Clean up cancel event
        _cancel_events.pop(invocation_id, None)

    # ── Non-streaming path ────────────────────────────────────────────
    if not stream:
        collected = []
        ns_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        try:
            g = await get_graph()
            async for chunk in g.astream(
                {"messages": [HumanMessage(content=message)], "user_id": user_id},
                config=config,
                stream_mode=["messages", "updates", "custom"],
                version="v2",
            ):
                if cancel_event.is_set():
                    _results[invocation_id] = {"status": "cancelled", "result": None}
                    return JSONResponse({"status": "cancelled", "invocation_id": invocation_id})

                chunk_type = chunk.get("type", "") if isinstance(chunk, dict) else (chunk[0] if isinstance(chunk, tuple) else "")
                chunk_data = chunk.get("data") if isinstance(chunk, dict) else (chunk[1] if isinstance(chunk, tuple) else chunk)

                # Skip custom events in non-streaming
                if chunk_type == "custom":
                    continue

                if chunk_type == "messages":
                    msg_data = chunk_data
                    if isinstance(msg_data, tuple) and len(msg_data) == 2:
                        msg, _meta = msg_data
                        usage = getattr(msg, "usage_metadata", None)
                        if usage:
                            ns_usage["input_tokens"] += usage.get("input_tokens", 0)
                            ns_usage["output_tokens"] += usage.get("output_tokens", 0)
                            ns_usage["total_tokens"] += usage.get("total_tokens", 0)
                        if isinstance(msg, (AIMessageChunk, AIMessage)) and msg.content:
                            collected.append(msg.content)
        except Exception as e:
            logger.exception("Error during graph execution (non-streaming)")
            _results[invocation_id] = {"status": "failed", "error": str(e)}
            return JSONResponse({"status": "failed", "error": str(e)}, status_code=500)

        final_text = "".join(collected)
        result = {
            "reply": final_text,
            "invocation_id": invocation_id,
            "thread_id": thread_id,
            "agent": "invoketest1-calculator",
            "protocol": "invocations/v0.0.1",
            "timestamp": int(time.time()),
            "usage": ns_usage,
        }
        _results[invocation_id] = {"status": "completed", "result": result}
        _cancel_events.pop(invocation_id, None)
        return JSONResponse({"status": "completed", "result": result})

    # ── Streaming path ────────────────────────────────────────────────
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
    logger.info("=== invoketest1 calculator agent starting ===")
    sys.stdout.flush()
    server.run()
