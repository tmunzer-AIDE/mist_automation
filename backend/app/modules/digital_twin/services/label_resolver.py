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
    """Resolve object names for each staged write.

    For POST writes, names come from the create payload only (there is no source
    object yet). For PUT/DELETE writes, names are resolved from backup objects.

    Returns a dict keyed by object_type with a list of names (one per write
    that touched that type). Missing names fall back to object_id (first 8
    chars) or the object_type when no object_id is available.
    """
    from app.modules.backup.models import BackupObject
    from app.modules.digital_twin.services.state_resolver import canonicalize_object_type

    result: dict[str, list[str]] = {}
    site_name_cache: dict[str, str] = {}

    async def _resolve_site_name(site_id: str) -> str:
        if site_id in site_name_cache:
            return site_name_cache[site_id]

        doc = await BackupObject.find(
            {
                "org_id": org_id,
                "is_deleted": False,
                "$or": [
                    {"object_type": "info", "site_id": site_id},
                    {"object_type": "site", "object_id": site_id},
                    {"object_type": "sites", "object_id": site_id},
                ],
            }
        ).sort([("version", -1)]).first_or_none()

        if doc:
            config = doc.configuration or {}
            site_name = doc.object_name or config.get("name") or site_id
        else:
            site_name = site_id

        site_name_cache[site_id] = site_name
        return site_name
    for w in writes:
        canonical = canonicalize_object_type(w.object_type) or ""
        if not canonical:
            continue

        name: str | None = None

        # For create writes, derive display names from payload first (no object_id yet).
        body = w.body or {}
        if canonical == "wlans":
            name = body.get("ssid")
        elif canonical in {"networks", "networktemplates", "sitetemplates", "sitegroups", "services", "servicepolicies"}:
            name = body.get("name")
        elif canonical == "info":
            # Site rename payloads are on /sites/{site_id} singleton writes.
            name = body.get("name")

        # Site-level singletons usually do not have object_id; use site name label.
        if canonical in {"info", "settings"} and w.site_id and not name:
            name = await _resolve_site_name(w.site_id)

        if w.method != "POST" and w.object_id:
            doc = await BackupObject.find(
                {
                    "org_id": org_id,
                    "object_type": canonical,
                    "object_id": w.object_id,
                    "is_deleted": False,
                }
            ).sort("-version").first_or_none()
            if doc:
                config = doc.configuration or {}
                # WLANs should always prefer SSID over object_name/name.
                if canonical == "wlans":
                    name = config.get("ssid") or doc.object_name or config.get("name")
                else:
                    name = doc.object_name or config.get("name") or config.get("ssid")

        resolved = name or (w.object_id[:8] if w.object_id else canonical)
        result.setdefault(canonical, []).append(resolved)

    return result


async def fetch_site_names(*, org_id: str, site_ids: list[str]) -> list[str]:
    """Resolve site names for a list of site IDs via a single query.

    Missing sites fall back to the site_id itself.
    """
    from app.modules.backup.models import BackupObject

    if not site_ids:
        return []

    cursor = BackupObject.find(
        {
            "org_id": org_id,
            "is_deleted": False,
            "$or": [
                {"object_type": "info", "site_id": {"$in": site_ids}},
                {"object_type": "site", "object_id": {"$in": site_ids}},
                {"object_type": "sites", "object_id": {"$in": site_ids}},
            ],
        }
    ).sort([("version", -1)])
    id_to_name: dict[str, str] = {}
    async for doc in cursor:
        sid = doc.site_id or doc.object_id
        if sid and sid not in id_to_name:
            config = doc.configuration or {}
            id_to_name[sid] = doc.object_name or config.get("name") or sid

    return [id_to_name.get(sid, sid) for sid in site_ids]
