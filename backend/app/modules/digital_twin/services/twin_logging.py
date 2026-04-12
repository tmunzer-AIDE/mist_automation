"""Structlog processor + context bindings for per-session log capture.

Usage:
    with bind_twin_session(session_id, phase="simulate"):
        ... run structlog.get_logger().info("event", key=value) ...

    entries = drain_buffer(session_id)
    session.simulation_logs.extend(entries)
    await session.save()
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Iterator

from app.modules.digital_twin.models import SimulationLogEntry

_MAX_ENTRIES_PER_SESSION = 1000

twin_session_id_var: ContextVar[str | None] = ContextVar("twin_session_id", default=None)
twin_session_phase_var: ContextVar[str | None] = ContextVar("twin_session_phase", default=None)

_buffers: dict[str, list[SimulationLogEntry]] = {}
_buffers_lock = Lock()


@contextmanager
def bind_twin_session(session_id: str, phase: str) -> Iterator[None]:
    """Bind session id and phase to the current logging context."""
    sid_token = twin_session_id_var.set(session_id)
    phase_token = twin_session_phase_var.set(phase)
    try:
        yield
    finally:
        twin_session_phase_var.reset(phase_token)
        twin_session_id_var.reset(sid_token)


def capture_twin_session_logs(
    _logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Structlog processor — appends the event to the per-session buffer if bound.

    Must be inserted into the structlog pipeline BEFORE the final renderer.
    """
    session_id = twin_session_id_var.get()
    if not session_id:
        return event_dict

    phase = twin_session_phase_var.get() or "other"
    event = event_dict.get("event", "")
    level = event_dict.get("level", method_name) or method_name
    context = {
        k: v for k, v in event_dict.items() if k not in {"event", "level", "timestamp"}
    }

    entry = SimulationLogEntry(
        timestamp=datetime.now(timezone.utc),
        level=level if level in {"debug", "info", "warning", "error"} else "info",
        event=str(event),
        phase=phase if phase in {"simulate", "remediate", "approve", "execute", "other"} else "other",
        context=context,
    )

    with _buffers_lock:
        buf = _buffers.setdefault(session_id, [])
        buf.append(entry)
        if len(buf) > _MAX_ENTRIES_PER_SESSION:
            del buf[: len(buf) - _MAX_ENTRIES_PER_SESSION]

    return event_dict


def drain_buffer(session_id: str) -> list[SimulationLogEntry]:
    """Return and clear the log buffer for the given session id."""
    with _buffers_lock:
        return _buffers.pop(session_id, [])
