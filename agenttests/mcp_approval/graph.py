"""
LangGraph calculator agent: plan → llm_call → tools loop.

Pure graph definition — no server concerns.
Tools are loaded from a remote MCP calculator server via langchain-mcp-adapters.
Uses AzureChatOpenAI with DefaultAzureCredential or API key.
"""

import os
import logging
from urllib.parse import urlparse as _urlparse

from dotenv import load_dotenv

load_dotenv(override=True)

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential, get_bearer_token_provider
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger("azure.ai.agentserver.user_agent.graph")


# ── MCP Tools (loaded at startup via init_mcp_tools) ─────────────────

_mcp_client = None
tools = []
tools_by_name = {}


async def init_mcp_tools():
    """Connect to MCP server and load tools. Call once at startup."""
    global _mcp_client, tools, tools_by_name

    mcp_url = os.getenv("MCP_SERVER_URL", "https://13v11bnq-8000.uks1.devtunnels.ms/mcp")
    logger.info("Connecting to MCP server at %s", mcp_url)

    _mcp_client = MultiServerMCPClient(
        {
            "calculator": {
                "url": mcp_url,
                "transport": "streamable_http",
            }
        }
    )

    tools = await _mcp_client.get_tools()
    tools_by_name = {t.name: t for t in tools}
    logger.info("Loaded MCP tools: %s", list(tools_by_name.keys()))


# ── LLM setup ───────────────────────────────────────────────────────

_llm = None
_llm_with_tools = None


def get_llm() -> AzureChatOpenAI:
    global _llm
    if _llm is None:
        project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
        if not project_endpoint:
            raise ValueError("AZURE_AI_PROJECT_ENDPOINT environment variable must be set")

        parsed = _urlparse(project_endpoint)
        azure_openai_endpoint = os.getenv(
            "AZURE_OPENAI_ENDPOINT",
            f"{parsed.scheme}://{parsed.netloc}",
        )

        client_id = os.getenv("AZURE_CLIENT_ID")
        if client_id:
            logger.info("Using ManagedIdentityCredential with client_id=%s", client_id)
            credential = ManagedIdentityCredential(client_id=client_id)
        else:
            logger.info("Using DefaultAzureCredential (local dev)")
            credential = DefaultAzureCredential()

        token_provider = get_bearer_token_provider(
            credential,
            "https://cognitiveservices.azure.com/.default",
        )

        _llm = AzureChatOpenAI(
            model=os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini"),
            azure_endpoint=azure_openai_endpoint,
            azure_ad_token_provider=token_provider,
            api_version=os.getenv("OPENAI_API_VERSION", "2025-03-01-preview"),
            temperature=0,
        )
    return _llm


def get_llm_with_tools() -> AzureChatOpenAI:
    global _llm_with_tools
    if _llm_with_tools is None:
        if not tools:
            raise RuntimeError("MCP tools not initialized. Call init_mcp_tools() first.")
        _llm_with_tools = get_llm().bind_tools(tools)
    return _llm_with_tools


# ── Prompts ──────────────────────────────────────────────────────────

PLAN_PROMPT = (
    "You are a planning assistant. Given the user's request, output a brief numbered plan "
    "of the steps you will take to solve it (which tools you will call and why). "
    "Be concise — 2-4 bullet points max. Output ONLY the plan, nothing else."
)

SYSTEM_PROMPT = (
    "You are a helpful assistant. You can perform arithmetic using add, multiply, "
    "and divide tools available via a remote MCP server. Use the provided tools to compute "
    "results when needed. Be concise in your final answer. Always answer the user's question directly."
)


# ── State ────────────────────────────────────────────────────────────


class AgentState(MessagesState):
    """Graph state — messages + optional user identity."""
    user_id: str = ""


# ── Nodes ────────────────────────────────────────────────────────────


def _system_prompt(base: str, state: AgentState) -> str:
    """Prepend user identity to a system prompt if available."""
    user_id = state.get("user_id", "")
    logger.info("_system_prompt: user_id=%r", user_id)
    if user_id:
        prompt = f"The current user's name is: {user_id}\n\n{base}"
        logger.info("System prompt (first 200 chars): %s", prompt[:200])
        return prompt
    return base


def plan_node(state: AgentState):
    """LLM creates a plan for how to solve the user's request."""
    writer = get_stream_writer()
    writer({"status": "planning", "node": "plan_node", "detail": "Creating a plan for the user's request..."})
    response = get_llm().invoke(
        [SystemMessage(content=_system_prompt(PLAN_PROMPT, state))] + state["messages"]
    )
    plan_text = response.content if isinstance(response.content, str) else str(response.content)
    writer({"status": "plan_complete", "node": "plan_node", "detail": "Plan created."})
    return {
        "messages": [AIMessage(content=f"<plan>{plan_text}</plan>")],
    }


def llm_call(state: AgentState):
    """LLM decides whether to call a tool or give a final answer."""
    writer = get_stream_writer()
    writer({"status": "thinking", "node": "llm_call", "detail": "Deciding whether to call a tool or answer directly..."})
    response = get_llm_with_tools().invoke(
        [SystemMessage(content=_system_prompt(SYSTEM_PROMPT, state))] + state["messages"]
    )
    has_tools = bool(getattr(response, 'tool_calls', None))
    writer({"status": "llm_done", "node": "llm_call", "detail": f"LLM responded. Tool calls: {has_tools}"})
    return {"messages": [response]}


async def tool_node(state: AgentState):
    """Execute tool calls from the last AI message via MCP.

    Creates a fresh MCP client session each time so the connection is alive
    even when the graph resumes from an interrupt in a later request.
    """
    writer = get_stream_writer()
    mcp_url = os.getenv("MCP_SERVER_URL", "https://13v11bnq-8000.uks1.devtunnels.ms/mcp")
    client = MultiServerMCPClient(
        {"calculator": {"url": mcp_url, "transport": "streamable_http"}}
    )
    fresh_tools = await client.get_tools()
    fresh_by_name = {t.name: t for t in fresh_tools}

    tool_names = [tc["name"] for tc in state["messages"][-1].tool_calls]
    writer({"status": "executing_tools", "node": "tools", "detail": f"Executing tools: {tool_names}"})

    results = []
    for tc in state["messages"][-1].tool_calls:
        tool_fn = fresh_by_name.get(tc["name"])
        if tool_fn is None:
            results.append(ToolMessage(
                content=f"Error: unknown tool '{tc['name']}'",
                tool_call_id=tc["id"],
            ))
            continue
        writer({"status": "tool_running", "node": "tools", "detail": f"Calling {tc['name']}({tc['args']})"})
        observation = await tool_fn.ainvoke(tc["args"])
        writer({"status": "tool_result", "node": "tools", "detail": f"{tc['name']} returned: {observation}"})
        results.append(ToolMessage(content=str(observation), tool_call_id=tc["id"]))
    return {"messages": results}


# ── Routing ──────────────────────────────────────────────────────────


def should_continue(state: AgentState):
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END


# ── Build ────────────────────────────────────────────────────────────


def build_graph():
    builder = StateGraph(AgentState)

    builder.add_node("plan_node", plan_node)
    builder.add_node("llm_call", llm_call)
    builder.add_node("tools", tool_node)

    builder.add_edge(START, "plan_node")
    builder.add_edge("plan_node", "llm_call")
    builder.add_conditional_edges("llm_call", should_continue, {"tools": "tools", END: END})
    builder.add_edge("tools", "llm_call")

    return builder.compile(checkpointer=MemorySaver(), interrupt_before=["tools"])
