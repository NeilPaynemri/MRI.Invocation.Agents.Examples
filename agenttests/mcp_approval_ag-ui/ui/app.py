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
AGENT_NAME = "invoketest1-mcp-agui-v4-custom-c038"
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
st.set_page_config(page_title="MCP Calculator Agent (AG-UI)", page_icon="🧮", layout="wide")
st.title("MCP Calculator Agent — AG-UI Invocations Tester")

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
    st.markdown(f"**Protocol:** `AG-UI / invocations`")
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
                answer_chunks = []     # only final answer text content
                pending_tools = {}     # toolCallId -> {name, args_chunks}
                current_node = ""
                current_msg_id = None  # track open TEXT_MESSAGE stream

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
                    event_type = event.get("type", "")

                    # ── RUN_STARTED ──
                    if event_type == "RUN_STARTED":
                        status_area.info(
                            f"⏳ Running... (thread: `{event.get('threadId', '?')}`, "
                            f"run: `{event.get('runId', '?')}`)"
                        )

                    # ── STEP_STARTED / STEP_FINISHED ──
                    elif event_type == "STEP_STARTED":
                        current_node = event.get("stepName", "")
                        status_area.info(f"⏳ Node: `{current_node}`...")

                    elif event_type == "STEP_FINISHED":
                        pass  # node done, nothing special to render

                    # ── TEXT_MESSAGE_START / CONTENT / END ──
                    elif event_type == "TEXT_MESSAGE_START":
                        current_msg_id = event.get("messageId", "")

                    elif event_type == "TEXT_MESSAGE_CONTENT":
                        delta = event.get("delta", "")
                        if delta:
                            if current_node == "plan_node":
                                # Plan chunks — accumulate but don't stream inline
                                answer_chunks.append(delta)
                            else:
                                # Final answer text
                                answer_chunks.append(delta)
                                clean = re.sub(r"<plan>.*?</plan>\s*", "", "".join(answer_chunks), flags=re.DOTALL)
                                text_placeholder.markdown(clean or "▌")

                    elif event_type == "TEXT_MESSAGE_END":
                        msg_id = event.get("messageId", "")
                        # If plan node just ended, extract plan for thoughts
                        if current_node == "plan_node":
                            plan_text = "".join(answer_chunks)
                            plan_match = re.search(r"<plan>(.*?)</plan>", plan_text, re.DOTALL)
                            if plan_match:
                                thoughts.append(f"📋 **Plan**:\n{plan_match.group(1).strip()}")
                            else:
                                thoughts.append(f"📋 **Plan**:\n{plan_text.strip()}")
                            _render_thoughts()
                            answer_chunks.clear()
                        current_msg_id = None

                    # ── TOOL_CALL_START / ARGS / END ──
                    elif event_type == "TOOL_CALL_START":
                        tc_id = event.get("toolCallId", "")
                        tc_name = event.get("toolCallName", "")
                        pending_tools[tc_id] = {"name": tc_name, "args_chunks": []}

                    elif event_type == "TOOL_CALL_ARGS":
                        tc_id = event.get("toolCallId", "")
                        delta = event.get("delta", "")
                        if tc_id in pending_tools:
                            pending_tools[tc_id]["args_chunks"].append(delta)

                    elif event_type == "TOOL_CALL_END":
                        tc_id = event.get("toolCallId", "")
                        if tc_id in pending_tools:
                            info = pending_tools[tc_id]
                            args_json = "".join(info["args_chunks"])
                            try:
                                args = json.loads(args_json)
                            except json.JSONDecodeError:
                                args = {"raw": args_json}
                            info["args"] = args
                            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
                            thoughts.append(f"⚡ **Calling** `{info['name']}({args_str})`")
                            _render_thoughts()

                    # ── TOOL_CALL_RESULT ──
                    elif event_type == "TOOL_CALL_RESULT":
                        tc_id = event.get("toolCallId", "?")
                        result_val = event.get("content", "")
                        tool_info = pending_tools.get(tc_id, {})
                        tool_name = tool_info.get("name", tc_id)
                        thoughts.append(f"&ensp;&ensp;✅ `{tool_name}` → `{result_val}`")
                        _render_thoughts()

                    # ── CUSTOM events (node_status, approval_required) ──
                    elif event_type == "CUSTOM":
                        custom_name = event.get("name", "")
                        custom_value = event.get("value", {})

                        if custom_name == "node_status":
                            status_text = custom_value.get("detail", custom_value.get("status", ""))
                            if status_text:
                                thoughts.append(f"💬 {status_text}")
                                _render_thoughts()

                        elif custom_name == "approval_required":
                            tool_calls = custom_value.get("tool_calls", [])
                            approval_thread = custom_value.get("thread_id", thread_id)
                            st.session_state.pending_approval = {
                                "tool_calls": tool_calls,
                                "thread_id": approval_thread,
                            }
                            for tc in tool_calls:
                                args_str = ", ".join(f"{k}={v}" for k, v in tc.get("args", {}).items())
                                thoughts.append(f"🔒 **Approval needed**: `{tc['name']}({args_str})`")
                            _render_thoughts()
                            status_area.warning("⏸️ Waiting for tool approval...")

                    # ── RUN_FINISHED ──
                    elif event_type == "RUN_FINISHED":
                        if not st.session_state.pending_approval:
                            status_area.success("✅ Done!")

                    # ── RUN_ERROR ──
                    elif event_type == "RUN_ERROR":
                        status_area.error(f"❌ Error: {event.get('message', 'unknown')}")

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
                event_type = event.get("type", "")

                if event_type == "RUN_STARTED":
                    status_area.info(
                        f"⏳ {'Executing tools...' if approved else 'Processing denial...'} "
                        f"(run: `{event.get('runId', '?')}`)"
                    )

                elif event_type == "STEP_STARTED":
                    status_area.info(f"⏳ Node: `{event.get('stepName', '')}`...")

                elif event_type == "TEXT_MESSAGE_CONTENT":
                    delta = event.get("delta", "")
                    if delta:
                        answer_chunks.append(delta)
                        text_placeholder.markdown("".join(answer_chunks))

                elif event_type == "TOOL_CALL_RESULT":
                    tc_id = event.get("toolCallId", "?")
                    result_val = event.get("content", "")
                    thoughts.append(f"✅ Tool result: `{result_val}`")
                    if thoughts:
                        with thoughts_placeholder.container():
                            with st.expander("💭 Agent thoughts", expanded=True):
                                for t in thoughts:
                                    st.markdown(t)

                elif event_type == "TOOL_CALL_END":
                    pass  # handled by TOOL_CALL_RESULT

                elif event_type == "CUSTOM":
                    custom_name = event.get("name", "")
                    custom_value = event.get("value", {})

                    if custom_name == "node_status":
                        status_text = custom_value.get("detail", custom_value.get("status", ""))
                        if status_text:
                            thoughts.append(f"💬 {status_text}")
                            if thoughts:
                                with thoughts_placeholder.container():
                                    with st.expander("💭 Agent thoughts", expanded=True):
                                        for t in thoughts:
                                            st.markdown(t)

                    elif custom_name == "approval_required":
                        # Another round of approval needed
                        tool_calls = custom_value.get("tool_calls", [])
                        st.session_state.pending_approval = {
                            "tool_calls": tool_calls,
                            "thread_id": custom_value.get("thread_id", approval_thread),
                        }
                        for tc in tool_calls:
                            args_str = ", ".join(f"{k}={v}" for k, v in tc.get("args", {}).items())
                            thoughts.append(f"🔒 **Approval needed**: `{tc['name']}({args_str})`")
                        status_area.warning("⏸️ Waiting for tool approval...")

                elif event_type == "RUN_FINISHED":
                    if not st.session_state.pending_approval:
                        status_area.success("✅ Done!")

                elif event_type == "RUN_ERROR":
                    status_area.error(f"❌ Error: {event.get('message', 'unknown')}")

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
