"""
Aggregation window model for event aggregation engine.

Collects webhook events over a time window before firing an aggregated trigger.
"""

from datetime import datetime, timezone

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel


class AggregationWindow(Document):
    """Tracks an active event aggregation window for a workflow + group key."""

    workflow_id: PydanticObjectId = Field(..., description="Reference to the workflow using this aggregation")
    group_key: str = Field(..., description="Grouping key, e.g. 'site:abc123'")
    window_start: datetime = Field(..., description="Window start time")
    window_end: datetime = Field(..., description="Window end time (window_start + window_seconds)")
    window_seconds: int = Field(..., description="Window duration in seconds")
    event_ids: list[PydanticObjectId] = Field(default_factory=list, description="IDs of buffered WebhookEvent docs")
    event_count: int = Field(default=0, description="Number of events currently in the window")

    # Track per-device state for closing event matching.
    # Key: device identifier (e.g. MAC address), Value: str(event_id) of the opening event.
    device_event_map: dict[str, str] = Field(
        default_factory=dict,
        description="Map of device identifier to opening event ID for closing event matching",
    )

    status: str = Field(
        default="collecting",
        description="Window status: collecting, fired, expired, cancelled",
    )
    fired_at: datetime | None = Field(default=None, description="Timestamp when the window was fired")
    execution_id: PydanticObjectId | None = Field(
        default=None, description="Reference to the WorkflowExecution created when fired"
    )

    site_id: str | None = Field(default=None, description="Mist site ID from the first event")
    site_name: str | None = Field(default=None, description="Mist site name from the first event")

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_summary(self) -> dict:
        """Build a serialisable summary dict (shared by REST + WS broadcasts)."""
        return {
            "window_id": str(self.id),
            "workflow_id": str(self.workflow_id),
            "group_key": self.group_key,
            "status": self.status,
            "event_count": self.event_count,
            "site_id": self.site_id,
            "site_name": self.site_name,
            "window_end": self.window_end.isoformat() if self.window_end else "",
            "window_seconds": self.window_seconds,
        }

    class Settings:
        name = "aggregation_windows"
        indexes = [
            IndexModel(
                [("workflow_id", ASCENDING), ("group_key", ASCENDING), ("status", ASCENDING)],
                name="workflow_group_status",
            ),
            IndexModel([("window_end", ASCENDING)], name="window_end"),
            IndexModel([("status", ASCENDING)], name="status"),
        ]
