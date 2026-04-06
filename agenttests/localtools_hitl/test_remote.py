"""Test the HITL agent: question → interrupt → resume with style choice."""
import json
import subprocess
import urllib.request
import uuid
import sys

AZ = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
SESSION_ID = str(uuid.uuid4())[:8]  # shared across all turns for container affinity
BASE = "https://fa-ouwa1-ai.services.ai.azure.com/api/projects/fa-ouwa1-project"
API = "2025-05-15-preview"
AGENT = "invoketest1-hitl-v3-custom-a827"  # Updated by deploy.py

def get_token():
    return subprocess.check_output(
        [AZ, "account", "get-access-token", "--resource", "https://ai.azure.com",
         "--query", "accessToken", "-o", "tsv"],
        text=True, shell=True,
    ).strip()

def api_call(method, path, body=None, stream=False, session_id=None):
    sid = session_id or SESSION_ID
    url = f"{BASE}{path}?api-version={API}&agent_session_id={sid}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        if stream:
            return resp
        raw = resp.read()
        return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        print(f"  HTTP {e.code}: {body_text[:1000]}")
        return None

def stream_and_collect(resp):
    """Read SSE lines, print them, return all parsed events."""
    events = []
    for line in resp:
        decoded = line.decode("utf-8", errors="replace").rstrip()
        if decoded.startswith("data: "):
            payload = decoded[6:]
            try:
                evt = json.loads(payload)
                events.append(evt)
            except json.JSONDecodeError:
                pass
        if decoded:
            print(f"  {decoded}")
    return events


# ── Turn 1: Ask a question ─────────────────────────────────────────
print(f"\n{'='*60}")
print(f"TURN 1: Ask question  (agent={AGENT})")
print(f"{'='*60}")
resp = api_call("POST", f"/agents/{AGENT}/versions/1/invocations",
                {"message": "What is (12 + 8) * 3?"}, stream=True)
if not resp:
    print("  FAILED — no response")
    sys.exit(1)

print(f"  Status: {resp.status}")
events = stream_and_collect(resp)

# Extract thread_id from session event
thread_id = None
for evt in events:
    if evt.get("event") == "session":
        thread_id = evt.get("thread_id")
        break

# Check we got interrupted
got_style_request = any(e.get("event") == "style_request" for e in events)
got_interrupted = any(e.get("event") == "interrupted" for e in events)

print(f"\n  thread_id: {thread_id}")
print(f"  got style_request: {got_style_request}")
print(f"  got interrupted: {got_interrupted}")

if not thread_id:
    print("  ERROR: no thread_id — cannot resume")
    sys.exit(1)
if not got_style_request:
    print("  WARNING: no style_request event — graph may not have interrupted")

# ── Turn 2: Resume with "rhyme" ───────────────────────────────────
print(f"\n{'='*60}")
print(f"TURN 2: Resume with style='rhyme'  thread={thread_id}")
print(f"{'='*60}")
resp2 = api_call("POST", f"/agents/{AGENT}/versions/1/invocations",
                 {"command": "resume", "style": "rhyme", "thread_id": thread_id},
                 stream=True)
if not resp2:
    print("  FAILED — no response")
    sys.exit(1)

print(f"  Status: {resp2.status}")
events2 = stream_and_collect(resp2)

got_done = any(e.get("event") == "done" for e in events2)
print(f"\n  got done: {got_done}")

# ── Turn 3: New question, resume with "normal" ───────────────────
print(f"\n{'='*60}")
print(f"TURN 3: New question")
print(f"{'='*60}")
resp3 = api_call("POST", f"/agents/{AGENT}/versions/1/invocations",
                 {"message": "What is 100 / 4?"}, stream=True)
if not resp3:
    print("  FAILED")
    sys.exit(1)

print(f"  Status: {resp3.status}")
events3 = stream_and_collect(resp3)

thread_id3 = None
for evt in events3:
    if evt.get("event") == "session":
        thread_id3 = evt.get("thread_id")
        break

print(f"\n  thread_id: {thread_id3}")

# ── Turn 4: Resume with "normal" ─────────────────────────────────
print(f"\n{'='*60}")
print(f"TURN 4: Resume with style='normal'  thread={thread_id3}")
print(f"{'='*60}")
resp4 = api_call("POST", f"/agents/{AGENT}/versions/1/invocations",
                 {"command": "resume", "style": "normal", "thread_id": thread_id3},
                 stream=True)
if not resp4:
    print("  FAILED")
    sys.exit(1)

print(f"  Status: {resp4.status}")
events4 = stream_and_collect(resp4)

got_done4 = any(e.get("event") == "done" for e in events4)
print(f"\n  got done: {got_done4}")
print(f"\n{'='*60}")
print("ALL TURNS COMPLETE")
print(f"{'='*60}")
