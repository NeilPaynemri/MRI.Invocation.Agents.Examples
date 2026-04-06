# invoketest1_localtools_skipplannode — Plan Node Filtering

Same as the baseline (`invoketest1_localtools`) but filters plan_node messages out of the SSE stream. Plan content still flows as custom events for the "thoughts" panel.

## What This Demonstrates

- **Tools:** Local Python functions (`add`, `subtract`, `multiply`, `divide`) defined directly in `graph.py`
- **Interrupt:** None — graph runs to completion
- **Plan Node Filtering:** **Yes** — `main.py` skips messages where `metadata.get("langgraph_node") == "plan_node"` and filters `plan_node` from updates dicts
- **Protocol:** Standard SSE
- **Custom Events:** Plan_node still emits `planning` and `plan_complete` custom events — these are NOT filtered, so the thoughts panel still works

## Graph Flow

```
plan_node → llm_call → tools → llm_call → ... → done
```

(Same graph as baseline — the filtering happens at the HTTP/SSE layer in `main.py`, not in the graph itself.)

## How the Filtering Works

In `main.py`'s streaming loop:

```python
# Messages stream: skip plan_node
if metadata.get("langgraph_node") == "plan_node":
    continue

# Updates stream: remove plan_node key from dict
chunk_data = {k: v for k, v in chunk_data.items() if k != "plan_node"}
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

The **only variant that filters SSE output by node**. Shows how to use `metadata.get("langgraph_node")` to selectively suppress messages from specific graph nodes while keeping their custom events.
