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

## How to Use

```bash
python deploy.py
python test_remote.py
python query_logs.py
cd ui && streamlit run app.py
```

## Key Difference from Other Variants

Shows **MCP tools without any gating**. Compare with `mcp_approval` which adds `interrupt_before=["tools"]` to pause for approval. This is the MCP equivalent of the `localtools` baseline — the simplest MCP example.
