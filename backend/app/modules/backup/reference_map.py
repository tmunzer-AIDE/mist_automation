"""
Static reference map for cross-object dependencies in Mist configurations.

Each entry maps an object type to the fields that reference other backed-up
object types.  The extraction logic traverses dot-notation paths (including
wildcard segments for dict-of-dicts like ``paths.*``) and validates that
resolved values look like UUIDs before recording them.
"""

import re
from dataclasses import dataclass, field

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


@dataclass
class RefDescriptor:
    field_path: str        # Dot-notation path, e.g. "matching.nactags"
    target_type: str       # Target object type key, e.g. "nactags"
    is_list: bool = False  # True if field holds a list of UUIDs


# ── Complete reference map ────────────────────────────────────────────────────

REFERENCE_MAP: dict[str, list[RefDescriptor]] = {
    "data": [
        RefDescriptor("alarmtemplate_id", "alarmtemplates"),
    ],
    "sites": [
        RefDescriptor("networktemplate_id", "networktemplates"),
        RefDescriptor("rftemplate_id", "rftemplates"),
        RefDescriptor("aptemplate_id", "aptemplates"),
        RefDescriptor("secpolicy_id", "secpolicies"),
        RefDescriptor("alarmtemplate_id", "alarmtemplates"),
        RefDescriptor("gatewaytemplate_id", "gatewaytemplates"),
        RefDescriptor("sitetemplate_id", "sitetemplates"),
        RefDescriptor("sitegroup_ids", "sitegroups", is_list=True),
    ],
    "templates": [
        RefDescriptor("applies_to.sitegroup_ids", "sitegroups", is_list=True),
    ],
    "wlans": [
        RefDescriptor("template_id", "templates"),
        RefDescriptor("mxtunnel_ids", "mxtunnels", is_list=True),
    ],
    "nacrules": [
        RefDescriptor("matching.nactags", "nactags", is_list=True),
        RefDescriptor("apply_tags", "nactags", is_list=True),
    ],
    "devices": [
        RefDescriptor("deviceprofile_id", "deviceprofiles"),
        RefDescriptor("map_id", "maps"),
    ],
    "servicepolicies": [
        RefDescriptor("idp_profile_id", "idpprofiles"),
    ],
    "secpolicies": [
        RefDescriptor("wlan_id", "wlans"),
    ],
    "mxedges": [
        RefDescriptor("mxcluster_id", "mxclusters"),
    ],
    "ssoroles": [
        RefDescriptor("sso_id", "ssos"),
    ],
    "nacportals": [
        RefDescriptor("sso_id", "ssos"),
    ],
    "pskportals": [
        RefDescriptor("sso_id", "ssos"),
    ],
    "vpns": [
        RefDescriptor("paths.*.profile", "servicepolicies"),
    ],
    "wxrules": [
        RefDescriptor("src_wxtags", "wxtags", is_list=True),
        RefDescriptor("dst_wxtags", "wxtags", is_list=True),
    ],
}


def _resolve_path(config: dict, path: str) -> list:
    """Resolve a dot-notation path (with optional ``*`` wildcard) to leaf values.

    Returns a flat list of leaf values found at *path* inside *config*.
    Missing keys are silently skipped.
    """
    parts = path.split(".")
    current: list = [config]

    for part in parts:
        next_level: list = []
        for node in current:
            if not isinstance(node, dict):
                continue
            if part == "*":
                # Wildcard: iterate all values of the dict
                next_level.extend(node.values())
            else:
                val = node.get(part)
                if val is not None:
                    next_level.append(val)
        current = next_level

    return current


def extract_references(
    object_type: str,
    config: dict,
) -> list[dict]:
    """Extract cross-object references from a configuration dict.

    Returns a list of dicts with keys ``target_type``, ``target_id``,
    ``field_path`` for every valid UUID reference found.
    """
    descriptors = REFERENCE_MAP.get(object_type)
    if not descriptors:
        return []

    refs: list[dict] = []
    for desc in descriptors:
        values = _resolve_path(config, desc.field_path)

        # Flatten lists when is_list is True
        ids: list = []
        for v in values:
            if desc.is_list and isinstance(v, list):
                ids.extend(v)
            else:
                ids.append(v)

        for raw_id in ids:
            if not isinstance(raw_id, str):
                continue
            if not UUID_RE.match(raw_id):
                continue
            refs.append({
                "target_type": desc.target_type,
                "target_id": raw_id,
                "field_path": desc.field_path,
            })

    return refs
