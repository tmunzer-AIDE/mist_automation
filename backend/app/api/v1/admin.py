"""
Admin API endpoints for system configuration and management.
"""

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status

from app.api.v1.system_health import collect_system_health
from app.config import settings as settings_module
from app.core.security import decrypt_sensitive_data, encrypt_sensitive_data
from app.dependencies import require_admin
from app.models.system import AuditLog, SystemConfig
from app.models.user import User
from app.modules.automation.models.execution import WorkflowExecution
from app.modules.automation.models.webhook import WebhookEvent
from app.modules.automation.models.workflow import Workflow
from app.modules.backup.models import BackupJob
from app.modules.backup.object_registry import (
    ORG_OBJECTS,
    SITE_OBJECTS,
    get_all_object_type_options,
    get_object_name,
)
from app.modules.backup.services.backup_service import fetch_objects
from app.schemas.admin import SystemSettingsUpdate

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/admin/settings", tags=["Admin"])
async def get_system_settings(_current_user: User = Depends(require_admin)):
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
        "execution_retention_days": config.execution_retention_days,
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
        "slack_signing_secret_set": bool(config.slack_signing_secret),
        # Email / SMTP
        "smtp_host": config.smtp_host,
        "smtp_port": config.smtp_port,
        "smtp_username": config.smtp_username,
        "smtp_password_set": bool(config.smtp_password),
        "smtp_from_email": config.smtp_from_email,
        "smtp_use_tls": config.smtp_use_tls,
        # Webhook
        "webhook_ip_whitelist": config.webhook_ip_whitelist,
        # System
        "maintenance_mode": config.maintenance_mode,
        # LLM (global toggle — configs managed via /llm/configs)
        "llm_enabled": config.llm_enabled,
        # Telemetry
        "telemetry_enabled": config.telemetry_enabled,
        "influxdb_url": config.influxdb_url,
        "influxdb_token_set": bool(config.influxdb_token),
        "influxdb_org": config.influxdb_org,
        "influxdb_bucket": config.influxdb_bucket,
        "telemetry_retention_days": config.telemetry_retention_days,
        "updated_at": config.updated_at,
    }


@router.put("/admin/settings", tags=["Admin"])
async def update_system_settings(
    settings: SystemSettingsUpdate = Body(...), current_user: User = Depends(require_admin)
):
    """
    Update system configuration settings (admin only).
    """
    # Get or create config
    config = await SystemConfig.get_config()

    # Only process fields that were explicitly sent in the request
    updates = settings.model_dump(exclude_unset=True)

    # Encrypt sensitive fields
    sensitive_encrypt = {
        "mist_api_token",
        "webhook_secret",
        "servicenow_password",
        "pagerduty_api_key",
        "slack_signing_secret",
        "smtp_password",
        "influxdb_token",
    }
    for field, value in updates.items():
        if field in sensitive_encrypt:
            if value and (not isinstance(value, str) or value.strip()):  # Non-empty: encrypt and store
                setattr(config, field, encrypt_sensitive_data(value))
            else:  # Empty/None: clear the field
                setattr(config, field, None)
        else:
            setattr(config, field, value)

    config.update_timestamp()
    await config.save()

    # Invalidate maintenance mode cache if changed
    if "maintenance_mode" in updates:
        from app.core.middleware import set_maintenance_cache

        set_maintenance_cache(bool(updates["maintenance_mode"]))

    # Invalidate cached Mist config so next API call picks up changes
    mist_config_fields = {"mist_api_token", "mist_org_id", "mist_cloud_region"}
    if mist_config_fields & set(updates.keys()):
        from app.services.mist_service_factory import invalidate_mist_config_cache

        invalidate_mist_config_cache()

    logger.info("system_settings_updated", user_id=str(current_user.id))

    # Log audit trail
    await AuditLog.log_event(
        event_type="settings_updated",
        event_category="system",
        description="System settings updated",
        user_id=current_user.id,
        user_email=current_user.email,
        details={"updated_fields": list(updates.keys())},
    )

    # If backup schedule changed, update the scheduler
    if "backup_enabled" in updates or "backup_full_schedule_cron" in updates:
        try:
            from app.workers import get_scheduler

            scheduler = get_scheduler()
            refreshed = await SystemConfig.get_config()
            if refreshed.backup_enabled and refreshed.backup_full_schedule_cron:
                await scheduler.schedule_backup(refreshed.backup_full_schedule_cron)
            else:
                await scheduler.unschedule_backup()
        except Exception as e:
            logger.warning("backup_schedule_update_failed", error=str(e))

    # If smee settings changed, notify the backup module
    if "smee_enabled" in updates or "smee_channel_url" in updates:
        from app.core.smee_service import start_smee, stop_smee

        refreshed = await SystemConfig.get_config()
        if refreshed.smee_enabled and refreshed.smee_channel_url:
            target = f"http://127.0.0.1:8000{settings_module.api_v1_prefix}/webhooks/mist"
            await start_smee(refreshed.smee_channel_url, target)
        else:
            await stop_smee()

    return {"status": "success", "message": "Settings updated"}


