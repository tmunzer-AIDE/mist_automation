"""
ASGI middleware that gates the MCP HTTP endpoint with Bearer authentication.

Wraps the FastMCP HTTP ASGI app. Extracts the Bearer token from the
Authorization header and validates it via one of two paths:

- **Personal Access Token** (``mist_pat_...``) — long-lived, hashed, user-scoped
  credential used by external MCP clients (Claude Desktop, VS Code, Cursor).
  See ``app/models/personal_access_token.py``.
- **JWT session token** — short-lived token issued via ``/api/v1/auth/login``,
  used by the in-app chat and other first-party callers.

On success, sets ``mcp_user_id_var`` before forwarding to the inner app.
Returns 401 JSON on auth failure.

In-process memory transport (``InProcessMCPClient``) is unaffected — it never
goes through ASGI.
"""

import json
from datetime import datetime, timezone

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

    @classmethod
    async def _authenticate(cls, token: str) -> str | None:
        """Validate a Bearer token (PAT or JWT). Return user_id or None."""
        from app.core.pat import is_pat_token

        try:
            if is_pat_token(token):
                return await cls._authenticate_pat(token)
            return await cls._authenticate_jwt(token)
        except Exception:
            logger.debug("mcp_auth_failed", exc_info=True)
            return None

    @staticmethod
    async def _authenticate_pat(token: str) -> str | None:
        """Validate a PAT and return the owning user_id."""
        from app.core.pat import hash_pat
        from app.core.tasks import create_background_task
        from app.models.personal_access_token import PersonalAccessToken
        from app.models.user import User

        pat = await PersonalAccessToken.find_one(PersonalAccessToken.token_hash == hash_pat(token))
        if not pat or not pat.is_usable():
            return None

        user = await User.get(pat.user_id)
        if not user or not user.is_active:
            return None

        create_background_task(_touch_pat_last_used(pat), name="pat_last_used")
        logger.debug("mcp_auth_via_pat", user_id=str(user.id), pat_id=str(pat.id))
        return str(user.id)

    @staticmethod
    async def _authenticate_jwt(token: str) -> str | None:
        """Validate a JWT session token and return the owning user_id."""
        from bson import ObjectId

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

        user = await User.get(ObjectId(user_id_str))
        if not user or not user.is_active:
            return None

        logger.debug("mcp_auth_via_jwt", user_id=str(user.id))
        return str(user.id)

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


async def _touch_pat_last_used(pat) -> None:  # type: ignore[no-untyped-def]
    """Update ``last_used_at`` on a PAT without blocking the request."""
    from app.models.personal_access_token import PersonalAccessToken

    try:
        await PersonalAccessToken.find_one(PersonalAccessToken.id == pat.id).update(
            {"$set": {"last_used_at": datetime.now(timezone.utc)}}
        )
    except Exception:
        logger.debug("pat_last_used_update_failed", pat_id=str(pat.id), exc_info=True)
