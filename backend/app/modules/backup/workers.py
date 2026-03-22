"""
Backup worker - handles scheduled and on-demand backup operations using Celery.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from beanie import PydanticObjectId

from app.config import settings
from app.core.celery_app import celery_app
from app.core.exceptions import MistAPIError
from app.modules.backup.models import BackupEventType, BackupJob, BackupLogEntry, BackupObject, BackupStatus, BackupType
from app.modules.backup.services.backup_logger import BackupLogger
from app.modules.backup.services.backup_service import BackupService
from app.modules.backup.services.git_service import GitService
from app.services.mist_service import MistService

logger = structlog.get_logger(__name__)


@celery_app.task(name="perform_backup", bind=True, max_retries=2)
def perform_backup_task(
    self, backup_id: str, backup_type: str = "scheduled", org_id: str | None = None, site_id: str | None = None
):
    """
    Celery task to perform a configuration backup.

    Args:
        backup_id: BackupJob ID
        backup_type: Type of backup (scheduled, manual, pre_change)
        org_id: Organization ID
        site_id: Site ID (optional, for site-specific backups)

    Returns:
        dict: Backup result
    """
    import asyncio

    return asyncio.run(perform_backup(backup_id, backup_type, org_id, site_id))


async def perform_backup(
    backup_id: str,
    backup_type: str = "scheduled",
    org_id: str | None = None,
    site_id: str | None = None,
    object_type: str | None = None,
    object_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Perform a configuration backup operation.

    Args:
        backup_id: BackupJob ID
        backup_type: Type of backup
        org_id: Organization ID
        site_id: Site ID (optional)

    Returns:
        dict: Backup result with statistics
    """
    start_time = datetime.now(timezone.utc)
    backup_job = None

    try:
        # Get backup job record
        backup_job = await BackupJob.get(PydanticObjectId(backup_id))
        if not backup_job:
            raise ValueError(f"Backup job {backup_id} not found")

        # Update status
        backup_job.status = BackupStatus.IN_PROGRESS
        backup_job.started_at = start_time
        await backup_job.save()

        backup_logger = BackupLogger(backup_id)
        await backup_logger.info("init", f"Backup job started (type={backup_type})")

        logger.info("backup_started", backup_id=backup_id, backup_type=backup_type, org_id=org_id, site_id=site_id)

        # Initialize services
        from app.services.mist_service_factory import create_mist_service

        mist_service = await create_mist_service(org_id=org_id)
        backup_service = BackupService(mist_service=mist_service, backup_logger=backup_logger)

        # Perform backup based on type
        if backup_type == "manual" and object_type:
            result = await backup_service.perform_manual_backup(
                object_type=object_type,
                object_ids=object_ids,
                site_id=site_id,
            )
        else:
            result = await backup_service.perform_full_backup()

        # Update backup job with results
        backup_job.status = BackupStatus.COMPLETED
        backup_job.completed_at = datetime.now(timezone.utc)
        backup_job.object_count = result.get("total", result.get("total_objects", 0))
        backup_job.size_bytes = result.get("total_size_bytes", 0)

        # Calculate duration
        if backup_job.started_at and backup_job.completed_at:
            started = backup_job.started_at
            completed = backup_job.completed_at
            # MongoDB may strip timezone info
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if completed.tzinfo is None:
                completed = completed.replace(tzinfo=timezone.utc)
            delta = completed - started
            duration_ms = int(delta.total_seconds() * 1000)
        else:
            duration_ms = 0

        await backup_job.save()

        # Git integration (if enabled)
        if settings.backup_git_enabled and settings.backup_git_repo_url:
            try:
                git_service = GitService(
                    repo_url=settings.backup_git_repo_url,
                    branch=settings.backup_git_branch,
                    author_name=settings.backup_git_author_name,
                    author_email=settings.backup_git_author_email,
                )

                # Fetch objects backed up during this job's time window
                backup_objects = await BackupObject.find(
                    BackupObject.backed_up_at >= backup_job.started_at,
                    BackupObject.backed_up_at <= backup_job.completed_at,
                ).to_list()

                if backup_objects:
                    commit_sha = await git_service.commit_multiple_backups(
                        backups=backup_objects,
                        message=f"Automated backup - {backup_type} ({len(backup_objects)} objects)",
                    )
                else:
                    commit_sha = None

                if commit_sha:
                    logger.info("backup_committed_to_git", backup_id=backup_id, commit_sha=commit_sha)

            except Exception as e:
                logger.warning("git_commit_failed", backup_id=backup_id, error=str(e))
                # Don't fail the backup if Git fails

        await backup_logger.info("complete", f"Backup completed: {backup_job.object_count} objects in {duration_ms}ms")

        logger.info(
            "backup_completed",
            backup_id=backup_id,
            duration_ms=duration_ms,
            object_count=backup_job.object_count,
            size_bytes=backup_job.size_bytes,
        )

        return {
            "backup_id": backup_id,
            "status": "completed",
            "duration_ms": duration_ms,
            "object_count": backup_job.object_count,
            "size_bytes": backup_job.size_bytes,
            "details": result,
        }

    except Exception as e:
        logger.error("backup_failed", backup_id=backup_id, error=str(e))

        # Mark backup as failed
        if backup_job:
            backup_job.status = BackupStatus.FAILED
            backup_job.completed_at = datetime.now(timezone.utc)
            backup_job.error = str(e)[:200]
            await backup_job.save()

            try:
                backup_logger = BackupLogger(backup_id)
                await backup_logger.error("complete", f"Backup failed: {str(e)}", details={"error": str(e)})
            except Exception:
                pass

        raise


