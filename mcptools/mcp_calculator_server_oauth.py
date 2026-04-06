"""
MCP server exposing calculator tools (add, multiply, divide) with OAuth Bearer token protection.

Run locally:
    python mcp_calculator_server_oauth.py

Starts an HTTP server on port 8001 using streamable-HTTP transport.
Expose via devtunnel for Foundry prompt agents to reach it.

OAuth configuration (via environment variables):
    OAUTH_SECRET       - HS256 shared secret for validating tokens (simple mode)
    OAUTH_JWKS_URI     - URI to fetch JWKS for RS256 validation (e.g. Azure AD)
    OAUTH_AUDIENCE     - Expected token audience (optional but recommended)
    OAUTH_ISSUER       - Expected token issuer (optional but recommended)

Set either OAUTH_SECRET (simple) or OAUTH_JWKS_URI (full OAuth provider like Azure AD / Entra ID).
"""

import os
import logging
from dotenv import load_dotenv
import httpx
import jwt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()
from jwt import PyJWKClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

OAUTH_SECRET = os.environ.get("OAUTH_SECRET")
OAUTH_JWKS_URI = os.environ.get("OAUTH_JWKS_URI")
OAUTH_AUDIENCE = os.environ.get("OAUTH_AUDIENCE")
OAUTH_ISSUER = os.environ.get("OAUTH_ISSUER")

if not OAUTH_SECRET and not OAUTH_JWKS_URI:
    raise RuntimeError("Set either OAUTH_SECRET or OAUTH_JWKS_URI environment variable.")

mcp = FastMCP("CalculatorServer")

_jwks_client: PyJWKClient | None = None
if OAUTH_JWKS_URI:
    _jwks_client = PyJWKClient(OAUTH_JWKS_URI)


class OAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning("401 - Missing or invalid Authorization header (got: %s)", auth_header[:30] if auth_header else "<empty>")
            return JSONResponse({"error": "Missing or invalid Authorization header"}, status_code=401)

        token = auth_header[len("Bearer "):]
        try:
            # Decode without verification first to log claims
            unverified = jwt.decode(token, options={"verify_signature": False})
            token_issuer = unverified.get("iss", "<none>")
            token_audience = unverified.get("aud", "<none>")
            logger.info("Token issuer: got=%s expected=%s", token_issuer, OAUTH_ISSUER or "<not checked>")
            logger.info("Token audience: got=%s expected=%s", token_audience, OAUTH_AUDIENCE or "<not checked>")

            if _jwks_client:
                signing_key = _jwks_client.get_signing_key_from_jwt(token)
                jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256"],
                    audience=OAUTH_AUDIENCE,
                    issuer=OAUTH_ISSUER,
                    options={"verify_aud": bool(OAUTH_AUDIENCE), "verify_iss": bool(OAUTH_ISSUER)},
                )
            else:
                jwt.decode(
                    token,
                    OAUTH_SECRET,
                    algorithms=["HS256"],
                    audience=OAUTH_AUDIENCE,
                    issuer=OAUTH_ISSUER,
                    options={"verify_aud": bool(OAUTH_AUDIENCE), "verify_iss": bool(OAUTH_ISSUER)},
                )
        except jwt.ExpiredSignatureError:
            logger.warning("401 - Token expired")
            return JSONResponse({"error": "Token expired"}, status_code=401)
        except jwt.InvalidTokenError as e:
            logger.warning("401 - Invalid token: %s", e)
            return JSONResponse({"error": f"Invalid token: {e}"}, status_code=401)

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
    app.add_middleware(OAuthMiddleware)

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
