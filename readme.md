# Hosted Agent Test Variants

Six variants of a LangGraph-based Foundry hosted agent, each demonstrating a different feature. All share the same core: plan_node → llm_call → tools loop, `get_stream_writer()` custom events, `version="v2"` streaming, `agent_session_id` container affinity, App Insights logging, and a Streamlit UI.

## Comparison Table

| Directory | Tools | Interrupt | Plan Filtering | Protocol | Key Concept |
|-----------|-------|-----------|---------------|----------|-------------|
| `invoketest1_localtools` | Local (add/subtract/multiply/divide) | None | No | SSE | **Baseline** — simplest full example |
| `invoketest1_localtools_hitl` | Local | `interrupt()` in style_check node | No | SSE | **Human-in-the-loop** — pauses to ask user for response style |
| `invoketest1_localtools_skipplannode` | Local | None | **Yes** | SSE | **Plan node filtering** — removes plan_node from SSE stream |
| `invoketest1_mcp_approval` | MCP (remote calculator) | `interrupt_before=["tools"]` | No | SSE | **Tool approval gate** — client approves/denies before execution |
| `invoketest1_mcp_approval_ag-ui` | MCP (remote calculator) | `interrupt_before=["tools"]` | No | **AG-UI** | **AG-UI protocol** — approval flow with AG-UI event translation |
| `invoketest1_mcp_noapproval` | MCP (remote calculator) | None | No | SSE | **MCP without gating** — tools execute automatically |

## Feature Details

### Local Tools vs MCP Tools

- **Local tools** (`invoketest1_localtools*`): Python `@tool` functions defined in `graph.py`. Simple, no external dependencies.
- **MCP tools** (`invoketest1_mcp_*`): Remote tools via `MultiServerMCPClient` connecting to an MCP calculator server. Requires the MCP server to be running.

### Interrupt Patterns

- **None** (`localtools`, `localtools_skipplannode`, `mcp_noapproval`): Graph runs to completion without pausing.
- **Declarative `interrupt_before=["tools"]`** (`mcp_approval`, `mcp_approval_ag-ui`): Set at `graph.compile()`. Pauses before the tools node. Client sends `{"approve": true/false}` — no data flows back from the user, just approve or deny.
- **Programmatic `interrupt()`** (`localtools_hitl`): Called inside a node function. Pauses mid-execution. User's response arrives via `Command(resume=value)` — arbitrary data can flow back (e.g. "rhyme" or "normal").

### Plan Node Filtering

- Only `invoketest1_localtools_skipplannode` filters plan_node messages from the SSE stream using `metadata.get("langgraph_node")`. Custom events (planning/plan_complete) still flow for the thoughts panel.

### Protocol

- **Standard SSE** (5 variants): Events include `message_chunk`, `node_update`, `tool_result`, `custom`, `done`.
- **AG-UI** (`mcp_approval_ag-ui`): Events translated to `RUN_STARTED`, `TEXT_MESSAGE_CONTENT`, `TOOL_CALL_START`, `TOOL_CALL_RESULT`, `CUSTOM`, `RUN_FINISHED`, etc.

## Common Commands

All variants follow the same workflow:

```bash
# Deploy (always creates a fresh agent with unique hash suffix)
python deploy.py

# Test (auto-updated by deploy.py with the new agent name)
python test_remote.py

# Query App Insights logs
python query_logs.py                    # traces, last 2h
python query_logs.py --type exceptions  # exceptions
python query_logs.py --type all         # both
python query_logs.py --since 6h         # custom time range

# Run Streamlit UI
cd ui && streamlit run app.py
```

## File Structure (each variant)

```
agent.yaml          # Agent metadata
graph.py            # LangGraph graph definition (nodes, tools, edges)
main.py             # HTTP server with SSE streaming endpoint
deploy.py           # Docker build + push + fresh agent creation
test_remote.py      # Automated 2-turn test against deployed agent
query_logs.py       # App Insights log querying via az rest
Dockerfile          # Python 3.12-slim container
requirements.txt    # Python dependencies
ui/app.py           # Streamlit chat UI
```
