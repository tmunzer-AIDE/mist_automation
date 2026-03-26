"""In-memory ring buffer and WebSocket broadcaster for system logs."""

from collections import deque
from typing import Any

_log_buffer: deque[dict[str, Any]] = deque(maxlen=500)


async def broadcast_log_entry(entry: dict[str, Any]) -> None:
    """Append to ring buffer and broadcast to subscribed admin clients."""
    from app.core.websocket import ws_manager

    _log_buffer.append(entry)
    await ws_manager.broadcast("logs:system", {"type": "log_entry", "data": entry})


def get_recent_logs(limit: int = 500) -> list[dict[str, Any]]:
    """Return the most recent log entries from the ring buffer."""
    return list(_log_buffer)[-limit:]
