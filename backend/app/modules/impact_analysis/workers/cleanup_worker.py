"""Cleanup worker for old monitoring sessions.

Registered as an APScheduler nightly job at 3:30 UTC (offset from
execution cleanup at 3:00 UTC).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog

from app.models.system import SystemConfig
from app.modules.impact_analysis.models import MonitoringSession, SessionStatus

logger = structlog.get_logger(__name__)

# Terminal statuses eligible for cleanup
_TERMINAL_STATUSES = {
    SessionStatus.COMPLETED.value,
    SessionStatus.ALERT.value,
    SessionStatus.FAILED.value,
    SessionStatus.CANCELLED.value,
}


async def cleanup_old_sessions() -> int:
    """Delete monitoring sessions older than retention period.

    Returns the number of deleted sessions.
    """
    config = await SystemConfig.get_config()
    retention_days = config.impact_analysis_retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    result = await MonitoringSession.find(
        {"status": {"$in": list(_TERMINAL_STATUSES)}},
        MonitoringSession.created_at < cutoff,
    ).delete()

    deleted = result.deleted_count if result else 0
    if deleted > 0:
        logger.info("impact_sessions_cleaned", deleted=deleted, retention_days=retention_days)

    return deleted
