"""Deploy hosted agent: always creates a BRAND NEW agent each time.

Version updates and delete+recreate both break MI credentials.
The only reliable approach is a fresh agent name every deploy.

Auto-generates a unique name like: invoketest1-v6-a3f1
Also updates test_remote.py with the new agent name.

Usage:
    python deploy.py                          # auto-generated name
    python deploy.py --name my-agent          # explicit name
    python deploy.py --image ...:v7           # override image tag
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error

# ── Defaults ─────────────────────────────────────────────────────────
ENDPOINT = "https://fa-ouwa1-ai.services.ai.azure.com/api/projects/fa-ouwa1-project"
API_VERSION = "2025-05-15-preview"
AGENT_PREFIX = "invoketest1"
DEFAULT_IMAGE = "faouwa1acr.azurecr.io/invoketest1:v7-custom"

AZ = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def make_agent_name(image):
    """Generate a unique agent name from the image tag + short hash of timestamp."""
    tag = image.rsplit(":", 1)[-1] if ":" in image else "latest"
    suffix = hashlib.md5(str(time.time()).encode()).hexdigest()[:4]
    return f"{AGENT_PREFIX}-{tag}-{suffix}"


def get_env_vars():
    return {
        "AZURE_AI_PROJECT_ENDPOINT": ENDPOINT,
        "MODEL_DEPLOYMENT_NAME": "gpt-4.1-mini",
    }


def get_definition(image):
    return {
        "kind": "hosted",
        "image": image,
        "cpu": "1",
        "memory": "2Gi",
        "container_protocol_versions": [
            {"protocol": "invocations", "version": "v0.0.1"}
        ],
        "environment_variables": get_env_vars(),
    }


# ── API helpers ──────────────────────────────────────────────────────

def get_token():
    return subprocess.check_output(
        [AZ, "account", "get-access-token",
         "--resource", "https://ai.azure.com",
         "--query", "accessToken", "-o", "tsv"],
        text=True, shell=True,
    ).strip()


def api(method, path, body=None):
    url = f"{ENDPOINT}{path}?api-version={API_VERSION}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(body_text)
        except json.JSONDecodeError:
            return e.code, body_text


def create_agent(name, image):
    """POST /agents — fresh create is the ONLY way MI works reliably."""
    body = {
        "name": name,
        "definition": get_definition(image),
        "metadata": {"enableVnextExperience": "true"},
    }
    return api("POST", "/agents", body)


def wait_for_active(name, timeout_secs=300):
    """Poll until agent is active or failed."""
    for i in range(timeout_secs // 5):
        code, agent = api("GET", f"/agents/{name}")
        if code == 200:
            ver = agent.get("versions", {}).get("latest", {})
            status = ver.get("status", "unknown")
            img = ver.get("definition", {}).get("image", "")
            print(f"  [{i*5}s] status={status}  image={img}")
            if status == "active":
                return ver
            if status == "failed":
                print("\n  FAILED to provision!")
                sys.exit(1)
        time.sleep(5)
    print("  Timed out waiting for active status.")
    sys.exit(1)


def update_test_remote(agent_name):
    """Patch test_remote.py so it points at the new agent."""
    test_file = os.path.join(SCRIPT_DIR, "test_remote.py")
    if not os.path.exists(test_file):
        return
    content = open(test_file, encoding="utf-8").read()
    new_content = re.sub(
        r'^AGENT\s*=\s*"[^"]*"',
        f'AGENT = "{agent_name}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if new_content != content:
        open(test_file, "w", encoding="utf-8").write(new_content)
        print(f"  Updated test_remote.py → AGENT = \"{agent_name}\"")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Deploy hosted agent (always fresh create — the only way MI works)")
    parser.add_argument("--name", default=None,
                        help="Agent name (default: auto-generated from image tag)")
    parser.add_argument("--image", default=DEFAULT_IMAGE,
                        help=f"Docker image (default: {DEFAULT_IMAGE})")
    args = parser.parse_args()

    image = args.image
    name = args.name or make_agent_name(image)

    print(f"Agent: {name}")
    print(f"Image: {image}")
    print()

    print(f"=== POST /agents (fresh create) ===")
    code, result = create_agent(name, image)
    print(f"  Status: {code}")
    if code not in (200, 201, 202):
        print(f"  FAILED: {json.dumps(result, indent=2)[:1000]}")
        sys.exit(1)
    ver_num = result.get("versions", {}).get("latest", {}).get("version", "?")
    print(f"  Created. Version: {ver_num}")

    print(f"\n=== Waiting for active ===")
    ver = wait_for_active(name)

    defn = ver.get("definition", {})
    print(f"\n  Version:  {ver.get('version', '?')}")
    print(f"  Image:    {defn.get('image')}")
    print(f"  Env vars: {list(defn.get('environment_variables', {}).keys())}")

    update_test_remote(name)

    print(f"\n  Agent '{name}' is ACTIVE!")
    print(f"  Test with:  python test_remote.py")


if __name__ == "__main__":
    main()
