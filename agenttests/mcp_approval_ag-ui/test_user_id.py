"""Quick test: send a request with user_id=bob and print the SSE stream."""
import json
import requests

url = "http://localhost:8088/invocations"
headers = {
    "Content-Type": "application/json",
    "x-agent-invocation-id": "test-name-1",
    "x-agent-session-id": "test-session",
}
body = {"message": "What is my name?", "user_id": "bob", "thread_id": "test-name-1"}

print(f"POST {url}")
print(f"Body: {json.dumps(body)}")
print("---")

with requests.post(url, json=body, headers=headers, stream=True, timeout=60) as resp:
    resp.raise_for_status()
    for line in resp.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            event = json.loads(line[6:])
            etype = event.get("event", "")
            if etype == "message_chunk":
                content = event.get("content", "")
                if content:
                    print(content, end="", flush=True)
            elif etype == "tool_result":
                print(f"\n  [tool_result] {event.get('content', '')}")
            elif etype == "done":
                print(f"\n--- DONE ---")
            elif etype == "session":
                print(f"[session] inv={event.get('invocation_id')} thread={event.get('thread_id')}")
            elif etype == "usage":
                print(f"\n[usage] in={event.get('input_tokens')} out={event.get('output_tokens')} total={event.get('total_tokens')}")
            else:
                print(f"\n  [{etype}] {json.dumps(event)[:200]}")
