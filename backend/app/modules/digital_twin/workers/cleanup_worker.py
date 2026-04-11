"""Cleanup worker for old twin sessions.

Registered as an APScheduler nightly job at 4:00 UTC (offset from
impact analysis cleanup at 3:30 UTC).

Note: TwinSession also has a 7-day TTL index on created_at, so MongoDB
handles automatic expiry. This worker provides explicit cleanup for
terminal sessions that may have been created before the TTL was set.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog

from app.modules.digital_twin.models import TwinSession, TwinSessionStatus

logger = structlog.get_logger(__name__)

_TERMINAL_STATUSES = {
    TwinSessionStatus.DEPLOYED.value,
    TwinSessionStatus.REJECTED.value,
    TwinSessionStatus.FAILED.value,
}


async def cleanup_old_twin_sessions(retention_days: int = 7) -> int:
    """Delete twin sessions older than retention period.

    Returns the number of deleted sessions.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    result = await TwinSession.find(
        {"status": {"$in": list(_TERMINAL_STATUSES)}},
        TwinSession.created_at < cutoff,
    ).delete()

    deleted = result.deleted_count if result else 0
    if deleted > 0:
        logger.info("twin_sessions_cleaned", deleted=deleted, retention_days=retention_days)

    return deleted
