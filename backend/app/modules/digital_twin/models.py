"""
Data models for the Digital Twin module.

TwinSession tracks a pre-deployment simulation: staged writes,
validation results, remediation history, and deployment status.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel

from app.models.mixins import TimestampMixin


class TwinSessionStatus(str, Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    DEPLOYED = "deployed"
    REJECTED = "rejected"
    FAILED = "failed"


class StagedWrite(BaseModel):
    """A single intercepted Mist API write operation."""

    sequence: int
    method: Literal["POST", "PUT", "DELETE"]
    endpoint: str
    body: dict[str, Any] | None = None
    object_type: str | None = None
    site_id: str | None = None
    object_id: str | None = None
    synthetic_response: dict[str, Any] | None = None


class CheckResult(BaseModel):
    """Result of a single validation check."""

    check_id: str
    check_name: str
    layer: int
    status: Literal["pass", "warning", "error", "critical", "skipped"]
    summary: str
    details: list[str] = Field(default_factory=list)
    affected_objects: list[str] = Field(default_factory=list)
    affected_sites: list[str] = Field(default_factory=list)
    remediation_hint: str | None = None


class PredictionReport(BaseModel):
    """Aggregated results of all validation checks."""

    total_checks: int = 0
    passed: int = 0
    warnings: int = 0
    errors: int = 0
    critical: int = 0
    skipped: int = 0
    check_results: list[CheckResult] = Field(default_factory=list)
    overall_severity: Literal["clean", "info", "warning", "error", "critical"] = "clean"
    summary: str = ""
    execution_safe: bool = True


class RemediationAttempt(BaseModel):
    """Record of a single LLM fix iteration."""

    attempt: int
    changed_writes: list[int] = Field(default_factory=list)
    previous_severity: str = ""
    new_severity: str = ""
    fixed_checks: list[str] = Field(default_factory=list)
    introduced_checks: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BaseSnapshotRef(BaseModel):
    """Reference to a backup snapshot used as base state."""

    backup_object_id: str
    version: int
    object_type: str
    object_id: str
    site_id: str | None = None


class TwinSession(Document, TimestampMixin):
    """
    Tracks a pre-deployment simulation session.

    Lifecycle: pending -> validating -> awaiting_approval -> approved -> executing -> deployed
    Or: -> rejected | failed at any point.
    """

    user_id: PydanticObjectId
    org_id: str
    source: Literal["llm_chat", "workflow", "backup_restore"] = "llm_chat"
    source_ref: str | None = None
    status: TwinSessionStatus = TwinSessionStatus.PENDING
    staged_writes: list[StagedWrite] = Field(default_factory=list)
    affected_sites: list[str] = Field(default_factory=list)
    affected_object_types: list[str] = Field(default_factory=list)
    base_snapshot_refs: list[BaseSnapshotRef] = Field(default_factory=list)
    live_fetched_at: datetime | None = None
    resolved_state: dict[str, Any] | None = None
    prediction_report: PredictionReport | None = None
    overall_severity: Literal["clean", "info", "warning", "error", "critical"] = "clean"
    remediation_count: int = 0
    remediation_history: list[RemediationAttempt] = Field(default_factory=list)
    ai_assessment: str | None = None
    ia_session_ids: list[str] = Field(default_factory=list)

    class Settings:
        name = "twin_sessions"
        indexes = [
            IndexModel([("user_id", ASCENDING), ("status", ASCENDING)]),
            IndexModel([("created_at", ASCENDING)], expireAfterSeconds=86400),
        ]
