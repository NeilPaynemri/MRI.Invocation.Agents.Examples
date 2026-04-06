# invoketest1_mcp_approval — MCP Tools with Approval Gate

Uses remote MCP tools (calculator server) with a declarative approval gate that pauses before tool execution so the client can approve or deny.

## What This Demonstrates

- **Tools:** Remote MCP tools via `MultiServerMCPClient` — connects to an MCP calculator server providing `add`, `multiply`, `divide`, etc.
- **Interrupt:** `interrupt_before=["tools"]` set at `graph.compile()` — declarative gate that pauses before the tools node runs
- **Plan Node Filtering:** No — plan_node messages appear in the SSE stream
- **Protocol:** Standard SSE
- **Approval Flow:** Client sends `{"approve": true/false, "thread_id": "..."}` to resume; denial injects a synthetic ToolMessage saying "User denied"

## Graph Flow

```
plan_node → llm_call ──INTERRUPT──> (client approves/denies) → tools → llm_call → ... → done
```

## How the Approval Works

1. LLM decides to call a tool (e.g. `add(12, 8)`)
2. Graph pauses **before** the `tools` node due to `interrupt_before`
3. SSE sends a `cancelled` event with the pending tool calls
4. Client sends approval: `{"approve": true, "thread_id": "..."}`
5. If approved, tools execute normally; if denied, a synthetic `ToolMessage("User denied tool execution")` is injected and the LLM responds accordingly

## Environment Setup

Copy `.env.example` to `.env` and fill in your values. Then create separate virtual environments for the agent and the UI:

```bash
# Agent venv
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
pip install -r requirements-public.txt

# UI venv (from the ui/ folder)
cd ui
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` contains the private-preview Azure SDK packages (from the Azure DevOps feed). `requirements-public.txt` contains the publicly available dependencies (LangGraph, LangChain, etc.).

## How to Use

With the agent `.venv` activated:

```bash
python deploy.py
python test_remote.py
python query_logs.py
```

For the Streamlit UI, activate the `ui/.venv` instead:

```bash
cd ui
streamlit run app.py
```

## Key Difference from Other Variants

Uses **declarative `interrupt_before=["tools"]`** — a compile-time gate that only allows approve/deny (no data returned from user). Compare with `localtools_hitl` which uses **programmatic `interrupt()`** to collect arbitrary user input.
