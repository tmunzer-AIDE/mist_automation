"""
Backup and restore API endpoints.
"""

import asyncio
import structlog
from datetime import datetime
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user_from_token
from app.models.backup import BackupJob, BackupStatus, BackupType
from app.models.user import User
from app.schemas.backup import BackupJobResponse, BackupJobListResponse, BackupDiffResponse

router = APIRouter()
logger = structlog.get_logger(__name__)


def _deep_diff(a: dict, b: dict, path: str = "") -> list[dict]:
    changes, all_keys = [], set(a) | set(b)
    for key in all_keys:
        p = f"{path}.{key}" if path else key
        if key not in a:
            changes.append({"path": p, "type": "added", "value": b[key]})
        elif key not in b:
            changes.append({"path": p, "type": "removed", "value": a[key]})
        elif isinstance(a[key], dict) and isinstance(b[key], dict):
            changes.extend(_deep_diff(a[key], b[key], p))
        elif a[key] != b[key]:
            changes.append({"path": p, "type": "modified", "old": a[key], "new": b[key]})
    return changes


@router.get("/backups", response_model=BackupJobListResponse, tags=["Backups"])
async def list_backups(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    backup_type: str | None = Query(None, description="Filter by backup type"),
    org_id: str | None = Query(None, description="Filter by organization ID"),
    _current_user: User = Depends(get_current_user_from_token)
):
    """
    List all configuration backups.
    """
    # Build query
    query = {}
    if backup_type:
        query["backup_type"] = backup_type
    if org_id:
        query["org_id"] = org_id

    # Get total count
    total = await BackupJob.find(query).count()

    # Get backups with pagination
    backups = await BackupJob.find(query).sort("-created_at").skip(skip).limit(limit).to_list()

    return BackupJobListResponse(
        backups=[
            BackupJobResponse(
                id=str(backup.id),
                backup_type=backup.backup_type.value,
                org_id=backup.org_id,
                org_name=backup.org_name,
                site_id=backup.site_id,
                site_name=backup.site_name,
                status=backup.status.value,
                object_count=backup.object_count,
                size_bytes=backup.size_bytes,
                created_at=backup.created_at,
                created_by=str(backup.created_by) if backup.created_by else None
            )
            for backup in backups
        ],
        total=total
    )


@router.post("/backups", response_model=BackupJobResponse, status_code=status.HTTP_201_CREATED, tags=["Backups"])
async def create_backup(
    org_id: str = Query(..., description="Organization ID to backup"),
    site_id: str | None = Query(None, description="Site ID to backup (optional)"),
    backup_type: str = Query("manual", description="Backup type: manual, scheduled, or pre_change"),
    current_user: User = Depends(get_current_user_from_token)
):
    """
    Manually trigger a configuration backup.
    """
    # Create backup record
    backup = BackupJob(
        backup_type=BackupType(backup_type),
        org_id=org_id,
        site_id=site_id,
        status=BackupStatus.PENDING,
        created_by=current_user.id
    )
    await backup.insert()

    logger.info("backup_created", backup_id=str(backup.id), org_id=org_id, user_id=str(current_user.id))

    from app.workers.backup_worker import perform_backup
    asyncio.create_task(perform_backup(str(backup.id), backup_type, org_id, site_id))

    return BackupJobResponse(
        id=str(backup.id),
        backup_type=backup.backup_type.value,
        org_id=backup.org_id,
        org_name=backup.org_name,
        site_id=backup.site_id,
        site_name=backup.site_name,
        status=backup.status.value,
        object_count=backup.object_count,
        size_bytes=backup.size_bytes,
        created_at=backup.created_at,
        created_by=str(backup.created_by) if backup.created_by else None
    )


