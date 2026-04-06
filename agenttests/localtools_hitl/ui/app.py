"""
Streamlit UI for testing the invoketest1-hitl agent.

Supports both local and remote (deployed) invocations endpoints.
Streams SSE events and displays results in real time.
Handles HITL interrupt/resume: after the agent computes an answer it
interrupts and asks the user to choose "rhyme" or "normal" style.
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
AGENT_NAME = "invoketest1-hitl-v3-custom-a827"
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


# ---------------------------------------------------------------------------
# Invoke helpers — initial question
# ---------------------------------------------------------------------------
def invoke_local(message: str, thread_id: str):
    """POST to local agent and stream SSE events."""
    url = f"{LOCAL_URL}/invocations"
    headers = {
        "Content-Type": "application/json",
        "x-agent-invocation-id": f"ui-{thread_id}",
        "x-agent-session-id": thread_id,
    }
    body = {"message": message, "thread_id": thread_id, "user_id": "bob"}
    with requests.post(url, json=body, headers=headers, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                yield line[6:]


def invoke_remote(message: str, thread_id: str, token: str):
    """POST to deployed agent via platform invocations gateway and stream SSE events."""
    url = (
        f"{ENDPOINT}/agents/{AGENT_NAME}/endpoint/protocols/invocations"
        f"?api-version={API_VERSION}&agent_session_id={thread_id}"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {"message": message, "thread_id": thread_id, "user_id": "bob"}
    with requests.post(url, json=body, headers=headers, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                yield line[6:]


# ---------------------------------------------------------------------------
# Invoke helpers — resume with style choice
# ---------------------------------------------------------------------------
def resume_local(style: str, thread_id: str):
    """POST resume to local agent and stream SSE events."""
    url = f"{LOCAL_URL}/invocations"
    headers = {
        "Content-Type": "application/json",
        "x-agent-invocation-id": f"ui-resume-{thread_id}",
        "x-agent-session-id": thread_id,
    }
    body = {"command": "resume", "style": style, "thread_id": thread_id}
    with requests.post(url, json=body, headers=headers, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                yield line[6:]


def resume_remote(style: str, thread_id: str, token: str):
    """POST resume to deployed agent and stream SSE events."""
    url = (
        f"{ENDPOINT}/agents/{AGENT_NAME}/endpoint/protocols/invocations"
        f"?api-version={API_VERSION}&agent_session_id={thread_id}"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {"command": "resume", "style": style, "thread_id": thread_id}
    with requests.post(url, json=body, headers=headers, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                yield line[6:]


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------
st.set_page_config(page_title="HITL Calculator Agent", page_icon="🧮", layout="wide")
st.title("HITL Calculator Agent — Invocations Tester")

# Session ID management
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())[:8]
if "last_mode" not in st.session_state:
    st.session_state.last_mode = None


def _new_conversation():
    st.session_state.session_id = str(uuid.uuid4())[:8]
    st.session_state.messages = []
    st.session_state.pending_style = None


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
if "pending_style" not in st.session_state:
    st.session_state.pending_style = None  # {thread_id, interrupt}

# Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("thoughts"):
            with st.expander("💭 Agent thoughts", expanded=False):
                for t in msg["thoughts"]:
                    st.markdown(t)
        st.markdown(msg["content"])


# ---------------------------------------------------------------------------
# Stream processing helper
# ---------------------------------------------------------------------------
def process_event_stream(event_stream, status_area, thoughts_placeholder,
                         text_placeholder, debug_placeholder, is_resume=False):
    """Process SSE events. Returns (final_answer, thoughts, all_events)."""
    all_events = []
    thoughts = []
    answer_chunks = []
    pending_tools = {}
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
                f"⏳ {'Resuming' if is_resume else 'Running'}... "
                f"(inv: `{event.get('invocation_id', '?')}`, "
                f"thread: `{event.get('thread_id', '?')}`)"
            )

        # ── message_chunk ──
        elif event_type == "message_chunk":
            current_node = node

            for tc in event.get("tool_calls", []):
                tc_name = tc.get("name", "")
                tc_id = tc.get("id", "")
                if tc_name and tc_id:
                    pending_tools[tc_id] = {"name": tc_name, "args": {}}

            content = event.get("content", "")
            if content:
                if node == "plan_node":
                    pass  # handled by plan_node "message" event
                elif node in ("llm_call", "final_answer"):
                    answer_chunks.append(content)
                    clean = re.sub(r"<plan>.*?</plan>\s*", "", "".join(answer_chunks), flags=re.DOTALL)
                    text_placeholder.markdown(clean or "▌")

        # ── message (complete node output) ──
        elif event_type == "message":
            current_node = node
            content = event.get("content", "")

            if node == "plan_node" and content:
                plan_match = re.search(r"<plan>(.*?)</plan>", content, re.DOTALL)
                plan_text = plan_match.group(1).strip() if plan_match else content.strip()
                if plan_text:
                    thoughts.append(f"📋 **Plan**:\n{plan_text}")
                    _render_thoughts()

            for tc in event.get("tool_calls", []):
                tc_name = tc.get("name", "")
                tc_id = tc.get("id", "")
                tc_args = tc.get("args", {})
                if tc_name:
                    pending_tools[tc_id] = {"name": tc_name, "args": tc_args}

        # ── node_update ──
        elif event_type == "node_update":
            current_node = node
            status_area.info(f"⏳ Node: `{node}`...")
            for msg_summary in event.get("messages", []):
                for tc in msg_summary.get("tool_calls", []):
                    tc_name = tc.get("name", "")
                    tc_args = tc.get("args", {})
                    if tc_name:
                        args_str = ", ".join(f"{k}={v}" for k, v in tc_args.items())
                        thoughts.append(f"⚡ **Calling** `{tc_name}({args_str})`")
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

        # ── custom (get_stream_writer events from graph nodes) ──
        elif event_type == "custom":
            status = event.get("status", "")
            detail = event.get("detail", "")
            node_name = event.get("node", "")
            if status and detail:
                icon = {"planning": "📝", "thinking": "🤔", "executing_tools": "⚡",
                        "tool_running": "🔧", "tool_result": "✅",
                        "awaiting_style": "⏸️", "formatting": "🎨",
                        }.get(status, "💬")
                thoughts.append(f"{icon} **{node_name}**: {detail}")
                _render_thoughts()
            if status:
                status_area.info(f"⏳ {detail or status}...")

        # ── usage ──
        elif event_type == "usage":
            in_tok = event.get("input_tokens", 0)
            out_tok = event.get("output_tokens", 0)
            tot_tok = event.get("total_tokens", 0)
            thoughts.append(f"📊 **Tokens**: {in_tok} in → {out_tok} out ({tot_tok} total)")
            _render_thoughts()

        # ── style_request (HITL interrupt) ──
        elif event_type == "style_request":
            interrupt_data = event.get("interrupt", {})
            style_thread = event.get("thread_id", thread_id)
            st.session_state.pending_style = {
                "thread_id": style_thread,
                "interrupt": interrupt_data,
            }
            preview = interrupt_data.get("answer_preview", "")
            thoughts.append(f"⏸️ **Interrupt**: Choose answer style (preview: *{preview}*)")
            _render_thoughts()
            status_area.warning("⏸️ Waiting for style choice...")

        # ── done ──
        elif event_type == "done":
            if not st.session_state.pending_style:
                status_area.success("✅ Done!")

        elif event_type == "interrupted":
            pass  # already handled by style_request

        elif event_type == "error":
            status_area.error(f"❌ Error: {event.get('message', 'unknown')}")

        elif event_type == "cancelled":
            status_area.warning("⚠️ Cancelled")

    final_answer = re.sub(r"<plan>.*?</plan>\s*", "", "".join(answer_chunks), flags=re.DOTALL).strip()
    return final_answer, thoughts, all_events


# ---------------------------------------------------------------------------
# Chat input — initial question
# ---------------------------------------------------------------------------
if prompt := st.chat_input("Ask a math question (e.g. What is (12 + 8) * 3?)"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        status_area = st.empty()
        thoughts_placeholder = st.empty()
        text_placeholder = st.empty()
        debug_placeholder = st.empty()
        status_area.info("⏳ Invoking agent...")

        try:
            if mode == "Local (localhost:8088)":
                event_stream = invoke_local(prompt, thread_id)
            else:
                token = get_azure_token()
                if not token:
                    st.stop()
                event_stream = invoke_remote(prompt, thread_id, token)

            final_answer, thoughts, all_events = process_event_stream(
                event_stream, status_area, thoughts_placeholder,
                text_placeholder, debug_placeholder,
            )

            if final_answer:
                text_placeholder.markdown(final_answer)
                st.session_state.messages.append({
                    "role": "assistant", "content": final_answer, "thoughts": thoughts,
                })
            elif not all_events:
                status_area.warning("No events received — agent may not be running.")

            if thoughts:
                with thoughts_placeholder.container():
                    with st.expander("💭 Agent thoughts", expanded=False):
                        for t in thoughts:
                            st.markdown(t)

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
# Style Choice Section (HITL resume)
# ---------------------------------------------------------------------------
def _handle_style_choice(style: str):
    """Send resume with the chosen style and process the response."""
    ps = st.session_state.pending_style
    if not ps:
        return

    resume_thread = ps["thread_id"]
    st.session_state.pending_style = None

    st.session_state.messages.append({
        "role": "user",
        "content": f"🎨 Style choice: **{style}**",
    })

    with st.chat_message("assistant"):
        status_area = st.empty()
        thoughts_placeholder = st.empty()
        text_placeholder = st.empty()
        debug_placeholder = st.empty()

        status_area.info(f"⏳ Resuming with style '{style}'...")

        try:
            if mode == "Local (localhost:8088)":
                event_stream = resume_local(style, resume_thread)
            else:
                token = get_azure_token()
                if not token:
                    st.stop()
                event_stream = resume_remote(style, resume_thread, token)

            final_answer, thoughts, all_events = process_event_stream(
                event_stream, status_area, thoughts_placeholder,
                text_placeholder, debug_placeholder, is_resume=True,
            )

            if final_answer:
                text_placeholder.markdown(final_answer)
                st.session_state.messages.append({
                    "role": "assistant", "content": final_answer, "thoughts": thoughts,
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


if st.session_state.pending_style:
    ps = st.session_state.pending_style
    interrupt_data = ps.get("interrupt", {})
    st.divider()
    st.subheader("🎨 Choose Answer Style")
    question = interrupt_data.get("question", "How should I format my answer?")
    preview = interrupt_data.get("answer_preview", "")
    st.markdown(f"**{question}**")
    if preview:
        st.markdown(f"Answer preview: *{preview}*")

    col1, col2, _ = st.columns([1, 1, 4])
    with col1:
        if st.button("🎶 Rhyme", type="primary", use_container_width=True):
            _handle_style_choice("rhyme")
            st.rerun()
    with col2:
        if st.button("📝 Normal", type="secondary", use_container_width=True):
            _handle_style_choice("normal")
            st.rerun()
