"""
MCP server exposing calculator tools (add, multiply, divide) with a reasoning parameter.

Run locally:
    python mcp_calculator_server.py

Starts an HTTP server on port 8000 using streamable-HTTP transport.
Expose via devtunnel for Foundry prompt agents to reach it.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("CalculatorServer")


@mcp.tool()
def multiply(a: int, b: int, reasoning: str = "") -> int:
    """Multiply a and b.

    Args:
        a: first int
        b: second int
        reasoning: Your reasoning for why you are calling this tool
    """
    return a * b


@mcp.tool()
def add(a: int, b: int, reasoning: str = "") -> int:
    """Adds a and b.

    Args:
        a: first int
        b: second int
        reasoning: Your reasoning for why you are calling this tool
    """
    return a + b


@mcp.tool()
def divide(a: int, b: int, reasoning: str = "") -> float:
    """Divide a and b.

    Args:
        a: first int
        b: second int
        reasoning: Your reasoning for why you are calling this tool
    """
    if b == 0:
        return float("inf")
    return a / b


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
