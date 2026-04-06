"""Query App Insights logs for the hosted agent.

Workaround for `foundry-agent logs` bug where KQL query JSON body
gets mangled by the shell subprocess. This script writes the JSON to
a temp file and passes it to `az rest` via @file syntax.

Usage:
    python query_logs.py                       # traces, last 2h
    python query_logs.py --type exceptions     # exceptions table
    python query_logs.py --type all            # traces + exceptions
    python query_logs.py --since 6h            # custom time range
    python query_logs.py --limit 100           # more results
    python query_logs.py --kql "traces | ..."  # custom KQL
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

# ── Config (from .foundry-agent.json or override) ────────────────────
DEFAULT_APP_INSIGHTS_ID = "b51382aa-2ff6-4ea1-bb3b-6b25c8bdb999"
AZ = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"


def query_app_insights(kql: str, app_id: str = DEFAULT_APP_INSIGHTS_ID) -> dict:
    """Execute a KQL query against App Insights using az rest + temp file."""
    body = json.dumps({"query": kql})

    # Write JSON body to temp file to avoid shell escaping issues
    fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="ai_query_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)

        url = f"https://api.applicationinsights.io/v1/apps/{app_id}/query"
        result = subprocess.run(
            [AZ, "rest", "--method", "POST", "--url", url,
             "--body", f"@{tmp_path}",
             "--headers", "Content-Type=application/json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"ERROR: az rest failed:\n{result.stderr}", file=sys.stderr)
            sys.exit(1)
        return json.loads(result.stdout)
    finally:
        os.unlink(tmp_path)


def format_rows(response: dict) -> None:
    """Pretty-print App Insights query results."""
    for table in response.get("tables", []):
        columns = [c["name"] for c in table.get("columns", [])]
        rows = table.get("rows", [])
        if not rows:
            print("  (no results)")
            return

        print(f"  [{len(rows)} rows]")
        print(f"  {'─' * 80}")
        for row in rows:
            record = dict(zip(columns, row))
            ts = record.get("timestamp", "")[:19]
            msg = record.get("message", record.get("outerMessage", ""))
            sev = record.get("severityLevel", "")
            print(f"  {ts}  sev={sev}  {msg[:120]}")

            # Show extra fields for exceptions
            if "innermostMessage" in record and record["innermostMessage"] != msg:
                print(f"    innermost: {record['innermostMessage'][:200]}")
            if "details" in record and record["details"]:
                details = record["details"]
                if isinstance(details, str):
                    try:
                        details = json.loads(details)
                    except json.JSONDecodeError:
                        pass
                if isinstance(details, list):
                    for d in details:
                        stack = d.get("rawStack", "")
                        if stack:
                            # Show last few lines of stack trace
                            lines = stack.strip().split("\\n")
                            for line in lines[-6:]:
                                print(f"    | {line}")
            if "customDimensions" in record and record["customDimensions"]:
                dims = record["customDimensions"]
                if isinstance(dims, str):
                    try:
                        dims = json.loads(dims)
                    except json.JSONDecodeError:
                        pass
                if isinstance(dims, dict):
                    code_file = dims.get("code.file.path", "")
                    code_func = dims.get("code.function.name", "")
                    code_line = dims.get("code.line.number", "")
                    if code_file:
                        print(f"    @ {code_file}:{code_line} in {code_func}")
        print(f"  {'─' * 80}")


def main():
    parser = argparse.ArgumentParser(description="Query App Insights logs")
    parser.add_argument("--type", choices=["traces", "exceptions", "all"],
                        default="traces", help="Table to query (default: traces)")
    parser.add_argument("--since", default="2h",
                        help="Time range, e.g. 1h, 6h, 1d (default: 2h)")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max rows (default: 50)")
    parser.add_argument("--app-id", default=DEFAULT_APP_INSIGHTS_ID,
                        help="App Insights App ID")
    parser.add_argument("--kql", default=None,
                        help="Custom KQL query (overrides --type/--since/--limit)")
    args = parser.parse_args()

    tables = []
    if args.kql:
        tables = [("custom", args.kql)]
    elif args.type == "all":
        tables = [
            ("traces", f"traces | where timestamp > ago({args.since}) | top {args.limit} by timestamp desc | project timestamp, message, severityLevel, customDimensions"),
            ("exceptions", f"exceptions | where timestamp > ago({args.since}) | top {args.limit} by timestamp desc | project timestamp, type, outerMessage, innermostMessage, severityLevel, details"),
        ]
    elif args.type == "exceptions":
        tables = [
            ("exceptions", f"exceptions | where timestamp > ago({args.since}) | top {args.limit} by timestamp desc | project timestamp, type, outerMessage, innermostMessage, severityLevel, details"),
        ]
    else:
        tables = [
            ("traces", f"traces | where timestamp > ago({args.since}) | top {args.limit} by timestamp desc | project timestamp, message, severityLevel, customDimensions"),
        ]

    for name, kql in tables:
        print(f"\n{'='*80}")
        print(f"  {name.upper()} (since {args.since}, limit {args.limit})")
        print(f"{'='*80}")
        resp = query_app_insights(kql, args.app_id)
        format_rows(resp)


if __name__ == "__main__":
    main()
