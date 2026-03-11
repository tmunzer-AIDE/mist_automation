"""
Backup and restore API endpoints.
"""

import asyncio
import re
import structlog
from datetime import datetime, timedelta, timezone
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.dependencies import get_current_user_from_token
from app.modules.backup.models import BackupJob, BackupLogEntry, BackupStatus, BackupType
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
    BackupLogEntryResponse,
    BackupLogListResponse,
    DailyObjectStats,
    DailyJobStats,
    BackupObjectStatsResponse,
    BackupJobStatsResponse,
    ParentReference,
    ChildReference,
    ObjectDependencyResponse,
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
        created_by=str(backup.created_by) if backup.created_by else None,
        webhook_event=backup.webhook_event,
    )


def _fill_missing_days(data: dict[str, dict], days: int = 30) -> list[str]:
    """Return sorted list of date strings for the last N days, filling gaps."""
    today = datetime.now(timezone.utc).date()
    all_dates = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    for d in all_dates:
        data.setdefault(d, {})
    return all_dates


@router.get("/backups/stats/objects", response_model=BackupObjectStatsResponse, tags=["Backups"])
async def get_object_stats(
    _current_user: User = Depends(get_current_user_from_token),
):
    """Daily count of distinct objects backed up over the last 30 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    pipeline: list[dict] = [
        {"$match": {"backed_up_at": {"$gte": cutoff}}},
        {
            "$group": {
                "_id": {
                    "date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$backed_up_at"}},
                    "object_id": "$object_id",
                },
            }
        },
        {
            "$group": {
                "_id": "$_id.date",
                "object_count": {"$sum": 1},
            }
        },
    ]

    results = await BackupObject.aggregate(pipeline).to_list()
    by_date: dict[str, dict] = {r["_id"]: {"object_count": r["object_count"]} for r in results}
    all_dates = _fill_missing_days(by_date)

    return BackupObjectStatsResponse(
        days=[
            DailyObjectStats(date=d, object_count=by_date[d].get("object_count", 0))
            for d in all_dates
        ]
    )


@router.get("/backups/stats/jobs", response_model=BackupJobStatsResponse, tags=["Backups"])
async def get_job_stats(
    _current_user: User = Depends(get_current_user_from_token),
):
    """Daily job statistics over the last 30 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    pipeline: list[dict] = [
        {"$match": {"created_at": {"$gte": cutoff}}},
        {
            "$addFields": {
                "duration_seconds": {
                    "$cond": {
                        "if": {"$and": [{"$ifNull": ["$completed_at", False]}, {"$ifNull": ["$started_at", False]}]},
                        "then": {"$divide": [{"$subtract": ["$completed_at", "$started_at"]}, 1000]},
                        "else": None,
                    }
                },
                "webhook_event_count": {
                    "$cond": {
                        "if": {"$isArray": "$webhook_event"},
                        "then": {"$size": "$webhook_event"},
                        "else": 0,
                    }
                },
            }
        },
        {
            "$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                "total": {"$sum": 1},
                "completed": {"$sum": {"$cond": [{"$eq": ["$status", "completed"]}, 1, 0]}},
                "failed": {"$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}},
                "webhook_events": {"$sum": "$webhook_event_count"},
                "avg_duration_seconds": {"$avg": "$duration_seconds"},
                "min_duration_seconds": {"$min": "$duration_seconds"},
                "max_duration_seconds": {"$max": "$duration_seconds"},
            }
        },
    ]

    results = await BackupJob.aggregate(pipeline).to_list()
    by_date: dict[str, dict] = {r["_id"]: r for r in results}
    all_dates = _fill_missing_days(by_date)

    return BackupJobStatsResponse(
        days=[
            DailyJobStats(
                date=d,
                total=by_date[d].get("total", 0),
                completed=by_date[d].get("completed", 0),
                failed=by_date[d].get("failed", 0),
                webhook_events=by_date[d].get("webhook_events", 0),
                avg_duration_seconds=by_date[d].get("avg_duration_seconds"),
                min_duration_seconds=by_date[d].get("min_duration_seconds"),
                max_duration_seconds=by_date[d].get("max_duration_seconds"),
            )
            for d in all_dates
        ]
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


OBJECT_SORT_FIELDS = {
    "object_name", "object_type", "version_count",
    "last_backed_up_at", "first_backed_up_at", "latest_version",
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
    sort: str | None = Query(None, description="Sort field"),
    order: str | None = Query(None, description="Sort direction: asc or desc"),
    _current_user: User = Depends(get_current_user_from_token),
):
    """
    List backed-up objects with latest version summary.
    Groups by object_id and returns one row per unique object.
    """
    # Scope to configured org
    config = await SystemConfig.get_config()
    configured_org_id = config.mist_org_id

    # Use MongoDB aggregation to get latest version per object_id
    pipeline: list[dict] = []

    # Match stage — apply filters
    match: dict = {}
    if configured_org_id:
        match["org_id"] = configured_org_id
    if object_type:
        match["object_type"] = object_type
    if site_id:
        match["site_id"] = site_id
    if scope == "org":
        match["site_id"] = None
    elif scope == "site":
        match["site_id"] = {"$ne": None}
    if search:
        escaped_search = re.escape(search)
        match["$or"] = [
            {"object_name": {"$regex": escaped_search, "$options": "i"}},
            {"object_type": {"$regex": escaped_search, "$options": "i"}},
            {"object_id": {"$regex": escaped_search, "$options": "i"}},
            {"restored_from_object_id": {"$regex": escaped_search, "$options": "i"}},
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
            "last_modified_at": {"$max": "$last_modified_at"},
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
    sort_field = sort if sort in OBJECT_SORT_FIELDS else "last_backed_up_at"
    sort_dir = 1 if order == "asc" else -1
    pipeline.append({"$sort": {sort_field: sort_dir}})
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
            last_modified_at=r.get("last_modified_at"),
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
    # Scope to configured org
    config = await SystemConfig.get_config()
    configured_org_id = config.mist_org_id

    query: dict = {}
    if configured_org_id:
        query["org_id"] = configured_org_id

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


@router.get("/backups/objects/{object_id}/dependencies", response_model=ObjectDependencyResponse, tags=["Backups"])
async def get_object_dependencies(
    object_id: str,
    _current_user: User = Depends(get_current_user_from_token),
):
    """
    Get parent and child dependencies for a backed-up object.

    Parents: objects this object references (from its ``references`` field).
    Children: objects that reference this object.
    Implicit site parent is included when the object has a ``site_id``.
    """
    # Find latest version — prefer non-deleted, fall back to any
    obj = await BackupObject.find(
        BackupObject.object_id == object_id,
        BackupObject.is_deleted == False,
    ).sort([("version", -1)]).first_or_none()

    if not obj:
        obj = await BackupObject.find(
            BackupObject.object_id == object_id,
        ).sort([("version", -1)]).first_or_none()

    if not obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No backup found for this object",
        )

    # --- Parents ---
    parents: list[ParentReference] = []

    # Explicit references stored on the document
    for ref in obj.references:
        # Try active first, then fall back to any version
        target = await BackupObject.find(
            BackupObject.object_id == ref.target_id,
            BackupObject.is_deleted == False,
        ).sort([("version", -1)]).first_or_none()

        target_deleted = False
        if not target:
            target = await BackupObject.find(
                BackupObject.object_id == ref.target_id,
            ).sort([("version", -1)]).first_or_none()
            if target:
                target_deleted = True

        parents.append(ParentReference(
            target_type=ref.target_type,
            target_id=ref.target_id,
            target_name=target.object_name if target else None,
            field_path=ref.field_path,
            exists_in_backup=target is not None,
            is_deleted=target_deleted,
        ))

    # Implicit site parent
    if obj.site_id:
        site = await BackupObject.find(
            BackupObject.object_id == obj.site_id,
            BackupObject.object_type == "sites",
            BackupObject.is_deleted == False,
        ).sort([("version", -1)]).first_or_none()

        site_deleted = False
        if not site:
            site = await BackupObject.find(
                BackupObject.object_id == obj.site_id,
                BackupObject.object_type == "sites",
            ).sort([("version", -1)]).first_or_none()
            if site:
                site_deleted = True

        parents.append(ParentReference(
            target_type="sites",
            target_id=obj.site_id,
            target_name=site.object_name if site else None,
            field_path="site_id",
            exists_in_backup=site is not None,
            is_deleted=site_deleted,
        ))

    # --- Children ---
    # Find objects whose references.target_id matches this object_id (including deleted)
    child_docs = await BackupObject.find(
        {"references.target_id": object_id},
    ).sort([("version", -1)]).to_list()

    # Deduplicate by object_id (keep latest version)
    seen_children: set[str] = set()
    children: list[ChildReference] = []
    for doc in child_docs:
        if doc.object_id in seen_children:
            continue
        seen_children.add(doc.object_id)
        # Find matching field_path(s) from the child's references
        for ref in doc.references:
            if ref.target_id == object_id:
                children.append(ChildReference(
                    source_type=doc.object_type,
                    source_id=doc.object_id,
                    source_name=doc.object_name,
                    field_path=ref.field_path,
                    is_deleted=doc.is_deleted,
                ))

    return ObjectDependencyResponse(
        object_id=obj.object_id,
        object_type=obj.object_type,
        object_name=obj.object_name,
        parents=parents,
        children=children,
    )


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


@router.post("/backups/objects/versions/{version_id}/restore", tags=["Backups"])
async def restore_object_version(
    version_id: str,
    dry_run: bool = Query(False, description="Preview restore without applying"),
    cascade: bool = Query(False, description="Cascade restore parents and children"),
    current_user: User = Depends(get_current_user_from_token),
):
    """Restore a backed-up object to a specific version in Mist.

    When ``cascade=True``, deleted parents are restored first (with new UUIDs),
    then the target object, then deleted children — all with ID remapping.
    """
    try:
        doc_id = PydanticObjectId(version_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid version ID format",
        ) from exc

    backup = await BackupObject.get(doc_id)
    if not backup:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup version not found",
        )

    logger.info(
        "restore_version_requested",
        version_id=version_id,
        object_id=backup.object_id,
        version=backup.version,
        dry_run=dry_run,
        cascade=cascade,
        user_id=str(current_user.id),
    )

    config = await SystemConfig.get_config()
    if not config or not config.mist_api_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mist API credentials not configured",
        )

    api_token = decrypt_sensitive_data(config.mist_api_token)
    from app.services.mist_service import MistService
    from app.modules.backup.services.restore_service import RestoreService

    mist_service = MistService(
        api_token=api_token,
        org_id=config.mist_org_id or "",
        cloud_region=config.mist_cloud_region or "global_01",
    )

    restore_service = RestoreService(mist_service=mist_service)

    try:
        if cascade:
            result = await restore_service.cascade_restore(
                version_id=doc_id,
                include_parents=True,
                include_children=True,
                dry_run=dry_run,
                restored_by=str(current_user.id),
            )
        elif backup.is_deleted:
            result = await restore_service.restore_deleted_object(
                object_id=backup.object_id,
                version=backup.version,
                dry_run=dry_run,
                restored_by=str(current_user.id),
            )
        else:
            result = await restore_service.restore_object(
                backup_id=doc_id,
                dry_run=dry_run,
                restored_by=str(current_user.id),
            )
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.get("/backups/{backup_id}/logs", response_model=BackupLogListResponse, tags=["Backups"])
async def get_backup_logs(
    backup_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    level: str | None = Query(None, description="Filter by log level: info, warning, error"),
    _current_user: User = Depends(get_current_user_from_token),
):
    """Get execution logs for a specific backup job."""
    try:
        job_oid = PydanticObjectId(backup_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid backup ID format",
        ) from exc

    query: dict = {"backup_job_id": job_oid}
    if level:
        query["level"] = level

    total = await BackupLogEntry.find(query).count()
    entries = await (
        BackupLogEntry.find(query)
        .sort([("timestamp", 1)])
        .skip(skip)
        .limit(limit)
        .to_list()
    )

    return BackupLogListResponse(
        logs=[
            BackupLogEntryResponse(
                id=str(e.id),
                backup_job_id=str(e.backup_job_id),
                timestamp=e.timestamp,
                level=e.level,
                phase=e.phase,
                message=e.message,
                object_type=e.object_type,
                object_id=e.object_id,
                object_name=e.object_name,
                site_id=e.site_id,
                details=e.details,
            )
            for e in entries
        ],
        total=total,
    )


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
        created_by=str(backup.created_by) if backup.created_by else None,
        webhook_event=backup.webhook_event,
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