"""
Config Compiler for the Digital Twin module.

Derives effective per-device configuration from the full Mist template
inheritance chain, and detects which sites are impacted by template changes.

Mist merge order:
  Switch:  derived_site_setting (base) → device config
  Gateway: gateway_template → device_profile → device config

Port config uses deep per-port merging for gateways so template fields
(e.g. wan_type) are preserved while device fields win on conflict.
"""

from __future__ import annotations

import copy
import re
from typing import Any

import structlog

from app.modules.digital_twin.models import StagedWrite

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Template type mapping
# ---------------------------------------------------------------------------

# Maps backup/API object_type → site info assignment field
TEMPLATE_TYPE_TO_FIELD: dict[str, str] = {
    "sitetemplates": "sitetemplate_id",
    "networktemplates": "networktemplate_id",
    "rftemplates": "rftemplate_id",
    "gatewaytemplates": "gatewaytemplate_id",
    "aptemplates": "aptemplate_id",
}

# Regex to extract (template_type, template_id) from Mist org-level API paths
# Matches: /api/v1/orgs/<org_id>/<template_type>/<template_id>
_TEMPLATE_PATH_RE = re.compile(
    r"/orgs/[^/]+/(" + "|".join(re.escape(t) for t in TEMPLATE_TYPE_TO_FIELD) + r")/([^/]+)$"
)


# ---------------------------------------------------------------------------
# 1. detect_template_changes
# ---------------------------------------------------------------------------


def detect_template_changes(staged_writes: list[StagedWrite]) -> list[dict[str, str]]:
    """Scan staged writes for org-level template modifications.

    Returns a list of dicts:
        [{"template_type": str, "template_id": str, "assignment_field": str}, ...]
    """
    results: list[dict[str, str]] = []
    for write in staged_writes:
        m = _TEMPLATE_PATH_RE.search(write.endpoint)
        if not m:
            continue
        template_type = m.group(1)
        template_id = m.group(2)
        assignment_field = TEMPLATE_TYPE_TO_FIELD[template_type]
        results.append(
            {
                "template_type": template_type,
                "template_id": template_id,
                "assignment_field": assignment_field,
            }
        )
    return results


# ---------------------------------------------------------------------------
# 2. find_impacted_sites
# ---------------------------------------------------------------------------


async def find_impacted_sites(template_type: str, template_id: str, org_id: str) -> list[str]:
    """Find all sites where the given template is assigned.

    Uses MongoDB aggregation on BackupObject(type="info"):
      match → sort version desc → group by object_id (latest per site) → match template field.

    Returns list of site_ids.
    """
    from app.modules.backup.models import BackupObject

    assignment_field = TEMPLATE_TYPE_TO_FIELD.get(template_type)
    if not assignment_field:
        logger.warning("find_impacted_sites_unknown_type", template_type=template_type)
        return []

    pipeline = [
        {"$match": {"object_type": "info", "org_id": org_id, "is_deleted": False}},
        {"$sort": {"version": -1}},
        {
            "$group": {
                "_id": "$object_id",
                "site_id": {"$first": "$site_id"},
                "configuration": {"$first": "$configuration"},
            }
        },
        {
            "$match": {
                f"configuration.{assignment_field}": template_id,
            }
        },
        {"$project": {"site_id": 1, "_id": 0}},
    ]

    site_ids: list[str] = []
    async for doc in BackupObject.aggregate(pipeline):
        sid = doc.get("site_id")
        if sid:
            site_ids.append(sid)

    return site_ids


# ---------------------------------------------------------------------------
# 3. resolve_vars
# ---------------------------------------------------------------------------


def resolve_vars(data: Any, site_vars: dict[str, Any]) -> Any:
    """Recursively replace {{key}} placeholders in strings, dicts, and lists.

    Unresolved vars are left as-is.
    """
    if not site_vars:
        return data
    if isinstance(data, str):
        for k, v in site_vars.items():
            data = data.replace(f"{{{{{k}}}}}", str(v))
        return data
    if isinstance(data, dict):
        return {k: resolve_vars(v, site_vars) for k, v in data.items()}
    if isinstance(data, list):
        return [resolve_vars(item, site_vars) for item in data]
    return data


