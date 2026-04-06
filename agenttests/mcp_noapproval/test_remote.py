"""Test the remotely deployed MCP calculator agent (no approval flow)."""
import json
import subprocess
import urllib.request
import urllib.error
import uuid

AZ = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
BASE = "https://fa-ouwa1-ai.services.ai.azure.com/api/projects/fa-ouwa1-project"
API = "2025-05-15-preview"
AGENT = "invoketest1-mcp-noap-v2-custom-9b47"
SESSION_ID = f"test-{uuid.uuid4().hex[:8]}"

def get_token():
    return subprocess.check_output(
        [AZ, "account", "get-access-token", "--resource", "https://ai.azure.com",
         "--query", "accessToken", "-o", "tsv"],
        text=True, shell=True,
    ).strip()

def invoke(message: str, session_id: str):
    """Send a message to the agent, stream SSE events. Returns parsed events."""
    url = (
        f"{BASE}/agents/{AGENT}/endpoint/protocols/invocations"
        f"?api-version={API}&agent_session_id={session_id}"
    )
    data = json.dumps({"message": message}).encode()
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


# === Turn 1: Addition ===
print(f"=== Turn 1: Addition (session={SESSION_ID}) ===")
print("Q: What is 12 + 8?")
events1 = invoke("What is 12 + 8?", SESSION_ID)
done1 = any(e.get("event") == "done" for e in events1)
print(f"\n  >>> Completed: {done1}")

# === Turn 2: Multiplication (multi-turn, same session) ===
print(f"\n=== Turn 2: Multiplication (session={SESSION_ID}) ===")
print("Q: What is 5 * 3?")
events2 = invoke("What is 5 * 3?", SESSION_ID)
done2 = any(e.get("event") == "done" for e in events2)
print(f"\n  >>> Completed: {done2}")
