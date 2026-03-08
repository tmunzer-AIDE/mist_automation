"""
Admin API endpoints for system configuration and management.
"""

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from app.config import settings as settings_module
from app.core.security import decrypt_sensitive_data, encrypt_sensitive_data
from app.dependencies import get_current_user_from_token, require_admin
from app.models.system import AuditLog, SystemConfig
from app.models.user import User
from app.modules.automation.models.workflow import Workflow
from app.modules.automation.models.execution import WorkflowExecution
from app.modules.backup.models import BackupJob
from app.modules.automation.models.webhook import WebhookEvent
from app.modules.backup.object_registry import (
    ORG_OBJECTS,
    SITE_OBJECTS,
    get_all_object_type_options,
    get_object_name,
)
from app.modules.backup.services.backup_service import fetch_objects

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
        "webhook_secret": decrypt_sensitive_data(config.webhook_secret) if config.webhook_secret else None,
        # Smee.io
        "smee_enabled": config.smee_enabled,
        "smee_channel_url": config.smee_channel_url,
        "max_concurrent_workflows": config.max_concurrent_workflows,
        "workflow_default_timeout": config.workflow_default_timeout,
        # Password Policy
        "min_password_length": config.min_password_length,
        "require_uppercase": config.require_uppercase,
        "require_lowercase": config.require_lowercase,
        "require_digits": config.require_digits,
        "require_special_chars": config.require_special_chars,
        # Session Management
        "session_timeout_hours": config.session_timeout_hours,
        "max_concurrent_sessions": config.max_concurrent_sessions,
        # Backup Configuration
        "backup_enabled": config.backup_enabled,
        "backup_full_schedule_cron": config.backup_full_schedule_cron,
        "backup_retention_days": config.backup_retention_days,
        "backup_git_enabled": config.backup_git_enabled,
        "backup_git_repo_url": config.backup_git_repo_url,
        "backup_git_branch": config.backup_git_branch,
        "backup_git_author_name": config.backup_git_author_name,
        "backup_git_author_email": config.backup_git_author_email,
        # External Integrations
        "slack_webhook_url": config.slack_webhook_url,
        "servicenow_instance_url": config.servicenow_instance_url,
        "servicenow_username": config.servicenow_username,
        "servicenow_password_set": bool(config.servicenow_password),
        "pagerduty_api_key_set": bool(config.pagerduty_api_key),
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

    # Update allowed fields (encrypt sensitive values)
    if "mist_api_token" in settings:
        config.mist_api_token = encrypt_sensitive_data(settings["mist_api_token"])
    if "mist_org_id" in settings:
        config.mist_org_id = settings["mist_org_id"]
    if "mist_cloud_region" in settings:
        config.mist_cloud_region = settings["mist_cloud_region"]
    if "webhook_secret" in settings:
        config.webhook_secret = encrypt_sensitive_data(settings["webhook_secret"])
    if "max_concurrent_workflows" in settings:
        config.max_concurrent_workflows = settings["max_concurrent_workflows"]
    if "workflow_default_timeout" in settings:
        config.workflow_default_timeout = settings["workflow_default_timeout"]

    # Password Policy
    plain_fields = [
        "min_password_length", "require_uppercase", "require_lowercase",
        "require_digits", "require_special_chars",
        # Session Management
        "session_timeout_hours", "max_concurrent_sessions",
        # Backup Configuration
        "backup_enabled", "backup_full_schedule_cron", "backup_retention_days",
        "backup_git_enabled", "backup_git_repo_url", "backup_git_branch",
        "backup_git_author_name", "backup_git_author_email",
        # Smee.io
        "smee_enabled", "smee_channel_url",
        # External Integrations (non-sensitive)
        "slack_webhook_url", "servicenow_instance_url", "servicenow_username",
    ]
    for field in plain_fields:
        if field in settings:
            setattr(config, field, settings[field])

    # Sensitive integration fields
    if "servicenow_password" in settings:
        config.servicenow_password = encrypt_sensitive_data(settings["servicenow_password"])
    if "pagerduty_api_key" in settings:
        config.pagerduty_api_key = encrypt_sensitive_data(settings["pagerduty_api_key"])

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

    # If smee settings changed, notify the backup module
    if "smee_enabled" in settings or "smee_channel_url" in settings:
        from app.modules.backup.services.smee_service import start_smee, stop_smee
        refreshed = await SystemConfig.get_config()
        if refreshed.smee_enabled and refreshed.smee_channel_url:
            target = f"http://127.0.0.1:8000{settings_module.api_v1_prefix}/backups/webhooks/mist"
            await start_smee(refreshed.smee_channel_url, target)
        else:
            await stop_smee()

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
        api_token = decrypt_sensitive_data(config.mist_api_token)
        service = MistService(
            api_token=api_token,
            org_id=config.mist_org_id or "",
            cloud_region=config.mist_cloud_region or "us",
        )
        connected, error = await service.test_connection()
        return {"status": "connected" if connected else "failed", "error": error}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