def _audit_log_to_dict(log: AuditLog) -> dict:
    """Build a response dict from an AuditLog document."""
    return {
        "id": str(log.id),
        "event_type": log.event_type,
        "event_category": log.event_category,
        "description": log.description,
        "user_id": str(log.user_id) if log.user_id else None,
        "user_email": log.user_email,
        "source_ip": log.source_ip,
        "target_type": log.target_type,
        "target_id": log.target_id,
        "target_name": log.target_name,
        "success": log.success,
        "timestamp": log.timestamp.isoformat() if log.timestamp else None,
        "details": log.details,
    }


def _build_audit_query(
    event_type: str | None = None,
    user_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Build a MongoDB query dict for audit log filtering."""
    query: dict = {}
    if event_type:
        query["event_type"] = event_type
    if user_id:
        query["user_id"] = user_id
    if start_date or end_date:
        from datetime import datetime, timezone

        def _parse_date(value: str) -> datetime:
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid date format: {value!r}"
                ) from e
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt

        ts_query: dict = {}
        if start_date:
            ts_query["$gte"] = _parse_date(start_date)
        if end_date:
            ts_query["$lte"] = _parse_date(end_date)
        query["timestamp"] = ts_query
    return query


@router.get("/admin/system-logs", tags=["Admin"])
async def get_system_logs(
    limit: int = Query(default=500, ge=1, le=500),
    _current_user: User = Depends(require_admin),
):
    """Get recent system logs from the in-memory ring buffer."""
    from app.core.log_broadcaster import get_recent_logs

    return {"logs": get_recent_logs(limit)}


@router.get("/admin/logs", tags=["Admin"])
async def get_audit_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    event_type: str | None = Query(None, description="Filter by event type"),
    user_id: str | None = Query(None, description="Filter by user ID"),
    start_date: str | None = Query(None, description="Start date (ISO 8601)"),
    end_date: str | None = Query(None, description="End date (ISO 8601)"),
    _current_user: User = Depends(require_admin),
):
    """
    Get system audit logs with optional date range filtering (admin only).
    """
    query = _build_audit_query(event_type, user_id, start_date, end_date)
    total = await AuditLog.find(query).count()
    logs = await AuditLog.find(query).sort("-timestamp").skip(skip).limit(limit).to_list()

    return {
        "logs": [_audit_log_to_dict(log) for log in logs],
        "total": total,
    }


@router.post("/admin/logs/export", tags=["Admin"])
async def export_audit_logs(
    request: Request,
    _current_user: User = Depends(require_admin),
):
    """
    Export audit logs as CSV with optional filters (admin only).
    """
    import csv
    import io
    import json
    from datetime import datetime, timezone

    from starlette.responses import StreamingResponse

    try:
        body = await request.json()
    except Exception:
        body = {}

    query = _build_audit_query(
        event_type=body.get("event_type"),
        user_id=body.get("user_id"),
        start_date=body.get("start_date"),
        end_date=body.get("end_date"),
    )

    filename = f"audit_logs_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.csv"

    async def _generate_csv():
        """Stream CSV in batches to avoid loading all rows into memory."""
        header = io.StringIO()
        csv.writer(header).writerow(
            [
                "Timestamp",
                "Event Type",
                "Category",
                "Description",
                "User Email",
                "Source IP",
                "Target Type",
                "Target Name",
                "Success",
                "Details",
            ]
        )
        yield header.getvalue().encode("utf-8")

        batch_size = 5000
        skip = 0
        while True:
            batch = await AuditLog.find(query).sort("-timestamp").skip(skip).limit(batch_size).to_list()
            if not batch:
                break

            chunk = io.StringIO()
            writer = csv.writer(chunk)
            for log in batch:
                writer.writerow(
                    [
                        log.timestamp.isoformat() if log.timestamp else "",
                        log.event_type or "",
                        log.event_category or "",
                        log.description or "",
                        log.user_email or "",
                        log.source_ip or "",
                        log.target_type or "",
                        log.target_name or "",
                        "Yes" if log.success else "No",
                        json.dumps(log.details, default=str) if log.details else "",
                    ]
                )
            yield chunk.getvalue().encode("utf-8")

            skip += batch_size
            if len(batch) < batch_size or skip >= 50_000:
                break

    return StreamingResponse(
        _generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/stats", tags=["Admin"])
async def get_system_stats(_current_user: User = Depends(require_admin)):
    """
    Get system statistics and metrics (admin only).
    Uses $facet aggregation to reduce DB round-trips.
    """

    from app.utils.db_helpers import facet_counts as _facet_counts

    wf_stats = await _facet_counts(Workflow, "status", ["enabled", "draft"])
    ex_stats = await _facet_counts(WorkflowExecution, "status", ["pending", "running", "succeeded", "failed"])
    bk_stats = await _facet_counts(BackupJob, "status", ["completed", "pending", "failed"])

    # Webhooks: boolean field needs dedicated facet (can't use generic helper with bool keys)
    wh_facet = await WebhookEvent.aggregate(
        [
            {
                "$facet": {
                    "total": [{"$count": "n"}],
                    "processed": [{"$match": {"processed": True}}, {"$count": "n"}],
                    "pending": [{"$match": {"processed": False}}, {"$count": "n"}],
                }
            }
        ]
    ).to_list()
    wh_row = wh_facet[0] if wh_facet else {}

    # Users: count by roles + is_active
    user_facet = await User.aggregate(
        [
            {
                "$facet": {
                    "total": [{"$count": "n"}],
                    "active": [{"$match": {"is_active": True}}, {"$count": "n"}],
                    "admins": [{"$match": {"roles": "admin"}}, {"$count": "n"}],
                }
            }
        ]
    ).to_list()
    ur = user_facet[0] if user_facet else {}

    def _extract(row: dict, key: str) -> int:
        bucket = row.get(key, [])
        return bucket[0]["n"] if bucket else 0

    return {
        "workflows": wf_stats,
        "executions": ex_stats,
        "backups": bk_stats,
        "webhooks": {
            "total": _extract(wh_row, "total"),
            "processed": _extract(wh_row, "processed"),
            "pending": _extract(wh_row, "pending"),
        },
        "users": {
            "total": _extract(ur, "total"),
            "active": _extract(ur, "active"),
            "admins": _extract(ur, "admins"),
        },
    }


@router.get("/admin/system-health", tags=["Admin"])
async def get_system_health(_current_user: User = Depends(require_admin)):
    """Get infrastructure health status (admin only)."""
    return await collect_system_health()


@router.post("/admin/mist/test-connection", tags=["Admin"])
async def test_mist_connection(
    request: Request,
    current_user: User = Depends(require_admin),
):
    """
    Test connection to Mist API (admin only).

    Accepts optional ``mist_api_token``, ``mist_org_id``, and
    ``mist_cloud_region`` in the request body.  When provided, the
    connection is tested with those values directly (no save required).
    Missing fields fall back to the saved system configuration.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    config = await SystemConfig.get_config()

    # Resolve each field: prefer request body, fall back to saved config
    api_token_raw = body.get("mist_api_token") or None
    if api_token_raw:
        api_token = api_token_raw  # plain-text from the form
    elif config and config.mist_api_token:
        api_token = decrypt_sensitive_data(config.mist_api_token)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mist API token not configured",
        )

    org_id = body.get("mist_org_id") or (config.mist_org_id if config else "") or ""
    cloud_region = body.get("mist_cloud_region") or (config.mist_cloud_region if config else "global_01") or "global_01"

    logger.info("mist_connection_test", user_id=str(current_user.id))

    from app.services.mist_service import MistService

    try:
        # Direct instantiation (not factory) — pre-save test with user-provided overrides
        service = MistService(
            api_token=api_token,
            org_id=org_id,
            cloud_region=cloud_region,
        )
        connected, error = await service.test_connection()
        return {"status": "connected" if connected else "failed", "error": error}
    except Exception as e:
        logger.warning("mist_connection_test_failed", error=str(e))
        return {"status": "failed", "error": "Connection test failed. Check your credentials and configuration."}


