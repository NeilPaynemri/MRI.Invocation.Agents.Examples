# invoketest1_localtools — Baseline

The simplest full example. Local tools, no interrupts, no filtering — everything streams through.

## What This Demonstrates

- **Tools:** Local Python functions (`add`, `subtract`, `multiply`, `divide`) defined directly in `graph.py`
- **Interrupt:** None — graph runs to completion
- **Plan Node Filtering:** No — plan_node messages appear in the SSE stream alongside all other nodes
- **Protocol:** Standard SSE (`message_chunk`, `node_update`, `tool_result`, `custom`, `done`)
- **Streaming:** `version="v2"` with `stream_mode=["messages", "updates", "custom"]`
- **Custom Events:** `get_stream_writer()` emits thinking/planning/tool status events on the `custom` channel

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
pip install -r requirements-public.txt   # if present

# UI venv (from the ui/ folder)
cd ui
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## How to Use

With the agent `.venv` activated:

```bash
python deploy.py                        # deploy (creates a fresh agent with unique hash suffix)
python test_remote.py                   # test
python query_logs.py                    # traces, last 2h
python query_logs.py --type all         # traces + exceptions
python query_logs.py --since 6h         # custom time range
```

For the Streamlit UI, activate the `ui/.venv` instead:

```bash
cd ui
streamlit run app.py
```

## Key Difference from Other Variants

This is the **baseline**. All other variants build on this pattern by adding one specific feature (HITL, plan filtering, MCP tools, approval gates, or AG-UI protocol).
