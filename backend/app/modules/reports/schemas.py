"""
Request/response schemas for the reports module.
"""

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class ValidationReportCreate(BaseModel):
    """Request body for creating a post-deployment validation report."""

    site_id: str = Field(..., description="Mist site ID to validate")

    @field_validator("site_id")
    @classmethod
    def validate_site_id(cls, v: str) -> str:
        if not _UUID_RE.match(v):
            raise ValueError("site_id must be a valid UUID")
        return v


class ReportJobResponse(BaseModel):
    """Response schema for a report job."""

    id: str
    report_type: str
    site_id: str
    site_name: str
    status: str
    progress: dict
    error: str | None = None
    created_by: str
    created_at: datetime
    completed_at: datetime | None = None


class ReportJobDetailResponse(ReportJobResponse):
    """Response schema for a report job with full results."""

    result: dict | None = None


class ReportJobListResponse(BaseModel):
    """Response schema for listing report jobs."""

    reports: list[ReportJobResponse]
    total: int
