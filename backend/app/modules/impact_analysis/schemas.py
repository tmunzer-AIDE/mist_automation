"""
Pydantic request/response schemas for the Config Change Impact Analysis module.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# ── Nested response models ────────────────────────────────────────────────


class ConfigChangeEventResponse(BaseModel):
    event_type: str
    device_mac: str
    device_name: str
    timestamp: datetime
    webhook_event_id: str | None = None
    payload_summary: dict = Field(default_factory=dict)
    config_diff: str | None = None
    device_model: str = ""
    firmware_version: str = ""
    commit_user: str = ""
    commit_method: str = ""


class DeviceIncidentResponse(BaseModel):
    event_type: str
    device_mac: str
    device_name: str
    timestamp: datetime
    webhook_event_id: str | None = None
    severity: str
    is_revert: bool
    resolved: bool
    resolved_at: datetime | None = None


# ── SLE data response ─────────────────────────────────────────────────────


class SleDataResponse(BaseModel):
    baseline: dict | None = None
    snapshots: list[dict] = Field(default_factory=list)
    delta: dict | None = None
    drill_down: dict | None = None


# ── Session responses ─────────────────────────────────────────────────────


class SessionResponse(BaseModel):
    """Summary view for session list."""

    id: str
    site_id: str
    site_name: str
    device_mac: str
    device_name: str
    device_type: str
    status: str
    config_change_count: int
    incident_count: int
    has_impact: bool
    impact_severity: str = Field(default="none")
    duration_minutes: int
    polls_completed: int
    polls_total: int
    progress: dict
    monitoring_started_at: datetime | None = None
    monitoring_ends_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TimelineEntryResponse(BaseModel):
    """Single timeline entry."""

    timestamp: datetime
    type: str
    title: str
    severity: str = ""
    data: dict = Field(default_factory=dict)


class SessionDetailResponse(SessionResponse):
    """Full detail view including all nested data."""

    org_id: str
    config_changes: list[ConfigChangeEventResponse] = Field(default_factory=list)
    incidents: list[DeviceIncidentResponse] = Field(default_factory=list)
    sle_data: SleDataResponse | None = None
    topology_baseline: dict | None = None
    topology_latest: dict | None = None
    validation_results: dict | None = None
    ai_assessment: dict | None = None
    ai_assessment_error: str | None = None
    timeline: list[TimelineEntryResponse] = Field(default_factory=list)


class SessionListResponse(BaseModel):
    """Paginated list of sessions."""

    sessions: list[SessionResponse]
    total: int


class SessionLogEntryResponse(BaseModel):
    """A single session log entry."""

    id: str
    session_id: str
    timestamp: datetime
    level: str
    phase: str
    message: str
    details: dict | None = None


class SessionLogListResponse(BaseModel):
    """Paginated session logs."""

    logs: list[SessionLogEntryResponse]
    total: int


# ── Request models ────────────────────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    """Manual session creation request."""

    site_id: str = Field(..., description="Mist site ID")
    device_mac: str = Field(
        ...,
        description="Device MAC address",
        pattern=r"^[0-9a-f]{12}$",
    )
    device_type: str = Field(
        ...,
        description="Device type: ap, switch, or gateway",
        pattern=r"^(ap|switch|gateway)$",
    )
    duration_minutes: int | None = Field(
        default=None, ge=1, le=360, description="Monitoring duration in minutes (omit for device-type default)"
    )
    interval_minutes: int | None = Field(
        default=None, ge=1, le=60, description="Polling interval in minutes (omit for device-type default)"
    )


# ── Dashboard summary ─────────────────────────────────────────────────────


class SessionSummaryResponse(BaseModel):
    """Dashboard counts for impact analysis sessions."""

    active: int = Field(default=0, description="Sessions currently monitoring")
    impacted: int = Field(default=0, description="Sessions with detected impact")
    completed_24h: int = Field(default=0, description="Sessions completed in the last 24 hours")
    total: int = Field(default=0, description="Total sessions")
    active_groups: int = Field(default=0, description="Active change groups")
    impacted_groups_24h: int = Field(default=0, description="Impacted groups in last 24h")


# ── Admin settings ────────────────────────────────────────────────────────


class ImpactSettingsResponse(BaseModel):
    """Current impact analysis settings (read-only view)."""

    impact_analysis_enabled: bool
    impact_analysis_default_duration_minutes: int
    impact_analysis_default_interval_minutes: int
    impact_analysis_sle_threshold_percent: float
    impact_analysis_retention_days: int


class ImpactSettingsUpdate(BaseModel):
    """Partial update for impact analysis settings."""

    impact_analysis_enabled: bool | None = None
    impact_analysis_default_duration_minutes: int | None = Field(None, ge=1, le=360)
    impact_analysis_default_interval_minutes: int | None = Field(None, ge=1, le=60)
    impact_analysis_sle_threshold_percent: float | None = Field(None, ge=1.0, le=50.0)
    impact_analysis_retention_days: int | None = Field(None, ge=1, le=365)


# ── Session chat ─────────────────────────────────────────────────────────


class SessionChatRequest(BaseModel):
    """User sends a message to the AI about this monitoring session."""

    message: str = Field(..., min_length=1, max_length=2000, description="User message text")
    stream_id: str | None = Field(default=None, description="WebSocket stream ID for real-time token streaming")
    mcp_config_ids: list[str] | None = Field(default=None, description="External MCP server config IDs to use")


class SessionChatResponse(BaseModel):
    """AI response to a session chat message."""

    reply: str
    thread_id: str
    usage: dict = Field(default_factory=dict)


# ── Change Group schemas ─────────────────────────────────────────────────


class IncidentSummaryResponse(BaseModel):
    type: str
    severity: str
    timestamp: datetime
    resolved: bool = False


class SLEDeltaResponse(BaseModel):
    metric: str
    baseline: float
    current: float
    delta_pct: float


class DeviceSummaryResponse(BaseModel):
    """Per-device summary within a change group."""

    session_id: str
    device_mac: str
    device_name: str
    device_type: str
    site_name: str
    status: str
    impact_severity: str
    failed_checks: list[str] = Field(default_factory=list)
    active_incidents: list[IncidentSummaryResponse] = Field(default_factory=list)
    worst_sle_delta: SLEDeltaResponse | None = None


class DeviceTypeCountsResponse(BaseModel):
    total: int = 0
    monitoring: int = 0
    completed: int = 0
    impacted: int = 0


class ValidationCheckSummaryResponse(BaseModel):
    check_name: str
    passed: int = 0
    failed: int = 0
    skipped: int = 0


class GroupSummaryResponse(BaseModel):
    total_devices: int = 0
    by_type: dict[str, DeviceTypeCountsResponse] = Field(default_factory=dict)
    worst_severity: str = "none"
    validation_summary: list[ValidationCheckSummaryResponse] = Field(default_factory=list)
    sle_summary: dict[str, SLEDeltaResponse] = Field(default_factory=dict)
    devices: list[DeviceSummaryResponse] = Field(default_factory=list)
    status: str = "monitoring"
    last_updated: datetime | None = None


class ChangeGroupResponse(BaseModel):
    """Summary view for group list."""

    id: str
    audit_id: str
    org_id: str
    site_id: str | None = None
    change_source: str
    change_description: str
    triggered_by: str | None = None
    triggered_at: datetime
    session_count: int
    summary: GroupSummaryResponse
    ai_assessment: dict | None = None
    ai_assessment_error: str | None = None
    created_at: datetime
    updated_at: datetime


class ChangeGroupDetailResponse(ChangeGroupResponse):
    """Full detail view including timeline."""

    timeline: list[TimelineEntryResponse] = Field(default_factory=list)


class ChangeGroupListResponse(BaseModel):
    """Paginated list of change groups."""

    groups: list[ChangeGroupResponse]
    total: int