@celery_app.task(name="cleanup_old_backups")
def cleanup_old_backups_task():
    """
    Celery task to clean up old backups based on retention policy.

    Returns:
        dict: Cleanup result
    """
    import asyncio

    return asyncio.run(cleanup_old_backups())


async def cleanup_old_backups() -> dict[str, Any]:
    """
    Clean up old backups based on retention policy.

    Returns:
        dict: Cleanup statistics
    """
    try:
        logger.info("backup_cleanup_started")

        # Calculate cutoff date
        from datetime import timedelta

        cutoff_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff_date = cutoff_date - timedelta(days=settings.backup_retention_days)

        # Find old backups
        old_backups = await BackupJob.find(
            BackupJob.created_at < cutoff_date, BackupJob.status.in_([BackupStatus.COMPLETED, BackupStatus.FAILED])
        ).to_list()

        deleted_count = 0
        for backup in old_backups:
            # Delete associated log entries
            await BackupLogEntry.find(BackupLogEntry.backup_job_id == backup.id).delete()
            await backup.delete()
            deleted_count += 1

        # Delete old BackupObject versions beyond the retention window,
        # but preserve the latest version of each object_id so we don't lose
        # the current backup of objects that haven't changed recently.
        latest_ids_pipeline = [
            {"$sort": {"version": -1}},
            {"$group": {"_id": "$object_id", "latest_doc_id": {"$first": "$_id"}}},
        ]
        latest_results = await BackupObject.aggregate(latest_ids_pipeline).to_list()
        latest_doc_ids = {r["latest_doc_id"] for r in latest_results}

        old_objects = await BackupObject.find(BackupObject.backed_up_at < cutoff_date).to_list()
        obj_deleted = 0
        for obj in old_objects:
            if obj.id not in latest_doc_ids:
                await obj.delete()
                obj_deleted += 1

        logger.info(
            "backup_cleanup_completed",
            deleted_jobs=deleted_count,
            deleted_objects=obj_deleted,
            cutoff_date=cutoff_date.isoformat(),
        )

        return {
            "status": "completed",
            "deleted_count": deleted_count,
            "cutoff_date": cutoff_date.isoformat(),
            "retention_days": settings.backup_retention_days,
        }

    except Exception as e:
        logger.error("backup_cleanup_failed", error=str(e))
        raise


