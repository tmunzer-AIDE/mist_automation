"""Pydantic request/response schemas for the Digital Twin API."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from app.modules.digital_twin.models import StagedWrite

if TYPE_CHECKING:
    from app.modules.digital_twin.models import TwinSession


class CheckResultResponse(BaseModel):
    check_id: str
    check_name: str
    layer: int
    status: str
    summary: str
    details: list[str] = Field(default_factory=list)
    affected_objects: list[str] = Field(default_factory=list)
    affected_sites: list[str] = Field(default_factory=list)
    remediation_hint: str | None = None
    pre_existing: bool = False
    description: str = ""


class PredictionReportResponse(BaseModel):
    total_checks: int = 0
    passed: int = 0
    warnings: int = 0
    errors: int = 0
    critical: int = 0
    skipped: int = 0
    check_results: list[CheckResultResponse] = Field(default_factory=list)
    overall_severity: str = "clean"
    summary: str = ""
    execution_safe: bool = True


class WriteDiffField(BaseModel):
    path: str
    change: Literal["added", "removed", "modified"]
    before: Any | None = None
    after: Any | None = None


class StagedWriteResponse(BaseModel):
    sequence: int
    method: str
    endpoint: str
    body: dict[str, Any] | None = None
    object_type: str | None = None
    site_id: str | None = None
    object_id: str | None = None
    diff: list[WriteDiffField] = Field(default_factory=list)
    diff_summary: str | None = None


class RemediationAttemptResponse(BaseModel):
    attempt: int
    changed_writes: list[int] = Field(default_factory=list)
    previous_severity: str = ""
    new_severity: str = ""
    fixed_checks: list[str] = Field(default_factory=list)
    introduced_checks: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None


class TwinSessionResponse(BaseModel):
    id: str
    status: str
    source: str
    source_ref: str | None = None
    overall_severity: str
    writes_count: int  # deprecated — will be removed after frontend migration
    affected_sites: list[str] = Field(default_factory=list)
    affected_site_labels: list[str] = Field(default_factory=list)
    affected_object_label: str | None = None
    affected_object_types: list[str] = Field(default_factory=list)
    remediation_count: int = 0
    prediction_report: PredictionReportResponse | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TwinSessionDetailResponse(TwinSessionResponse):
    ai_assessment: str | None = None
    execution_safe: bool = False
    staged_writes: list[StagedWriteResponse] = Field(default_factory=list)
    remediation_history: list[RemediationAttemptResponse] = Field(default_factory=list)


class TwinSessionListResponse(BaseModel):
    sessions: list[TwinSessionResponse]
    total: int


def _build_report_response(session: TwinSession) -> PredictionReportResponse | None:
    """Build a PredictionReportResponse from a session's prediction_report."""
    if not session.prediction_report:
        return None
    p = session.prediction_report
    return PredictionReportResponse(
        total_checks=p.total_checks,
        passed=p.passed,
        warnings=p.warnings,
        errors=p.errors,
        critical=p.critical,
        skipped=p.skipped,
        check_results=[CheckResultResponse(**r.model_dump()) for r in p.check_results],
        overall_severity=p.overall_severity,
        summary=p.summary,
        execution_safe=p.execution_safe,
    )


def session_to_response(session: TwinSession) -> TwinSessionResponse:
    """Convert a TwinSession document to a response DTO."""
    return TwinSessionResponse(
        id=str(session.id),
        status=session.status.value,
        source=session.source,
        source_ref=session.source_ref,
        overall_severity=session.overall_severity,
        writes_count=len(session.staged_writes),
        affected_sites=session.affected_sites,
        affected_site_labels=session.affected_site_labels,
        affected_object_label=session.affected_object_label,
        affected_object_types=session.affected_object_types,
        remediation_count=session.remediation_count,
        prediction_report=_build_report_response(session),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def session_to_detail_response(session: TwinSession) -> TwinSessionDetailResponse:
    """Convert a TwinSession document to a detail response DTO with full write and remediation history."""
    from app.modules.digital_twin.services.state_resolver import canonicalize_object_type
    from app.modules.digital_twin.services.write_diff import build_write_diff

    base = session_to_response(session)

    base_state = session.resolved_state or {}

    def _base_body_for(write: StagedWrite) -> dict[str, Any] | None:
        canonical = canonicalize_object_type(write.object_type) or ""
        key = str((canonical, write.site_id, write.object_id))
        value = base_state.get(key)
        return value if isinstance(value, dict) else None

    staged_writes: list[StagedWriteResponse] = []
    for w in session.staged_writes:
        diff_entries, diff_summary = build_write_diff(w, _base_body_for(w))
        staged_writes.append(
            StagedWriteResponse(
                sequence=w.sequence,
                method=w.method,
                endpoint=w.endpoint,
                body=w.body,
                object_type=w.object_type,
                site_id=w.site_id,
                object_id=w.object_id,
                diff=[WriteDiffField(**d) for d in diff_entries],
                diff_summary=diff_summary,
            )
        )

    return TwinSessionDetailResponse(
        **base.model_dump(),
        ai_assessment=session.ai_assessment,
        execution_safe=session.prediction_report.execution_safe if session.prediction_report else False,
        staged_writes=staged_writes,
        remediation_history=[
            RemediationAttemptResponse(
                attempt=r.attempt,
                changed_writes=r.changed_writes,
                previous_severity=r.previous_severity,
                new_severity=r.new_severity,
                fixed_checks=r.fixed_checks,
                introduced_checks=r.introduced_checks,
                timestamp=r.timestamp,
            )
            for r in session.remediation_history
        ],
    )
