# invoketest1_mcp_approval_ag-ui — AG-UI Protocol

Same approval flow as `invoketest1_mcp_approval` but translates LangGraph events into the AG-UI (Agent-UI) protocol instead of the standard SSE format.

## What This Demonstrates

- **Tools:** Remote MCP tools via `MultiServerMCPClient` — connects to an MCP calculator server
- **Interrupt:** `interrupt_before=["tools"]` — same declarative approval gate as `mcp_approval`
- **Plan Node Filtering:** No
- **Protocol:** **AG-UI** — events use AG-UI types: `RUN_STARTED`, `STEP_STARTED`, `TEXT_MESSAGE_START`, `TEXT_MESSAGE_CONTENT`, `TEXT_MESSAGE_END`, `TOOL_CALL_START`, `TOOL_CALL_ARGS`, `TOOL_CALL_END`, `TOOL_CALL_RESULT`, `CUSTOM`, `STEP_FINISHED`, `RUN_FINISHED`, `RUN_ERROR`

## Graph Flow

```
plan_node → llm_call ──INTERRUPT──> (client approves/denies) → tools → llm_call → ... → done
```

(Same graph as `mcp_approval` — the difference is entirely in `main.py`'s SSE event translation layer.)

## AG-UI Event Mapping

| LangGraph Event | AG-UI Event |
|----------------|-------------|
| Stream start | `RUN_STARTED` |
| Node enters | `STEP_STARTED` |
| AI message token | `TEXT_MESSAGE_CONTENT` |
| Tool call detected | `TOOL_CALL_START` → `TOOL_CALL_ARGS` → `TOOL_CALL_END` |
| Tool result | `TOOL_CALL_RESULT` |
| Custom event | `CUSTOM` |
| Stream end | `RUN_FINISHED` |
| Error | `RUN_ERROR` |

## How to Use

```bash
python deploy.py
python test_remote.py
python query_logs.py
cd ui && streamlit run app.py
```

## Key Difference from Other Variants

The **only variant using AG-UI protocol**. All other variants use the standard SSE event format. This shows how to build a translation layer in `main.py` that converts LangGraph streaming into AG-UI events for clients that expect that protocol.