@router.get("/admin/mist/sites", tags=["Admin"])
async def list_mist_sites(
    _current_user: User = Depends(get_current_user_from_token)
):
    """
    List sites from Mist organization.
    """
    config = await SystemConfig.get_config()
    if not config or not config.mist_api_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mist API not configured"
        )

    from app.services.mist_service import MistService
    try:
        api_token = decrypt_sensitive_data(config.mist_api_token)
        service = MistService(
            api_token=api_token,
            org_id=config.mist_org_id or "",
            cloud_region=config.mist_cloud_region or "global_01",
        )
        sites = await service.get_sites()
        return {"sites": [{"id": s.get("id"), "name": s.get("name", "")} for s in sites]}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch sites from Mist: {str(e)}"
        )


@router.get("/admin/mist/object-types", tags=["Admin"])
async def list_mist_object_types(
    _current_user: User = Depends(get_current_user_from_token)
):
    """
    Return all supported Mist object types for frontend dropdowns.
    """
    return {"object_types": get_all_object_type_options()}


@router.get("/admin/mist/objects", tags=["Admin"])
async def list_mist_objects(
    object_type: str = Query(..., description="Object type in 'org:key' or 'site:key' format"),
    site_id: str | None = Query(None, description="Site ID for site-level objects"),
    _current_user: User = Depends(get_current_user_from_token)
):
    """
    List objects of a given type from Mist organization.
    Uses the object registry for consistent API calls.
    """
    config = await SystemConfig.get_config()
    if not config or not config.mist_api_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mist API not configured"
        )

    # Parse scope and key
    if ":" not in object_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="object_type must be in 'org:key' or 'site:key' format"
        )

    scope, key = object_type.split(":", 1)
    if scope == "org":
        obj_def = ORG_OBJECTS.get(key)
    elif scope == "site":
        obj_def = SITE_OBJECTS.get(key)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scope '{scope}', must be 'org' or 'site'"
        )

    if not obj_def:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown object type: {object_type}"
        )

    if scope == "site" and not site_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="site_id is required for site-level objects"
        )

    from app.services.mist_service import MistService
    try:
        api_token = decrypt_sensitive_data(config.mist_api_token)
        service = MistService(
            api_token=api_token,
            org_id=config.mist_org_id or "",
            cloud_region=config.mist_cloud_region or "global_01",
        )

        fetch_kwargs = {}
        if scope == "site":
            fetch_kwargs["site_id"] = site_id
        else:
            fetch_kwargs["org_id"] = service.org_id

        raw = await fetch_objects(service.session, obj_def, **fetch_kwargs)
        objects = [
            {
                "id": o.get("id", key),
                "name": get_object_name(o, obj_def),
                "type": o.get("type", ""),
            }
            for o in raw
        ]

        return {"objects": objects}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch objects from Mist: {str(e)}"
        )


@router.get("/admin/workers/status", tags=["Admin"])
async def get_worker_status(
    _current_user: User = Depends(require_admin)
):
    """
    Get status of background workers (admin only).
    """
    from app.modules.automation.workers.scheduler import get_scheduler
    scheduler = get_scheduler()
    jobs = scheduler.get_scheduled_workflows() if scheduler._initialized else []
    return {
        "scheduler": {
            "status": "running" if scheduler._initialized else "stopped",
            "scheduled_workflows": len(jobs),
            "jobs": jobs,
        }
    }
