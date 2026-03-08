"""
Backup module webhook receiver and Smee.io management endpoints.

Receives Mist audit webhooks to trigger incremental backups,
independently from the automation module's webhook handling.
"""

import asyncio
import hashlib
import hmac

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Header, Query, Request, status

from app.config import settings as app_settings
from app.dependencies import get_current_user_from_token, require_admin
from app.models.system import SystemConfig
from app.models.user import User

router = APIRouter()
logger = structlog.get_logger(__name__)


# ── Webhook listener ─────────────────────────────────────────────────────────

def _verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify Mist webhook HMAC-SHA256 signature."""
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


@router.post("/backups/webhooks/mist", tags=["Backups"])
async def receive_backup_webhook(
    request: Request,
    x_mist_signature: str | None = Header(None, description="Mist webhook signature"),
    x_forwarded_by: str | None = Header(None, description="Set by internal Smee forwarder"),
):
    """
    Receive Mist audit webhooks for incremental backup.

    Mist sends audit webhooks as flat JSON objects (one event per request),
    e.g.::

        {
            "wlan_id": "...",
            "message": "Add WLAN \"Corp-SSID\"",
            "org_id": "...",
            "site_id": "...",
            "id": "...",
            "admin_name": "...",
            ...
        }

    The handler also accepts the envelope format ``{topic, events: [...]}``
    for forward-compatibility.
    """
    body = await request.body()
    payload = await request.json()

    # When the Smee.io client forwards an event, the body has been
    # round-tripped through JSON parse/serialize so the HMAC signature
    # will not match.  We trust Smee-forwarded requests only when they
    # originate from localhost (127.0.0.1).
    smee_forwarded = (
        x_forwarded_by == "smee"
        and request.client
        and request.client.host in ("127.0.0.1", "::1")
    )

    # Signature verification using the system webhook secret
    config = await SystemConfig.get_config()
    if config.webhook_secret and not smee_forwarded:
        from app.core.security import decrypt_sensitive_data

        if not x_mist_signature:
            logger.warning("backup_webhook_signature_missing")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing webhook signature",
            )

        secret = decrypt_sensitive_data(config.webhook_secret)
        if not _verify_signature(body, x_mist_signature, secret):
            logger.warning("backup_webhook_signature_invalid")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )

    # Normalise payload: support both envelope and flat formats
    if "topic" in payload and "events" in payload:
        # Envelope format: {topic: "audits", events: [...]}
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
    events = [
        e for e in events
        if e and any(k for k in e if k not in _META_KEYS)
    ]

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

    asyncio.create_task(perform_incremental_backup(configured_org_id, events))

    return {
        "status": "received",
        "message": f"Incremental backup triggered for {len(events)} audit event(s)",
    }


# ── Smee.io management ───────────────────────────────────────────────────────

@router.get("/backups/smee/status", tags=["Backups"])
async def get_smee_status(
    _current_user: User = Depends(require_admin),
):
    """Get Smee.io client status."""
    from app.modules.backup.services.smee_service import get_smee_client

    client = get_smee_client()
    return {
        "running": client.is_running if client else False,
        "channel_url": client.channel_url if client else None,
    }


@router.post("/backups/smee/start", tags=["Backups"])
async def start_smee_client(
    request: Request,
    current_user: User = Depends(require_admin),
):
    """Start the Smee.io webhook forwarder for the backup module.

    Accepts an optional ``smee_channel_url`` in the request body so the
    user can start the client with a new URL without saving first.  The
    provided URL is persisted automatically.
    """
    # Parse optional JSON body
    try:
        body = await request.json()
    except Exception:
        body = {}

    config = await SystemConfig.get_config()

    # Prefer URL from request body, fall back to saved config
    channel_url = body.get("smee_channel_url") or config.smee_channel_url
    if not channel_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Smee.io channel URL not configured",
        )

    from app.modules.backup.services.smee_service import start_smee

    target = f"http://127.0.0.1:8000{app_settings.api_v1_prefix}/backups/webhooks/mist"
    await start_smee(channel_url, target)

    # Persist the URL and enabled state
    config.smee_channel_url = channel_url
    config.smee_enabled = True
    config.update_timestamp()
    await config.save()

    logger.info("smee_started_via_api", user_id=str(current_user.id))
    return {"status": "started", "channel_url": channel_url}


@router.post("/backups/smee/stop", tags=["Backups"])
async def stop_smee_client(
    current_user: User = Depends(require_admin),
):
    """Stop the Smee.io webhook forwarder."""
    from app.modules.backup.services.smee_service import stop_smee

    await stop_smee()

    config = await SystemConfig.get_config()
    config.smee_enabled = False
    config.update_timestamp()
    await config.save()

    logger.info("smee_stopped_via_api", user_id=str(current_user.id))
    return {"status": "stopped"}
