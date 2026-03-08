"""
Admin API endpoints for system configuration and management.
"""

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from app.dependencies import require_admin
from app.models.system import AuditLog, SystemConfig
from app.models.user import User
from app.models.workflow import Workflow
from app.models.execution import WorkflowExecution
from app.models.backup import BackupJob
from app.models.webhook import WebhookEvent

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/admin/settings", tags=["Admin"])
async def get_system_settings(
    _current_user: User = Depends(require_admin)
):
    """
    Get system configuration settings (admin only).
    """
    # Get or create default config
    config = await SystemConfig.get_config()

    return {
        "mist_api_token_set": bool(config.mist_api_token),
        "mist_org_id": config.mist_org_id,
        "mist_cloud_region": config.mist_cloud_region,
        "webhook_secret_set": bool(config.webhook_secret),
        "max_concurrent_workflows": config.max_concurrent_workflows,
        "workflow_default_timeout": config.workflow_default_timeout,
        "updated_at": config.updated_at
    }


@router.put("/admin/settings", tags=["Admin"])
async def update_system_settings(
    settings: dict = Body(...),
    current_user: User = Depends(require_admin)
):
    """
    Update system configuration settings (admin only).
    """
    # Get or create config
    config = await SystemConfig.get_config()

    # Update allowed fields
    if "mist_api_token" in settings:
        config.mist_api_token = settings["mist_api_token"]
    if "mist_org_id" in settings:
        config.mist_org_id = settings["mist_org_id"]
    if "mist_cloud_region" in settings:
        config.mist_cloud_region = settings["mist_cloud_region"]
    if "webhook_secret" in settings:
        config.webhook_secret = settings["webhook_secret"]
    if "max_concurrent_workflows" in settings:
        config.max_concurrent_workflows = settings["max_concurrent_workflows"]
    if "workflow_default_timeout" in settings:
        config.workflow_default_timeout = settings["workflow_default_timeout"]

    config.update_timestamp()
    await config.save()

    logger.info("system_settings_updated", user_id=str(current_user.id))

    # Log audit trail
    await AuditLog.log_event(
        event_type="settings_updated",
        event_category="system",
        description="System settings updated",
        user_id=current_user.id,
        user_email=current_user.email,
        details={"updated_fields": list(settings.keys())}
    )

    return {"status": "success", "message": "Settings updated"}


@router.get("/admin/logs", tags=["Admin"])
async def get_audit_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    event_type: str | None = Query(None, description="Filter by event type"),
    user_id: str | None = Query(None, description="Filter by user ID"),
    _current_user: User = Depends(require_admin)
):
    """
    Get system audit logs (admin only).
    """
    # Build query
    query = {}
    if event_type:
        query["event_type"] = event_type
    if user_id:
        query["user_id"] = user_id

    # Get total count
    total = await AuditLog.find(query).count()

    # Get logs with pagination
    logs = await AuditLog.find(query).sort("-timestamp").skip(skip).limit(limit).to_list()

    return {
        "logs": [
            {
                "id": str(log.id),
                "event_type": log.event_type,
                "user_id": str(log.user_id) if log.user_id else None,
                "user_email": log.user_email,
                "source_ip": log.source_ip,
                "timestamp": log.timestamp,
                "details": log.details
            }
            for log in logs
        ],
        "total": total
    }


@router.get("/admin/stats", tags=["Admin"])
async def get_system_stats(
    _current_user: User = Depends(require_admin)
):
    """
    Get system statistics and metrics (admin only).
    """
    # Gather statistics from various collections
    stats = {
        "workflows": {
            "total": await Workflow.find().count(),
            "enabled": await Workflow.find(Workflow.status == "enabled").count(),
            "draft": await Workflow.find(Workflow.status == "draft").count()
        },
        "executions": {
            "total": await WorkflowExecution.find().count(),
            "pending": await WorkflowExecution.find(WorkflowExecution.status == "pending").count(),
            "running": await WorkflowExecution.find(WorkflowExecution.status == "running").count(),
            "succeeded": await WorkflowExecution.find(WorkflowExecution.status == "succeeded").count(),
            "failed": await WorkflowExecution.find(WorkflowExecution.status == "failed").count()
        },
        "backups": {
            "total": await BackupJob.find().count(),
            "completed": await BackupJob.find(BackupJob.status == "completed").count(),
            "pending": await BackupJob.find(BackupJob.status == "pending").count(),
            "failed": await BackupJob.find(BackupJob.status == "failed").count()
        },
        "webhooks": {
            "total": await WebhookEvent.find().count(),
            "processed": await WebhookEvent.find(WebhookEvent.processed == True).count(),
            "pending": await WebhookEvent.find(WebhookEvent.processed == False).count()
        },
        "users": {
            "total": await User.find().count(),
            "active": await User.find(User.is_active == True).count(),
            "admins": await User.find({"roles": "admin"}).count()
        }
    }

    return stats


@router.post("/admin/mist/test-connection", tags=["Admin"])
async def test_mist_connection(
    current_user: User = Depends(require_admin)
):
    """
    Test connection to Mist API (admin only).
    """
    # Get system config
    config = await SystemConfig.get_config()

    if not config or not config.mist_api_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mist API token not configured"
        )

    logger.info("mist_connection_test", user_id=str(current_user.id))

    from app.services.mist_service import MistService
    try:
        service = MistService(api_token=config.mist_api_token, org_id=config.mist_org_id or "")
        connected, error = await service.test_connection()
        return {"status": "connected" if connected else "failed", "error": error}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@router.get("/admin/workers/status", tags=["Admin"])
async def get_worker_status(
    _current_user: User = Depends(require_admin)
):
    """
    Get status of background workers (admin only).
    """
    from app.workers.scheduler import get_scheduler
    scheduler = get_scheduler()
    jobs = scheduler.get_scheduled_workflows() if scheduler._initialized else []
    return {
        "scheduler": {
            "status": "running" if scheduler._initialized else "stopped",
            "scheduled_workflows": len(jobs),
            "jobs": jobs,
        }
    }
