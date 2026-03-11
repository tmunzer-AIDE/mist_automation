"""
WebSocket endpoint with JWT authentication and channel-based pub/sub.
"""

import structlog
from fastapi import APIRouter, Query, WebSocketDisconnect
from starlette.websockets import WebSocket

from app.core.security import decode_token
from app.core.websocket import ws_manager
from app.models.session import UserSession

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = Query(...)):
    """Authenticated WebSocket with channel subscribe/unsubscribe."""
    # Validate JWT
    payload = decode_token(token)
    if not payload:
        await ws.close(code=4001, reason="Invalid token")
        return

    token_jti = payload.get("jti")
    if not token_jti:
        await ws.close(code=4001, reason="Invalid token claims")
        return

    session = await UserSession.find_one(UserSession.token_jti == token_jti)
    if not session or session.is_expired():
        await ws.close(code=4001, reason="Session expired")
        return

    await ws.accept()
    ws_manager.connect(ws)
    logger.info("ws_authenticated", user_id=payload.get("sub"))

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
