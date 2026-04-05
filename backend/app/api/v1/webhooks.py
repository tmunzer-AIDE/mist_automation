"""
Unified webhook gateway, event management, and Smee.io management endpoints.

Single POST endpoint receives all Mist webhooks and routes internally
to the automation and/or backup modules.
"""

import hashlib
import hmac
import ipaddress
from datetime import datetime, timedelta, timezone

import structlog
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from app.config import settings
from app.core.tasks import create_background_task
from app.core.webhook_extractor import enrich_event, extract_event_fields
from app.core.websocket import ws_manager
from app.dependencies import get_current_user_from_token, require_admin, require_automation_role
from app.models.system import SystemConfig
from app.models.user import User
from app.modules.automation.models.webhook import WebhookEvent
from app.modules.automation.schemas.webhook import (
    WebhookEventDetailResponse,
    WebhookEventResponse,
    WebhookListResponse,
    WebhookStatsBucket,
    WebhookStatsResponse,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


class SmeeStartRequest(BaseModel):
    smee_channel_url: str | None = None


def _verify_mist_signature(payload: bytes, signature: str, secret: str, *, use_sha256: bool = False) -> bool:
    """Verify a Mist webhook HMAC signature.

    X-Mist-Signature    (v1): HMAC-SHA1   (40-char hex)
    X-Mist-Signature-v2 (v2): HMAC-SHA256 (64-char hex)
    """
    if not signature or not secret:
        return False
    sig = signature.strip()
    digestmod = hashlib.sha256 if use_sha256 else hashlib.sha1
    expected = hmac.new(secret.encode(), payload, digestmod).hexdigest()
    return hmac.compare_digest(sig, expected)


def _event_fields(event: WebhookEvent) -> dict:
    """Common fields shared by response schema and monitor dict."""
    return {
        "id": str(event.id),
        "webhook_type": event.webhook_type,
        "webhook_topic": event.webhook_topic,
        "webhook_id": event.webhook_id,
        "source_ip": event.source_ip,
        "site_id": event.site_id,
        "org_id": event.org_id,
        "processed": event.processed,
        "matched_workflows": [str(wid) for wid in event.matched_workflows],
        "executions_triggered": [str(eid) for eid in event.executions_triggered],
        "signature_valid": event.signature_valid,
        "routed_to": event.routed_to,
        "response_status": event.response_status,
        "received_at": event.received_at,
        "processed_at": event.processed_at,
        "event_type": event.event_type,
        "org_name": event.org_name,
        "site_name": event.site_name,
        "device_name": event.device_name,
        "device_mac": event.device_mac,
        "event_details": event.event_details,
        "event_timestamp": event.event_timestamp,
    }


def _event_to_response(
    event: WebhookEvent, *, include_payload: bool = False
) -> WebhookEventResponse | WebhookEventDetailResponse:
    """Convert a WebhookEvent document to a response schema."""
    kwargs = {**_event_fields(event), "response_body": event.response_body}
    if include_payload:
        return WebhookEventDetailResponse(**kwargs, payload=event.payload, headers=event.headers)
    return WebhookEventResponse(**kwargs)


def _event_to_monitor_dict(event: WebhookEvent) -> dict:
    """Convert a WebhookEvent to a flat dict for REST and WebSocket monitor responses."""
    fields = _event_fields(event)
    # Monitor dict uses ISO strings for dates
    fields["received_at"] = event.received_at.isoformat() if event.received_at else None
    fields["processed_at"] = event.processed_at.isoformat() if event.processed_at else None
    fields["event_timestamp"] = event.event_timestamp.isoformat() if event.event_timestamp else None
    return fields


def _ip_in_allowlist(client_ip: str, allowlist: list[str]) -> bool:
    """Check if client IP matches any entry in the allowlist (supports CIDR)."""
    try:
        addr = ipaddress.ip_address(client_ip)
        # Unwrap IPv4-mapped IPv6 (::ffff:x.x.x.x) so it matches IPv4 CIDR entries
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        return any(addr in ipaddress.ip_network(entry, strict=False) for entry in allowlist)
    except ValueError:
        return False


# ── Unified webhook gateway ──────────────────────────────────────────────────


@router.post("/webhooks/mist", tags=["Webhooks"])
async def receive_mist_webhook(
    request: Request,
    x_mist_signature: str | None = Header(None, description="Mist webhook HMAC-SHA1 signature (v1)"),
    x_mist_signature_v2: str | None = Header(None, description="Mist webhook HMAC-SHA256 signature (v2)"),
    x_forwarded_by: str | None = Header(None, description="Set by internal Smee forwarder"),
):
    """
    Unified Mist webhook gateway.

    Receives all Mist webhooks, stores them as WebhookEvents,
    and routes internally to both the automation and backup modules.
    """
    body = await request.body()
    payload = await request.json()

    # Extract event details
    topic = payload.get("topic", "unknown")
    webhook_type = topic
    webhook_id = payload.get("id", f"mist_{topic}_{hashlib.sha256(body).hexdigest()[:16]}")

    # Smee localhost bypass: trust requests forwarded by the local Smee client (dev only)
    smee_forwarded = (
        settings.debug and x_forwarded_by == "smee" and request.client and request.client.host in ("127.0.0.1", "::1")
    )

    # Load config (used for IP allowlist + signature verification)
    config = await SystemConfig.get_config()

    # IP allowlist enforcement
    if config.webhook_ip_whitelist and not smee_forwarded:
        client_ip = request.client.host if request.client else None
        if not _ip_in_allowlist(client_ip or "", config.webhook_ip_whitelist):
            logger.warning("webhook_ip_blocked", client_ip=client_ip)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IP address not allowed")

    signature_valid = None  # None = unchecked (no secret configured)
    if not config.webhook_secret and not smee_forwarded:
        logger.warning("webhook_no_secret_configured", webhook_type=webhook_type)
    if config.webhook_secret and not smee_forwarded:
        from app.core.security import decrypt_sensitive_data

        # Prefer v2 (SHA256) over v1 (SHA1); require at least one
        sig_header = x_mist_signature_v2 or x_mist_signature
        if not sig_header:
            logger.warning("webhook_signature_missing", webhook_type=webhook_type)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing webhook signature",
            )

        secret = decrypt_sensitive_data(config.webhook_secret)
        use_sha256 = x_mist_signature_v2 is not None
        signature_valid = _verify_mist_signature(body, sig_header, secret, use_sha256=use_sha256)
        if not signature_valid:
            logger.warning(
                "webhook_signature_invalid",
                webhook_type=webhook_type,
                sig_version="v2" if use_sha256 else "v1",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )

    # Determine routing targets
    routed_to = ["automation"]
    if topic == "audits":
        routed_to.append("backup")
    if webhook_type == "device-events":
        routed_to.append("impact_analysis")

    # Split webhook into individual events
    events = payload.get("events", [])
    if not events:
        events = [payload]  # Treat as single event if no events array

    source_ip = request.client.host if request.client else None
    _STORED_HEADERS = {"content-type", "x-mist-signature", "x-mist-signature-v2", "user-agent", "x-forwarded-for"}
    headers = {k: v for k, v in request.headers.items() if k.lower() in _STORED_HEADERS}

    created_event_ids = []
    for idx, event in enumerate(events):
        enriched = enrich_event(event, topic, payload)
        fields = extract_event_fields(event, topic, payload)

        # For audit events, use audit_id for deduplication
        if topic == "audits" and event.get("audit_id"):
            evt_webhook_id = f"audit_{event['audit_id']}"
        elif len(events) > 1:
            evt_webhook_id = f"{webhook_id}_evt_{idx}"
        else:
            evt_webhook_id = webhook_id

        webhook_event = WebhookEvent(
            webhook_type=webhook_type,
            webhook_topic=topic,
            webhook_id=evt_webhook_id,
            source_ip=source_ip,
            site_id=event.get("site_id") or payload.get("site_id"),
            org_id=event.get("org_id") or payload.get("org_id"),
            payload=enriched,
            headers=headers,
            signature_valid=signature_valid,
            routed_to=routed_to,
            event_type=fields["event_type"],
            org_name=fields["org_name"],
            site_name=fields["site_name"],
            device_name=fields["device_name"],
            device_mac=fields["device_mac"],
            event_details=fields["event_details"],
            event_timestamp=fields["event_timestamp"],
        )
        try:
            await webhook_event.insert()
            created_event_ids.append(str(webhook_event.id))
        except DuplicateKeyError:
            logger.info("webhook_duplicate_ignored", webhook_id=evt_webhook_id, webhook_type=webhook_type)
            continue

        logger.info(
            "webhook_event_stored",
            webhook_id=evt_webhook_id,
            webhook_type=webhook_type,
            event_index=idx,
        )

        # Dispatch to automation (one event at a time)
        from app.modules.automation.workers.webhook_worker import process_webhook

        create_background_task(
            process_webhook(str(webhook_event.id), webhook_type, enriched, event_type=fields["event_type"]),
            name=f"webhook-automation-{evt_webhook_id}",
        )

        # Route device-events to impact analysis
        if webhook_type == "device-events":
            from app.modules.impact_analysis.workers.event_handler import handle_device_event

            create_background_task(
                handle_device_event(str(webhook_event.id), fields["event_type"], enriched),
                name=f"impact-{evt_webhook_id}",
            )

        # Broadcast to WebSocket monitor
        create_background_task(
            ws_manager.broadcast(
                "webhook:monitor",
                {"type": "webhook_received", "data": _event_to_monitor_dict(webhook_event)},
            ),
            name=f"ws-broadcast-{evt_webhook_id}",
        )

    # Backup still receives the FULL original payload (unchanged)
    backup_result = None
    if "backup" in routed_to:
        from app.modules.backup.webhook_handler import process_backup_webhook

        backup_result = await process_backup_webhook(payload, config)

    # Build response
    response_body = {
        "status": "received",
        "event_ids": created_event_ids,
        "events_count": len(created_event_ids),
        "routed_to": routed_to,
        "message": f"{len(created_event_ids)} event(s) received and routed for processing",
    }
    if backup_result:
        response_body["backup_result"] = backup_result

    return response_body


