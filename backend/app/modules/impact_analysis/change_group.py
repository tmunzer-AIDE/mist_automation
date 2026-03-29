"""
Change Group model — groups monitoring sessions triggered by the same audit event.
"""

from datetime import datetime, timezone

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import IndexModel

from app.models.mixins import TimestampMixin
from app.modules.impact_analysis.models import TimelineEntry


class IncidentSummary(BaseModel):
    """Abbreviated incident for the group summary."""

    type: str
    severity: str
    timestamp: datetime
    resolved: bool = False


class SLEDelta(BaseModel):
    """SLE metric delta for a single metric."""

    metric: str
    baseline: float
    current: float
    delta_pct: float


class DeviceSummary(BaseModel):
    """Per-device summary within a change group."""

    session_id: PydanticObjectId
    device_mac: str
    device_name: str
    device_type: str  # "ap", "switch", "gateway"
    site_name: str
    status: str
    impact_severity: str
    failed_checks: list[str] = Field(default_factory=list)
    active_incidents: list[IncidentSummary] = Field(default_factory=list)
    worst_sle_delta: SLEDelta | None = None


class DeviceTypeCounts(BaseModel):
    """Counts per device type."""

    total: int = 0
    monitoring: int = 0
    completed: int = 0
    impacted: int = 0


class ValidationCheckSummary(BaseModel):
    """Aggregate pass/fail/skip counts for a single validation check."""

    check_name: str
    passed: int = 0
    failed: int = 0
    skipped: int = 0


class GroupSummary(BaseModel):
    """Live aggregate summary of all child sessions."""

    total_devices: int = 0
    by_type: dict[str, DeviceTypeCounts] = Field(default_factory=dict)
    worst_severity: str = "none"
    validation_summary: list[ValidationCheckSummary] = Field(default_factory=list)
    sle_summary: dict[str, SLEDelta] = Field(default_factory=dict)
    devices: list[DeviceSummary] = Field(default_factory=list)
    status: str = "monitoring"  # "monitoring", "partial", "completed"
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChangeGroup(TimestampMixin, Document):
    """Groups monitoring sessions triggered by the same configuration change (audit_id)."""

    audit_id: str = Field(..., description="Correlation key from Mist webhooks")
    org_id: str = Field(..., description="Mist organization ID")
    site_id: str | None = Field(default=None, description="Site ID (None for org-level changes)")

    # What triggered this
    change_source: str = Field(default="", description="e.g. org_template, site_settings")
    change_description: str = Field(default="", description="Human-readable, e.g. Template 'Branch-AP' modified")
    triggered_by: str | None = Field(default=None, description="User/method from audit event")
    triggered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Child sessions
    session_ids: list[PydanticObjectId] = Field(default_factory=list)

    # Live aggregate summary
    summary: GroupSummary = Field(default_factory=GroupSummary)

    # AI assessment (one per group)
    ai_assessment: dict | None = Field(default=None, description="LLM-generated group impact assessment")
    ai_assessment_error: str | None = Field(default=None)
    ai_analysis_in_progress: bool = Field(default=False)
    conversation_thread_id: str | None = Field(default=None)

    # Group-level timeline (creation, AI analysis, severity escalations)
    timeline: list[TimelineEntry] = Field(default_factory=list)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "change_groups"
        indexes = [
            IndexModel([("audit_id", 1)], unique=True),
            IndexModel([("org_id", 1)]),
            IndexModel([("summary.status", 1)]),
            IndexModel([("created_at", -1)]),
        ]
