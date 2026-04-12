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
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Iterator

from app.modules.digital_twin.models import SimulationLogEntry

_MAX_ENTRIES_PER_SESSION = 5000
_MAX_ACTIVE_SESSIONS = 500
_BUFFER_TTL = timedelta(hours=1)
_MAX_CONTEXT_DEPTH = 4
_MAX_CONTEXT_ITEMS = 50
_MAX_CONTEXT_STR_LEN = 300
_MAX_CONTEXT_CHARS = 3000

twin_session_id_var: ContextVar[str | None] = ContextVar("twin_session_id", default=None)
twin_session_phase_var: ContextVar[str | None] = ContextVar("twin_session_phase", default=None)

_buffers: dict[str, list[SimulationLogEntry]] = {}
_last_seen: dict[str, datetime] = {}
_buffers_lock = Lock()


def _truncate_context_value(value: Any, *, depth: int = 0) -> Any:
    """Bound context size/depth before persisting in memory and MongoDB."""
    if depth >= _MAX_CONTEXT_DEPTH:
        return "<truncated>"

    if isinstance(value, str):
        return value if len(value) <= _MAX_CONTEXT_STR_LEN else value[:_MAX_CONTEXT_STR_LEN] + "..."

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= _MAX_CONTEXT_ITEMS:
                result["__truncated__"] = f"{len(value) - _MAX_CONTEXT_ITEMS} more keys"
                break
            result[str(key)] = _truncate_context_value(item, depth=depth + 1)
        return result

    if isinstance(value, (list, tuple, set)):
        items = list(value)
        truncated = [_truncate_context_value(item, depth=depth + 1) for item in items[:_MAX_CONTEXT_ITEMS]]
        if len(items) > _MAX_CONTEXT_ITEMS:
            truncated.append(f"... ({len(items) - _MAX_CONTEXT_ITEMS} more items)")
        return truncated

    return value


def _sanitize_context(raw_context: dict[str, Any]) -> dict[str, Any]:
    context = _truncate_context_value(raw_context, depth=0)
    if not isinstance(context, dict):
        context = {"value": context}

    rendered = str(context)
    if len(rendered) > _MAX_CONTEXT_CHARS:
        return {"__truncated__": f"context exceeded {_MAX_CONTEXT_CHARS} chars"}
    return context


def _evict_buffers_locked(now: datetime) -> None:
    """Evict stale/excess session buffers while holding _buffers_lock."""
    cutoff = now - _BUFFER_TTL
    stale_ids = [sid for sid, ts in _last_seen.items() if ts < cutoff]
    for sid in stale_ids:
        _buffers.pop(sid, None)
        _last_seen.pop(sid, None)

    if len(_buffers) <= _MAX_ACTIVE_SESSIONS:
        return

    # Keep newest active sessions when cardinality exceeds the hard cap.
    overflow = len(_buffers) - _MAX_ACTIVE_SESSIONS
    oldest = sorted(_last_seen.items(), key=lambda item: item[1])[:overflow]
    for sid, _ in oldest:
        _buffers.pop(sid, None)
        _last_seen.pop(sid, None)


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
    context = _sanitize_context(
        {
            k: v for k, v in event_dict.items() if k not in {"event", "level", "timestamp"}
        }
    )

    entry = SimulationLogEntry(
        timestamp=datetime.now(timezone.utc),
        level=level if level in {"debug", "info", "warning", "error"} else "info",
        event=str(event),
        phase=phase if phase in {"simulate", "remediate", "approve", "execute", "other"} else "other",
        context=context,
    )

    with _buffers_lock:
        now = datetime.now(timezone.utc)
        _evict_buffers_locked(now)
        buf = _buffers.setdefault(session_id, [])
        buf.append(entry)
        _last_seen[session_id] = now
        if len(buf) > _MAX_ENTRIES_PER_SESSION:
            del buf[: len(buf) - _MAX_ENTRIES_PER_SESSION]

    return event_dict


def drain_buffer(session_id: str) -> list[SimulationLogEntry]:
    """Return and clear the log buffer for the given session id."""
    with _buffers_lock:
        _last_seen.pop(session_id, None)
        return _buffers.pop(session_id, [])
