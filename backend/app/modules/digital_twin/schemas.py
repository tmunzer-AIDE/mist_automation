"""Pydantic request/response schemas for the Digital Twin API."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

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


class StagedWriteResponse(BaseModel):
    sequence: int
    method: str
    endpoint: str
    body: dict[str, Any] | None = None
    object_type: str | None = None
    site_id: str | None = None
    object_id: str | None = None


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
    writes_count: int
    affected_sites: list[str] = Field(default_factory=list)
    remediation_count: int = 0
    prediction_report: PredictionReportResponse | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TwinSessionDetailResponse(TwinSessionResponse):
    ai_assessment: str | None = None
    execution_safe: bool = True
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
        remediation_count=session.remediation_count,
        prediction_report=_build_report_response(session),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def session_to_detail_response(session: TwinSession) -> TwinSessionDetailResponse:
    """Convert a TwinSession document to a detail response DTO with full write and remediation history."""
    base = session_to_response(session)
    return TwinSessionDetailResponse(
        **base.model_dump(),
        ai_assessment=session.ai_assessment,
        execution_safe=session.prediction_report.execution_safe if session.prediction_report else True,
        staged_writes=[
            StagedWriteResponse(
                sequence=w.sequence,
                method=w.method,
                endpoint=w.endpoint,
                body=w.body,
                object_type=w.object_type,
                site_id=w.site_id,
                object_id=w.object_id,
            )
            for w in session.staged_writes
        ],
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
