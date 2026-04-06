"""Quick test: send a math request to exercise MCP calculator tools."""
import json
import requests

url = "http://localhost:8088/invocations"
headers = {
    "Content-Type": "application/json",
    "x-agent-invocation-id": "test-mcp-calc-1",
    "x-agent-session-id": "test-mcp-session",
}
body = {
    "message": "What is 3 + 5? Use the add tool to compute it.",
    "user_id": "bob",
    "thread_id": "test-mcp-calc-1",
}

print(f"POST {url}")
print(f"Body: {json.dumps(body)}")
print("---")

with requests.post(url, json=body, headers=headers, stream=True, timeout=120) as resp:
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
                tr = event.get("content", "")
                print(f"\n  [tool_result] {tr}")
            elif etype == "done":
                print("\n--- DONE ---")
            elif etype == "session":
                inv = event.get("invocation_id")
                tid = event.get("thread_id")
                print(f"[session] inv={inv} thread={tid}")
            elif etype == "usage":
                inp = event.get("input_tokens")
                out = event.get("output_tokens")
                tot = event.get("total_tokens")
                print(f"\n[usage] in={inp} out={out} total={tot}")
            else:
                print(f"\n  [{etype}] {json.dumps(event)[:200]}")
