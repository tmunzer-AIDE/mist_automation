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
