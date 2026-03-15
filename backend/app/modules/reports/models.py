"""
Report models for storing validation report jobs and results.
"""

from datetime import datetime, timezone
from enum import Enum

from beanie import Document, PydanticObjectId
from pydantic import Field

from app.models.mixins import TimestampMixin


class ReportStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportType(str, Enum):
    POST_DEPLOYMENT_VALIDATION = "post_deployment_validation"


class ReportJob(TimestampMixin, Document):
    """A report generation job with results."""

    report_type: ReportType = Field(..., description="Type of report")
    site_id: str = Field(..., description="Mist site ID")
    site_name: str = Field(default="", description="Site name (populated at runtime)")
    status: ReportStatus = Field(default=ReportStatus.PENDING)
    progress: dict = Field(
        default_factory=lambda: {"current_step": "", "completed": 0, "total": 0, "details": ""}
    )
    result: dict | None = Field(default=None, description="Full validation results")
    error: str | None = Field(default=None, description="Error message if failed")
    options: dict = Field(default_factory=dict, description="Report options")
    created_by: PydanticObjectId = Field(..., description="User who created the report")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = Field(default=None)

    class Settings:
        name = "report_jobs"
        indexes = [
            "report_type",
            "site_id",
            "status",
            "created_by",
        ]
