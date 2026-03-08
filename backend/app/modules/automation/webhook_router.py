"""
Webhook receiver and event management API endpoints.
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
from app.modules.automation.schemas.webhook import WebhookEventResponse, WebhookListResponse

router = APIRouter()
logger = structlog.get_logger(__name__)


def verify_mist_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify the Mist webhook signature.
    """
    if not signature or not secret:
        return False

    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(signature, expected)


@router.post("/webhooks/mist", tags=["Webhooks"])
async def receive_mist_webhook(
    request: Request,
    x_mist_signature: str | None = Header(None, description="Mist webhook signature")
):
    """
    Receive and process Mist webhook events.
    This endpoint is called by Mist when events occur.
    """
    # Get raw body for signature verification
    body = await request.body()
    payload = await request.json()

    # Extract event details
    webhook_type = payload.get("topic", "unknown")
    webhook_id = payload.get("id", f"mist_{webhook_type}_{hash(str(body))}")

    # Check for duplicate events
    existing = await WebhookEvent.find_one(WebhookEvent.webhook_id == webhook_id)
    if existing:
        logger.info("webhook_duplicate_ignored", webhook_id=webhook_id, webhook_type=webhook_type)
        return {"status": "duplicate", "message": "Event already processed"}

    # Verify signature with stored webhook secret from SystemConfig
    from app.models.system import SystemConfig
    config = await SystemConfig.get_config()
    signature_valid = True
    if config.webhook_secret:
        from app.core.security import decrypt_sensitive_data

        if not x_mist_signature:
            logger.warning("webhook_signature_missing", webhook_type=webhook_type)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing webhook signature",
            )

        secret = decrypt_sensitive_data(config.webhook_secret)
        signature_valid = verify_mist_signature(body, x_mist_signature, secret)
        if not signature_valid:
            logger.warning("webhook_signature_invalid", webhook_type=webhook_type)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )

    # Store the webhook event
    webhook_event = WebhookEvent(
        webhook_type=webhook_type,
        webhook_id=webhook_id,
        payload=payload,
        headers=dict(request.headers),
        signature_valid=signature_valid
    )
    await webhook_event.insert()

    logger.info("webhook_received", webhook_id=webhook_event.webhook_id, webhook_type=webhook_type)

    # Trigger workflow matching and execution asynchronously
    from app.modules.automation.workers.webhook_worker import process_webhook
    asyncio.create_task(process_webhook(str(webhook_event.id), webhook_type, payload))

    return {
        "status": "received",
        "event_id": str(webhook_event.id),
        "message": "Webhook event received and queued for processing"
    }


@router.get("/webhooks/events", response_model=WebhookListResponse, tags=["Webhooks"])
async def list_webhook_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    webhook_type: str | None = Query(None, description="Filter by webhook type"),
    processed: bool | None = Query(None, description="Filter by processed status"),
    _current_user: User = Depends(get_current_user_from_token)
):
    """
    List webhook events received from Mist.
    """
    # Build query
    query = {}
    if webhook_type:
        query["webhook_type"] = webhook_type
    if processed is not None:
        query["processed"] = processed

    # Get total count
    total = await WebhookEvent.find(query).count()

    # Get events with pagination
    events = await WebhookEvent.find(query).sort("-received_at").skip(skip).limit(limit).to_list()

    return WebhookListResponse(
        events=[
            WebhookEventResponse(
                id=str(event.id),
                event_id=event.webhook_id,
                event_type=event.webhook_type,
                source="mist",
                processed=event.processed,
                received_at=event.received_at,
                processed_at=event.processed_at,
                payload=event.payload
            )
            for event in events
        ],
        total=total
    )


@router.get("/webhooks/events/{event_id}", response_model=WebhookEventResponse, tags=["Webhooks"])
async def get_webhook_event(
    event_id: str,
    _current_user: User = Depends(get_current_user_from_token)
):
    """
    Get webhook event details by ID.
    """
    try:
        event = await WebhookEvent.get(PydanticObjectId(event_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid event ID format"
        ) from exc

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook event not found"
        )

    return WebhookEventResponse(
        id=str(event.id),
        event_id=event.webhook_id,
        event_type=event.webhook_type,
        source="mist",
        processed=event.processed,
        received_at=event.received_at,
        processed_at=event.processed_at,
        payload=event.payload,
        headers=event.headers,
        signature=None,
        error=None
    )


@router.post("/webhooks/events/{event_id}/replay", tags=["Webhooks"])
async def replay_webhook_event(
    event_id: str,
    current_user: User = Depends(get_current_user_from_token)
):
    """
    Replay a webhook event through the workflow engine.
    """
    try:
        event = await WebhookEvent.get(PydanticObjectId(event_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid event ID format"
        ) from exc

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook event not found"
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
        "message": "Webhook event queued for replay"
    }
