"""Diagnostic remote test to narrow down the multi-turn failure."""
import json
import subprocess
import urllib.request
import uuid
import time

AZ = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
BASE = "https://fa-ouwa1-ai.services.ai.azure.com/api/projects/fa-ouwa1-project"
API = "2025-05-15-preview"
AGENT = "invoketest1-mcp-calculator"

def get_token():
    return subprocess.check_output(
        [AZ, "account", "get-access-token", "--resource", "https://ai.azure.com",
         "--query", "accessToken", "-o", "tsv"],
        text=True, shell=True,
    ).strip()

def invoke(message: str, session_id: str):
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
        for line in resp:
            decoded = line.decode("utf-8", errors="replace").rstrip()
            if decoded.startswith("data: "):
                try:
                    ev = json.loads(decoded[6:])
                    events.append(ev)
                    evtype = ev.get("event", "")
                    if evtype in ("error", "done", "session"):
                        print(f"  [{evtype}] {json.dumps(ev)}")
                    elif evtype == "node_update":
                        print(f"  [node_update] node={ev.get('node')}")
                    elif evtype == "tool_result":
                        print(f"  [tool_result] {ev.get('content', '')[:80]}")
                    elif evtype == "message":
                        print(f"  [message] node={ev.get('node')} content={ev.get('content', '')[:80]}")
                except json.JSONDecodeError:
                    pass
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        print(f"  HTTP {e.code}: {body_text[:500]}")
    
    has_error = any(e.get("event") == "error" for e in events)
    has_done = any(e.get("event") == "done" for e in events)
    return "ERROR" if has_error else ("OK" if has_done else "UNKNOWN")

# ── Test 1: Fresh session, tool call (baseline) ──
s1 = f"diag-{uuid.uuid4().hex[:8]}"
print(f"\n=== TEST 1: Fresh session ({s1}), tool call ===")
print("Q: What is 5 + 3?")
r = invoke("What is 5 + 3?", s1)
print(f"Result: {r}\n")

time.sleep(2)

# ── Test 2: DIFFERENT fresh session, tool call (second request to container) ──
s2 = f"diag-{uuid.uuid4().hex[:8]}"
print(f"\n=== TEST 2: Different fresh session ({s2}), tool call ===")
print("Q: What is 7 * 4?")
r = invoke("What is 7 * 4?", s2)
print(f"Result: {r}\n")

time.sleep(2)

# ── Test 3: Same session as Test 1, NO tool needed ──
print(f"\n=== TEST 3: Same session as Test 1 ({s1}), NO tools ===")
print("Q: What is the capital of France?")
r = invoke("What is the capital of France?", s1)
print(f"Result: {r}\n")

time.sleep(2)

# ── Test 4: Same session as Test 1, tool needed (the failing case) ──
print(f"\n=== TEST 4: Same session as Test 1 ({s1}), tool needed ===")
print("Q: Now what is that result times 2?")
r = invoke("Now what is that result times 2?", s1)
print(f"Result: {r}\n")
