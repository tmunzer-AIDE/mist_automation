"""
Backup service for fetching and storing Mist configuration backups.
"""

from datetime import datetime, timezone
from typing import Any, Optional
import hashlib
import json
import structlog
from beanie import PydanticObjectId

from app.models.backup import (
    BackupObject,
    BackupObjectType,
    BackupEventType,
    BackupStatus,
)
from app.services.mist_service import MistService
from app.core.exceptions import BackupError, ConfigurationError
from app.config import settings

logger = structlog.get_logger(__name__)


class BackupService:
    """Service for managing configuration backups."""

    def __init__(self, mist_service: Optional[MistService] = None):
        """
        Initialize backup service.

        Args:
            mist_service: Optional MistService instance
        """
        self.mist_service = mist_service or MistService()
        self.org_id = self.mist_service.org_id

    async def perform_full_backup(self) -> dict[str, Any]:
        """
        Perform a full backup of all Mist configurations.

        Returns:
            dict: Backup statistics

        Raises:
            BackupError: If backup fails
        """
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

        try:
            # Backup organization-level objects
            await self._backup_org_objects(stats)

            # Backup site-level objects
            await self._backup_site_objects(stats)

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(
                "full_backup_completed",
                org_id=self.org_id,
                duration_seconds=duration,
                **stats,
            )

            return {
                **stats,
                "duration_seconds": duration,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error("full_backup_failed", org_id=self.org_id, error=str(e))
            raise BackupError(f"Full backup failed: {str(e)}")

    async def _backup_org_objects(self, stats: dict[str, Any]) -> None:
        """Backup organization-level objects."""
        
        # Backup WLANs
        try:
            wlans = await self.mist_service.get_wlans()
            for wlan in wlans:
                result = await self._backup_object(
                    object_type=BackupObjectType.WLAN,
                    object_id=wlan["id"],
                    config=wlan,
                    org_id=self.org_id,
                )
                self._update_stats(stats, BackupObjectType.WLAN, result)
            logger.debug("org_wlans_backed_up", count=len(wlans))
        except Exception as e:
            logger.error("backup_org_wlans_failed", error=str(e))
            stats["errors"] += 1

        # Backup templates
        try:
            templates = await self.mist_service.get_templates()
            for template in templates:
                result = await self._backup_object(
                    object_type=BackupObjectType.TEMPLATE,
                    object_id=template["id"],
                    config=template,
                    org_id=self.org_id,
                )
                self._update_stats(stats, BackupObjectType.TEMPLATE, result)
            logger.debug("org_templates_backed_up", count=len(templates))
        except Exception as e:
            logger.error("backup_org_templates_failed", error=str(e))
            stats["errors"] += 1

    async def _backup_site_objects(self, stats: dict[str, Any]) -> None:
        """Backup site-level objects for all sites."""
        
        try:
            sites = await self.mist_service.get_sites()
            
            for site in sites:
                site_id = site["id"]
                
                # Backup site configuration itself
                result = await self._backup_object(
                    object_type=BackupObjectType.SITE,
                    object_id=site_id,
                    config=site,
                    org_id=self.org_id,
                    site_id=site_id,
                )
                self._update_stats(stats, BackupObjectType.SITE, result)

                # Backup site WLANs
                try:
                    site_wlans = await self.mist_service.get_wlans(site_id=site_id)
                    for wlan in site_wlans:
                        result = await self._backup_object(
                            object_type=BackupObjectType.WLAN,
                            object_id=wlan["id"],
                            config=wlan,
                            org_id=self.org_id,
                            site_id=site_id,
                        )
                        self._update_stats(stats, BackupObjectType.WLAN, result)
                except Exception as e:
                    logger.error("backup_site_wlans_failed", site_id=site_id, error=str(e))
                    stats["errors"] += 1

                # Backup site devices
                try:
                    devices = await self.mist_service.get_devices(site_id=site_id)
                    for device in devices:
                        device_type = device.get("type", "ap").lower()
                        object_type = (
                            BackupObjectType.AP if device_type == "ap"
                            else BackupObjectType.SWITCH if device_type == "switch"
                            else BackupObjectType.GATEWAY if device_type == "gateway"
                            else BackupObjectType.AP
                        )
                        
                        result = await self._backup_object(
                            object_type=object_type,
                            object_id=device["id"],
                            config=device,
                            org_id=self.org_id,
                            site_id=site_id,
                        )
                        self._update_stats(stats, object_type, result)
                except Exception as e:
                    logger.error("backup_site_devices_failed", site_id=site_id, error=str(e))
                    stats["errors"] += 1

            logger.debug("sites_backed_up", count=len(sites))

        except Exception as e:
            logger.error("backup_sites_failed", error=str(e))
            raise

    async def _backup_object(
        self,
        object_type: BackupObjectType,
        object_id: str,
        config: dict[str, Any],
        org_id: str,
        site_id: Optional[str] = None,
    ) -> str:
        """
        Backup a single object.

        Args:
            object_type: Type of object
            object_id: Object UUID
            config: Object configuration
            org_id: Organization ID
            site_id: Optional site ID

        Returns:
            "created", "updated", or "unchanged"
        """
        # Calculate configuration hash
        config_hash = self._calculate_hash(config)

        # Get object name
        object_name = config.get("name") or config.get("ssid") or object_id[:8]

        # Check if object already exists
        existing = await BackupObject.find_one(
            BackupObject.object_id == object_id,
            BackupObject.is_deleted == False,
        ).sort([("version", -1)])

        if existing:
            # Check if configuration changed
            if existing.configuration_hash == config_hash:
                logger.debug(
                    "object_unchanged",
                    object_type=object_type,
                    object_id=object_id,
                    object_name=object_name,
                )
                return "unchanged"

            # Configuration changed - create new version
            changed_fields = self._find_changed_fields(existing.configuration, config)
            
            new_backup = BackupObject(
                object_type=object_type.value,
                object_id=object_id,
                object_name=object_name,
                org_id=org_id,
                site_id=site_id,
                configuration=config,
                configuration_hash=config_hash,
                version=existing.version + 1,
                previous_version_id=existing.id,
                event_type=BackupEventType.UPDATED,
                changed_fields=changed_fields,
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
            return "updated"

        else:
            # New object - create first version
            new_backup = BackupObject(
                object_type=object_type.value,
                object_id=object_id,
                object_name=object_name,
                org_id=org_id,
                site_id=site_id,
                configuration=config,
                configuration_hash=config_hash,
                version=1,
                event_type=BackupEventType.FULL_BACKUP,
                changed_fields=[],
            )
            await new_backup.insert()

            logger.info(
                "object_created",
                object_type=object_type,
                object_id=object_id,
                object_name=object_name,
            )
            return "created"

    async def backup_single_object(
        self,
        object_type: str,
        object_id: str,
        event_type: BackupEventType = BackupEventType.INCREMENTAL,
    ) -> BackupObject:
        """
        Backup a single object by fetching it from Mist API.

        Args:
            object_type: Type of Mist object
            object_id: Object UUID
            event_type: Type of backup event

        Returns:
            Created or updated BackupObject

        Raises:
            BackupError: If backup fails
        """
        try:
            # Fetch object from Mist API based on type
            # This is simplified - actual implementation would need type-specific API calls
            config = await self._fetch_object_from_mist(object_type, object_id)

            result = await self._backup_object(
                object_type=BackupObjectType(object_type),
                object_id=object_id,
                config=config,
                org_id=self.org_id,
            )

            # Get the backup object
            backup = await BackupObject.find_one(
                BackupObject.object_id == object_id,
            ).sort([("version", -1)])

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
        """
        Mark an object as deleted.

        Args:
            object_id: Object UUID
            deleted_by: Who deleted the object

        Returns:
            Updated backup object or None if not found
        """
        # Find latest version
        existing = await BackupObject.find_one(
            BackupObject.object_id == object_id,
            BackupObject.is_deleted == False,
        ).sort([("version", -1)])

        if not existing:
            logger.warning("object_not_found_for_deletion", object_id=object_id)
            return None

        # Create deletion record
        deletion_backup = BackupObject(
            object_type=existing.object_type,
            object_id=object_id,
            object_name=existing.object_name,
            org_id=existing.org_id,
            site_id=existing.site_id,
            configuration=existing.configuration,
            configuration_hash=existing.configuration_hash,
            version=existing.version + 1,
            previous_version_id=existing.id,
            event_type=BackupEventType.DELETED,
            changed_fields=[],
            is_deleted=True,
            deleted_at=datetime.now(timezone.utc),
            backed_up_by=deleted_by or "system",
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
        """
        Get all versions of an object.

        Args:
            object_id: Object UUID
            include_deleted: Whether to include deleted versions

        Returns:
            List of backup objects ordered by version (newest first)
        """
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
        """
        Get object version at a specific point in time.

        Args:
            object_id: Object UUID
            timestamp: Point in time to retrieve

        Returns:
            Backup object or None
        """
        backup = await BackupObject.find_one(
            BackupObject.object_id == object_id,
            BackupObject.backed_up_at <= timestamp,
        ).sort([("backed_up_at", -1)])

        return backup

    # ===== Helper Methods =====

    def _calculate_hash(self, config: dict[str, Any]) -> str:
        """Calculate SHA256 hash of configuration."""
        # Sort keys for consistent hashing
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()

    def _find_changed_fields(
        self,
        old_config: dict[str, Any],
        new_config: dict[str, Any],
        prefix: str = "",
    ) -> list[str]:
        """
        Find which fields changed between two configurations.

        Args:
            old_config: Old configuration
            new_config: New configuration
            prefix: Field path prefix for nested objects

        Returns:
            List of changed field paths
        """
        changed = []

        # Get all keys from both configs
        all_keys = set(old_config.keys()) | set(new_config.keys())

        for key in all_keys:
            field_path = f"{prefix}.{key}" if prefix else key

            # Key added
            if key not in old_config:
                changed.append(field_path)
                continue

            # Key removed
            if key not in new_config:
                changed.append(field_path)
                continue

            # Values different
            old_value = old_config[key]
            new_value = new_config[key]

            if isinstance(old_value, dict) and isinstance(new_value, dict):
                # Recursively check nested objects
                nested_changes = self._find_changed_fields(old_value, new_value, field_path)
                changed.extend(nested_changes)
            elif old_value != new_value:
                changed.append(field_path)

        return changed

    def _update_stats(
        self,
        stats: dict[str, Any],
        object_type: BackupObjectType,
        result: str,
    ) -> None:
        """Update backup statistics."""
        stats["total"] += 1
        stats[result] += 1

        # Update per-type stats
        type_key = object_type.value
        if type_key not in stats["by_type"]:
            stats["by_type"][type_key] = {"total": 0, "created": 0, "updated": 0, "unchanged": 0}
        
        stats["by_type"][type_key]["total"] += 1
        stats["by_type"][type_key][result] += 1

    async def _fetch_object_from_mist(
        self,
        object_type: str,
        object_id: str,
    ) -> dict[str, Any]:
        """
        Fetch a specific object from Mist API.

        This is a simplified implementation. Real implementation would need
        type-specific API calls.
        """
        # This would need to be expanded based on object type
        # For now, return a generic GET
        endpoint = f"/api/v1/orgs/{self.org_id}/{object_type}s/{object_id}"
        return await self.mist_service.api_get(endpoint)
