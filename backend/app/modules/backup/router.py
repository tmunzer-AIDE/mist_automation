"""
Backup and restore API endpoints.
"""

import asyncio
import structlog
from datetime import datetime
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.dependencies import get_current_user_from_token
from app.modules.backup.models import BackupJob, BackupStatus, BackupType
from app.models.user import User
from app.models.system import SystemConfig
from app.core.security import decrypt_sensitive_data
from app.modules.backup.models import BackupObject
from app.modules.backup.schemas import (
    BackupJobResponse,
    BackupJobListResponse,
    BackupDiffResponse,
    BackupObjectSummary,
    BackupObjectListResponse,
    BackupChangeEvent,
    BackupChangeListResponse,
    BackupObjectVersionResponse,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


async def _resolve_site_names(site_ids: set[str]) -> dict[str, str]:
    """Batch-resolve site IDs to site names.

    Resolution order:
    1. Backed-up site data (``object_type="sites"``) — no API call needed.
    2. Mist API ``get_sites()`` — fallback for sites not yet backed up.

    Returns:
        Mapping of site_id → site_name.
    """
    if not site_ids:
        return {}

    names: dict[str, str] = {}

    # 1. Try backed-up site data
    docs = await (
        BackupObject.find(
            {"object_type": "sites", "object_id": {"$in": list(site_ids)}},
        )
        .sort([("version", -1)])
        .to_list()
    )
    for d in docs:
        if d.object_id not in names:
            names[d.object_id] = (
                d.object_name
                or d.configuration.get("name")
                or d.object_id[:8]
            )

    # 2. Fallback to Mist API for any unresolved IDs
    missing = site_ids - names.keys()
    if missing:
        try:
            config = await SystemConfig.get_config()
            if config and config.mist_api_token:
                from app.services.mist_service import MistService

                api_token = decrypt_sensitive_data(config.mist_api_token)
                service = MistService(
                    api_token=api_token,
                    org_id=config.mist_org_id or "",
                    cloud_region=config.mist_cloud_region or "global_01",
                )
                sites = await service.get_sites()
                for s in sites:
                    sid = s.get("id", "")
                    if sid in missing:
                        names[sid] = s.get("name", sid[:8])
        except Exception as exc:
            logger.debug("site_name_api_fallback_failed", error=str(exc))

    return names


class BackupCreateRequest(BaseModel):
    backup_type: str = Field(default="full", description="Backup type: manual or full")
    site_id: str | None = Field(default=None, description="Site ID (for site-scoped manual backup)")
    object_type: str | None = Field(default=None, description="Object type in 'org:key' or 'site:key' format (for manual backup)")
    object_ids: list[str] | None = Field(default=None, description="Object IDs to backup (for manual list-type backup)")


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
    request: BackupCreateRequest,
    current_user: User = Depends(get_current_user_from_token)
):
    """
    Trigger a configuration backup.
    For 'full' backups: backs up the entire org (org_id from system config).
    For 'manual' backups: backs up selected objects.
    """
    # Get org_id from system config
    config = await SystemConfig.get_config()
    if not config or not config.mist_org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mist Organization ID not configured in system settings"
        )
    org_id = config.mist_org_id

    # Validate manual backup params
    if request.backup_type == "manual":
        if not request.object_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="object_type is required for manual backups"
            )
        if ":" not in request.object_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="object_type must be in 'org:key' or 'site:key' format"
            )
        scope, key = request.object_type.split(":", 1)

        from app.modules.backup.object_registry import ORG_OBJECTS, SITE_OBJECTS
        registry = ORG_OBJECTS if scope == "org" else SITE_OBJECTS
        obj_def = registry.get(key)
        if not obj_def:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown object type: {request.object_type}"
            )
        if scope == "site" and not request.site_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="site_id is required for site-scoped manual backups"
            )
        if obj_def.is_list and (not request.object_ids or len(request.object_ids) == 0):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one object_id is required for list-type manual backups"
            )

    # Create backup record
    backup = BackupJob(
        backup_type=BackupType(request.backup_type),
        org_id=org_id,
        site_id=request.site_id,
        status=BackupStatus.PENDING,
        created_by=current_user.id
    )
    await backup.insert()

    logger.info("backup_created", backup_id=str(backup.id), org_id=org_id, user_id=str(current_user.id))

    from app.modules.backup.workers import perform_backup
    asyncio.create_task(perform_backup(
        str(backup.id),
        request.backup_type,
        org_id,
        request.site_id,
        object_type=request.object_type,
        object_ids=request.object_ids,
    ))

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


