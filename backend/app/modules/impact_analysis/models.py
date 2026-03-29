"""
Config Change Impact Analysis models.

MonitoringSession tracks the lifecycle of observing a device after a config change,
capturing incidents, SLE baselines/snapshots, topology, and AI assessments.
"""

from datetime import datetime, timezone
from enum import Enum

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel

from app.models.mixins import TimestampMixin


class SessionStatus(str, Enum):
    PENDING = "pending"
    BASELINE_CAPTURE = "baseline_capture"
    AWAITING_CONFIG = "awaiting_config"
    MONITORING = "monitoring"
    VALIDATING = "validating"  # Device validation done, SLE + webhook monitoring continue
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeviceType(str, Enum):
    AP = "ap"
    SWITCH = "switch"
    GATEWAY = "gateway"


VALID_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.PENDING: {SessionStatus.BASELINE_CAPTURE, SessionStatus.FAILED, SessionStatus.CANCELLED},
    SessionStatus.BASELINE_CAPTURE: {
        SessionStatus.AWAITING_CONFIG,
        SessionStatus.MONITORING,  # fallback triggers (CONFIGURED without prior CONFIG_CHANGED)
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
    },
    SessionStatus.AWAITING_CONFIG: {
        SessionStatus.MONITORING,  # CONFIGURED event received
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
    },
    SessionStatus.MONITORING: {
        SessionStatus.VALIDATING,
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
    },
    SessionStatus.VALIDATING: {
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
    },
    SessionStatus.COMPLETED: set(),
    SessionStatus.FAILED: set(),
    SessionStatus.CANCELLED: set(),
}

ACTIVE_STATUSES: set[SessionStatus] = {
    SessionStatus.PENDING,
    SessionStatus.BASELINE_CAPTURE,
    SessionStatus.AWAITING_CONFIG,
    SessionStatus.MONITORING,
    SessionStatus.VALIDATING,
}


# ── Device-type monitoring defaults ─────────────────────────────────────
# (duration_minutes, interval_minutes) — used for webhook-triggered sessions
DEVICE_TYPE_MONITORING_DEFAULTS: dict[DeviceType, tuple[int, int]] = {
    DeviceType.AP: (2, 1),  # 2 min: 2 polls x 60s
    DeviceType.SWITCH: (5, 1),  # 5 min: 5 polls x 60s
    DeviceType.GATEWAY: (10, 2),  # 10 min: 5 polls x 120s
}


def get_monitoring_defaults(device_type: DeviceType) -> tuple[int, int]:
    """Return (duration_minutes, interval_minutes) for the given device type."""
    return DEVICE_TYPE_MONITORING_DEFAULTS.get(device_type, (10, 2))


# ── Timeline ────────────────────────────────────────────────────────────


class TimelineEntryType(str, Enum):
    CONFIG_CHANGE = "config_change"
    VALIDATION = "validation"
    WEBHOOK_EVENT = "webhook_event"
    SLE_CHECK = "sle_check"
    AI_ANALYSIS = "ai_analysis"
    STATUS_CHANGE = "status_change"
    AI_NARRATION = "ai_narration"  # AI-generated phase narration messages
    CHAT_MESSAGE = "chat_message"  # User question / AI response in session chat