# ---------------------------------------------------------------------------
# 4. compile_switch_config
# ---------------------------------------------------------------------------


def compile_switch_config(
    derived_setting: dict[str, Any],
    device_config: dict[str, Any],
    site_vars: dict[str, Any],
) -> dict[str, Any]:
    """Compile effective switch configuration.

    Mist merge order: derived_setting (site-level, already template-merged) → device.

    Returns compiled config dict with resolved variables.
    """
    port_usages = {
        **dict(derived_setting.get("port_usages") or {}),
        **dict(device_config.get("port_usages") or {}),
    }
    networks = resolve_vars(
        {
            **dict(derived_setting.get("networks") or {}),
            **dict(device_config.get("networks") or {}),
        },
        site_vars,
    )
    dhcpd_config = resolve_vars(
        {
            **dict(derived_setting.get("dhcpd_config") or {}),
            **dict(device_config.get("dhcpd_config") or {}),
        },
        site_vars,
    )
    # Port config: site setting provides the base, device overrides per-port
    port_config = {
        **dict(derived_setting.get("port_config") or {}),
        **dict(device_config.get("port_config") or {}),
    }

    return {
        "port_usages": port_usages,
        "networks": networks,
        "dhcpd_config": dhcpd_config,
        "port_config": port_config,
    }


# ---------------------------------------------------------------------------
# 5. compile_gateway_config
# ---------------------------------------------------------------------------


def _deep_merge_port_config(*configs: dict[str, Any] | None) -> dict[str, Any]:
    """Deep merge port_config dicts, per port.  Later configs win on field conflicts."""
    merged: dict[str, dict[str, Any]] = {}
    for cfg in configs:
        if not cfg:
            continue
        for port, port_cfg in cfg.items():
            if port in merged:
                merged[port] = {**merged[port], **port_cfg}
            else:
                merged[port] = dict(port_cfg)
    return merged


def compile_gateway_config(
    gw_template: dict[str, Any],
    device_profile: dict[str, Any],
    device_config: dict[str, Any],
    site_vars: dict[str, Any],
) -> dict[str, Any]:
    """Compile effective gateway configuration.

    Mist merge order: gw_template → device_profile → device_config.
    - port_usages, networks, dhcpd_config: shallow merge (later wins)
    - port_config: deep merge per port (template fields preserved, device overrides)
    - ip_configs: shallow merge (gw_template + device)

    Returns compiled config dict with resolved variables.
    """
    port_usages = {
        **dict(gw_template.get("port_usages") or {}),
        **dict(device_profile.get("port_usages") or {}),
        **dict(device_config.get("port_usages") or {}),
    }
    networks = resolve_vars(
        {
            **dict(gw_template.get("networks") or {}),
            **dict(device_profile.get("networks") or {}),
            **dict(device_config.get("networks") or {}),
        },
        site_vars,
    )
    dhcpd_config = resolve_vars(
        {
            **dict(gw_template.get("dhcpd_config") or {}),
            **dict(device_profile.get("dhcpd_config") or {}),
            **dict(device_config.get("dhcpd_config") or {}),
        },
        site_vars,
    )
    port_config = _deep_merge_port_config(
        gw_template.get("port_config"),
        device_profile.get("port_config"),
        device_config.get("port_config"),
    )
    ip_configs = {
        **dict(gw_template.get("ip_configs") or {}),
        **dict(device_profile.get("ip_configs") or {}),
        **dict(device_config.get("ip_configs") or {}),
    }

    return {
        "port_usages": port_usages,
        "networks": networks,
        "dhcpd_config": dhcpd_config,
        "port_config": port_config,
        "ip_configs": ip_configs,
    }


# ---------------------------------------------------------------------------
# 6. _get_derived_site_setting
# ---------------------------------------------------------------------------


async def _get_derived_site_setting(site_id: str, org_id: str) -> dict[str, Any]:
    """Load derived site setting from backup (latest version)."""
    from app.modules.backup.models import BackupObject

    backup = (
        await BackupObject.find(
            {
                "object_type": "setting",
                "site_id": site_id,
                "org_id": org_id,
                "is_deleted": False,
            }
        )
        .sort([("version", -1)])
        .first_or_none()
    )
    return backup.configuration if backup else {}


