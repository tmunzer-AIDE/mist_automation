"""Per-session logger for impact analysis diagnostics.

Follows the BackupLogger pattern: writes to both structlog (console) and
MongoDB (SessionLogEntry collection) for per-session queryable logs.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.modules.impact_analysis.models import SessionLogEntry

logger = structlog.get_logger(__name__)


class SessionLogger:
    """Logs impact analysis events to structlog and persists them per session."""

    def __init__(self, session_id: str):
        self.session_id = session_id

    async def info(self, phase: str, message: str, **kwargs: Any) -> None:
        await self._log("info", phase, message, **kwargs)

    async def warning(self, phase: str, message: str, **kwargs: Any) -> None:
        await self._log("warning", phase, message, **kwargs)

    async def error(self, phase: str, message: str, **kwargs: Any) -> None:
        await self._log("error", phase, message, **kwargs)

    async def debug(self, phase: str, message: str, **kwargs: Any) -> None:
        await self._log("debug", phase, message, **kwargs)

    async def api_call(self, phase: str, endpoint: str, status_code: int, data_summary: Any = None) -> None:
        """Log a Mist API call with response summary."""
        await self._log(
            "debug",
            phase,
            f"API {endpoint} -> {status_code}",
            details={"endpoint": endpoint, "status_code": status_code, "data_summary": data_summary},
        )

    async def _log(self, level: str, phase: str, message: str, **kwargs: Any) -> None:
        details = kwargs.pop("details", None)

        # Structlog output (console)
        log_fn = getattr(logger, level, logger.info)
        log_fn(
            message,
            session_id=self.session_id,
            phase=phase,
            **{k: v for k, v in kwargs.items() if k != "details"},
        )

        # Persist to MongoDB
        entry = SessionLogEntry(
            session_id=self.session_id,
            level=level,
            phase=phase,
            message=message,
            details=details,
        )
        try:
            await entry.insert()
        except Exception as exc:
            logger.warning("session_log_insert_failed", session_id=self.session_id, error=str(exc))
