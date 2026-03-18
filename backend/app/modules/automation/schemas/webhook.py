"""
Webhook schemas.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WebhookEventResponse(BaseModel):
    """Webhook event summary response schema (used in list endpoint)."""

    id: str = Field(..., description="Webhook event ID")
    webhook_type: str = Field(..., description="Webhook type")
    webhook_topic: str | None = Field(None, description="Webhook topic")
    webhook_id: str = Field(..., description="Unique webhook ID")
    source_ip: str | None = Field(None, description="Source IP address")
    site_id: str | None = Field(None, description="Mist site ID")
    org_id: str | None = Field(None, description="Mist organization ID")
    processed: bool = Field(..., description="Whether processed")
    matched_workflows: list[str] = Field(default_factory=list, description="Matched workflow IDs")
    executions_triggered: list[str] = Field(default_factory=list, description="Triggered execution IDs")
    signature_valid: bool = Field(..., description="Signature validity")
    routed_to: list[str] = Field(default_factory=list, description="Modules routed to")
    response_status: int = Field(default=200, description="HTTP status code returned")
    response_body: dict = Field(default_factory=dict, description="Response body returned")
    received_at: datetime = Field(..., description="Receipt timestamp")
    processed_at: datetime | None = Field(None, description="Processing timestamp")

    # Extracted monitor fields
    event_type: str | None = Field(None, description="Event type")
    org_name: str | None = Field(None, description="Organization name")
    site_name: str | None = Field(None, description="Site name")
    device_name: str | None = Field(None, description="Device name")
    device_mac: str | None = Field(None, description="Device MAC address")
    event_details: str | None = Field(None, description="Event summary text")
    event_timestamp: datetime | None = Field(None, description="Event timestamp from Mist payload")

    class Config:
        from_attributes = True


class WebhookEventDetailResponse(WebhookEventResponse):
    """Webhook event detail response schema (includes payload and headers)."""

    payload: dict[str, Any] = Field(..., description="Webhook payload")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP headers")


class WebhookListResponse(BaseModel):
    """Webhook list response schema."""

    events: list[WebhookEventResponse] = Field(..., description="List of webhook events")
    total: int = Field(..., description="Total number of events")


class WebhookStatsBucket(BaseModel):
    """Single time bucket in webhook volume stats."""

    bucket: str = Field(..., description="Time bucket label, e.g. '2026-03-11T14:00' or '2026-03-11'")
    total: int = Field(..., description="Total webhook count in this bucket")
    by_topic: dict[str, int] = Field(default_factory=dict, description="Webhook count per topic")


class WebhookStatsResponse(BaseModel):
    """Aggregated webhook volume statistics."""

    buckets: list[WebhookStatsBucket] = Field(..., description="Time-bucketed volume data")
    granularity: str = Field(..., description="Bucket granularity: 'hourly' or 'daily'")
    hours: int = Field(..., description="Time range in hours")