@router.get("/backups/{backup_id}", response_model=BackupJobResponse, tags=["Backups"])
async def get_backup(
    backup_id: str,
    _current_user: User = Depends(get_current_user_from_token)
):
    """
    Get backup details by ID with full configuration data.
    """
    try:
        backup = await BackupJob.get(PydanticObjectId(backup_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid backup ID format"
        ) from exc

    if not backup:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup not found"
        )

    return BackupJobResponse(
        id=str(backup.id),
        backup_type=backup.backup_type.value,
        org_id=backup.org_id,
        org_name=backup.org_name,
        site_id=backup.site_id,
        site_name=backup.site_name,
        status=backup.status.value,
        object_count=backup.object_count,
        size_bytes=backup.size_bytes,
        created_at=backup.created_at,
        created_by=str(backup.created_by) if backup.created_by else None,
        data=backup.data,
        error=backup.error
    )


@router.post("/backups/{backup_id}/restore", tags=["Backups"])
async def restore_backup(
    backup_id: str,
    dry_run: bool = Query(False, description="Perform a dry run without applying changes"),
    current_user: User = Depends(get_current_user_from_token)
):
    """
    Restore configuration from a backup.
    """
    try:
        backup = await BackupJob.get(PydanticObjectId(backup_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid backup ID format"
        ) from exc

    if not backup:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup not found"
        )

    if backup.status != BackupStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot restore from incomplete backup"
        )

    logger.info("backup_restore_triggered", backup_id=str(backup.id), dry_run=dry_run, user_id=str(current_user.id))

    from app.workers.backup_worker import perform_restore
    asyncio.create_task(perform_restore(str(backup.id), dry_run))

    return {
        "status": "queued",
        "backup_id": str(backup.id),
        "dry_run": dry_run,
        "message": "Restore operation queued for processing"
    }


@router.get("/backups/compare", response_model=BackupDiffResponse, tags=["Backups"])
async def compare_backups(
    backup_id_1: str = Query(..., description="First backup ID"),
    backup_id_2: str = Query(..., description="Second backup ID"),
    _current_user: User = Depends(get_current_user_from_token)
):
    """
    Compare two backups to see configuration differences.
    """
    # Get both backups
    try:
        backup1 = await BackupJob.get(PydanticObjectId(backup_id_1))
        backup2 = await BackupJob.get(PydanticObjectId(backup_id_2))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid backup ID format"
        ) from exc

    if not backup1 or not backup2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or both backups not found"
        )

    if backup1.data is None or backup1.status != BackupStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Backup {backup_id_1} is not completed or has no data"
        )

    if backup2.data is None or backup2.status != BackupStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Backup {backup_id_2} is not completed or has no data"
        )

    differences = _deep_diff(backup1.data, backup2.data)
    added_count = sum(1 for d in differences if d["type"] == "added")
    removed_count = sum(1 for d in differences if d["type"] == "removed")
    modified_count = sum(1 for d in differences if d["type"] == "modified")

    return BackupDiffResponse(
        backup_id_1=str(backup1.id),
        backup_id_2=str(backup2.id),
        differences=differences,
        added_count=added_count,
        removed_count=removed_count,
        modified_count=modified_count
    )


@router.get("/backups/timeline", tags=["Backups"])
async def get_backup_timeline(
    org_id: str = Query(..., description="Organization ID"),
    site_id: str | None = Query(None, description="Site ID (optional)"),
    start_date: str | None = Query(None, description="Start date (ISO format)"),
    end_date: str | None = Query(None, description="End date (ISO format)"),
    _current_user: User = Depends(get_current_user_from_token)
):
    """
    Get timeline view of configuration changes over time.
    """
    # Build query
    query = {"org_id": org_id}
    if site_id:
        query["site_id"] = site_id

    if start_date:
        query["created_at"] = {"$gte": datetime.fromisoformat(start_date)}
    if end_date:
        query.setdefault("created_at", {})["$lte"] = datetime.fromisoformat(end_date)

    # Get backups
    backups = await BackupJob.find(query).sort("-created_at").to_list()

    return {
        "org_id": org_id,
        "site_id": site_id,
        "backups": [
            {
                "id": str(backup.id),
                "backup_type": backup.backup_type.value,
                "status": backup.status.value,
                "object_count": backup.object_count,
                "created_at": backup.created_at,
                "created_by": str(backup.created_by) if backup.created_by else None
            }
            for backup in backups
        ],
        "total": len(backups)
    }
