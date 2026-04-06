# invoketest1_localtools_hitl — Human-in-the-Loop

Demonstrates programmatic interrupts using LangGraph's `interrupt()` primitive to pause execution and collect user input mid-graph.

## What This Demonstrates

- **Tools:** Local Python functions (`add`, `subtract`, `multiply`, `divide`) defined directly in `graph.py`
- **Interrupt:** `interrupt()` called inside `style_check` node — pauses after the LLM produces an answer to ask the user how they want it delivered (rhyme or normal)
- **Plan Node Filtering:** No — plan_node messages appear in the SSE stream
- **Protocol:** Standard SSE
- **Resume:** Client sends `Command(resume="rhyme")` or `Command(resume="normal")` to continue

## Graph Flow

```
plan_node → llm_call → tools → llm_call → style_check ──INTERRUPT──> (user chooses) → style_rewrite → done
```

## How the Interrupt Works

1. LLM computes the answer (e.g. "60")
2. `style_check` node calls `interrupt({"question": "How should I respond?", "options": ["rhyme", "normal"]})` 
3. Graph pauses, SSE sends the interrupt payload to the client
4. Client resumes with the user's choice via `Command(resume=value)`
5. `style_rewrite` node reformats the answer in the chosen style

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

Uses **programmatic `interrupt()`** inside a node function — the interrupt returns a value from the user (not just approve/deny). Compare with `mcp_approval` which uses **declarative `interrupt_before=["tools"]`** for a simple gate.
