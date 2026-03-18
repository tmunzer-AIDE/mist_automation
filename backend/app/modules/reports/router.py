"""
Reports API endpoints.
"""

import asyncio
import re
from datetime import datetime, timezone

import structlog
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from app.core.exceptions import AuthorizationException
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


# ── Shared helpers ────────────────────────────────────────────────────────


def _dict_to_response(item: dict) -> ReportJobResponse:
    """Build a ReportJobResponse from a raw MongoDB aggregation dict."""
    return ReportJobResponse(
        id=str(item.get("_id", item.get("id", ""))),
        report_type=item.get("report_type", ""),
        site_id=item.get("site_id", ""),
        site_name=item.get("site_name", ""),
        status=item.get("status", ""),
        progress=item.get("progress", {}),
        error=item.get("error"),
        created_by=str(item.get("created_by", "")),
        created_at=item.get("created_at"),
        completed_at=item.get("completed_at"),
    )


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


async def _get_report(report_id: str) -> ReportJob:
    """Fetch a report by ID or raise 400/404."""
    try:
        job = await ReportJob.get(PydanticObjectId(report_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid report ID") from exc
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return job


def _check_report_access(job: ReportJob, user: User) -> None:
    """Verify the user owns the report or is an admin."""
    if not user.is_admin() and job.created_by != user.id:
        raise AuthorizationException("You do not have access to this report")


def _safe_filename(name: str) -> str:
    """Sanitize a string for use in filenames."""
    return re.sub(r"[^a-zA-Z0-9\-_.]", "_", name).strip("_") or "site"


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
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch sites from Mist") from e


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
    match: dict = {"report_type": ReportType.POST_DEPLOYMENT_VALIDATION.value}
    if not _current_user.is_admin():
        match["created_by"] = _current_user.id
    if site_id:
        match["site_id"] = site_id

    pipeline: list[dict] = [{"$match": match}, {"$sort": {"created_at": -1}}]
    facet_pipeline = pipeline + [
        {
            "$facet": {
                "total": [{"$count": "n"}],
                "items": [{"$skip": skip}, {"$limit": limit}],
            }
        }
    ]

    results = await ReportJob.aggregate(facet_pipeline).to_list()
    row = results[0] if results else {}
    total = row.get("total", [{}])[0].get("n", 0) if row.get("total") else 0
    items = row.get("items", [])

    return ReportJobListResponse(
        reports=[_dict_to_response(item) for item in items],
        total=total,
    )


@router.get("/reports/validation/{report_id}", response_model=ReportJobDetailResponse, tags=["Reports"])
async def get_validation_report(
    report_id: str,
    current_user: User = Depends(require_reports_role),
):
    """Get a validation report with full results."""
    job = await _get_report(report_id)
    _check_report_access(job, current_user)

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
    current_user: User = Depends(require_reports_role),
):
    """Delete a validation report."""
    job = await _get_report(report_id)
    _check_report_access(job, current_user)

    await job.delete()
    logger.info("validation_report_deleted", report_id=report_id, user_id=str(current_user.id))


# ── Export ────────────────────────────────────────────────────────────────


@router.get("/reports/validation/{report_id}/export/pdf", tags=["Reports"])
async def export_validation_pdf(
    report_id: str,
    current_user: User = Depends(require_reports_role),
):
    """Export a completed validation report as PDF."""
    job = await _get_report(report_id)
    _check_report_access(job, current_user)
    if job.status != ReportStatus.COMPLETED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Report is not completed yet")

    from app.modules.reports.services.export_service import generate_pdf

    pdf_bytes = await asyncio.to_thread(generate_pdf, job)
    safe_name = _safe_filename(job.site_name)
    completed = job.completed_at or datetime.now(timezone.utc)
    filename = f"validation_{safe_name}_{completed:%Y%m%d}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/validation/{report_id}/export/csv", tags=["Reports"])
async def export_validation_csv(
    report_id: str,
    current_user: User = Depends(require_reports_role),
):
    """Export a completed validation report as a ZIP of CSV files."""
    job = await _get_report(report_id)
    _check_report_access(job, current_user)
    if job.status != ReportStatus.COMPLETED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Report is not completed yet")

    from app.modules.reports.services.export_service import generate_csv_zip

    zip_bytes = await asyncio.to_thread(generate_csv_zip, job)
    safe_name = _safe_filename(job.site_name)
    completed = job.completed_at or datetime.now(timezone.utc)
    filename = f"validation_{safe_name}_{completed:%Y%m%d}.zip"

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
