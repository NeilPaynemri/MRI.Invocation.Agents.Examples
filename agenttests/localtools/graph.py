"""
LangGraph calculator agent: plan → llm_call → tools loop.

Pure graph definition — no server concerns.
Uses AzureChatOpenAI with DefaultAzureCredential or API key.
"""

import os
import logging
from urllib.parse import urlparse as _urlparse

from dotenv import load_dotenv

load_dotenv(override=True)

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential, get_bearer_token_provider

logger = logging.getLogger(__name__)


# ── Tools ────────────────────────────────────────────────────────────


@tool
def add(a: int, b: int) -> int:
    """Add a and b.

    Args:
        a: first int
        b: second int
    """
    return a + b


@tool
def subtract(a: int, b: int) -> int:
    """Subtract b from a.

    Args:
        a: first int
        b: second int
    """
    return a - b


@tool
def multiply(a: int, b: int) -> int:
    """Multiply a and b.

    Args:
        a: first int
        b: second int
    """
    return a * b


@tool
def divide(a: int, b: int) -> float:
    """Divide a by b.

    Args:
        a: first int
        b: second int
    """
    if b == 0:
        return float("inf")
    return a / b


tools = [add, subtract, multiply, divide]
tools_by_name = {t.name: t for t in tools}


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
        _llm_with_tools = get_llm().bind_tools(tools)
    return _llm_with_tools


# ── Prompts ──────────────────────────────────────────────────────────

PLAN_PROMPT = (
    "You are a planning assistant. Given the user's request, output a brief numbered plan "
    "of the steps you will take to solve it (which tools you will call and why). "
    "Be concise — 2-4 bullet points max. Output ONLY the plan, nothing else."
)

SYSTEM_PROMPT = (
    "You are a helpful assistant. You can perform arithmetic using add, subtract, multiply, "
    "and divide tools. Use the provided tools to compute results when needed. "
    "Be concise in your final answer. Always answer the user's question directly."
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
    has_tools = hasattr(response, "tool_calls") and response.tool_calls
    writer({"status": "llm_done", "node": "llm_call", "detail": f"LLM responded. Tool calls: {bool(has_tools)}"})
    return {"messages": [response]}


def tool_node(state: AgentState):
    """Execute tool calls from the last AI message."""
    writer = get_stream_writer()
    pending = [tc["name"] for tc in state["messages"][-1].tool_calls]
    writer({"status": "executing_tools", "node": "tools", "detail": f"Executing tools: {pending}"})
    results = []
    for tc in state["messages"][-1].tool_calls:
        tool_fn = tools_by_name[tc["name"]]
        writer({"status": "tool_running", "node": "tools", "detail": f"Calling {tc['name']}({tc['args']})"})
        observation = tool_fn.invoke(tc["args"])
        writer({"status": "tool_result", "node": "tools", "detail": f"{tc['name']} returned: {observation}"})
        results.append(ToolMessage(content=str(observation), tool_call_id=tc["id"]))
    return {"messages": results}


# ── Routing ──────────────────────────────────────────────────────────


def should_continue(state: AgentState):
    last = state["messages"][-1]
    if last.tool_calls:
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

    return builder.compile(checkpointer=MemorySaver())