@router.get("/backups/objects", response_model=BackupObjectListResponse, tags=["Backups"])
async def list_backup_objects(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    search: str | None = Query(None, description="Search object name, type, or ID"),
    object_type: str | None = Query(None, description="Filter by object type"),
    site_id: str | None = Query(None, description="Filter by site ID"),
    scope: str | None = Query(None, description="Filter by scope: org or site"),
    status_filter: str | None = Query(None, alias="status", description="Filter: active, deleted"),
    _current_user: User = Depends(get_current_user_from_token),
):
    """
    List backed-up objects with latest version summary.
    Groups by object_id and returns one row per unique object.
    """
    # Use MongoDB aggregation to get latest version per object_id
    pipeline: list[dict] = []

    # Match stage — apply filters
    match: dict = {}
    if object_type:
        match["object_type"] = object_type
    if site_id:
        match["site_id"] = site_id
    if scope == "org":
        match["site_id"] = None
    elif scope == "site":
        match["site_id"] = {"$ne": None}
    if search:
        match["$or"] = [
            {"object_name": {"$regex": search, "$options": "i"}},
            {"object_type": {"$regex": search, "$options": "i"}},
            {"object_id": {"$regex": search, "$options": "i"}},
        ]
    if match:
        pipeline.append({"$match": match})

    # Sort by version descending so $first picks latest
    pipeline.append({"$sort": {"version": -1}})

    # Group by object_id — pick latest version's data
    pipeline.append({
        "$group": {
            "_id": "$object_id",
            "object_id": {"$first": "$object_id"},
            "object_type": {"$first": "$object_type"},
            "object_name": {"$first": "$object_name"},
            "org_id": {"$first": "$org_id"},
            "site_id": {"$first": "$site_id"},
            "latest_version": {"$first": "$version"},
            "version_count": {"$sum": 1},
            "first_backed_up_at": {"$min": "$backed_up_at"},
            "last_backed_up_at": {"$max": "$backed_up_at"},
            "is_deleted": {"$first": "$is_deleted"},
            "event_type": {"$first": "$event_type"},
        }
    })

    # Post-group filter for status
    if status_filter == "active":
        pipeline.append({"$match": {"is_deleted": False}})
    elif status_filter == "deleted":
        pipeline.append({"$match": {"is_deleted": True}})

    # Count total before pagination
    count_pipeline = pipeline + [{"$count": "total"}]
    count_result = await BackupObject.aggregate(count_pipeline).to_list()
    total = count_result[0]["total"] if count_result else 0

    # Sort, skip, limit
    pipeline.append({"$sort": {"last_backed_up_at": -1}})
    pipeline.append({"$skip": skip})
    pipeline.append({"$limit": limit})

    results = await BackupObject.aggregate(pipeline).to_list()

    # Resolve site names for all site-scoped objects
    site_ids = {r["site_id"] for r in results if r.get("site_id")}
    site_names = await _resolve_site_names(site_ids)

    objects = []
    for r in results:
        site_id_val = r.get("site_id")
        objects.append(BackupObjectSummary(
            object_id=r["object_id"],
            object_type=r["object_type"],
            object_name=r.get("object_name"),
            org_id=r["org_id"],
            site_id=site_id_val,
            site_name=site_names.get(site_id_val) if site_id_val else None,
            scope="org" if not site_id_val else "site",
            version_count=r["version_count"],
            latest_version=r["latest_version"],
            first_backed_up_at=r["first_backed_up_at"],
            last_backed_up_at=r["last_backed_up_at"],
            is_deleted=r.get("is_deleted", False),
            event_type=r.get("event_type", ""),
        ))

    return BackupObjectListResponse(objects=objects, total=total)