def queue_backup(
    backup_id: str, backup_type: str = "scheduled", org_id: str | None = None, site_id: str | None = None
) -> str:
    """
    Queue a backup operation for asynchronous processing.

    Args:
        backup_id: BackupJob ID
        backup_type: Type of backup
        org_id: Organization ID
        site_id: Site ID (optional)

    Returns:
        str: Celery task ID
    """
    task = perform_backup_task.delay(backup_id, backup_type, org_id, site_id)

    logger.info("backup_queued", backup_id=backup_id, backup_type=backup_type, task_id=task.id)

    return task.id


def schedule_periodic_backups():
    """
    Set up periodic backup tasks using Celery Beat.

    This should be configured in Celery Beat schedule.
    """
    # Configure in celerybeat-schedule.py or via celery_app.conf.beat_schedule
    celery_app.conf.beat_schedule = {
        "daily-full-backup": {
            "task": "perform_backup",
            "schedule": settings.backup_full_schedule_cron,
            "args": (None, "scheduled", settings.mist_org_id, None),
        },
        "weekly-cleanup": {
            "task": "cleanup_old_backups",
            "schedule": "0 3 * * 0",  # Weekly on Sunday at 3 AM
        },
    }

    logger.info("periodic_backups_scheduled", full_backup_schedule=settings.backup_full_schedule_cron)


def _is_delete_event(event: dict) -> bool:
    """Check whether a Mist audit event represents a deletion."""
    message = (event.get("message") or "").strip()
    return message.lower().startswith("delete ")


async def _resolve_and_delete_by_name(
    backup_service: "BackupService",
    event: dict,
    obj_type: str,
    site_id: str | None,
    deleted_by: str,
) -> Optional["BackupObject"]:
    """Resolve an object by name from the audit message and mark it deleted.

    Mist delete webhooks often send ``<type>_id: "None"`` instead of the
    real UUID.  The message however contains the object name, e.g.:
    ``Delete PSK "fdsqfdqsf"``.

    We extract the quoted name, look up the latest active BackupObject
    matching (object_type, object_name, site_id), and mark it deleted.
    """
    import re as _re

    message = event.get("message", "")
    # Try to extract the name between quotes: Delete PSK "some name"
    match = _re.search(r'"([^"]+)"', message)
    if not match:
        logger.warning("delete_event_no_name_in_message", message=message)
        return None

    object_name = match.group(1)

    # Find the latest active version matching name + type
    query: dict = {
        "object_type": obj_type,
        "object_name": object_name,
        "is_deleted": False,
    }
    if site_id:
        query["site_id"] = site_id

    existing = await BackupObject.find(query).sort([("version", -1)]).first_or_none()
    if not existing:
        logger.warning(
            "delete_event_object_not_found_by_name",
            object_type=obj_type,
            object_name=object_name,
            site_id=site_id,
        )
        return None

    return await backup_service.mark_object_deleted(
        object_id=existing.object_id,
        deleted_by=deleted_by,
    )


_REFERENCE_FIELD_INDEX: dict[str, set[str]] | None = None


def _get_reference_field_index() -> dict[str, set[str]]:
    """Build a reverse index: field_name -> set of object types that own that reference.

    Only includes simple (non-dotted) field_paths since event fields are flat.
    Cached in a module-level variable since REFERENCE_MAP is static.
    """
    global _REFERENCE_FIELD_INDEX
    if _REFERENCE_FIELD_INDEX is None:
        from app.modules.backup.reference_map import REFERENCE_MAP

        _REFERENCE_FIELD_INDEX = {}
        for owner_type, descriptors in REFERENCE_MAP.items():
            for desc in descriptors:
                if "." not in desc.field_path:
                    _REFERENCE_FIELD_INDEX.setdefault(desc.field_path, set()).add(owner_type)
    return _REFERENCE_FIELD_INDEX


