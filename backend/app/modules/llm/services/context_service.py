"""
Gathers data from other modules to feed LLM prompt builders.

This is the bridge between the LLM module and the rest of the app.
"""

import structlog
from beanie import PydanticObjectId

from app.core.exceptions import DataNotFoundException

logger = structlog.get_logger(__name__)


async def get_backup_diff_context(version_id_1: str, version_id_2: str) -> dict:
    """Fetch two BackupObject versions and compute their diff.

    Returns a dict with:
      - object_type, object_name, event_type
      - old_version, new_version (version numbers)
      - changed_fields (from the newer version)
      - diff_entries (list of {path, type, old?, new?, value?})
    """
    from app.modules.backup.models import BackupObject
    from app.modules.backup.router import _deep_diff

    try:
        v1 = await BackupObject.get(PydanticObjectId(version_id_1))
        v2 = await BackupObject.get(PydanticObjectId(version_id_2))
    except Exception as exc:
        raise DataNotFoundException("Invalid version ID format") from exc

    if not v1 or not v2:
        raise DataNotFoundException("One or both backup versions not found")

    # Ensure v1 is the older version
    if v1.version > v2.version:
        v1, v2 = v2, v1

    diff_entries = _deep_diff(v1.configuration, v2.configuration)

    return {
        "object_type": v2.object_type,
        "object_name": v2.object_name,
        "event_type": v2.event_type,
        "old_version": v1.version,
        "new_version": v2.version,
        "changed_fields": v2.changed_fields,
        "diff_entries": diff_entries,
    }
