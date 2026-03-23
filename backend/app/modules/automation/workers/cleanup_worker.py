"""Cleanup worker — purges old workflow executions based on retention policy."""

from datetime import datetime, timedelta, timezone

import structlog

logger = structlog.get_logger(__name__)


async def cleanup_old_executions() -> dict:
    """Delete WorkflowExecution documents older than execution_retention_days."""
    from app.models.system import SystemConfig
    from app.modules.automation.models.execution import WorkflowExecution

    config = await SystemConfig.get_config()
    retention_days = config.execution_retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    result = await WorkflowExecution.find(WorkflowExecution.started_at < cutoff).delete()
    deleted = result.deleted_count if result else 0

    logger.info("execution_cleanup_completed", deleted_count=deleted, retention_days=retention_days)
    return {"deleted_count": deleted, "retention_days": retention_days}
