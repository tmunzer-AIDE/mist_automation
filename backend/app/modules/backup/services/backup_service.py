"""
Backup service for fetching and storing Mist configuration backups.
"""

from datetime import datetime, timezone
from typing import Any, Optional
import hashlib
import json
import mistapi
import structlog
from beanie import PydanticObjectId

from app.modules.backup.models import (
    BackupObject,
    BackupEventType,
    BackupStatus,
    ObjectReference,
)
from app.modules.backup.reference_map import extract_references
from app.modules.backup.object_registry import (
    ORG_OBJECTS,
    SITE_OBJECTS,
    ObjectDef,
    get_object_name,
)
from app.services.mist_service import MistService
from app.core.exceptions import BackupError, ConfigurationError
from app.config import settings

logger = structlog.get_logger(__name__)


async def fetch_objects(
    session,
    obj_def: ObjectDef,
    org_id: str | None = None,
    site_id: str | None = None,
) -> list[dict]:
    """Call the mistapi function and return a list of objects.

    This is a shared utility used by both the backup service and admin API.
    """
    kwargs: dict[str, Any] = {}
    if obj_def.request_type:
        kwargs["type"] = obj_def.request_type

    if site_id:
        result = await mistapi.arun(
            obj_def.mistapi_function, session, site_id, **kwargs
        )
    else:
        result = await mistapi.arun(
            obj_def.mistapi_function, session, org_id, **kwargs
        )

    if result.status_code != 200:
        raise BackupError(f"API returned {result.status_code}")

    data = result.data
    if not obj_def.is_list:
        return [data] if isinstance(data, dict) else []
    if isinstance(data, dict) and "results" in data:
        return data["results"]  # search endpoints
    return data if isinstance(data, list) else []


