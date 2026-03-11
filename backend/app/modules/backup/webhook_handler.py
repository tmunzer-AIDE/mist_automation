"""
Backup module webhook processing.

Called by the unified webhook gateway (api/v1/webhooks.py) when
the webhook topic is "audits".
"""

import structlog

from app.core.tasks import create_background_task
from app.models.system import SystemConfig

logger = structlog.get_logger(__name__)


async def process_backup_webhook(payload: dict, config: SystemConfig) -> dict:
    """Process a webhook payload for backup. Returns status dict.

    Called by the unified webhook gateway when topic == "audits".
    """
    # Normalise payload: support both envelope and flat formats
    if "topic" in payload and "events" in payload:
        topic = payload["topic"]
        if topic != "audits":
            return {"status": "ignored", "reason": f"topic '{topic}' is not handled by backup"}
        events = payload["events"]
    else:
        # Flat audit event (one per request) — the common Mist format
        events = [payload]

    # Filter out empty/ping events — Mist sends heartbeat pings with
    # empty or minimal payloads that contain no actionable object data.
    _META_KEYS = {"id", "org_id", "site_id", "admin_id", "topic", "events"}
    events = [e for e in events if e and any(k for k in e if k not in _META_KEYS)]

    if not events:
        return {"status": "ignored", "reason": "no actionable events in payload"}

    # Validate org_id against configured org
    configured_org_id = config.mist_org_id or ""
    payload_org_id = payload.get("org_id", "")
    if not configured_org_id:
        return {"status": "ignored", "reason": "no org_id configured"}
    if payload_org_id and payload_org_id != configured_org_id:
        logger.warning(
            "backup_webhook_org_mismatch",
            payload_org_id=payload_org_id,
            configured_org_id=configured_org_id,
        )
        return {"status": "ignored", "reason": "org_id does not match configured organization"}

    logger.info("backup_webhook_received", event_count=len(events))

    # Trigger incremental backup for each changed object
    from app.modules.backup.workers import perform_incremental_backup

    create_background_task(
        perform_incremental_backup(configured_org_id, events),
        name=f"backup-incremental-{len(events)}-events",
    )

    return {
        "status": "received",
        "message": f"Incremental backup triggered for {len(events)} audit event(s)",
    }
