"""
Streamlit UI for testing the invoketest1-mcp-calculator agent.

Supports both local and remote (deployed) invocations endpoints.
Streams SSE events and displays results in real time.
"""

import json
import re
import subprocess
import uuid
import streamlit as st
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ENDPOINT = "https://fa-ouwa1-ai.services.ai.azure.com/api/projects/fa-ouwa1-project"
AGENT_NAME = "invoketest1-mcp-noap-v2-custom-9b47"
API_VERSION = "2025-05-15-preview"
LOCAL_URL = "http://localhost:8088"


def get_azure_token():
    """Get an Azure access token via az CLI."""
    try:
        r = subprocess.run(
            [r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
             "account", "get-access-token",
             "--resource", "https://ai.azure.com",
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return r.stdout.strip()
    except Exception as e:
        st.error(f"Failed to get Azure token: {e}")
        return None


def invoke_local(message: str, thread_id: str, approve=None):
    """POST to local agent and stream SSE events."""
    url = f"{LOCAL_URL}/invocations"
    headers = {
        "Content-Type": "application/json",
        "x-agent-invocation-id": f"ui-{thread_id}",
        "x-agent-session-id": thread_id,
    }
    body = {"thread_id": thread_id, "user_id": "bob"}
    if approve is not None:
        body["approve"] = approve
    else:
        body["message"] = message

    with requests.post(url, json=body, headers=headers, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                yield line[6:]


def invoke_local_sync(message: str, thread_id: str) -> dict:
    """POST to local agent with stream=false, return JSON."""
    url = f"{LOCAL_URL}/invocations"
    headers = {
        "Content-Type": "application/json",
        "x-agent-invocation-id": f"ui-{thread_id}",
        "x-agent-session-id": thread_id,
    }
    body = {"message": message, "thread_id": thread_id, "user_id": "bob", "stream": False}
    resp = requests.post(url, json=body, headers=headers, timeout=120)
    resp.raise_for_status()
    return resp.json()


def invoke_remote(message: str, thread_id: str, token: str, approve=None):
    """POST to deployed agent via platform invocations gateway and stream SSE events."""
    url = (
        f"{ENDPOINT}/agents/{AGENT_NAME}/endpoint/protocols/invocations"
        f"?api-version={API_VERSION}&agent_session_id={thread_id}"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {"thread_id": thread_id, "user_id": "bob"}
    if approve is not None:
        body["approve"] = approve
    else:
        body["message"] = message

    with requests.post(url, json=body, headers=headers, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                yield line[6:]


def invoke_remote_sync(message: str, thread_id: str, token: str) -> dict:
    """POST to deployed agent with stream=false, return JSON."""
    url = (
        f"{ENDPOINT}/agents/{AGENT_NAME}/endpoint/protocols/invocations"
        f"?api-version={API_VERSION}&agent_session_id={thread_id}"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {"message": message, "thread_id": thread_id, "user_id": "bob", "stream": False}
    resp = requests.post(url, json=body, headers=headers, timeout=120)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------
st.set_page_config(page_title="MCP Calculator Agent", page_icon="🧮", layout="wide")
st.title("MCP Calculator Agent — Invocations Tester")

# Session ID management
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())[:8]
if "last_mode" not in st.session_state:
    st.session_state.last_mode = None

def _new_conversation():
    st.session_state.session_id = str(uuid.uuid4())[:8]
    st.session_state.messages = []
    st.session_state.pending_approval = None

# Sidebar
with st.sidebar:
    st.header("Settings")
    mode = st.radio("Target", ["Remote (Deployed)", "Local (localhost:8088)"])

    # Auto-new-session when switching modes
    if st.session_state.last_mode is not None and mode != st.session_state.last_mode:
        _new_conversation()
    st.session_state.last_mode = mode

    use_streaming = st.toggle("Streaming", value=True)
    thread_id = st.text_input("Session ID (for multi-turn)", value=st.session_state.session_id)
    st.session_state.session_id = thread_id  # sync manual edits back

    if st.button("🔄 New Conversation", use_container_width=True):
        _new_conversation()
        st.rerun()

    st.markdown("---")
    st.markdown(f"**Agent:** `{AGENT_NAME}`")
    st.markdown(f"**Protocol:** `invocations/v0.0.1`")
    if mode == "Remote (Deployed)":
        st.markdown(f"**Endpoint:** `{ENDPOINT}`")
    else:
        st.markdown(f"**URL:** `{LOCAL_URL}`")

# Chat history
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_approval" not in st.session_state:
    st.session_state.pending_approval = None  # {tool_calls: [...], thread_id: str}

# Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("thoughts"):
            with st.expander("💭 Agent thoughts", expanded=False):
                for t in msg["thoughts"]:
                    st.markdown(t)
        st.markdown(msg["content"])

# Chat input
if prompt := st.chat_input("Ask a math question (e.g. What is (12 + 8) * 3?)"):
    # Show user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Invoke agent
    with st.chat_message("assistant"):
        status_area = st.empty()

        status_area.info("⏳ Invoking agent...")

        # ── Non-streaming path ────────────────────────────────────
        if not use_streaming:
            try:
                if mode == "Local (localhost:8088)":
                    result = invoke_local_sync(prompt, thread_id)
                else:
                    token = get_azure_token()
                    if not token:
                        st.stop()
                    result = invoke_remote_sync(prompt, thread_id, token)

                reply = result.get("result", {}).get("reply", "") if "result" in result else result.get("reply", "")
                usage = result.get("result", {}).get("usage", {}) if "result" in result else result.get("usage", {})

                # Clean plan tags from reply
                clean_reply = re.sub(r"<plan>.*?</plan>\s*", "", reply, flags=re.DOTALL).strip() if reply else ""

                thoughts = []
                # Extract plan from reply if present
                plan_match = re.search(r"<plan>(.*?)</plan>", reply, re.DOTALL) if reply else None
                if plan_match:
                    thoughts.append(f"📋 **Plan**:\n{plan_match.group(1).strip()}")

                if usage and usage.get("total_tokens", 0) > 0:
                    thoughts.append(
                        f"📊 **Tokens**: {usage.get('input_tokens', 0)} in → "
                        f"{usage.get('output_tokens', 0)} out ({usage.get('total_tokens', 0)} total)"
                    )

                if thoughts:
                    with st.expander("💭 Agent thoughts", expanded=False):
                        for t in thoughts:
                            st.markdown(t)

                if clean_reply:
                    st.markdown(clean_reply)
                    st.session_state.messages.append({"role": "assistant", "content": clean_reply})

                with st.expander("🐛 Raw JSON response", expanded=False):
                    st.json(result)

                status_area.success("\u2705 Done!")

            except requests.exceptions.ConnectionError:
                status_area.error(
                    "\u274c Connection refused. Is the agent running?"
                    + (" Start it with `python main.py`" if "Local" in mode else "")
                )
            except requests.exceptions.HTTPError as e:
                status_area.error(f"\u274c HTTP Error: {e.response.status_code} \u2014 {e.response.text[:500]}")
            except Exception as e:
                status_area.error(f"\u274c Error: {e}")

        # ── Streaming path ────────────────────────────────────────
        else:
            # Layout: thoughts expander at top, then answer text, then debug
            thoughts_placeholder = st.empty()
            text_placeholder = st.empty()
            debug_placeholder = st.empty()

            try:
                if mode == "Local (localhost:8088)":
                    event_stream = invoke_local(prompt, thread_id)
                else:
                    token = get_azure_token()
                    if not token:
                        st.stop()
                    event_stream = invoke_remote(prompt, thread_id, token)

                all_events = []
                thoughts = []          # list of markdown strings for the expander
                answer_chunks = []     # only llm_call text content (final answer)
                pending_tools = {}     # tool_call_id -> {name, args}
                current_node = ""

                def _render_thoughts():
                    if thoughts:
                        with thoughts_placeholder.container():
                            with st.expander("💭 Agent thoughts", expanded=True):
                                for t in thoughts:
                                    st.markdown(t)

                for raw in event_stream:
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    all_events.append(event)
                    event_type = event.get("event", "")
                    node = event.get("node", current_node)

                    # ── session ──
                    if event_type == "session":
                        status_area.info(
                            f"⏳ Running... (inv: `{event.get('invocation_id', '?')}`, "
                            f"thread: `{event.get('thread_id', '?')}`)"
                        )

                    # ── message_chunk ──
                    elif event_type == "message_chunk":
                        current_node = node

                        # Tool call fragments from chunks — just register name/id,
                        # we show the complete call from node_update instead
                        for tc in event.get("tool_calls", []):
                            tc_name = tc.get("name", "")
                            tc_id = tc.get("id", "")
                            if tc_name and tc_id:
                                pending_tools[tc_id] = {"name": tc_name, "args": {}}

                        content = event.get("content", "")
                        if content:
                            if node == "plan_node":
                                # Plan text — don't show inline, accumulate for thoughts
                                pass  # handled by plan_node "message" event
                            elif node == "llm_call":
                                # Final answer text — stream to main area
                                answer_chunks.append(content)
                                clean = re.sub(r"<plan>.*?</plan>\s*", "", "".join(answer_chunks), flags=re.DOTALL)
                                text_placeholder.markdown(clean or "▌")

                    # ── message (complete node output) ──
                    elif event_type == "message":
                        current_node = node
                        content = event.get("content", "")

                        if node == "plan_node" and content:
                            # Extract plan from <plan> tags, or use raw content
                            plan_match = re.search(r"<plan>(.*?)</plan>", content, re.DOTALL)
                            if plan_match:
                                plan_text = plan_match.group(1).strip()
                            else:
                                plan_text = content.strip()
                            if plan_text:
                                thoughts.append(f"📋 **Plan**:\n{plan_text}")
                                _render_thoughts()

                        # Register tool calls from message events
                        for tc in event.get("tool_calls", []):
                            tc_name = tc.get("name", "")
                            tc_id = tc.get("id", "")
                            tc_args = tc.get("args", {})
                            if tc_name:
                                pending_tools[tc_id] = {"name": tc_name, "args": tc_args}

                    # ── node_update (complete node summary with full args) ──
                    elif event_type == "node_update":
                        current_node = node
                        status_area.info(f"⏳ Node: `{node}`...")

                        for msg_summary in event.get("messages", []):
                            # Tool calls with complete arguments
                            for tc in msg_summary.get("tool_calls", []):
                                tc_name = tc.get("name", "")
                                tc_args = tc.get("args", {})
                                if tc_name:
                                    args_str = ", ".join(f"{k}={v}" for k, v in tc_args.items())
                                    thoughts.append(f"⚡ **Calling** `{tc_name}({args_str})`")
                                    # Update pending_tools with complete args
                                    for tid, info in pending_tools.items():
                                        if info["name"] == tc_name and not info["args"]:
                                            info["args"] = tc_args
                                            break
                            _render_thoughts()

                    # ── tool_result ──
                    elif event_type == "tool_result":
                        tc_id = event.get("tool_call_id", "?")
                        result_val = event.get("content", "")
                        tool_info = pending_tools.get(tc_id, {})
                        tool_name = tool_info.get("name", tc_id)
                        thoughts.append(f"&ensp;&ensp;✅ `{tool_name}` → `{result_val}`")
                        _render_thoughts()

                    # ── custom (get_stream_writer events) ──
                    elif event_type == "custom":
                        status = event.get("status", "")
                        detail = event.get("detail", "")
                        icon = {"planning": "\U0001f504", "thinking": "\U0001f504", "executing_tools": "\U0001f504",
                                "plan_complete": "\u2705", "llm_done": "\u2705",
                                "tool_running": "\u2699\ufe0f", "tool_result": "\U0001f4e6"}.get(status, "\u2139\ufe0f")
                        thoughts.append(f"{icon} **{status}**: {detail}")
                        _render_thoughts()

                    # ── usage ──
                    elif event_type == "usage":
                        in_tok = event.get("input_tokens", 0)
                        out_tok = event.get("output_tokens", 0)
                        tot_tok = event.get("total_tokens", 0)
                        thoughts.append(
                            f"📊 **Tokens**: {in_tok} in → {out_tok} out ({tot_tok} total)"
                        )
                        _render_thoughts()

                    # ── done ──
                    elif event_type == "done":
                        status_area.success("✅ Done!")

                    elif event_type == "error":
                        status_area.error(f"❌ Error: {event.get('message', 'unknown')}")

                    elif event_type == "cancelled":
                        status_area.warning("⚠️ Cancelled")

                    # ── approval_required ──
                    elif event_type == "approval_required":
                        tool_calls = event.get("tool_calls", [])
                        approval_thread = event.get("thread_id", thread_id)
                        st.session_state.pending_approval = {
                            "tool_calls": tool_calls,
                            "thread_id": approval_thread,
                        }
                        # Show pending tools as a thought
                        for tc in tool_calls:
                            args_str = ", ".join(f"{k}={v}" for k, v in tc.get("args", {}).items())
                            thoughts.append(f"🔒 **Approval needed**: `{tc['name']}({args_str})`")
                        _render_thoughts()
                        status_area.warning("⏸️ Waiting for tool approval...")

                # Final render — clean answer
                final_answer = re.sub(r"<plan>.*?</plan>\s*", "", "".join(answer_chunks), flags=re.DOTALL).strip()
                if final_answer:
                    text_placeholder.markdown(final_answer)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": final_answer,
                        "thoughts": thoughts,
                    })
                elif not all_events:
                    status_area.warning("No events received — agent may not be running.")

                # Collapse thoughts expander now that we're done
                if thoughts:
                    with thoughts_placeholder.container():
                        with st.expander("💭 Agent thoughts", expanded=False):
                            for t in thoughts:
                                st.markdown(t)

                # Debug: raw SSE events
                with debug_placeholder.container():
                    with st.expander("🐛 Raw SSE events", expanded=False):
                        for evt in all_events:
                            st.json(evt)

            except requests.exceptions.ConnectionError:
                status_area.error(
                    "❌ Connection refused. Is the agent running?"
                    + (" Start it with `python main.py`" if "Local" in mode else "")
                )
            except requests.exceptions.HTTPError as e:
                status_area.error(f"❌ HTTP Error: {e.response.status_code} — {e.response.text[:500]}")
            except Exception as e:
                status_area.error(f"❌ Error: {e}")


# ---------------------------------------------------------------------------
# Tool Approval Section
# ---------------------------------------------------------------------------
def _handle_approval(approved: bool):
    """Send approval/denial to the agent and process the response."""
    pa = st.session_state.pending_approval
    if not pa:
        return

    approval_thread = pa["thread_id"]
    st.session_state.pending_approval = None

    action = "Approved" if approved else "Denied"
    st.session_state.messages.append({
        "role": "user",
        "content": f"🔑 Tool execution **{action.lower()}**",
    })

    with st.chat_message("assistant"):
        status_area = st.empty()
        thoughts_placeholder = st.empty()
        text_placeholder = st.empty()
        debug_placeholder = st.empty()

        status_area.info(f"⏳ {'Executing tools...' if approved else 'Processing denial...'}")

        try:
            if mode == "Local (localhost:8088)":
                event_stream = invoke_local("", approval_thread, approve=approved)
            else:
                token = get_azure_token()
                if not token:
                    st.stop()
                event_stream = invoke_remote("", approval_thread, token, approve=approved)

            all_events = []
            thoughts = []
            answer_chunks = []

            for raw in event_stream:
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                all_events.append(event)
                event_type = event.get("event", "")
                node = event.get("node", "")

                if event_type == "message_chunk" and node == "llm_call":
                    content = event.get("content", "")
                    if content:
                        answer_chunks.append(content)
                        text_placeholder.markdown("".join(answer_chunks))

                elif event_type == "tool_result":
                    tc_id = event.get("tool_call_id", "?")
                    result_val = event.get("content", "")
                    thoughts.append(f"✅ Tool result: `{result_val}`")
                    if thoughts:
                        with thoughts_placeholder.container():
                            with st.expander("💭 Agent thoughts", expanded=True):
                                for t in thoughts:
                                    st.markdown(t)

                elif event_type == "node_update":
                    for msg_summary in event.get("messages", []):
                        for tc in msg_summary.get("tool_calls", []):
                            tc_name = tc.get("name", "")
                            tc_args = tc.get("args", {})
                            if tc_name:
                                args_str = ", ".join(f"{k}={v}" for k, v in tc_args.items())
                                thoughts.append(f"⚡ `{tc_name}({args_str})`")

                elif event_type == "approval_required":
                    # Another round of approval needed
                    tool_calls = event.get("tool_calls", [])
                    st.session_state.pending_approval = {
                        "tool_calls": tool_calls,
                        "thread_id": event.get("thread_id", approval_thread),
                    }
                    for tc in tool_calls:
                        args_str = ", ".join(f"{k}={v}" for k, v in tc.get("args", {}).items())
                        thoughts.append(f"🔒 **Approval needed**: `{tc['name']}({args_str})`")
                    status_area.warning("⏸️ Waiting for tool approval...")

                elif event_type == "done":
                    if not st.session_state.pending_approval:
                        status_area.success("✅ Done!")

            final_answer = "".join(answer_chunks).strip()
            if final_answer:
                text_placeholder.markdown(final_answer)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": final_answer,
                    "thoughts": thoughts,
                })

            if thoughts:
                with thoughts_placeholder.container():
                    with st.expander("💭 Agent thoughts", expanded=False):
                        for t in thoughts:
                            st.markdown(t)

            with debug_placeholder.container():
                with st.expander("🐛 Raw SSE events", expanded=False):
                    for evt in all_events:
                        st.json(evt)

        except Exception as e:
            status_area.error(f"❌ Error: {e}")


if st.session_state.pending_approval:
    pa = st.session_state.pending_approval
    st.divider()
    st.subheader("🔒 Tool Approval Required")
    st.markdown("The agent wants to call the following tool(s):")
    for tc in pa["tool_calls"]:
        args_str = ", ".join(f"**{k}**={v}" for k, v in tc.get("args", {}).items())
        st.markdown(f"- `{tc['name']}` ({args_str})")

    col1, col2, _ = st.columns([1, 1, 4])
    with col1:
        if st.button("✅ Approve", type="primary", use_container_width=True):
            _handle_approval(True)
            st.rerun()
    with col2:
        if st.button("❌ Deny", type="secondary", use_container_width=True):
            _handle_approval(False)
            st.rerun()
