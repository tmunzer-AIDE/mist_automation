"""
Build virtual state from backup snapshots + staged writes.

The state is a dict keyed by (object_type, site_id, object_id) tuples.
Each value is the full config dict for that object.

For state resolution involving backup data and live API, see resolve_state()
which is async and requires database access. The pure functions here
(merge_write_into_state, apply_staged_writes) are testable without DB.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from app.modules.digital_twin.models import BaseSnapshotRef, StagedWrite

logger = structlog.get_logger(__name__)

StateKey = tuple[str, str | None, str | None]


def merge_write_into_state(
    state: dict[StateKey, dict[str, Any]],
    write: StagedWrite,
) -> None:
    """Apply a single staged write to the virtual state dict (mutates in place)."""
    key: StateKey = (write.object_type or "", write.site_id, write.object_id)

    if write.method == "DELETE":
        state.pop(key, None)
        return

    if write.method == "POST":
        temp_id = f"twin-{uuid.uuid4().hex[:12]}"
        key = (write.object_type or "", write.site_id, temp_id)
        state[key] = dict(write.body) if write.body else {}
        state[key]["id"] = temp_id
        return

    # PUT — merge into existing or create
    existing = state.get(key, {})
    if write.body:
        existing.update(write.body)
    state[key] = existing


def apply_staged_writes(
    base_state: dict[StateKey, dict[str, Any]],
    writes: list[StagedWrite],
) -> dict[StateKey, dict[str, Any]]:
    """Apply all staged writes to a copy of the base state, in sequence order."""
    state = dict(base_state)
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
            types.add(w.object_type)
    return sorted(sites), sorted(types)


async def load_base_state_from_backup(
    org_id: str,
    writes: list[StagedWrite],
) -> tuple[dict[StateKey, dict[str, Any]], list[BaseSnapshotRef]]:
    """Load current config for all objects affected by staged writes from backup snapshots."""
    from app.modules.backup.models import BackupObject

    base_state: dict[StateKey, dict[str, Any]] = {}
    refs: list[BaseSnapshotRef] = []

    for write in writes:
        if not write.object_id or not write.object_type:
            continue
        if write.method == "POST":
            continue

        query = {
            "object_type": write.object_type,
            "object_id": write.object_id,
            "is_deleted": False,
        }
        if write.site_id:
            query["site_id"] = write.site_id

        backup = await BackupObject.find(query).sort([("version", -1)]).first_or_none()
        if backup:
            key: StateKey = (write.object_type, write.site_id, write.object_id)
            base_state[key] = dict(backup.configuration)
            refs.append(
                BaseSnapshotRef(
                    backup_object_id=str(backup.id),
                    version=backup.version,
                    object_type=write.object_type,
                    object_id=write.object_id,
                    site_id=write.site_id,
                )
            )

    return base_state, refs


async def load_all_objects_of_type(
    org_id: str,
    object_type: str,
    site_id: str | None = None,
) -> list[dict[str, Any]]:
    """Load all latest backup objects of a given type for conflict checking."""
    from app.modules.backup.models import BackupObject

    pipeline: list[dict[str, Any]] = [
        {"$match": {"object_type": object_type, "org_id": org_id, "is_deleted": False}},
    ]
    if site_id:
        pipeline[0]["$match"]["site_id"] = site_id

    pipeline.extend([
        {"$sort": {"version": -1}},
        {"$group": {"_id": "$object_id", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
    ])

    results = await BackupObject.aggregate(pipeline).to_list()
    return [r.get("configuration", {}) for r in results if r.get("configuration")]