def _extract_type_from_message(
    message: str,
    org_objects: dict,
    site_objects: dict,
) -> str | None:
    """Extract object type from audit message when no *_id fields matched.

    Mist audit messages follow ``<Action> <ObjectType> "name"`` or
    ``<Action> <ObjectType> ...``.  Returns the registry key if the type
    word(s) match a known object type, else None.
    """
    import re as _re

    match = _re.match(
        r"^(?:Add|Update|Delete|Modify|Create|Remove)\s+(.+?)(?:\s+\".*\"|$)",
        message,
        _re.IGNORECASE,
    )
    if not match:
        return None

    raw_type = match.group(1).strip().lower()
    # Build candidate registry keys:
    # "site" → ["site", "sites"], "site group" → ["sitegroup", "sitegroups"]
    no_space = raw_type.replace(" ", "")
    candidates = [raw_type, raw_type + "s", no_space, no_space + "s"]
    if raw_type.endswith("y"):
        candidates.append(raw_type[:-1] + "ies")
    if no_space.endswith("y"):
        candidates.append(no_space[:-1] + "ies")

    for candidate in candidates:
        if candidate in org_objects or candidate in site_objects:
            return candidate

    # Fallback: drop leading scope qualifiers ("Site Settings" → "Settings")
    words = raw_type.split()
    if len(words) > 1:
        for i in range(1, len(words)):
            suffix = " ".join(words[i:])
            no_space_suffix = suffix.replace(" ", "")
            sub_candidates = [suffix, suffix + "s", no_space_suffix, no_space_suffix + "s"]
            if suffix.endswith("y"):
                sub_candidates.append(suffix[:-1] + "ies")
            if no_space_suffix.endswith("y"):
                sub_candidates.append(no_space_suffix[:-1] + "ies")
            for candidate in sub_candidates:
                if candidate in org_objects or candidate in site_objects:
                    return candidate

    return None


def _extract_object_info(event: dict) -> tuple[str | None, str | None, str | None]:
    """Extract (object_type, object_id, site_id) from a flat Mist audit event.

    Mist audit events contain ``<type>_id`` fields that identify the changed
    object.  For example ``wlan_id`` maps to object type ``wlans`` in the
    backup object registry.

    When multiple ``*_id`` fields are present (e.g. ``wlan_id`` and
    ``template_id`` for a WLAN belonging to a template), the function uses
    :data:`REFERENCE_MAP` to disambiguate: fields that are cross-object
    references of another candidate are filtered out.

    Returns:
        Tuple of (registry_key, object_id, site_id).  Any element may be None
        if the event does not contain enough information.
    """
    from app.modules.backup.object_registry import ORG_OBJECTS, SITE_OBJECTS

    site_id = event.get("site_id")

    # Fields that are metadata, not object references
    _SKIP_FIELDS = {"id", "org_id", "site_id", "admin_id"}

    # Phase 1: Collect all candidate matches
    # Each candidate is (registry_key, field_name, value_or_None)
    matches: list[tuple[str, str, str | None]] = []

    for field_name, value in event.items():
        if not field_name.endswith("_id") or field_name in _SKIP_FIELDS or not value:
            continue

        # Mist sends "None" (string) for some delete events — treat as missing
        resolved_value: str | None = None if value == "None" else value

        singular = field_name[: -len("_id")]
        candidate_keys = [singular, singular + "s"]
        if singular.endswith("y"):
            candidate_keys.append(singular[:-1] + "ies")

        registry = SITE_OBJECTS if site_id else ORG_OBJECTS
        fallback = ORG_OBJECTS if site_id else SITE_OBJECTS

        for candidate in candidate_keys:
            if candidate in registry or candidate in fallback:
                matches.append((candidate, field_name, resolved_value))
                break

    if not matches:
        # If we have an explicit "object" field (envelope format), use that
        if event.get("object"):
            return event["object"], event.get("id"), site_id

        # Fallback: parse object type from the audit message.
        # Mist audit messages follow the pattern: "<Action> <Type> ..."
        # e.g. 'Add Site "MyCorp Office"', 'Delete PSK "guest"'
        resolved = _extract_type_from_message(event.get("message", ""), ORG_OBJECTS, SITE_OBJECTS)
        if resolved:
            return resolved, None, site_id

        return None, None, site_id

    if len(matches) == 1:
        registry_key, _, obj_value = matches[0]
        return registry_key, obj_value, site_id

    # Phase 2: Multiple candidates — use REFERENCE_MAP to disambiguate.
    # Filter out candidates whose field_name is a reference field owned by
    # another candidate's object type.
    ref_index = _get_reference_field_index()
    match_keys = {m[0] for m in matches}

    filtered = [m for m in matches if not (ref_index.get(m[1], set()) & match_keys)]

    # Safety: if filtering removed everything, fall back to original list
    if not filtered:
        filtered = matches

    registry_key, _, obj_value = filtered[0]
    return registry_key, obj_value, site_id


