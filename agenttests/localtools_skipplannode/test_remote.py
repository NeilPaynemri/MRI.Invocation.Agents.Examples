"""Test the remotely deployed invocations-protocol agent via Foundry API."""
import json
import subprocess
import urllib.request

AZ = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
BASE = "https://fa-ouwa1-ai.services.ai.azure.com/api/projects/fa-ouwa1-project"
API = "2025-05-15-preview"
AGENT = "invoketest1-skipplan-v1-custom-27f8"

def get_token():
    return subprocess.check_output(
        [AZ, "account", "get-access-token", "--resource", "https://ai.azure.com",
         "--query", "accessToken", "-o", "tsv"],
        text=True, shell=True,
    ).strip()

def api_call(method, path, body=None, stream=False):
    url = f"{BASE}{path}?api-version={API}"
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

print(f"POST /agents/{AGENT}/versions/1/invocations")
resp = api_call("POST", f"/agents/{AGENT}/versions/1/invocations",
                {"message": "What is (12 + 8) * 3?"}, stream=True)
if resp:
    print(f"  Status: {resp.status}")
    for line in resp:
        decoded = line.decode("utf-8", errors="replace").rstrip()
        if decoded:
            print(f"  {decoded}")
else:
    print("  FAILED")
