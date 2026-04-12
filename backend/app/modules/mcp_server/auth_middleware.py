"""
ASGI middleware that gates the MCP HTTP endpoint with JWT authentication.

Wraps the FastMCP HTTP ASGI app. Extracts Bearer token from the Authorization
header, validates JWT + session, and sets ``mcp_user_id_var`` before forwarding
to the inner app. Returns 401 JSON on auth failure.

In-process memory transport (``InProcessMCPClient``) is unaffected — it never
goes through ASGI.
"""

import json

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

from app.modules.mcp_server.server import mcp_user_id_var

logger = structlog.get_logger(__name__)


class MCPAuthMiddleware:
    """ASGI wrapper that authenticates HTTP requests to the MCP server."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Pass through lifespan, WebSocket, etc.
            await self.app(scope, receive, send)
            return

        # Extract Authorization header from ASGI scope
        token = self._extract_bearer_token(scope)
        if not token:
            await self._send_401(send, "Authentication required")
            return

        user_id = await self._authenticate(token)
        if not user_id:
            await self._send_401(send, "Invalid or expired token")
            return

        # Set user context for MCP tool handlers via token-based reset
        ctx_token = mcp_user_id_var.set(user_id)
        try:
            await self.app(scope, receive, send)
        finally:
            mcp_user_id_var.reset(ctx_token)

    @staticmethod
    def _extract_bearer_token(scope: Scope) -> str | None:
        """Extract Bearer token from ASGI scope headers."""
        for key, value in scope.get("headers", []):
            if key == b"authorization":
                auth = value.decode("latin-1")
                if auth.lower().startswith("bearer "):
                    return auth[7:].strip()
        return None

    @staticmethod
    async def _authenticate(token: str) -> str | None:
        """Validate JWT and return user_id string, or None on failure."""
        try:
            from app.core.security import decode_token
            from app.models.session import UserSession
            from app.models.user import User

            payload = decode_token(token)
            if not payload:
                return None

            user_id_str = payload.get("sub")
            token_jti = payload.get("jti")
            if not user_id_str or not token_jti:
                return None

            session = await UserSession.find_one(UserSession.token_jti == token_jti)
            if not session or session.is_expired():
                return None

            from bson import ObjectId

            user = await User.get(ObjectId(user_id_str))
            if not user or not user.is_active:
                return None

            return str(user.id)
        except Exception:
            logger.debug("mcp_auth_failed", exc_info=True)
            return None

    @staticmethod
    async def _send_401(send: Send, detail: str) -> None:
        """Send a 401 JSON response."""
        body = json.dumps({"error": detail}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"content-length", str(len(body)).encode()],
                ],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})