async def _check_object_exists_in_mist(
    mist_service: MistService,
    object_type: str,
    object_id: str,
    org_id: str,
    site_id: str | None,
) -> bool:
    """Check if an object still exists in Mist.  Returns True if 200, False if 404."""
    if site_id:
        endpoint = f"/api/v1/sites/{site_id}/{object_type}/{object_id}"
    else:
        endpoint = f"/api/v1/orgs/{org_id}/{object_type}/{object_id}"
    try:
        await mist_service.api_get(endpoint)
        return True
    except MistAPIError as e:
        if e.details.get("api_status_code") == 404:
            return False
        raise


async def _cascade_mark_children_deleted(
    backup_service: "BackupService",
    mist_service: MistService,
    parent_object: BackupObject,
    deleted_by: str,
    backup_logger: "BackupLogger",
) -> int:
    """Mark children as deleted when a parent is deleted.

    Returns the count of children marked deleted.
    """
    from app.modules.backup.reference_map import (
        API_VERIFIED_CASCADE_TYPES,
        get_reverse_reference_map,
    )

    count = 0
    parent_type = parent_object.object_type

    if parent_type in API_VERIFIED_CASCADE_TYPES:
        # e.g. templates → verify each child via API before marking
        reverse_refs = get_reverse_reference_map().get(parent_type, [])
        if not reverse_refs:
            return 0

        children = (
            await BackupObject.find({"references.target_id": parent_object.object_id, "is_deleted": False})
            .sort([("version", -1)])
            .to_list()
        )

        # Deduplicate by object_id (keep latest version)
        seen: set[str] = set()
        unique_children: list[BackupObject] = []
        for child in children:
            if child.object_id not in seen:
                seen.add(child.object_id)
                unique_children.append(child)

        sem = asyncio.Semaphore(5)

        async def _check_and_mark(child: BackupObject) -> int:
            async with sem:
                try:
                    exists = await _check_object_exists_in_mist(
                        mist_service,
                        child.object_type,
                        child.object_id,
                        child.org_id,
                        child.site_id,
                    )
                    if not exists:
                        result = await backup_service.mark_object_deleted(
                            object_id=child.object_id,
                            deleted_by=deleted_by,
                        )
                        if result:
                            logger.info(
                                "cascade_child_marked_deleted",
                                parent_type=parent_type,
                                parent_id=parent_object.object_id,
                                child_type=child.object_type,
                                child_id=child.object_id,
                            )
                            await backup_logger.info(
                                "org_objects" if not child.site_id else "site_objects",
                                f"Cascade delete: {child.object_type} '{child.object_name}' "
                                f"(parent {parent_type} deleted)",
                                object_type=child.object_type,
                                object_id=child.object_id,
                                object_name=child.object_name,
                                site_id=child.site_id,
                            )
                            return 1
                except Exception as exc:
                    logger.warning(
                        "cascade_check_failed",
                        child_id=child.object_id,
                        error=str(exc),
                    )
                return 0

        results = await asyncio.gather(*[_check_and_mark(c) for c in unique_children])
        count = sum(results)

    elif parent_type == "sites":
        # All objects scoped to this site are deleted
        children = (
            await BackupObject.find({"site_id": parent_object.object_id, "is_deleted": False})
            .sort([("version", -1)])
            .to_list()
        )

        seen: set[str] = set()
        for child in children:
            if child.object_id in seen:
                continue
            seen.add(child.object_id)
            result = await backup_service.mark_object_deleted(
                object_id=child.object_id,
                deleted_by=deleted_by,
            )
            if result:
                count += 1
                await backup_logger.info(
                    "site_objects",
                    f"Cascade delete: {child.object_type} '{child.object_name}' " f"(site deleted)",
                    object_type=child.object_type,
                    object_id=child.object_id,
                    object_name=child.object_name,
                    site_id=child.site_id,
                )

    elif parent_type == "data":
        # Org deleted — mark everything in org
        children = (
            await BackupObject.find({"org_id": parent_object.org_id, "is_deleted": False})
            .sort([("version", -1)])
            .to_list()
        )

        seen: set[str] = set()
        for child in children:
            if child.object_id in seen:
                continue
            seen.add(child.object_id)
            result = await backup_service.mark_object_deleted(
                object_id=child.object_id,
                deleted_by=deleted_by,
            )
            if result:
                count += 1

    if count:
        logger.info(
            "cascade_delete_completed",
            parent_type=parent_type,
            parent_id=parent_object.object_id,
            children_deleted=count,
        )

    return count