@router.post("/admin/integrations/test-slack", tags=["Admin"])
async def test_slack_connection(request: Request, current_user: User = Depends(require_admin)):
    """Test Slack webhook connection by sending a test message."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    config = await SystemConfig.get_config()
    webhook_url = body.get("slack_webhook_url") or config.slack_webhook_url
    if not webhook_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Slack webhook URL not configured")

    from app.utils.url_safety import validate_outbound_url

    validate_outbound_url(webhook_url)

    from app.services.notification_service import NotificationService

    service = NotificationService()
    try:
        success, error = await service.test_slack_connection(webhook_url=webhook_url)
        return {"status": "connected" if success else "failed", "error": error}
    except Exception:
        return {"status": "failed", "error": "Slack connection test failed"}
    finally:
        await service.close()


@router.post("/admin/integrations/test-servicenow", tags=["Admin"])
async def test_servicenow_connection(request: Request, current_user: User = Depends(require_admin)):
    """Test ServiceNow connection."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    config = await SystemConfig.get_config()
    instance_url = body.get("servicenow_instance_url") or config.servicenow_instance_url
    username = body.get("servicenow_username") or config.servicenow_username
    raw_pw = body.get("servicenow_password")
    password = (
        raw_pw
        if raw_pw
        else (decrypt_sensitive_data(config.servicenow_password) if config.servicenow_password else None)
    )

    if not all([instance_url, username, password]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ServiceNow credentials not configured")

    from app.utils.url_safety import validate_outbound_url

    validate_outbound_url(instance_url)

    from app.services.notification_service import NotificationService

    service = NotificationService()
    try:
        success, error = await service.test_servicenow_connection(
            instance_url=instance_url, username=username, password=password
        )
        return {"status": "connected" if success else "failed", "error": error}
    except Exception:
        return {"status": "failed", "error": "ServiceNow connection test failed"}
    finally:
        await service.close()


@router.post("/admin/integrations/test-pagerduty", tags=["Admin"])
async def test_pagerduty_connection(request: Request, current_user: User = Depends(require_admin)):
    """Test PagerDuty integration key (format validation)."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    config = await SystemConfig.get_config()
    raw_key = body.get("pagerduty_api_key")
    key = (
        raw_key if raw_key else (decrypt_sensitive_data(config.pagerduty_api_key) if config.pagerduty_api_key else None)
    )

    if not key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PagerDuty integration key not configured")

    from app.services.notification_service import NotificationService

    service = NotificationService()
    try:
        success, error = await service.test_pagerduty_connection(integration_key=key)
        return {"status": "connected" if success else "failed", "error": error}
    except Exception:
        return {"status": "failed", "error": "PagerDuty connection test failed"}
    finally:
        await service.close()


@router.get("/admin/mist/sites", tags=["Admin"])
async def list_mist_sites(_current_user: User = Depends(require_admin)):
    """
    List sites from Mist organization.
    """
    from app.services.mist_service_factory import create_mist_service

    try:
        service = await create_mist_service()
        sites = await service.get_sites()
        return {"sites": [{"id": s.get("id"), "name": s.get("name", "")} for s in sites]}
    except Exception as e:
        logger.error("mist_sites_fetch_failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch sites from Mist") from e


@router.get("/admin/mist/sites/{site_id}/aps", tags=["Admin"])
async def list_site_aps(site_id: str, _current_user: User = Depends(require_admin)):
    """List APs for a specific Mist site (for dropdowns)."""
    from app.services.mist_service_factory import create_mist_service

    try:
        service = await create_mist_service()
        devices = await service.api_get(
            f"/api/v1/sites/{site_id}/stats/devices", params={"type": "ap", "limit": "1000"}
        )
        aps = [{"mac": d.get("mac", ""), "name": d.get("name", d.get("mac", ""))} for d in devices]
        return {"aps": aps}
    except Exception as e:
        logger.error("mist_aps_fetch_failed", site_id=site_id, error=str(e))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch APs from Mist") from e


@router.get("/admin/mist/object-types", tags=["Admin"])
async def list_mist_object_types(_current_user: User = Depends(require_admin)):
    """
    Return all supported Mist object types for frontend dropdowns.
    """
    return {"object_types": get_all_object_type_options()}


@router.get("/admin/mist/objects", tags=["Admin"])
async def list_mist_objects(
    object_type: str = Query(..., description="Object type in 'org:key' or 'site:key' format"),
    site_id: str | None = Query(None, description="Site ID for site-level objects"),
    _current_user: User = Depends(require_admin),
):
    """
    List objects of a given type from Mist organization.
    Uses the object registry for consistent API calls.
    """
    # Parse scope and key
    if ":" not in object_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="object_type must be in 'org:key' or 'site:key' format"
        )

    scope, key = object_type.split(":", 1)
    if scope == "org":
        obj_def = ORG_OBJECTS.get(key)
    elif scope == "site":
        obj_def = SITE_OBJECTS.get(key)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid scope '{scope}', must be 'org' or 'site'"
        )

    if not obj_def:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown object type: {object_type}")

    if scope == "site" and not site_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="site_id is required for site-level objects"
        )

    from app.services.mist_service_factory import create_mist_service

    try:
        service = await create_mist_service()

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
        logger.error("mist_objects_fetch_failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch objects from Mist") from e


@router.get("/admin/workers/status", tags=["Admin"])
async def get_worker_status(_current_user: User = Depends(require_admin)):
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
