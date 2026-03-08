"""
Backup execution logger — writes to both structlog and MongoDB.
"""

from datetime import datetime, timezone
from typing import Any

import structlog
from beanie import PydanticObjectId

from app.modules.backup.models import BackupLogEntry

logger = structlog.get_logger(__name__)


class BackupLogger:
    """Logs backup execution events to structlog and persists them as BackupLogEntry documents."""

    def __init__(self, backup_job_id: str | PydanticObjectId):
        self.backup_job_id = PydanticObjectId(backup_job_id) if isinstance(backup_job_id, str) else backup_job_id

    async def info(self, phase: str, message: str, **kwargs: Any) -> None:
        await self._log("info", phase, message, **kwargs)

    async def warning(self, phase: str, message: str, **kwargs: Any) -> None:
        await self._log("warning", phase, message, **kwargs)

    async def error(self, phase: str, message: str, **kwargs: Any) -> None:
        await self._log("error", phase, message, **kwargs)

    async def _log(self, level: str, phase: str, message: str, **kwargs: Any) -> None:
        # Structlog output
        log_fn = getattr(logger, level, logger.info)
        log_fn(
            message,
            backup_job_id=str(self.backup_job_id),
            phase=phase,
            **{k: v for k, v in kwargs.items() if k not in ("details",)},
        )

        # Persist to MongoDB
        entry = BackupLogEntry(
            backup_job_id=self.backup_job_id,
            timestamp=datetime.now(timezone.utc),
            level=level,
            phase=phase,
            message=message,
            object_type=kwargs.get("object_type"),
            object_id=kwargs.get("object_id"),
            object_name=kwargs.get("object_name"),
            site_id=kwargs.get("site_id"),
            details=kwargs.get("details"),
        )
        try:
            await entry.insert()
        except Exception as exc:
            logger.warning("backup_log_entry_insert_failed", error=str(exc))