async def perform_incremental_backup(org_id: str, audit_events: list[dict]) -> None:
    """
    Process Mist audit webhook events and trigger incremental backups
    for the affected objects.

    Handles both flat audit events (with ``wlan_id``, ``network_id``, etc.)
    and envelope-style events (with ``object`` field).

    Args:
        org_id: Mist organization ID
        audit_events: List of audit event dicts from the Mist webhook payload
    """
    backup_job = None
    try:
        from app.modules.backup.object_registry import SITE_OBJECTS
        from app.services.mist_service_factory import create_mist_service

        mist_service = await create_mist_service(org_id=org_id)

        # Create a BackupJob record for this incremental backup
        backup_job = BackupJob(
            backup_type=BackupType.WEBHOOK,
            org_id=org_id,
            status=BackupStatus.IN_PROGRESS,
            started_at=datetime.now(timezone.utc),
            webhook_event=audit_events,
        )
        await backup_job.insert()
        backup_logger = BackupLogger(str(backup_job.id))
        await backup_logger.info("init", f"Incremental backup started ({len(audit_events)} events)")

        backup_service = BackupService(mist_service=mist_service, backup_logger=backup_logger)

        backed_up = 0
        for event in audit_events:
            obj_type, obj_id, site_id = _extract_object_info(event)

            if not obj_type:
                logger.debug(
                    "incremental_backup_skip_unknown_type",
                    message=event.get("message", ""),
                    keys=list(event.keys()),
                )
                continue

            # Determine scope-prefixed object type
            scope = "site" if site_id and obj_type in SITE_OBJECTS else "org"
            prefixed_type = f"{scope}:{obj_type}"

            try:
                # ── Handle delete events ────────────────────────────────
                if _is_delete_event(event):
                    deleted_by = event.get("admin_name", "system")

                    if obj_id:
                        # We have the object ID — mark it deleted directly
                        result = await backup_service.mark_object_deleted(
                            object_id=obj_id,
                            deleted_by=deleted_by,
                        )
                    else:
                        # Mist sent "None" as the ID — resolve by name from
                        # the message, e.g. 'Delete PSK "fdsqfdqsf"'
                        result = await _resolve_and_delete_by_name(
                            backup_service,
                            event,
                            obj_type,
                            site_id,
                            deleted_by,
                        )

                    if result:
                        backed_up += 1
                        logger.info(
                            "incremental_backup_object_deleted",
                            object_type=prefixed_type,
                            object_id=result.object_id,
                            object_name=result.object_name,
                            message=event.get("message", ""),
                        )
                        await backup_logger.info(
                            "org_objects" if not site_id else "site_objects",
                            f"Deleted {prefixed_type} '{result.object_name}' (v{result.version})",
                            object_type=prefixed_type,
                            object_id=result.object_id,
                            object_name=result.object_name,
                            site_id=site_id,
                        )

                        # Cascade-mark children as deleted
                        cascade_count = await _cascade_mark_children_deleted(
                            backup_service,
                            mist_service,
                            result,
                            deleted_by,
                            backup_logger,
                        )
                        backed_up += cascade_count
                    else:
                        logger.warning(
                            "incremental_backup_delete_not_found",
                            object_type=prefixed_type,
                            message=event.get("message", ""),
                        )
                        await backup_logger.warning(
                            "org_objects" if not site_id else "site_objects",
                            f"Could not find object to delete for {prefixed_type}: {event.get('message', '')}",
                            object_type=prefixed_type,
                            site_id=site_id,
                        )
                    continue

                # ── Normal backup ───────────────────────────────────────
                await backup_service.perform_manual_backup(
                    object_type=prefixed_type,
                    object_ids=[obj_id] if obj_id else None,
                    site_id=site_id,
                    event_type_if_new=BackupEventType.CREATED,
                )
                backed_up += 1
                logger.info(
                    "incremental_backup_object_done",
                    object_type=prefixed_type,
                    object_id=obj_id,
                    message=event.get("message", ""),
                )
                await backup_logger.info(
                    "org_objects" if not site_id else "site_objects",
                    f"Incremental backup: {prefixed_type} {obj_id or 'all'}",
                    object_type=prefixed_type,
                    object_id=obj_id,
                    site_id=site_id,
                )
            except Exception as exc:
                logger.warning(
                    "incremental_backup_object_failed",
                    object_type=prefixed_type,
                    object_id=obj_id,
                    error=str(exc),
                )
                await backup_logger.warning(
                    "org_objects" if not site_id else "site_objects",
                    f"Incremental backup failed for {prefixed_type}: {str(exc)}",
                    object_type=prefixed_type,
                    object_id=obj_id,
                    site_id=site_id,
                    details={"error": str(exc)},
                )

        logger.info(
            "incremental_backup_completed",
            org_id=org_id,
            events=len(audit_events),
            backed_up=backed_up,
        )

        if backed_up == 0:
            # No objects were actually backed up — discard the job and its logs
            # to avoid cluttering the database with empty webhook jobs.
            await BackupLogEntry.find(BackupLogEntry.backup_job_id == backup_job.id).delete()
            await backup_job.delete()
            logger.info("incremental_backup_discarded", org_id=org_id, reason="no objects backed up")
            return

        await backup_logger.info(
            "complete", f"Incremental backup completed: {backed_up}/{len(audit_events)} events processed"
        )
        backup_job.status = BackupStatus.COMPLETED
        backup_job.completed_at = datetime.now(timezone.utc)
        backup_job.object_count = backed_up
        await backup_job.save()

    except Exception as exc:
        logger.error("incremental_backup_failed", org_id=org_id, error=str(exc))
        # Try to mark the job as failed if it was created
        try:
            if backup_job:
                backup_job.status = BackupStatus.FAILED
                backup_job.completed_at = datetime.now(timezone.utc)
                backup_job.error = str(exc)[:200]
                await backup_job.save()
                backup_logger = BackupLogger(str(backup_job.id))
                await backup_logger.error(
                    "complete", f"Incremental backup failed: {str(exc)}", details={"error": str(exc)}
                )
        except Exception:
            pass