class TimelineEntry(BaseModel):
    """A single entry in the chronological session timeline."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    type: TimelineEntryType = Field(..., description="Entry type")
    title: str = Field(..., description="Human-readable summary")
    severity: str = Field(default="", description="info, warning, critical, or empty")
    data: dict = Field(default_factory=dict, description="Type-specific payload")


# ── Config change and incident models ───────────────────────────────────


class ConfigChangeEvent(BaseModel):
    """A single config change event associated with a monitoring session."""

    event_type: str = Field(..., description="Mist event type (e.g. GW_CONFIGURED)")
    device_mac: str = Field(..., description="Device MAC address")
    device_name: str = Field(default="", description="Device name")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Event timestamp")
    webhook_event_id: str | None = Field(default=None, description="Reference to WebhookEvent document ID")
    payload_summary: dict = Field(default_factory=dict, description="Abbreviated event payload")
    config_diff: str | None = Field(default=None, description="Junos config diff (EX/SRX only, from SW/GW_CONFIGURED)")
    config_before: dict | None = Field(default=None, description="Config state before change (from audit webhook)")
    config_after: dict | None = Field(default=None, description="Config state after change (from audit webhook)")
    change_message: str = Field(default="", description="Audit message (e.g. 'Update Device ...')")
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

    # Change group reference (if this session is part of a grouped config change)
    change_group_id: PydanticObjectId | None = Field(
        default=None, description="Parent ChangeGroup ID (if part of a multi-device change)"
    )

    device_clients: list[dict] = Field(
        default_factory=list, description="LLDP neighbor MACs captured at baseline (for AP-switch correlation)"
    )
    device_port_stats: list[dict] = Field(
        default_factory=list, description="Port stats for monitored device (captured during validation)"
    )

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
    config_applied_at: datetime | None = Field(default=None, description="When the CONFIGURED event was received")
    monitoring_started_at: datetime | None = Field(default=None, description="When active monitoring began")
    monitoring_ends_at: datetime | None = Field(default=None, description="When monitoring is scheduled to end")
    completed_at: datetime | None = Field(default=None, description="When the session finished")

    # Awaiting config warnings (e.g. timeout)
    awaiting_config_warnings: list[str] = Field(
        default_factory=list, description="Warnings from the awaiting config phase"
    )

    # SLE data
    sle_baseline: dict | None = Field(default=None, description="SLE metrics captured before monitoring")
    sle_snapshots: list[dict] = Field(default_factory=list, description="Periodic SLE snapshots during monitoring")
    sle_delta: dict | None = Field(default=None, description="Computed SLE change from baseline")
    sle_drill_down: dict | None = Field(default=None, description="Detailed SLE drill-down data")

    # Routing peer baseline (OSPF/BGP)
    routing_baseline: dict | None = Field(
        default=None, description="Baseline OSPF/BGP peer stats captured before monitoring"
    )

    # Topology
    topology_baseline: dict | None = Field(default=None, description="Network topology snapshot at baseline")
    topology_latest: dict | None = Field(default=None, description="Most recent topology snapshot")

    # Template baseline (for config drift detection)
    template_baseline: dict | None = Field(
        default=None, description="Template configs captured at baseline for drift detection"
    )

    # Validation and analysis
    validation_results: dict | None = Field(default=None, description="Structured validation check results")
    ai_assessment: dict | None = Field(default=None, description="LLM-generated impact assessment")
    ai_assessment_error: str | None = Field(default=None, description="Error from AI assessment if it failed")
    ai_analysis_in_progress: bool = Field(default=False, description="True while AI analysis is running")
    impact_severity: str = Field(default="none", description="Impact severity: none, info, warning, critical")
    template_drift: dict | None = Field(default=None, description="Template config drift detected at finalization")

    # Chronological timeline (for UI display — all events, checks, analyses in order)
    timeline: list[TimelineEntry] = Field(default_factory=list, description="Chronological session timeline")

    # LLM conversation thread for session chat (user Q&A)
    conversation_thread_id: str | None = Field(
        default=None, description="ConversationThread ID for session chat"
    )

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
                name="device_mac_active_unique",
                partialFilterExpression={
                    "status": {"$in": ["pending", "baseline_capture", "awaiting_config", "monitoring", "validating"]}
                },
            ),
        ]


class SessionLogEntry(Document):
    """Per-session log entry for impact analysis diagnostics."""

    session_id: str = Field(..., description="MonitoringSession ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    level: str = Field(default="info", description="Log level: info, warning, error, debug")
    phase: str = Field(default="", description="Pipeline phase: baseline, monitoring, validation, sle, event, analysis")
    message: str = Field(..., description="Log message")
    details: dict | None = Field(default=None, description="Additional data (API responses, check results, etc.)")

    class Settings:
        name = "impact_session_logs"
        indexes = [
            "session_id",
            [("session_id", 1), ("timestamp", 1)],
        ]