# ---------------------------------------------------------------------------
# 7. _compile_site_devices
# ---------------------------------------------------------------------------


async def _compile_site_devices(
    state: dict[tuple, dict[str, Any]],
    site_id: str,
    org_id: str,
    template_changes: list[dict[str, str]],
) -> None:
    """Compile device configs for all devices in a site within the virtual state.

    Loads derived site setting and optional gateway template, then replaces
    each device's config with the compiled effective config.
    """
    from app.modules.backup.models import BackupObject

    # Load derived site setting (base for switches)
    derived_setting = await _get_derived_site_setting(site_id, org_id)

    # Apply template changes that affect this site
    for change in template_changes:
        assignment_field = change["assignment_field"]
        site_info = state.get(("info", site_id, None), {})
        if site_info.get(assignment_field) == change["template_id"]:
            # The template being changed is assigned to this site — load new version
            tmpl_key = (change["template_type"], None, change["template_id"])
            if tmpl_key in state:
                # Template is in virtual state (i.e. being modified by this session)
                tmpl_config = state[tmpl_key]
                if change["template_type"] == "networktemplates":
                    derived_setting = {**derived_setting, **tmpl_config}

    site_vars: dict[str, Any] = {str(k): str(v) for k, v in derived_setting.get("vars", {}).items()}

    # Load gateway template if any site device is a gateway
    gw_template_id = state.get(("info", site_id, None), {}).get("gatewaytemplate_id")
    gw_template: dict[str, Any] = {}
    if gw_template_id:
        gw_key = ("gatewaytemplates", None, gw_template_id)
        if gw_key in state:
            gw_template = state[gw_key]
        else:
            backup = (
                await BackupObject.find(
                    {"object_type": "gatewaytemplates", "object_id": gw_template_id, "is_deleted": False}
                )
                .sort([("version", -1)])
                .first_or_none()
            )
            gw_template = backup.configuration if backup else {}

    # Compile each device
    for key, config in list(state.items()):
        obj_type, obj_site, obj_id = key
        if obj_type != "devices" or obj_site != site_id:
            continue

        device_type = config.get("type", "")
        if device_type == "switch":
            compiled = compile_switch_config(derived_setting, config, site_vars)
        elif device_type == "gateway":
            # Load device profile if assigned
            device_profile: dict[str, Any] | None = None
            dp_id = config.get("deviceprofile_id")
            if dp_id:
                dp_backup = (
                    await BackupObject.find({"object_type": "deviceprofiles", "object_id": dp_id, "is_deleted": False})
                    .sort([("version", -1)])
                    .first_or_none()
                )
                if dp_backup:
                    device_profile = dp_backup.configuration

            compiled = compile_gateway_config(gw_template, device_profile or {}, config, site_vars)
        else:
            # APs: no port config to compile
            compiled = dict(config)

        state[key] = {**config, **compiled}


# ---------------------------------------------------------------------------
# 8. compile_virtual_state (main entry point)
# ---------------------------------------------------------------------------


async def compile_virtual_state(
    virtual_state: dict[tuple, dict[str, Any]],
    staged_writes: list[StagedWrite],
    org_id: str,
) -> tuple[dict[tuple, dict[str, Any]], list[str]]:
    """Compile effective per-device config for all affected sites.

    1. Deep copy state
    2. Detect template changes in staged writes
    3. Find all sites impacted by template changes
    4. Also collect explicit site_ids from staged writes
    5. Compile device configs per site

    Returns: (compiled_state, all_site_ids)
    """
    compiled = copy.deepcopy(virtual_state)

    # Collect sites that are directly affected (have device/setting writes)
    explicit_site_ids: set[str] = set()
    for write in staged_writes:
        if write.site_id:
            explicit_site_ids.add(write.site_id)

    # Detect template changes
    template_changes = detect_template_changes(staged_writes)

    # Find sites impacted by template changes
    template_site_ids: set[str] = set()
    for change in template_changes:
        impacted = await find_impacted_sites(change["template_type"], change["template_id"], org_id)
        template_site_ids.update(impacted)

    all_site_ids = explicit_site_ids | template_site_ids

    # Compile per site
    for site_id in all_site_ids:
        await _compile_site_devices(compiled, site_id, org_id, template_changes)

    return compiled, list(all_site_ids)
