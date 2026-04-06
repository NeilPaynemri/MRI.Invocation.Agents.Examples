"""Test the remotely deployed AG-UI invocations-protocol agent with tool approval flow."""
import json
import subprocess
import urllib.request
import urllib.error
import uuid

AZ = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
BASE = "https://fa-ouwa1-ai.services.ai.azure.com/api/projects/fa-ouwa1-project"
API = "2025-05-15-preview"
AGENT = "invoketest1-mcp-agui-v4-custom-c038"
SESSION_ID = f"test-{uuid.uuid4().hex[:8]}"

def get_token():
    return subprocess.check_output(
        [AZ, "account", "get-access-token", "--resource", "https://ai.azure.com",
         "--query", "accessToken", "-o", "tsv"],
        text=True, shell=True,
    ).strip()

def invoke(message: str = "", session_id: str = "", approve=None):
    """Send a message or approval/denial to the agent, stream SSE events.
    Returns a list of parsed SSE event dicts (AG-UI format with 'type' field)."""
    url = (
        f"{BASE}/agents/{AGENT}/endpoint/protocols/invocations"
        f"?api-version={API}&agent_session_id={session_id}"
    )
    body = {}
    if approve is not None:
        body["approve"] = approve
    else:
        body["message"] = message

    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    })
    events = []
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        print(f"  Status: {resp.status}")
        for line in resp:
            decoded = line.decode("utf-8", errors="replace").rstrip()
            if decoded:
                print(f"  {decoded}")
                if decoded.startswith("data: "):
                    try:
                        events.append(json.loads(decoded[6:]))
                    except json.JSONDecodeError:
                        pass
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        print(f"  HTTP {e.code}: {body_text[:1000]}")
    return events


# === Turn 1: Ask a question — expect approval_required CUSTOM event ===
print(f"=== Turn 1: Ask question (session={SESSION_ID}) ===")
print(f"Q: What is 12 + 8?")
events = invoke("What is 12 + 8?", SESSION_ID)

# Check AG-UI events
run_started = any(e.get("type") == "RUN_STARTED" for e in events)
run_finished = any(e.get("type") == "RUN_FINISHED" for e in events)
print(f"\n  >>> RUN_STARTED: {run_started}, RUN_FINISHED: {run_finished}")

# Check for approval_required CUSTOM event
approval_event = next((e for e in events if e.get("type") == "CUSTOM" and e.get("name") == "approval_required"), None)
if approval_event:
    tool_calls = approval_event.get("value", {}).get("tool_calls", [])
    print(f"  >>> Approval required for: {[tc['name'] for tc in tool_calls]}")

    # === Turn 2: Approve the tool call ===
    print(f"\n=== Turn 2: Approve tool call (session={SESSION_ID}) ===")
    events2 = invoke(session_id=SESSION_ID, approve=True)

    # Check for RUN_FINISHED
    done = any(e.get("type") == "RUN_FINISHED" for e in events2)
    text_msgs = [e for e in events2 if e.get("type") == "TEXT_MESSAGE_CONTENT"]
    print(f"\n  >>> Completed: {done}, text chunks: {len(text_msgs)}")
else:
    print("\n  >>> No approval required — tool ran directly (unexpected)")


# === Turn 3: Ask another question and DENY the tool call ===
print(f"\n=== Turn 3: Ask question to deny (session={SESSION_ID}) ===")
print(f"Q: What is 5 * 3?")
events3 = invoke("What is 5 * 3?", SESSION_ID)

approval_event3 = next((e for e in events3 if e.get("type") == "CUSTOM" and e.get("name") == "approval_required"), None)
if approval_event3:
    tool_calls3 = approval_event3.get("value", {}).get("tool_calls", [])
    print(f"\n  >>> Approval required for: {[tc['name'] for tc in tool_calls3]}")

    # === Turn 4: Deny the tool call ===
    print(f"\n=== Turn 4: Deny tool call (session={SESSION_ID}) ===")
    events4 = invoke(session_id=SESSION_ID, approve=False)
    done4 = any(e.get("type") == "RUN_FINISHED" for e in events4)
    print(f"\n  >>> Completed after denial: {done4}")
else:
    print("\n  >>> No approval required (unexpected)")