class BackupService:
    """Service for managing configuration backups."""

    def __init__(self, mist_service: Optional[MistService] = None, backup_logger=None):
        self.mist_service = mist_service or MistService()
        self.org_id = self.mist_service.org_id
        self.backup_logger = backup_logger

    async def perform_full_backup(self) -> dict[str, Any]:
        """Perform a full backup of all Mist configurations."""
        logger.info("full_backup_started", org_id=self.org_id)
        start_time = datetime.now(timezone.utc)

        stats = {
            "total": 0,
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "errors": 0,
            "by_type": {},
        }

        if self.backup_logger:
            await self.backup_logger.info("init", "Full backup started", details={"org_id": self.org_id})

        try:
            await self._backup_org_objects(stats)
            await self._backup_site_objects(stats)

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(
                "full_backup_completed",
                org_id=self.org_id,
                duration_seconds=duration,
                **stats,
            )

            if self.backup_logger:
                await self.backup_logger.info("complete", f"Full backup completed in {duration:.1f}s", details=stats)

            return {
                **stats,
                "duration_seconds": duration,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error("full_backup_failed", org_id=self.org_id, error=str(e))
            if self.backup_logger:
                await self.backup_logger.error("complete", f"Full backup failed: {str(e)}", details={"error": str(e)})
            raise BackupError(f"Full backup failed: {str(e)}")

    async def _backup_org_objects(self, stats: dict[str, Any]) -> None:
        """Backup all organization-level objects from the registry."""
        for obj_type_key, obj_def in ORG_OBJECTS.items():
            try:
                objects = await fetch_objects(
                    self.mist_service.session,
                    obj_def,
                    org_id=self.org_id,
                )
                for obj in objects:
                    result = await self._backup_object(
                        object_type=obj_type_key,
                        object_id=obj.get("id", obj_type_key),
                        config=obj,
                        org_id=self.org_id,
                        name_override=get_object_name(obj, obj_def),
                    )
                    self._update_stats(stats, obj_type_key, result)
                logger.debug(f"org_{obj_type_key}_backed_up", count=len(objects))
                if self.backup_logger:
                    type_stats = stats["by_type"].get(obj_type_key, {})
                    await self.backup_logger.info(
                        "org_objects",
                        f"Processed {len(objects)} {obj_type_key}: {type_stats.get('created', 0)} created, {type_stats.get('updated', 0)} updated, {type_stats.get('unchanged', 0)} unchanged",
                        object_type=obj_type_key,
                        details=type_stats,
                    )
            except Exception as e:
                logger.error(f"backup_org_{obj_type_key}_failed", error=str(e))
                if self.backup_logger:
                    await self.backup_logger.error(
                        "org_objects",
                        f"Failed to backup {obj_type_key}: {str(e)}",
                        object_type=obj_type_key,
                        details={"error": str(e)},
                    )
                stats["errors"] += 1

    async def _backup_site_objects(self, stats: dict[str, Any]) -> None:
        """Backup site-level objects for all sites."""
        try:
            sites_def = ORG_OBJECTS["sites"]
            all_sites = await fetch_objects(
                self.mist_service.session, sites_def, org_id=self.org_id
            )

            for site in all_sites:
                site_id = site["id"]

                # Backup each site-level object type
                for obj_type_key, obj_def in SITE_OBJECTS.items():
                    try:
                        objects = await fetch_objects(
                            self.mist_service.session,
                            obj_def,
                            site_id=site_id,
                        )
                        for obj in objects:
                            result = await self._backup_object(
                                object_type=obj_type_key,
                                object_id=obj.get("id", obj_type_key),
                                config=obj,
                                org_id=self.org_id,
                                site_id=site_id,
                                name_override=get_object_name(obj, obj_def),
                            )
                            self._update_stats(stats, obj_type_key, result)
                        if self.backup_logger:
                            type_stats = stats["by_type"].get(obj_type_key, {})
                            await self.backup_logger.info(
                                "site_objects",
                                f"Site {site_id[:8]}: processed {len(objects)} {obj_type_key}: {type_stats.get('created', 0)} created, {type_stats.get('updated', 0)} updated",
                                object_type=obj_type_key,
                                site_id=site_id,
                                details=type_stats,
                            )
                    except Exception as e:
                        logger.error(
                            f"backup_site_{obj_type_key}_failed",
                            site_id=site_id,
                            error=str(e),
                        )
                        if self.backup_logger:
                            await self.backup_logger.error(
                                "site_objects",
                                f"Site {site_id[:8]}: failed to backup {obj_type_key}: {str(e)}",
                                object_type=obj_type_key,
                                site_id=site_id,
                                details={"error": str(e)},
                            )
                        stats["errors"] += 1

            logger.debug("sites_backed_up", count=len(all_sites))

        except Exception as e:
            logger.error("backup_sites_failed", error=str(e))
            raise

    async def _backup_object(
        self,
        object_type: str,
        object_id: str,
        config: dict[str, Any],
        org_id: str,
        site_id: Optional[str] = None,
        name_override: Optional[str] = None,
        event_type_if_new: BackupEventType = BackupEventType.FULL_BACKUP,
    ) -> str:
        """Backup a single object. Returns "created", "updated", or "unchanged"."""
        config_hash = self._calculate_hash(config)
        object_name = name_override or config.get("name") or config.get("ssid") or object_id[:8]

        # Extract cross-object references
        refs = [ObjectReference(**r) for r in extract_references(object_type, config)]

        # Check if object already exists (latest version)
        existing = await BackupObject.find(
            BackupObject.object_id == object_id,
            BackupObject.is_deleted == False,
        ).sort([("version", -1)]).first_or_none()

        now = datetime.now(timezone.utc)

        if existing:
            if existing.configuration_hash == config_hash:
                # No diff — just update backed_up_at on the existing version
                existing.backed_up_at = now
                await existing.save()
                logger.debug(
                    "object_unchanged",
                    object_type=object_type,
                    object_id=object_id,
                    object_name=object_name,
                )
                return "unchanged"

            changed_fields = self._find_changed_fields(existing.configuration, config)
            next_ver = await BackupObject.next_version(object_id)

            new_backup = BackupObject(
                object_type=object_type,
                object_id=object_id,
                object_name=object_name,
                org_id=org_id,
                site_id=site_id,
                configuration=config,
                configuration_hash=config_hash,
                version=next_ver,
                previous_version_id=existing.id,
                event_type=BackupEventType.UPDATED,
                changed_fields=changed_fields,
                backed_up_at=now,
                last_modified_at=now,
                references=refs,
            )
            await new_backup.insert()

            logger.info(
                "object_updated",
                object_type=object_type,
                object_id=object_id,
                object_name=object_name,
                version=new_backup.version,
                changed_fields=changed_fields,
            )
            if self.backup_logger:
                await self.backup_logger.info(
                    "org_objects" if not site_id else "site_objects",
                    f"Updated {object_type} '{object_name}' (v{new_backup.version}, {len(changed_fields)} fields changed)",
                    object_type=object_type,
                    object_id=object_id,
                    object_name=object_name,
                    site_id=site_id,
                    details={"changed_fields": changed_fields, "version": new_backup.version},
                )
            return "updated"

        else:
            # Check if a deleted version exists (object was deleted then re-created)
            latest_any = await BackupObject.find(
                BackupObject.object_id == object_id,
            ).sort([("version", -1)]).first_or_none()

            next_ver_new = (latest_any.version + 1) if latest_any else 1
            prev_id = latest_any.id if latest_any else None

            new_backup = BackupObject(
                object_type=object_type,
                object_id=object_id,
                object_name=object_name,
                org_id=org_id,
                site_id=site_id,
                configuration=config,
                configuration_hash=config_hash,
                version=next_ver_new,
                previous_version_id=prev_id,
                event_type=event_type_if_new,
                changed_fields=[],
                backed_up_at=now,
                last_modified_at=now,
                references=refs,
            )
            await new_backup.insert()

            logger.info(
                "object_created",
                object_type=object_type,
                object_id=object_id,
                object_name=object_name,
            )
            if self.backup_logger:
                await self.backup_logger.info(
                    "org_objects" if not site_id else "site_objects",
                    f"Created {object_type} '{object_name}'",
                    object_type=object_type,
                    object_id=object_id,
                    object_name=object_name,
                    site_id=site_id,
                )
            return "created"

    async def perform_manual_backup(
        self,
        object_type: str,
        object_ids: list[str] | None = None,
        site_id: str | None = None,
        event_type_if_new: BackupEventType = BackupEventType.FULL_BACKUP,
    ) -> dict[str, Any]:
        """Perform a manual backup of selected objects.

        Args:
            object_type: Format "org:key" or "site:key" (e.g. "org:wlans", "site:maps").
            object_ids: List of object IDs to backup (for list types).
            site_id: Site ID (required for site-scoped types).
            event_type_if_new: Event type for first-time objects (FULL_BACKUP or CREATED).
        """
        logger.info(
            "manual_backup_started",
            org_id=self.org_id,
            site_id=site_id,
            object_type=object_type,
            object_count=len(object_ids) if object_ids else 0,
        )
        start_time = datetime.now(timezone.utc)

        stats = {
            "total": 0,
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "errors": 0,
            "by_type": {},
        }

        try:
            scope, key = object_type.split(":", 1)
            if scope == "org":
                obj_def = ORG_OBJECTS.get(key)
            else:
                obj_def = SITE_OBJECTS.get(key)

            if not obj_def:
                raise BackupError(f"Unknown object type: {object_type}")

            # Fetch objects
            fetch_kwargs: dict[str, Any] = {}
            if scope == "site":
                fetch_kwargs["site_id"] = site_id
            else:
                fetch_kwargs["org_id"] = self.org_id

            raw_objects = await fetch_objects(
                self.mist_service.session, obj_def, **fetch_kwargs
            )

            # Filter to selected IDs if provided (for list types)
            if obj_def.is_list and object_ids:
                raw_objects = [o for o in raw_objects if o.get("id") in object_ids]

            for obj in raw_objects:
                try:
                    result = await self._backup_object(
                        object_type=key,
                        object_id=obj.get("id", key),
                        config=obj,
                        org_id=self.org_id,
                        site_id=site_id,
                        name_override=get_object_name(obj, obj_def),
                        event_type_if_new=event_type_if_new,
                    )
                    self._update_stats(stats, key, result)
                except Exception as e:
                    logger.error(
                        "manual_backup_object_failed",
                        object_id=obj.get("id"),
                        error=str(e),
                    )
                    stats["errors"] += 1

        except BackupError:
            raise
        except Exception as e:
            logger.error("manual_backup_fetch_failed", error=str(e))
            raise BackupError(f"Manual backup failed: {str(e)}")

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(
            "manual_backup_completed",
            org_id=self.org_id,
            duration_seconds=duration,
            **stats,
        )
        return {
            **stats,
            "duration_seconds": duration,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def backup_single_object(
        self,
        object_type: str,
        object_id: str,
        event_type: BackupEventType = BackupEventType.INCREMENTAL,
    ) -> BackupObject:
        """Backup a single object by fetching it from Mist API."""
        try:
            config = await self._fetch_object_from_mist(object_type, object_id)

            await self._backup_object(
                object_type=object_type,
                object_id=object_id,
                config=config,
                org_id=self.org_id,
                event_type_if_new=event_type,
            )

            backup = await BackupObject.find(
                BackupObject.object_id == object_id,
            ).sort([("version", -1)]).first_or_none()

            return backup

        except Exception as e:
            logger.error(
                "single_object_backup_failed",
                object_type=object_type,
                object_id=object_id,
                error=str(e),
            )
            raise BackupError(f"Failed to backup {object_type} {object_id}: {str(e)}")

    async def mark_object_deleted(
        self,
        object_id: str,
        deleted_by: Optional[str] = None,
    ) -> Optional[BackupObject]:
        """Mark an object as deleted."""
        existing = await BackupObject.find(
            BackupObject.object_id == object_id,
            BackupObject.is_deleted == False,
        ).sort([("version", -1)]).first_or_none()

        if not existing:
            logger.warning("object_not_found_for_deletion", object_id=object_id)
            return None

        next_ver = await BackupObject.next_version(object_id)

        deletion_backup = BackupObject(
            object_type=existing.object_type,
            object_id=object_id,
            object_name=existing.object_name,
            org_id=existing.org_id,
            site_id=existing.site_id,
            configuration=existing.configuration,
            configuration_hash=existing.configuration_hash,
            version=next_ver,
            previous_version_id=existing.id,
            event_type=BackupEventType.DELETED,
            changed_fields=[],
            is_deleted=True,
            deleted_at=datetime.now(timezone.utc),
            backed_up_by=deleted_by or "system",
            references=existing.references,
        )
        await deletion_backup.insert()

        logger.info(
            "object_marked_deleted",
            object_id=object_id,
            object_name=existing.object_name,
            deleted_by=deleted_by,
        )
        return deletion_backup

    async def get_object_versions(
        self,
        object_id: str,
        include_deleted: bool = False,
    ) -> list[BackupObject]:
        """Get all versions of an object."""
        query = BackupObject.find(BackupObject.object_id == object_id)

        if not include_deleted:
            query = query.find(BackupObject.is_deleted == False)

        versions = await query.sort([("version", -1)]).to_list()
        return versions

    async def get_object_at_time(
        self,
        object_id: str,
        timestamp: datetime,
    ) -> Optional[BackupObject]:
        """Get object version at a specific point in time."""
        backup = await BackupObject.find(
            BackupObject.object_id == object_id,
            BackupObject.backed_up_at <= timestamp,
        ).sort([("backed_up_at", -1)]).first_or_none()

        return backup

    # ===== Helper Methods =====

    def _calculate_hash(self, config: dict[str, Any]) -> str:
        """Calculate SHA256 hash of configuration."""
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()

    def _find_changed_fields(
        self,
        old_config: dict[str, Any],
        new_config: dict[str, Any],
        prefix: str = "",
    ) -> list[str]:
        """Find which fields changed between two configurations."""
        changed = []
        all_keys = set(old_config.keys()) | set(new_config.keys())

        for key in all_keys:
            field_path = f"{prefix}.{key}" if prefix else key

            if key not in old_config:
                changed.append(field_path)
                continue
            if key not in new_config:
                changed.append(field_path)
                continue

            old_value = old_config[key]
            new_value = new_config[key]

            if isinstance(old_value, dict) and isinstance(new_value, dict):
                nested_changes = self._find_changed_fields(old_value, new_value, field_path)
                changed.extend(nested_changes)
            elif old_value != new_value:
                changed.append(field_path)

        return changed

    def _update_stats(
        self,
        stats: dict[str, Any],
        object_type: str,
        result: str,
    ) -> None:
        """Update backup statistics."""
        stats["total"] += 1
        stats[result] += 1

        if object_type not in stats["by_type"]:
            stats["by_type"][object_type] = {"total": 0, "created": 0, "updated": 0, "unchanged": 0}

        stats["by_type"][object_type]["total"] += 1
        stats["by_type"][object_type][result] += 1

    async def _fetch_object_from_mist(
        self,
        object_type: str,
        object_id: str,
    ) -> dict[str, Any]:
        """Fetch a specific object from Mist API."""
        endpoint = f"/api/v1/orgs/{self.org_id}/{object_type}s/{object_id}"
        return await self.mist_service.api_get(endpoint)
