"""Resolve human-readable labels for Twin sessions.

Separates the pure formatting logic (testable) from the DB lookups
(integration-tested via twin_service).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.digital_twin.models import StagedWrite


def _count_by_type(object_types: list[str]) -> dict[str, int]:
    """Return a {type: count} dict preserving insertion order of first occurrence."""
    counts: dict[str, int] = {}
    for t in object_types:
        counts[t] = counts.get(t, 0) + 1
    return counts


def format_object_label(
    *,
    object_types: list[str],
    object_names_by_type: dict[str, list[str]],
) -> str | None:
    """Build the human-readable object label for a Twin session.

    - empty -> None
    - 1 object -> "{type}: {name}"
    - N objects of same type -> "N {type}"
    - mixed types -> "N objects: a type_a, b type_b"
    """
    if not object_types:
        return None

    counts = _count_by_type(object_types)

    if len(object_types) == 1:
        the_type = object_types[0]
        names = object_names_by_type.get(the_type, [])
        if names:
            return f"{the_type}: {names[0]}"
        return the_type

    if len(counts) == 1:
        the_type = next(iter(counts))
        return f"{counts[the_type]} {the_type}"

    parts = [f"{count} {t}" for t, count in counts.items()]
    total = len(object_types)
    return f"{total} objects: {', '.join(parts)}"


async def fetch_object_names_by_type(
    *,
    org_id: str,
    writes: "list[StagedWrite]",
) -> dict[str, list[str]]:
    """Resolve object names from backup data for each staged write.

    Returns a dict keyed by object_type with a list of names (one per write that
    touched that type). Missing names fall back to the first 8 chars of object_id.
    """
    from app.modules.backup.models import BackupObject
    from app.modules.digital_twin.services.state_resolver import canonicalize_object_type

    result: dict[str, list[str]] = {}
    for w in writes:
        canonical = canonicalize_object_type(w.object_type) or ""
        if not canonical:
            continue

        name: str | None = None
        if w.object_id:
            doc = await BackupObject.find(
                {
                    "org_id": org_id,
                    "object_type": canonical,
                    "object_id": w.object_id,
                    "is_deleted": False,
                }
            ).first_or_none()
            if doc:
                data = getattr(doc, "data", None) or {}
                name = data.get("name") or data.get("ssid")

        if not name:
            name = (w.object_id[:8] if w.object_id else canonical)

        result.setdefault(canonical, []).append(name)

    return result


async def fetch_site_names(*, org_id: str, site_ids: list[str]) -> list[str]:
    """Resolve site names for a list of site IDs via a single query.

    Missing sites fall back to the site_id itself (truncated to 8 chars).
    """
    from app.modules.backup.models import BackupObject

    if not site_ids:
        return []

    cursor = BackupObject.find(
        {
            "org_id": org_id,
            "object_type": "info",
            "site_id": {"$in": site_ids},
            "is_deleted": False,
        }
    )
    id_to_name: dict[str, str] = {}
    async for doc in cursor:
        data = getattr(doc, "data", None) or {}
        sid = getattr(doc, "site_id", None)
        if sid:
            id_to_name[sid] = data.get("name") or sid[:8]

    return [id_to_name.get(sid, sid[:8]) for sid in site_ids]
