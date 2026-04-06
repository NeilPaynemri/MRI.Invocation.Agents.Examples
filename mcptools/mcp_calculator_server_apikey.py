"""
MCP server exposing calculator tools (add, multiply, divide) with a reasoning parameter,
protected by API key authentication.

Run locally:
    python mcp_calculator_server_apikey.py

Requires API key header "KEY" on every request.
Configure in Foundry as Key-based auth with key name "KEY".
"""

import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

API_KEY = os.environ.get("MCP_API_KEY", "SECRET")

mcp = FastMCP("CalculatorServer")


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        key = request.headers.get("KEY")
        if key != API_KEY:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


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
    app = mcp.streamable_http_app()
    app.add_middleware(ApiKeyMiddleware)

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
