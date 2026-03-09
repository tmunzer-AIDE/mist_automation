"""
Unified webhook gateway and event management API endpoints.

Single POST endpoint receives all Mist webhooks and routes internally
to the automation and/or backup modules.
"""

import asyncio
import hashlib
import hmac

import structlog
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request, status

from app.dependencies import get_current_user_from_token
from app.models.user import User
from app.modules.automation.models.webhook import WebhookEvent
from app.modules.automation.schemas.webhook import (
    WebhookEventDetailResponse,
    WebhookEventResponse,
    WebhookListResponse,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


def _verify_mist_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify the Mist webhook HMAC-SHA256 signature."""
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


# ── Unified webhook gateway ──────────────────────────────────────────────────

@router.post("/webhooks/mist", tags=["Webhooks"])
async def receive_mist_webhook(
    request: Request,
    x_mist_signature: str | None = Header(None, description="Mist webhook signature"),
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
    webhook_id = payload.get("id", f"mist_{topic}_{hash(str(body))}")

    # Check for duplicate events
    existing = await WebhookEvent.find_one(WebhookEvent.webhook_id == webhook_id)
    if existing:
        logger.info("webhook_duplicate_ignored", webhook_id=webhook_id, webhook_type=webhook_type)
        return {"status": "duplicate", "message": "Event already processed"}

    # Smee localhost bypass: trust requests forwarded by the local Smee client
    smee_forwarded = (
        x_forwarded_by == "smee"
        and request.client
        and request.client.host in ("127.0.0.1", "::1")
    )

    # Verify signature with stored webhook secret from SystemConfig
    from app.models.system import SystemConfig
    config = await SystemConfig.get_config()

    signature_valid = True
    if config.webhook_secret and not smee_forwarded:
        from app.core.security import decrypt_sensitive_data

        if not x_mist_signature:
            logger.warning("webhook_signature_missing", webhook_type=webhook_type)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing webhook signature",
            )

        secret = decrypt_sensitive_data(config.webhook_secret)
        signature_valid = _verify_mist_signature(body, x_mist_signature, secret)
        if not signature_valid:
            logger.warning("webhook_signature_invalid", webhook_type=webhook_type)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )

    # Determine routing targets
    routed_to = ["automation"]
    if topic == "audits":
        routed_to.append("backup")

    # Store the webhook event
    webhook_event = WebhookEvent(
        webhook_type=webhook_type,
        webhook_topic=payload.get("topic"),
        webhook_id=webhook_id,
        source_ip=request.client.host if request.client else None,
        site_id=payload.get("site_id"),
        org_id=payload.get("org_id"),
        payload=payload,
        headers=dict(request.headers),
        signature_valid=signature_valid,
        routed_to=routed_to,
    )
    await webhook_event.insert()

    logger.info(
        "webhook_received",
        webhook_id=webhook_event.webhook_id,
        webhook_type=webhook_type,
        routed_to=routed_to,
    )

    # Dispatch to automation module
    from app.modules.automation.workers.webhook_worker import process_webhook
    asyncio.create_task(process_webhook(str(webhook_event.id), webhook_type, payload))

    # Dispatch to backup module if applicable
    backup_result = None
    if "backup" in routed_to:
        from app.modules.backup.webhook_router import process_backup_webhook
        backup_result = await process_backup_webhook(payload, config)

    # Build response
    response_body = {
        "status": "received",
        "event_id": str(webhook_event.id),
        "routed_to": routed_to,
        "message": "Webhook event received and routed for processing",
    }
    if backup_result:
        response_body["backup_result"] = backup_result

    # Update event with response info
    webhook_event.response_status = 200
    webhook_event.response_body = response_body
    await webhook_event.save()

    return response_body


# ── Event listing & detail ───────────────────────────────────────────────────

def _event_to_summary(event: WebhookEvent) -> WebhookEventResponse:
    """Convert a WebhookEvent document to a summary response."""
    return WebhookEventResponse(
        id=str(event.id),
        webhook_type=event.webhook_type,
        webhook_topic=event.webhook_topic,
        webhook_id=event.webhook_id,
        source_ip=event.source_ip,
        site_id=event.site_id,
        org_id=event.org_id,
        processed=event.processed,
        matched_workflows=[str(wid) for wid in event.matched_workflows],
        executions_triggered=[str(eid) for eid in event.executions_triggered],
        signature_valid=event.signature_valid,
        routed_to=event.routed_to,
        response_status=event.response_status,
        response_body=event.response_body,
        received_at=event.received_at,
        processed_at=event.processed_at,
    )


def _event_to_detail(event: WebhookEvent) -> WebhookEventDetailResponse:
    """Convert a WebhookEvent document to a detail response."""
    return WebhookEventDetailResponse(
        id=str(event.id),
        webhook_type=event.webhook_type,
        webhook_topic=event.webhook_topic,
        webhook_id=event.webhook_id,
        source_ip=event.source_ip,
        site_id=event.site_id,
        org_id=event.org_id,
        processed=event.processed,
        matched_workflows=[str(wid) for wid in event.matched_workflows],
        executions_triggered=[str(eid) for eid in event.executions_triggered],
        signature_valid=event.signature_valid,
        routed_to=event.routed_to,
        response_status=event.response_status,
        response_body=event.response_body,
        received_at=event.received_at,
        processed_at=event.processed_at,
        payload=event.payload,
        headers=event.headers,
    )


@router.get("/webhooks/events", response_model=WebhookListResponse, tags=["Webhooks"])
async def list_webhook_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    webhook_type: str | None = Query(None, description="Filter by webhook type"),
    processed: bool | None = Query(None, description="Filter by processed status"),
    _current_user: User = Depends(get_current_user_from_token),
):
    """List webhook events received from Mist."""
    query = {}
    if webhook_type:
        query["webhook_type"] = webhook_type
    if processed is not None:
        query["processed"] = processed

    total = await WebhookEvent.find(query).count()
    events = await WebhookEvent.find(query).sort("-received_at").skip(skip).limit(limit).to_list()

    return WebhookListResponse(
        events=[_event_to_summary(event) for event in events],
        total=total,
    )


@router.get("/webhooks/events/{event_id}", response_model=WebhookEventDetailResponse, tags=["Webhooks"])
async def get_webhook_event(
    event_id: str,
    _current_user: User = Depends(get_current_user_from_token),
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

    return _event_to_detail(event)


@router.post("/webhooks/events/{event_id}/replay", tags=["Webhooks"])
async def replay_webhook_event(
    event_id: str,
    current_user: User = Depends(get_current_user_from_token),
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
    asyncio.create_task(process_webhook(str(event.id), event.webhook_type, event.payload))

    return {
        "status": "queued",
        "message": "Webhook event queued for replay",
    }
