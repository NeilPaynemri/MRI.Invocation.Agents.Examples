# Hosted Agent Test Variants

Six variants of a LangGraph-based Foundry hosted agent, each demonstrating a different feature. All share the same core: plan_node → llm_call → tools loop, `get_stream_writer()` custom events, `version="v2"` streaming, `agent_session_id` container affinity, App Insights logging, and a Streamlit UI.

## Prerequisites

These examples run on the new Foundry hosted agent backend (private preview). Before using anything in this repo you need:

1. **Clone the private preview repo** and run the setup:
   ```bash
   gh repo clone microsoft/hosted-agents-vnext-private-preview
   cd hosted-agents-vnext-private-preview
   .\install.ps1          # installs uv + foundry-agent CLI
   ./setup-environment.sh # provisions AI Services, ACR, App Insights, RBAC
   ```

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

### Protocol & SSE Events

All variants stream via `graph.astream()` with `stream_mode=["messages", "updates", "custom"]` and `version="v2"`. Each chunk has a `type` (`"messages"`, `"updates"`, or `"custom"`) that determines which SSE events it produces. The AG-UI variant translates these into a different event set.

#### Stream mode: `messages`

Fires for every LangChain message object (chunks during streaming, full messages at end).

| SSE event | Source object | Key fields | When |
|-----------|--------------|------------|------|
| `message_chunk` | `AIMessageChunk` | `node`, `content`, `tool_calls[]` | LLM is streaming text **or** deciding to call a tool. Tool calls appear as a `tool_calls` array on the chunk — there is no separate "tool_call" event. |
| `tool_result` | `ToolMessage` | `node`, `content`, `tool_call_id` | A tool has executed. `tool_call_id` links back to the `id` in the originating `message_chunk.tool_calls[]`. |
| `message` | `AIMessage` (non-chunk) | `node`, `content`, `tool_calls[]` | Complete AI message (less common in streaming — typically you see `message_chunk` instead). |

A typical tool-calling sequence:
1. `message_chunk` with `tool_calls: [{id: "call_123", name: "add", args: {a: 12, b: 8}}]` — LLM decided to call `add`
2. `tool_result` with `tool_call_id: "call_123"`, `content: "20"` — tool returned
3. More `message_chunk` events with `content` — LLM gives the final answer

#### Stream mode: `updates`

Fires once per node execution, summarising what changed in the graph state.

| SSE event | Key fields | When |
|-----------|------------|------|
| `node_update` | `node`, `messages[]` (summaries with `type`, `content_preview`, `tool_calls`, `tool_call_id`) | A graph node has finished. Useful for tracking execution order (plan_node → llm_call → tools → llm_call → ...). |

#### Stream mode: `custom`

Fires from `get_stream_writer()` calls inside graph nodes. Free-form dicts for UI status/progress.

| SSE event | Typical fields | When |
|-----------|---------------|------|
| `custom` | `status`, `node`, `detail` | Node emits progress. Examples: `{"status": "planning", "node": "plan_node", ...}`, `{"status": "tool_running", "node": "tools", "detail": "Calling add({a: 12, b: 8})"}` |

#### Control events (outside the stream loop)

| SSE event | When |
|-----------|------|
| `session` | First event — includes `invocation_id` and `thread_id` |
| `usage` | After the stream — token usage summary (`input_tokens`, `output_tokens`, `total_tokens`) |
| `done` | Final event — stream complete |
| `error` | Exception during graph execution |
| `cancelled` | Client cancelled the invocation |
| `approval_required` | *(approval variants only)* Graph hit `interrupt_before=["tools"]` — includes `tool_calls[]` for the client to approve/deny |

#### AG-UI protocol (`mcp_approval_ag-ui` only)

Translates the above into AG-UI events: `RUN_STARTED`, `TEXT_MESSAGE_CONTENT`, `TOOL_CALL_START`, `TOOL_CALL_ARGS`, `TOOL_CALL_END`, `TOOL_CALL_RESULT`, `CUSTOM`, `RUN_FINISHED`, etc.

## File Structure (each variant)

```
agent.yaml          # Agent metadata
graph.py            # LangGraph graph definition (nodes, tools, edges)
main.py             # HTTP server with SSE streaming endpoint
deploy.py           # Docker build + push + fresh agent creation
test_remote.py      # Automated 2-turn test against deployed agent
query_logs.py       # App Insights log querying via az rest
Dockerfile          # Python 3.12-slim container
requirements.txt    # Python dependencies (private-preview Azure SDK)
requirements-public.txt  # Public dependencies (if present — LangGraph, LangChain, etc.)
ui/app.py           # Streamlit chat UI
ui/requirements.txt # UI dependencies
.env.example        # Environment variable template
```

## Environment Setup

Each variant (and its `ui/` subfolder) needs its own virtual environment. Copy `.env.example` to `.env` and fill in your values, then from the variant's directory:

```bash
# Agent venv
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
pip install -r requirements-public.txt   # if present

# UI venv (from the ui/ folder)
cd ui
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` contains the private-preview Azure SDK packages (from the Azure DevOps feed). `requirements-public.txt` (present in MCP variants) contains the publicly available dependencies.

## Common Commands

All variants follow the same workflow. Activate the agent `.venv` first:

```bash
# With agent .venv activated:
python deploy.py                        # deploy (creates a fresh agent with unique hash suffix)
python test_remote.py                   # test (auto-updated by deploy.py with new agent name)
python query_logs.py                    # traces, last 2h
python query_logs.py --type exceptions  # exceptions
python query_logs.py --type all         # both
python query_logs.py --since 6h         # custom time range
```

For the Streamlit UI, activate the `ui/.venv` instead:

```bash
# With ui/.venv activated:
cd ui
streamlit run app.py
```