@router.get("/backups/changes", response_model=BackupChangeListResponse, tags=["Backups"])
async def list_backup_changes(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    object_type: str | None = Query(None, description="Filter by object type"),
    event_type: str | None = Query(None, description="Filter by event type"),
    site_id: str | None = Query(None, description="Filter by site ID"),
    scope: str | None = Query(None, description="Filter by scope: org or site"),
    start_date: str | None = Query(None, description="Start date (ISO format)"),
    end_date: str | None = Query(None, description="End date (ISO format)"),
    _current_user: User = Depends(get_current_user_from_token),
):
    """
    List individual backup change events for the timeline view.
    Each row is a single version of a backed-up object.
    """
    query: dict = {}

    if object_type:
        query["object_type"] = object_type
    if event_type:
        query["event_type"] = event_type
    if site_id:
        query["site_id"] = site_id
    if scope == "org":
        query["site_id"] = None
    elif scope == "site":
        query["site_id"] = {"$ne": None}

    if start_date:
        query.setdefault("backed_up_at", {})["$gte"] = datetime.fromisoformat(start_date)
    if end_date:
        query.setdefault("backed_up_at", {})["$lte"] = datetime.fromisoformat(end_date)

    total = await BackupObject.find(query).count()
    docs = await (
        BackupObject.find(query)
        .sort([("backed_up_at", -1)])
        .skip(skip)
        .limit(limit)
        .to_list()
    )

    # Resolve site names
    site_ids = {d.site_id for d in docs if d.site_id}
    site_names = await _resolve_site_names(site_ids)

    changes = []
    for d in docs:
        changes.append(BackupChangeEvent(
            id=str(d.id),
            object_id=d.object_id,
            object_type=d.object_type,
            object_name=d.object_name,
            site_id=d.site_id,
            site_name=site_names.get(d.site_id) if d.site_id else None,
            scope="org" if not d.site_id else "site",
            event_type=d.event_type.value if hasattr(d.event_type, 'value') else d.event_type,
            version=d.version,
            changed_fields=d.changed_fields,
            backed_up_at=d.backed_up_at,
            backed_up_by=d.backed_up_by,
        ))

    return BackupChangeListResponse(changes=changes, total=total)


@router.get("/backups/objects/{object_id}/versions", tags=["Backups"])
async def get_object_versions(
    object_id: str,
    _current_user: User = Depends(get_current_user_from_token),
):
    """
    Get all versions of a backed-up object.
    """
    docs = await (
        BackupObject.find(BackupObject.object_id == object_id)
        .sort([("version", -1)])
        .to_list()
    )

    if not docs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No backup records found for this object"
        )

    versions = []
    for d in docs:
        versions.append(BackupObjectVersionResponse(
            id=str(d.id),
            object_id=d.object_id,
            object_type=d.object_type,
            object_name=d.object_name,
            org_id=d.org_id,
            site_id=d.site_id,
            version=d.version,
            event_type=d.event_type.value if hasattr(d.event_type, 'value') else d.event_type,
            changed_fields=d.changed_fields,
            backed_up_at=d.backed_up_at,
            backed_up_by=d.backed_up_by,
            is_deleted=d.is_deleted,
            configuration=d.configuration,
        ))

    return {"versions": versions, "total": len(versions)}


@router.get("/backups/{backup_id}", response_model=BackupJobResponse, tags=["Backups"])
async def get_backup(
    backup_id: str,
    _current_user: User = Depends(get_current_user_from_token)
):
    """
    Get a specific backup by ID.
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
        created_by=str(backup.created_by) if backup.created_by else None
    )


@router.post("/backups/{backup_id}/restore", tags=["Backups"])
async def restore_backup(
    backup_id: str,
    dry_run: bool = Query(False, description="Perform a dry run without making changes"),
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
            detail="Only completed backups can be restored"
        )

    logger.info(
        "restore_requested",
        backup_id=backup_id,
        dry_run=dry_run,
        user_id=str(current_user.id)
    )

    from app.modules.backup.workers import perform_restore
    asyncio.create_task(perform_restore(backup_id, dry_run=dry_run))

    return {
        "message": "Restore initiated" if not dry_run else "Dry run restore initiated",
        "backup_id": backup_id,
        "dry_run": dry_run
    }