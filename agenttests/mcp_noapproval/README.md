# invoketest1_mcp_noapproval — MCP Tools without Approval

Uses remote MCP tools (calculator server) with no approval gate — tools execute automatically as soon as the LLM decides to call them.

## What This Demonstrates

- **Tools:** Remote MCP tools via `MultiServerMCPClient` — connects to an MCP calculator server providing `add`, `multiply`, `divide`, etc.
- **Interrupt:** None — graph runs to completion without pausing
- **Plan Node Filtering:** No — plan_node messages appear in the SSE stream
- **Protocol:** Standard SSE

## Graph Flow

```
plan_node → llm_call → tools → llm_call → ... → done
```

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

Shows **MCP tools without any gating**. Compare with `mcp_approval` which adds `interrupt_before=["tools"]` to pause for approval. This is the MCP equivalent of the `localtools` baseline — the simplest MCP example.