# ── Stats ─────────────────────────────────────────────────────────────────────


@router.get("/webhooks/stats", response_model=WebhookStatsResponse, tags=["Webhooks"])
async def get_webhook_stats(
    hours: int = Query(24, ge=1, le=720, description="Time range in hours (max 30 days)"),
    _current_user: User = Depends(require_automation_role),
):
    """Get aggregated webhook volume statistics bucketed by time."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    granularity = "hourly" if hours <= 48 else "daily"

    # MongoDB date truncation unit
    if granularity == "hourly":
        date_trunc_unit = "hour"
        bucket_fmt = "%Y-%m-%dT%H:00"
        step = timedelta(hours=1)
    else:
        date_trunc_unit = "day"
        bucket_fmt = "%Y-%m-%d"
        step = timedelta(days=1)

    pipeline = [
        {"$match": {"received_at": {"$gte": since}}},
        {
            "$group": {
                "_id": {
                    "bucket": {"$dateTrunc": {"date": "$received_at", "unit": date_trunc_unit}},
                    "topic": {"$ifNull": ["$webhook_topic", "unknown"]},
                },
                "count": {"$sum": 1},
            }
        },
        {
            "$group": {
                "_id": "$_id.bucket",
                "topics": {"$push": {"topic": "$_id.topic", "count": "$count"}},
                "total": {"$sum": "$count"},
            }
        },
        {"$sort": {"_id": 1}},
    ]

    results = await WebhookEvent.get_motor_collection().aggregate(pipeline).to_list(length=None)

    # Build lookup from aggregation results
    bucket_map: dict[str, dict] = {}
    for row in results:
        bucket_dt: datetime = row["_id"]
        label = bucket_dt.strftime(bucket_fmt)
        by_topic = {t["topic"]: t["count"] for t in row["topics"]}
        bucket_map[label] = {"total": row["total"], "by_topic": by_topic}

    # Gap-fill missing buckets
    buckets: list[WebhookStatsBucket] = []
    cursor = since.replace(minute=0, second=0, microsecond=0)
    if granularity == "daily":
        cursor = cursor.replace(hour=0)
    while cursor <= now:
        label = cursor.strftime(bucket_fmt)
        if label in bucket_map:
            buckets.append(WebhookStatsBucket(bucket=label, **bucket_map[label]))
        else:
            buckets.append(WebhookStatsBucket(bucket=label, total=0, by_topic={}))
        cursor += step

    return WebhookStatsResponse(buckets=buckets, granularity=granularity, hours=hours)


# ── Event listing & detail ───────────────────────────────────────────────────


@router.get("/webhooks/events", response_model=WebhookListResponse, tags=["Webhooks"])
async def list_webhook_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    webhook_type: str | None = Query(None, description="Filter by webhook type"),
    processed: bool | None = Query(None, description="Filter by processed status"),
    _current_user: User = Depends(require_automation_role),
):
    """List webhook events received from Mist."""
    query = {}
    if webhook_type:
        query["webhook_type"] = webhook_type
    if processed is not None:
        query["processed"] = processed

    total = await WebhookEvent.find(query).count()
    events = await WebhookEvent.find(query).sort(["-event_timestamp", "-received_at"]).skip(skip).limit(limit).to_list()

    return WebhookListResponse(
        events=[_event_to_response(event) for event in events],
        total=total,
    )


@router.get("/webhooks/events/{event_id}", response_model=WebhookEventDetailResponse, tags=["Webhooks"])
async def get_webhook_event(
    event_id: str,
    _current_user: User = Depends(require_automation_role),
):
    """Get webhook event details by ID."""
    try:
        event = await WebhookEvent.get(PydanticObjectId(event_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid event ID format",
        ) from exc

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook event not found",
        )

    return _event_to_response(event, include_payload=True)


@router.post("/webhooks/events/{event_id}/replay", tags=["Webhooks"])
async def replay_webhook_event(
    event_id: str,
    current_user: User = Depends(require_automation_role),
):
    """Replay a webhook event through the workflow engine."""
    try:
        event = await WebhookEvent.get(PydanticObjectId(event_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid event ID format",
        ) from exc

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook event not found",
        )

    # Mark event as unprocessed to allow replay
    event.processed = False
    event.processed_at = None
    await event.save()

    logger.info("webhook_replay_triggered", event_id=str(event.id), user_id=str(current_user.id))

    from app.modules.automation.workers.webhook_worker import process_webhook

    # Extract event_type from the stored event for correct event_type_filter matching
    event_type = event.event_type
    create_background_task(
        process_webhook(str(event.id), event.webhook_type, event.payload, event_type=event_type),
        name=f"webhook-replay-{event.webhook_id}",
    )

    return {
        "status": "queued",
        "message": "Webhook event queued for replay",
    }


# ── Smee.io management ───────────────────────────────────────────────────────


@router.get("/webhooks/smee/status", tags=["Webhooks"])
async def get_smee_status(
    _current_user: User = Depends(require_admin),
):
    """Get Smee.io client status."""
    from app.core.smee_service import get_smee_client

    client = get_smee_client()
    return {
        "running": client.is_running if client else False,
        "channel_url": client.channel_url if client else None,
    }


@router.post("/webhooks/smee/start", tags=["Webhooks"])
async def start_smee_client(
    body: SmeeStartRequest | None = None,
    current_user: User = Depends(require_admin),
):
    """Start the Smee.io webhook forwarder.

    Accepts an optional ``smee_channel_url`` in the request body so the
    user can start the client with a new URL without saving first.  The
    provided URL is persisted automatically.
    """
    config = await SystemConfig.get_config()

    # Prefer URL from request body, fall back to saved config
    channel_url = (body.smee_channel_url if body else None) or config.smee_channel_url
    if not channel_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Smee.io channel URL not configured",
        )

    from app.core.smee_service import start_smee

    target = settings.smee_target_url or f"http://127.0.0.1:8000{settings.api_v1_prefix}/webhooks/mist"
    await start_smee(channel_url, target)

    # Persist the URL and enabled state
    config.smee_channel_url = channel_url
    config.smee_enabled = True
    config.update_timestamp()
    await config.save()

    logger.info("smee_started_via_api", user_id=str(current_user.id))
    return {"status": "started", "channel_url": channel_url}


@router.post("/webhooks/smee/stop", tags=["Webhooks"])
async def stop_smee_client(
    current_user: User = Depends(require_admin),
):
    """Stop the Smee.io webhook forwarder."""
    from app.core.smee_service import stop_smee

    await stop_smee()

    config = await SystemConfig.get_config()
    config.smee_enabled = False
    config.update_timestamp()
    await config.save()

    logger.info("smee_stopped_via_api", user_id=str(current_user.id))
    return {"status": "stopped"}
