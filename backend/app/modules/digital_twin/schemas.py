"""Pydantic request/response schemas for the Digital Twin API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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


class TwinSessionResponse(BaseModel):
    id: str
    status: str
    source: str
    overall_severity: str
    writes_count: int
    affected_sites: list[str] = Field(default_factory=list)
    remediation_count: int = 0
    prediction_report: PredictionReportResponse | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TwinSessionListResponse(BaseModel):
    sessions: list[TwinSessionResponse]
    total: int


def session_to_response(session) -> TwinSessionResponse:
    """Convert a TwinSession document to a response DTO."""
    report = None
    if session.prediction_report:
        p = session.prediction_report
        report = PredictionReportResponse(
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

    return TwinSessionResponse(
        id=str(session.id),
        status=session.status.value,
        source=session.source,
        overall_severity=session.overall_severity,
        writes_count=len(session.staged_writes),
        affected_sites=session.affected_sites,
        remediation_count=session.remediation_count,
        prediction_report=report,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
