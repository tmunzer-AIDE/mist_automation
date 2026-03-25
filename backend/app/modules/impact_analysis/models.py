"""
Config Change Impact Analysis models.

MonitoringSession tracks the lifecycle of observing a device after a config change,
capturing incidents, SLE baselines/snapshots, topology, and AI assessments.
"""

from datetime import datetime, timezone
from enum import Enum

from beanie import Document
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel

from app.models.mixins import TimestampMixin


class SessionStatus(str, Enum):
    PENDING = "pending"
    BASELINE_CAPTURE = "baseline_capture"
    MONITORING = "monitoring"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    ALERT = "alert"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeviceType(str, Enum):
    AP = "ap"
    SWITCH = "switch"
    GATEWAY = "gateway"


VALID_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.PENDING: {SessionStatus.BASELINE_CAPTURE, SessionStatus.FAILED, SessionStatus.CANCELLED},
    SessionStatus.BASELINE_CAPTURE: {SessionStatus.MONITORING, SessionStatus.FAILED, SessionStatus.CANCELLED},
    SessionStatus.MONITORING: {
        SessionStatus.ANALYZING,
        SessionStatus.ALERT,
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
    },
    SessionStatus.ANALYZING: {SessionStatus.COMPLETED, SessionStatus.ALERT, SessionStatus.FAILED},
    SessionStatus.ALERT: {SessionStatus.MONITORING, SessionStatus.COMPLETED, SessionStatus.CANCELLED},
    SessionStatus.COMPLETED: set(),
    SessionStatus.FAILED: set(),
    SessionStatus.CANCELLED: set(),
}

ACTIVE_STATUSES: set[SessionStatus] = {
    SessionStatus.PENDING,
    SessionStatus.BASELINE_CAPTURE,
    SessionStatus.MONITORING,
}


class ConfigChangeEvent(BaseModel):
    """A single config change event associated with a monitoring session."""

    event_type: str = Field(..., description="Mist event type (e.g. GW_CONFIGURED)")
    device_mac: str = Field(..., description="Device MAC address")
    device_name: str = Field(default="", description="Device name")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Event timestamp")
    webhook_event_id: str | None = Field(default=None, description="Reference to WebhookEvent document ID")
    payload_summary: dict = Field(default_factory=dict, description="Abbreviated event payload")
    config_diff: str | None = Field(default=None, description="Junos config diff (EX/SRX only, from SW/GW_CONFIGURED)")
    device_model: str = Field(default="", description="Device hardware model")
    firmware_version: str = Field(default="", description="Firmware version at time of config change")
    commit_user: str = Field(default="", description="User who committed the config change")
    commit_method: str = Field(default="", description="Commit method (netconf, cli, etc.)")


class DeviceIncident(BaseModel):
    """An incident detected during monitoring (e.g. device disconnect, SLE degradation)."""

    event_type: str = Field(..., description="Incident type (e.g. AP_DISCONNECTED, SLE_DEGRADED)")
    device_mac: str = Field(..., description="Device MAC address")
    device_name: str = Field(default="", description="Device name")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Incident timestamp")
    webhook_event_id: str | None = Field(default=None, description="Reference to WebhookEvent document ID")
    severity: str = Field(default="warning", description="Incident severity: warning or critical")
    is_revert: bool = Field(default=False, description="Whether this incident triggered a config revert")
    resolved: bool = Field(default=False, description="Whether the incident has been resolved")
    resolved_at: datetime | None = Field(default=None, description="When the incident was resolved")


class MonitoringSession(TimestampMixin, Document):
    """Tracks the full lifecycle of monitoring a device after a config change."""

    # Device identification
    site_id: str = Field(..., description="Mist site ID")
    site_name: str = Field(default="", description="Site name")
    org_id: str = Field(..., description="Mist organization ID")
    device_mac: str = Field(..., description="Device MAC address")
    device_name: str = Field(default="", description="Device name")
    device_type: DeviceType = Field(..., description="Device type: ap, switch, or gateway")
    device_mist_id: str | None = Field(default=None, description="Mist device UUID (resolved from MAC via topology)")

    # Session state
    status: SessionStatus = Field(default=SessionStatus.PENDING, description="Current session status")

    # Events and incidents
    config_changes: list[ConfigChangeEvent] = Field(default_factory=list, description="Config change events")
    incidents: list[DeviceIncident] = Field(default_factory=list, description="Detected incidents")

    # Monitoring configuration
    duration_minutes: int = Field(default=60, description="Total monitoring duration in minutes")
    interval_minutes: int = Field(default=10, description="Polling interval in minutes")
    polls_completed: int = Field(default=0, description="Number of polling cycles completed")
    polls_total: int = Field(default=0, description="Total polling cycles expected")

    # Timing
    monitoring_started_at: datetime | None = Field(default=None, description="When active monitoring began")
    monitoring_ends_at: datetime | None = Field(default=None, description="When monitoring is scheduled to end")
    completed_at: datetime | None = Field(default=None, description="When the session finished")

    # SLE data
    sle_baseline: dict | None = Field(default=None, description="SLE metrics captured before monitoring")
    sle_snapshots: list[dict] = Field(default_factory=list, description="Periodic SLE snapshots during monitoring")
    sle_delta: dict | None = Field(default=None, description="Computed SLE change from baseline")
    sle_drill_down: dict | None = Field(default=None, description="Detailed SLE drill-down data")

    # Topology
    topology_baseline: dict | None = Field(default=None, description="Network topology snapshot at baseline")
    topology_latest: dict | None = Field(default=None, description="Most recent topology snapshot")

    # Validation and analysis
    validation_results: dict | None = Field(default=None, description="Structured validation check results")
    ai_assessment: dict | None = Field(default=None, description="LLM-generated impact assessment")
    ai_assessment_error: str | None = Field(default=None, description="Error from AI assessment if it failed")

    # Progress tracking (for WS updates)
    progress: dict = Field(
        default_factory=lambda: {"phase": "pending", "percent": 0, "message": "Waiting to start"},
        description="Current progress for UI display",
    )

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "monitoring_sessions"
        indexes = [
            IndexModel([("site_id", 1)]),
            IndexModel([("status", 1)]),
            IndexModel([("device_mac", 1), ("status", 1)]),
            IndexModel([("created_at", -1)]),
            IndexModel(
                [("device_mac", ASCENDING)],
                unique=True,
                partialFilterExpression={"status": {"$in": ["pending", "baseline_capture", "monitoring"]}},
            ),
        ]
