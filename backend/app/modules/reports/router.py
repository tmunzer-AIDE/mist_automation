"""
Reports API endpoints.
"""

import re

import structlog
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from app.core.tasks import create_background_task
from app.dependencies import require_reports_role
from app.models.user import User
from app.modules.reports.models import ReportJob, ReportStatus, ReportType
from app.modules.reports.schemas import (
    ReportJobDetailResponse,
    ReportJobListResponse,
    ReportJobResponse,
    ValidationReportCreate,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


def _job_to_response(job: ReportJob) -> ReportJobResponse:
    return ReportJobResponse(
        id=str(job.id),
        report_type=job.report_type.value,
        site_id=job.site_id,
        site_name=job.site_name,
        status=job.status.value,
        progress=job.progress,
        error=job.error,
        created_by=str(job.created_by),
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


# ── Sites (for site picker) ─────────────────────────────────────────────


@router.get("/reports/sites", tags=["Reports"])
async def list_sites(_current_user: User = Depends(require_reports_role)):
    """List organization sites for the report site picker."""
    from app.services.mist_service_factory import create_mist_service

    try:
        service = await create_mist_service()
        sites = await service.get_sites()
        return {"sites": [{"id": s.get("id"), "name": s.get("name", "")} for s in sites]}
    except Exception as e:
        logger.error("report_sites_fetch_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch sites from Mist"
        ) from e


# ── Validation Reports ───────────────────────────────────────────────────


@router.post(
    "/reports/validation",
    response_model=ReportJobResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Reports"],
)
async def create_validation_report(
    request: ValidationReportCreate,
    current_user: User = Depends(require_reports_role),
):
    """Create a new post-deployment validation report for a site."""
    job = ReportJob(
        report_type=ReportType.POST_DEPLOYMENT_VALIDATION,
        site_id=request.site_id,
        status=ReportStatus.PENDING,
        created_by=current_user.id,
    )
    await job.insert()

    logger.info(
        "validation_report_created",
        report_id=str(job.id),
        site_id=request.site_id,
        user_id=str(current_user.id),
    )

    from app.modules.reports.services.validation_service import run_post_deployment_validation

    create_background_task(
        run_post_deployment_validation(str(job.id), request.site_id),
        name=f"validation-report-{job.id}",
    )

    return _job_to_response(job)


@router.get("/reports/validation", response_model=ReportJobListResponse, tags=["Reports"])
async def list_validation_reports(
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    site_id: str | None = Query(None, description="Filter by site ID"),
    _current_user: User = Depends(require_reports_role),
):
    """List past validation reports."""
    query: dict = {"report_type": ReportType.POST_DEPLOYMENT_VALIDATION.value}
    if site_id:
        query["site_id"] = site_id

    total = await ReportJob.find(query).count()
    jobs = await ReportJob.find(query).sort("-created_at").skip(skip).limit(limit).to_list()

    return ReportJobListResponse(
        reports=[_job_to_response(j) for j in jobs],
        total=total,
    )


@router.get("/reports/validation/{report_id}", response_model=ReportJobDetailResponse, tags=["Reports"])
async def get_validation_report(
    report_id: str,
    _current_user: User = Depends(require_reports_role),
):
    """Get a validation report with full results."""
    try:
        job = await ReportJob.get(PydanticObjectId(report_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid report ID") from exc

    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    return ReportJobDetailResponse(
        id=str(job.id),
        report_type=job.report_type.value,
        site_id=job.site_id,
        site_name=job.site_name,
        status=job.status.value,
        progress=job.progress,
        error=job.error,
        result=job.result,
        created_by=str(job.created_by),
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


@router.delete("/reports/validation/{report_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Reports"])
async def delete_validation_report(
    report_id: str,
    _current_user: User = Depends(require_reports_role),
):
    """Delete a validation report."""
    try:
        job = await ReportJob.get(PydanticObjectId(report_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid report ID") from exc

    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    await job.delete()
    logger.info("validation_report_deleted", report_id=report_id, user_id=str(_current_user.id))


# ── Export ────────────────────────────────────────────────────────────────


@router.get("/reports/validation/{report_id}/export/pdf", tags=["Reports"])
async def export_validation_pdf(
    report_id: str,
    _current_user: User = Depends(require_reports_role),
):
    """Export a completed validation report as PDF."""
    job = await _get_completed_report(report_id)

    from app.modules.reports.services.export_service import generate_pdf

    pdf_bytes = generate_pdf(job)
    safe_name = _safe_filename(job.site_name)
    filename = f"validation_{safe_name}_{job.completed_at:%Y%m%d}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/validation/{report_id}/export/csv", tags=["Reports"])
async def export_validation_csv(
    report_id: str,
    _current_user: User = Depends(require_reports_role),
):
    """Export a completed validation report as a ZIP of CSV files."""
    job = await _get_completed_report(report_id)

    from app.modules.reports.services.export_service import generate_csv_zip

    zip_bytes = generate_csv_zip(job)
    safe_name = _safe_filename(job.site_name)
    filename = f"validation_{safe_name}_{job.completed_at:%Y%m%d}.zip"

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _safe_filename(name: str) -> str:
    """Sanitize a string for use in filenames."""
    return re.sub(r"[^\w\-.]", "_", name).strip("_") or "site"


async def _get_completed_report(report_id: str) -> ReportJob:
    """Fetch a report and verify it's completed."""
    try:
        job = await ReportJob.get(PydanticObjectId(report_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid report ID") from exc

    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    if job.status != ReportStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Report is not completed yet",
        )

    return job
