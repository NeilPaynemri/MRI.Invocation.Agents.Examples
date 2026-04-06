"""Test graph locally — bypass Starlette/Foundry to isolate the multi-turn error."""
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", stream=sys.stdout)

from graph import build_graph, init_mcp_tools
from langchain_core.messages import HumanMessage


async def main():
    print("=== Initializing MCP tools ===")
    await init_mcp_tools()
    graph = build_graph()

    config = {"configurable": {"thread_id": "local-test-1"}}

    # Turn 1
    print("\n=== Turn 1: What is (12 + 8) * 3? ===")
    try:
        async for chunk in graph.astream(
            {"messages": [HumanMessage(content="What is (12 + 8) * 3?")], "user_id": ""},
            config=config,
            stream_mode=["messages", "updates"],
        ):
            chunk_type = chunk[0] if isinstance(chunk, tuple) else "?"
            if chunk_type == "updates":
                data = chunk[1]
                for node, state_delta in data.items():
                    if isinstance(state_delta, dict):
                        msgs = state_delta.get("messages", [])
                        for m in msgs:
                            print(f"  [{node}] {type(m).__name__}: {str(m.content)[:120]}")
    except Exception as e:
        print(f"  TURN 1 ERROR: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()

    # Turn 2
    print("\n=== Turn 2: Now divide that result by 10 ===")
    try:
        async for chunk in graph.astream(
            {"messages": [HumanMessage(content="Now divide that result by 10")], "user_id": ""},
            config=config,
            stream_mode=["messages", "updates"],
        ):
            chunk_type = chunk[0] if isinstance(chunk, tuple) else "?"
            if chunk_type == "updates":
                data = chunk[1]
                for node, state_delta in data.items():
                    if isinstance(state_delta, dict):
                        msgs = state_delta.get("messages", [])
                        for m in msgs:
                            print(f"  [{node}] {type(m).__name__}: {str(m.content)[:120]}")
    except Exception as e:
        print(f"  TURN 2 ERROR: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()

    print("\n=== Done ===")


asyncio.run(main())
