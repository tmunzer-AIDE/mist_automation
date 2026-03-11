"""
Webhook event model for tracking incoming webhooks.
"""

from datetime import datetime, timezone

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel


class WebhookEvent(Document):
    """Webhook event tracking model."""

    # Webhook metadata
    webhook_type: str = Field(..., description="Webhook type: alarm, audit, device-events, etc.")
    webhook_topic: str | None = Field(default=None, description="Specific topic within webhook type")
    webhook_id: str = Field(..., description="Unique webhook ID for deduplication")

    # Source information
    source_ip: str | None = Field(default=None, description="Source IP address")
    site_id: str | None = Field(default=None, description="Mist site ID")
    org_id: str | None = Field(default=None, description="Mist organization ID")

    # Webhook data (single enriched event dict after splitting)
    payload: dict = Field(..., description="Single enriched event payload")
    headers: dict = Field(default_factory=dict, description="HTTP headers")

    # Extracted monitor fields (denormalized for fast listing)
    event_type: str | None = Field(default=None, description="Event type from event.type")
    org_name: str | None = Field(default=None, description="Organization name")
    site_name: str | None = Field(default=None, description="Site name")
    device_name: str | None = Field(default=None, description="Device name / AP / switch name")
    device_mac: str | None = Field(default=None, description="Device MAC address")
    event_details: str | None = Field(default=None, description="Event text / message / reason")

    # Processing status
    processed: bool = Field(default=False, description="Whether webhook has been processed")
    matched_workflows: list[PydanticObjectId] = Field(
        default_factory=list, description="List of workflow IDs that matched"
    )
    executions_triggered: list[PydanticObjectId] = Field(
        default_factory=list, description="List of execution IDs triggered"
    )

    # Validation
    signature_valid: bool = Field(default=True, description="Whether webhook signature was valid")

    # Routing
    routed_to: list[str] = Field(default_factory=list, description="Modules routed to: 'automation', 'backup'")

    # HTTP response sent back to Mist
    response_status: int = Field(default=200, description="HTTP status code returned")
    response_body: dict = Field(default_factory=dict, description="Response body returned to caller")

    # Timestamps
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: datetime | None = Field(default=None, description="When webhook was processed")

    class Settings:
        name = "webhook_events"
        indexes = [
            IndexModel([("webhook_id", ASCENDING)], unique=True),
            "webhook_type",
            [("received_at", -1)],  # Descending order for recent events
            "site_id",
            "org_id",
            "processed",
        ]

    def mark_processed(
        self,
        matched_workflow_ids: list[PydanticObjectId] | None = None,
        execution_ids: list[PydanticObjectId] | None = None,
    ):
        """Mark webhook as processed."""
        self.processed = True
        self.processed_at = datetime.now(timezone.utc)

        if matched_workflow_ids:
            self.matched_workflows = matched_workflow_ids

        if execution_ids:
            self.executions_triggered = execution_ids

    def extract_event_data(self) -> list[dict]:
        """Extract events from webhook payload."""
        # Mist webhooks typically have an 'events' array
        if isinstance(self.payload, dict):
            return self.payload.get("events", [])
        return []

    class Config:
        json_schema_extra = {
            "example": {
                "webhook_type": "alarm",
                "webhook_topic": "ap_offline",
                "webhook_id": "webhook_12345_abc",
                "site_id": "4ac1dcf4-9d8b-7211-65c4-057819f0862b",
                "org_id": "2818e386-8dec-2562-9ede-5b8a0fbbdc71",
                "payload": {
                    "topic": "alarms",
                    "events": [
                        {
                            "type": "ap_offline",
                            "timestamp": 1638360000,
                            "ap_mac": "5c:5b:35:00:00:01",
                            "site_id": "4ac1dcf4-9d8b-7211-65c4-057819f0862b",
                        }
                    ],
                },
                "processed": True,
            }
        }
