"""
Build virtual state from backup snapshots + staged writes.

The state is a dict keyed by (object_type, site_id, object_id) tuples.
Each value is the full config dict for that object.

For state resolution involving backup data and live API, see resolve_state()
which is async and requires database access. The pure functions here
(merge_write_into_state, apply_staged_writes) are testable without DB.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

import structlog

from app.modules.digital_twin.models import BaseSnapshotRef, StagedWrite

logger = structlog.get_logger(__name__)

StateKey = tuple[str, str | None, str | None]

_OBJECT_TYPE_ALIASES: dict[str, str] = {
    "setting": "settings",
    "site_setting": "settings",
    "site": "info",
    "site_devices": "devices",
    "site_networks": "networks",
    "site_wlans": "wlans",
}

_SINGLETON_OBJECT_TYPES: set[str] = {"settings", "info", "data"}

DELETED_SENTINEL_KEY = "__twin_deleted__"
# Backward-compatible alias for internal callers/tests that still reference the private name.
_DELETED_SENTINEL_KEY = DELETED_SENTINEL_KEY


def canonicalize_object_type(object_type: str | None) -> str | None:
    """Map endpoint/object aliases to canonical backup object_type values."""
    if object_type is None:
        return None
    return _OBJECT_TYPE_ALIASES.get(object_type, object_type)


def object_type_query_values(object_type: str | None) -> list[str]:
    """Return canonical + legacy object_type labels for backward-compatible queries."""
    canonical = canonicalize_object_type(object_type)
    if canonical is None:
        return []

    values: list[str] = [canonical]
    if object_type and object_type not in values:
        values.append(object_type)

    for alias, mapped in _OBJECT_TYPE_ALIASES.items():
        if mapped == canonical and alias not in values:
            values.append(alias)

    return values


def is_twin_deleted(config: dict[str, Any] | None) -> bool:
    """Return True when an object config is marked with the Twin deletion sentinel."""
    return bool(config and config.get(DELETED_SENTINEL_KEY))


def merge_write_into_state(
    state: dict[StateKey, dict[str, Any]],
    write: StagedWrite,
) -> None:
    """Apply a single staged write to the virtual state dict (mutates in place)."""
    object_type = canonicalize_object_type(write.object_type) or ""
    key: StateKey = (object_type, write.site_id, write.object_id)

    if write.method == "DELETE":
        # Keep an explicit tombstone so downstream snapshot builders can remove
        # objects from the predicted state instead of silently falling back.
        state[key] = {DELETED_SENTINEL_KEY: True}
        return

    if write.method == "POST":
        temp_id = f"twin-{uuid.uuid4().hex[:12]}"
        key = (object_type, write.site_id, temp_id)
        state[key] = dict(write.body) if write.body else {}
        state[key]["id"] = temp_id
        return

    # PUT — apply root-level partial update semantics.
    existing = state.get(key, {})
    if existing.get(DELETED_SENTINEL_KEY):
        existing = {}

    if write.body:
        for k, v in write.body.items():
            existing[k] = v

    state[key] = existing


def apply_staged_writes(
    base_state: dict[StateKey, dict[str, Any]],
    writes: list[StagedWrite],
) -> dict[StateKey, dict[str, Any]]:
    """Apply all staged writes to a deep copy of the base state, in sequence order.

    A deep copy is required because ``merge_write_into_state`` mutates nested
    dicts in place (e.g. PUT updates under a site setting). A shallow copy
    would share nested refs with ``base_state`` and silently mutate the
    caller's baseline.
    """
    state = copy.deepcopy(base_state)
    sorted_writes = sorted(writes, key=lambda w: w.sequence)
    for write in sorted_writes:
        merge_write_into_state(state, write)
    return state


def collect_affected_metadata(
    writes: list[StagedWrite],
) -> tuple[list[str], list[str]]:
    """Collect unique site_ids and object_types from staged writes."""
    sites: set[str] = set()
    types: set[str] = set()
    for w in writes:
        if w.site_id:
            sites.add(w.site_id)
        if w.object_type:
            types.add(canonicalize_object_type(w.object_type) or w.object_type)
    return sorted(sites), sorted(types)


async def load_base_state_from_backup(
    org_id: str,
    writes: list[StagedWrite],
) -> tuple[dict[StateKey, dict[str, Any]], list[BaseSnapshotRef]]:
    """Load current config for all objects affected by staged writes from backup snapshots."""
    from app.modules.backup.models import BackupObject

    base_state: dict[StateKey, dict[str, Any]] = {}
    refs: list[BaseSnapshotRef] = []

    loaded_keys: set[StateKey] = set()

    for write in writes:
        if write.method == "POST":
            continue

        object_type = canonicalize_object_type(write.object_type)
        if not object_type:
            continue

        key: StateKey = (object_type, write.site_id, write.object_id)
        if key in loaded_keys:
            continue

        query: dict[str, Any] = {
            "object_type": object_type,
            "org_id": org_id,
            "is_deleted": False,
        }
        if write.site_id:
            query["site_id"] = write.site_id

        # Regular collection objects (have object_id) and singleton objects
        # (settings/info) are loaded slightly differently.
        if write.object_id:
            query["object_id"] = write.object_id
        elif object_type not in _SINGLETON_OBJECT_TYPES:
            continue

        backup = None
        if object_type == "info" and write.site_id and not write.object_id:
            # Site identity/template bindings can be stored under multiple
            # backup shapes. Resolve in deterministic order so a partial
            # /sites/{site_id} payload merges onto the full current singleton
            # instead of starting from an empty dict.
            fallback_queries = [
                {
                    "object_type": "info",
                    "site_id": write.site_id,
                    "org_id": org_id,
                    "is_deleted": False,
                },
                {
                    "object_type": "site",
                    "object_id": write.site_id,
                    "org_id": org_id,
                    "is_deleted": False,
                },
                {
                    "object_type": "sites",
                    "object_id": write.site_id,
                    "org_id": org_id,
                    "is_deleted": False,
                },
            ]
            for fallback_query in fallback_queries:
                backup = await BackupObject.find(fallback_query).sort([("version", -1)]).first_or_none()
                if backup:
                    break
        else:
            backup = await BackupObject.find(query).sort([("version", -1)]).first_or_none()

        if not backup:
            continue

        storage_key: StateKey = (object_type, write.site_id, write.object_id)
        base_state[storage_key] = dict(backup.configuration)
        refs.append(
            BaseSnapshotRef(
                backup_object_id=str(backup.id),
                version=backup.version,
                object_type=object_type,
                object_id=backup.object_id or write.object_id or "singleton",
                site_id=write.site_id,
            )
        )
        loaded_keys.add(key)

    return base_state, refs


async def load_all_objects_of_type(
    org_id: str,
    object_type: str,
    site_id: str | None = None,
    org_level_only: bool = False,
) -> list[dict[str, Any]]:
    """Load latest backup objects of a given type.

    Args:
        org_id: Mist org ID.
        object_type: Backup object type key.
        site_id: Optional site scope. When provided, only that site's objects are loaded.
        org_level_only: When True and site_id is None, only org-scoped objects
            (site_id null/missing) are loaded.
    """
    from app.modules.backup.models import BackupObject

    canonical_type = canonicalize_object_type(object_type) or object_type

    match: dict[str, Any] = {"object_type": canonical_type, "org_id": org_id, "is_deleted": False}
    if site_id:
        match["site_id"] = site_id
    elif org_level_only:
        match["site_id"] = None

    pipeline: list[dict[str, Any]] = [{"$match": match}]

    pipeline.extend(
        [
            {"$sort": {"version": -1}},
            {"$group": {"_id": "$object_id", "doc": {"$first": "$$ROOT"}}},
            {"$replaceRoot": {"newRoot": "$doc"}},
        ]
    )

    results = await BackupObject.aggregate(pipeline).to_list()
    return [r.get("configuration", {}) for r in results if r.get("configuration")]
