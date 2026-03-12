"""
WebSocket endpoint with first-message JWT authentication and channel-based pub/sub.

The frontend sends { "type": "auth", "token": "<jwt>" } as the first message
after connection open. The token is validated and the server responds with
{ "type": "auth_ok" } or { "type": "auth_error" } before any channel operations
are allowed.
"""

import asyncio

import structlog
from fastapi import APIRouter, WebSocketDisconnect
from starlette.websockets import WebSocket

from app.core.security import decode_token
from app.core.websocket import ws_manager
from app.models.session import UserSession

router = APIRouter()
logger = structlog.get_logger(__name__)

AUTH_TIMEOUT_SECONDS = 10


async def _authenticate(ws: WebSocket) -> dict | None:
    """Wait for the auth message and validate the JWT. Returns the token payload or None."""
    try:
        data = await asyncio.wait_for(ws.receive_json(), timeout=AUTH_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.warning("ws_auth_timeout")
        await ws.send_json({"type": "auth_error", "reason": "Auth timeout"})
        await ws.close(code=4001, reason="Auth timeout")
        return None

    if data.get("type") != "auth" or not data.get("token"):
        await ws.send_json({"type": "auth_error", "reason": "Expected auth message"})
        await ws.close(code=4001, reason="Expected auth message")
        return None

    payload = decode_token(data["token"])
    if not payload:
        await ws.send_json({"type": "auth_error", "reason": "Invalid token"})
        await ws.close(code=4001, reason="Invalid token")
        return None

    token_jti = payload.get("jti")
    if not token_jti:
        await ws.send_json({"type": "auth_error", "reason": "Invalid token claims"})
        await ws.close(code=4001, reason="Invalid token claims")
        return None

    session = await UserSession.find_one(UserSession.token_jti == token_jti)
    if not session or session.is_expired():
        await ws.send_json({"type": "auth_error", "reason": "Session expired"})
        await ws.close(code=4001, reason="Session expired")
        return None

    return payload


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """Authenticated WebSocket with channel subscribe/unsubscribe.

    Protocol:
    1. Server accepts the raw connection.
    2. Client sends { "type": "auth", "token": "<jwt>" } within 10 seconds.
    3. Server responds { "type": "auth_ok" } on success or { "type": "auth_error" } on failure.
    4. After auth, client may send subscribe/unsubscribe/pong messages.
    """
    await ws.accept()

    # --- First-message authentication ---
    payload = await _authenticate(ws)
    if not payload:
        return

    await ws.send_json({"type": "auth_ok"})
    ws_manager.connect(ws)
    logger.info("ws_authenticated", user_id=payload.get("sub"))

    # --- Message loop ---
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type") or data.get("action")

            if msg_type == "pong":
                ws_manager.record_pong(ws)
            elif msg_type == "subscribe":
                channel = data.get("channel")
                if channel:
                    ws_manager.subscribe(ws, channel)
            elif msg_type == "unsubscribe":
                channel = data.get("channel")
                if channel:
                    ws_manager.unsubscribe(ws, channel)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("ws_error", error=str(e))
    finally:
        ws_manager.disconnect(ws)
