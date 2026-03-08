"""
Webhook schemas.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WebhookEventResponse(BaseModel):
    """Webhook event response schema."""

    id: str = Field(..., description="Webhook event ID")
    webhook_type: str = Field(..., description="Webhook type")
    webhook_topic: str | None = Field(None, description="Webhook topic")
    webhook_id: str = Field(..., description="Unique webhook ID")
    source_ip: str | None = Field(None, description="Source IP address")
    site_id: str | None = Field(None, description="Mist site ID")
    org_id: str | None = Field(None, description="Mist organization ID")
    payload: dict[str, Any] = Field(..., description="Webhook payload")
    processed: bool = Field(..., description="Whether processed")
    matched_workflows: list[str] = Field(..., description="Matched workflow IDs")
    executions_triggered: list[str] = Field(..., description="Triggered execution IDs")
    signature_valid: bool = Field(..., description="Signature validity")
    received_at: datetime = Field(..., description="Receipt timestamp")
    processed_at: datetime | None = Field(None, description="Processing timestamp")

    class Config:
        from_attributes = True


class WebhookListResponse(BaseModel):
    """Webhook list response schema."""

    events: list[WebhookEventResponse] = Field(..., description="List of webhook events")
    total: int = Field(..., description="Total number of events")
