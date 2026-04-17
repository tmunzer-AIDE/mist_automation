"""
Config Compiler for the Digital Twin module.

Derives effective per-device configuration from the full Mist template
inheritance chain, and detects which sites are impacted by template changes.

Mist merge order:
  Switch:  network_template (with switch_matching.rules applied against the
           switch's name/model/role, first match wins)
           -> site_setting overlay
           -> device_profile
           -> device config (with port_config comma/range expansion)
  Gateway: gateway_template -> device_profile -> device config

Only fields in ``NETWORK_TEMPLATE_FIELDS`` flow through the template /
site_setting / device_profile overlays; device-level config is copied as-is.
Merge semantics are:

- ``port_config`` dicts are expanded (comma lists and Juniper range notation)
  and then merged per-port — inherited fields are preserved, overrides win.
- Other dicts shallow-merge (later overlay wins on conflict).
- Lists concatenate.
- Scalars overwrite.

Reference implementation: tmunzer/mistmcp::get_configuration_objects.py lines
1080-1310 (``_get_computed_device_configuration``, ``_process_switch_template``,
``_process_switch_rule``, ``_process_switch_rule_match``,
``_process_switch_interface``). This module adapts that logic to work on
backup-sourced inputs since we don't have access to Mist's live
``getSiteSettingDerived`` endpoint.
"""

from __future__ import annotations

import asyncio
import copy
import re
from typing import Any

import structlog

from app.modules.digital_twin.models import StagedWrite
from app.modules.digital_twin.services.state_resolver import is_twin_deleted

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Template type mapping
# ---------------------------------------------------------------------------

# Maps backup/API object_type → site info assignment field. Device profiles
# are a special case: they are assigned per-device (``device.deviceprofile_id``)
# rather than per-site, so ``find_impacted_sites`` branches on this type to
# scan backup devices rather than site info.
TEMPLATE_TYPE_TO_FIELD: dict[str, str] = {
    "sitetemplates": "sitetemplate_id",
    "networktemplates": "networktemplate_id",
    "rftemplates": "rftemplate_id",
    "gatewaytemplates": "gatewaytemplate_id",
    "aptemplates": "aptemplate_id",
    "deviceprofiles": "deviceprofile_id",
}

# Regex to extract (template_type, template_id) from Mist org-level API paths
# Matches: /api/v1/orgs/<org_id>/<template_type>/<template_id>
_TEMPLATE_PATH_RE = re.compile(
    r"/orgs/[^/]+/(" + "|".join(re.escape(t) for t in TEMPLATE_TYPE_TO_FIELD) + r")/([^/]+)$"
)

# ---------------------------------------------------------------------------
# Field allowlists — copied verbatim from mistmcp reference
# ---------------------------------------------------------------------------

# Fields that flow through the network_template / site_setting / device_profile
# overlay chain for both switches and gateways. Fields outside this set are
# dropped during template-side merges (device-level config is not filtered).
NETWORK_TEMPLATE_FIELDS: frozenset[str] = frozenset(
    {
        "auto_upgrade_linecard",
        "acl_policies",
        "acl_tags",
        "additional_config_cmds",
        "dhcp_snooping",
        "disabled_system_defined_port_usages",
        "dns_servers",
        "dns_suffix",
        "extra_routes",
        "extra_routes6",
        "fips_enabled",
        "id",
        "mist_nac",
        "networks",
        "ntp_servers",
        "port_mirroring",
        "port_usages",
        "radius_config",
        "remote_syslog",
        "snmp_config",
        "routing_policies",
        "switch_matching",
        "switch_mgmt",
        "vrf_config",
        "vrf_instances",
    }
)

# Fields that flow through the gateway chain in addition to NETWORK_TEMPLATE_FIELDS.
# These are gateway-only fields (or fields that, unlike switches, ARE inherited
# from gateway templates):
#
# - ``ip_configs``: gateway-only concept (per-VLAN L3 interfaces)
# - ``port_config``: gateway templates define port layout at the top level, not
#   through switch_matching rules. Switches deliberately omit top-level
#   port_config inheritance; gateways depend on it.
# - ``dhcpd_config``: gateways run DHCP servers (switches don't).
GATEWAY_EXTRA_FIELDS: frozenset[str] = frozenset({"ip_configs", "port_config", "dhcpd_config"})


# ---------------------------------------------------------------------------
# Switch rule matching + port interface expansion — helpers ported from mistmcp
# ---------------------------------------------------------------------------


def _process_switch_interface(port_config: dict[str, Any]) -> dict[str, Any]:
    """Expand Juniper range and comma-list notation in a port_config dict.

    Mist switch templates and device configs can use compact keys:

    - ``"ge-0/0/1,ge-0/0/2"`` — comma list, each port gets the same value
    - ``"ge-0/0/1-10"`` — range notation, expands to ``ge-0/0/1`` .. ``ge-0/0/10``
    - ``"ge-0-1/0/0"`` — range on the fpc field
    - ``"ge-0/0-1/0"`` — range on the pic field

    This is a prerequisite for correct merging: a template range key and a
    per-device point key would never collide without expansion. Ported from
    ``_process_switch_interface`` in the mistmcp reference.
    """
    port_config_tmp: dict[str, Any] = {}
    for key, value in port_config.items():
        if "," in key:
            for k in (s.strip() for s in key.split(",")):
                port_config_tmp[k] = value
        else:
            port_config_tmp[key] = value

    expanded: dict[str, Any] = {}
    for key, value in port_config_tmp.items():
        # Juniper port name shape: <prefix>-<fpc>/<pic>/<port>. A range is
        # indicated by a "-" in exactly one of fpc / pic / port. Keys with
        # fewer than two "-" characters (e.g. plain "ge-0/0/1") are passed
        # through untouched.
        if key.count("-") > 1:
            try:
                prefix, interfaces = key.split("-", 1)
                fpc, pic, port = interfaces.split("/")
            except ValueError:
                expanded[key] = value
                continue
            # A reversed range (start > end) produces an empty Python `range`
            # and silently drops the key. Log and preserve the original key so
            # the misconfiguration is visible rather than causing missing
            # port_config entries downstream.
            if "-" in fpc:
                fpc_start, fpc_end = fpc.split("-")
                try:
                    start_i, end_i = int(fpc_start), int(fpc_end)
                except ValueError:
                    expanded[key] = value
                    continue
                if start_i > end_i:
                    logger.warning("port_range_reversed", key=key, axis="fpc")
                    expanded[key] = value
                    continue
                for fpc_num in range(start_i, end_i + 1):
                    expanded[f"{prefix}-{fpc_num}/{pic}/{port}"] = value
            elif "-" in pic:
                pic_start, pic_end = pic.split("-")
                try:
                    start_i, end_i = int(pic_start), int(pic_end)
                except ValueError:
                    expanded[key] = value
                    continue
                if start_i > end_i:
                    logger.warning("port_range_reversed", key=key, axis="pic")
                    expanded[key] = value
                    continue
                for pic_num in range(start_i, end_i + 1):
                    expanded[f"{prefix}-{fpc}/{pic_num}/{port}"] = value
            elif "-" in port:
                port_start, port_end = port.split("-")
                try:
                    start_i, end_i = int(port_start), int(port_end)
                except ValueError:
                    expanded[key] = value
                    continue
                if start_i > end_i:
                    logger.warning("port_range_reversed", key=key, axis="port")
                    expanded[key] = value
                    continue
                for port_num in range(start_i, end_i + 1):
                    expanded[f"{prefix}-{fpc}/{pic}/{port_num}"] = value
            else:
                expanded[key] = value
        else:
            expanded[key] = value
    return expanded


def _match_switch_condition(switch_value: str, match_key: str, match_value: str) -> bool:
    """Evaluate a single ``match_*`` condition from a switch_matching rule.

    Supports two forms:

    - ``match_name`` / ``match_model`` / ``match_role`` — case-insensitive
      exact equality against the switch attribute
    - ``match_name[0:3]`` — substring slice of the switch attribute, then
      case-insensitive equality

    Returns False on out-of-range slices or malformed keys. Ported from
    ``_process_switch_rule_match`` in the mistmcp reference.
    """
    if ":" in match_key:
        try:
            bracket = match_key.replace("]", "").split("[", 1)[1]
            match_start, match_stop = bracket.split(":")
            start_i, stop_i = int(match_start), int(match_stop)
        except (ValueError, IndexError):
            return False
        if len(switch_value) <= stop_i:
            return False
        return switch_value[start_i:stop_i].lower() == match_value.lower()
    return switch_value.lower() == match_value.lower()


def _merge_template_field(data: dict[str, Any], key: str, value: Any) -> None:
    """Merge a single template field into ``data`` in place.

    - ``port_config`` is expanded via ``_process_switch_interface`` and then
      merged **per-port, per-field** so a sparse device override (e.g.
      ``{"poe_disabled": true}``) preserves the inherited ``usage`` /
      ``vlan_id`` from the template rule. This deviates from the mistmcp
      reference which does shallow per-port replacement; deep per-port merge
      matches Mist's actual behaviour where device configs store deltas on
      top of the inherited profile.
    - Other dicts shallow-merge (later overlay wins on conflict).
    - Lists concatenate.
    - Scalars overwrite.

    Centralizes the merge rules used across every overlay stage (network
    template, site setting, device profile, device config).
    """
    if key == "port_config":
        expanded = _process_switch_interface(value) if isinstance(value, dict) else value
        if isinstance(expanded, dict):
            existing_ports = data.get(key) or {}
            merged_ports: dict[str, Any] = dict(existing_ports)
            for port, port_cfg in expanded.items():
                existing_cfg = merged_ports.get(port)
                if isinstance(existing_cfg, dict) and isinstance(port_cfg, dict):
                    merged_ports[port] = {**existing_cfg, **port_cfg}
                else:
                    merged_ports[port] = port_cfg
            data[key] = merged_ports
        else:
            data[key] = expanded
        return
    existing = data.get(key)
    if isinstance(value, dict) and isinstance(existing, dict):
        data[key] = {**existing, **value}
    elif isinstance(value, list) and isinstance(existing, list):
        data[key] = existing + value
    else:
        data[key] = value


def _apply_switch_rules(
    rules: list[dict[str, Any]],
    switch_name: str,
    switch_model: str,
    switch_role: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Apply the first matching switch_matching rule to ``data``.

    Iterates ``rules`` in order. For each rule, collects enabled conditions
    (``match_name*``, ``match_model*``, ``match_role``) and requires every
    enabled condition to pass. When a rule matches, its remaining fields
    (minus ``name`` and the ``match_*`` keys) are merged into ``data`` via
    :func:`_merge_template_field`, and the function returns immediately —
    **first match wins**. A rule with no enabled conditions matches
    unconditionally.

    Ported from ``_process_switch_rule`` in the mistmcp reference.
    """
    for rule in rules:
        rule_body = dict(rule)
        rule_body.pop("name", None)

        name_enabled = model_enabled = role_enabled = False
        name_ok = model_ok = role_ok = False

        for k, v in rule.items():
            if k.startswith("match_name"):
                name_enabled = True
                rule_body.pop(k, None)
                name_ok = _match_switch_condition(switch_name, k, v)
            elif k.startswith("match_model"):
                model_enabled = True
                rule_body.pop(k, None)
                model_ok = _match_switch_condition(switch_model, k, v)
            elif k == "match_role":
                role_enabled = True
                rule_body.pop(k, None)
                role_ok = _match_switch_condition(switch_role, k, v)

        if (not name_enabled or name_ok) and (not model_enabled or model_ok) and (not role_enabled or role_ok):
            for key, value in rule_body.items():
                _merge_template_field(data, key, value)
            return data
    return data


def _apply_network_template(
    template: dict[str, Any],
    switch_name: str,
    switch_model: str,
    switch_role: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Merge a network template (or site_setting / device_profile) into ``data``.

    Only keys in :data:`NETWORK_TEMPLATE_FIELDS` are copied through. The
    ``switch_matching`` key is special-cased: when ``enable`` is truthy, its
    ``rules`` list is evaluated against the switch's attributes and the first
    matching rule is applied via :func:`_apply_switch_rules`. The ``name``
    field is explicitly skipped (matches mistmcp behaviour).

    Ported from ``_process_switch_template`` in the mistmcp reference.
    """
    for key, value in template.items():
        if key not in NETWORK_TEMPLATE_FIELDS or key == "name":
            continue
        if key == "switch_matching" and isinstance(value, dict) and value.get("enable"):
            _apply_switch_rules(
                value.get("rules") or [],
                switch_name,
                switch_model,
                switch_role,
                data,
            )
            continue
        _merge_template_field(data, key, value)
    return data


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
    """Find all sites where the given template/profile is assigned.

    For site-level assignments (``sitetemplates``, ``networktemplates``,
    ``rftemplates``, ``gatewaytemplates``, ``aptemplates``), scans
    ``BackupObject(type="info")`` and matches
    ``configuration.{assignment_field}``.

    For ``deviceprofiles`` — which are assigned per-device, not per-site —
    scans ``BackupObject(type="devices")`` for devices carrying
    ``configuration.deviceprofile_id == template_id`` and returns the
    distinct ``site_id`` values. This ensures that staged writes to a
    device profile re-compile every site whose devices consume it.

    Returns a list of site_ids.
    """
    from app.modules.backup.models import BackupObject

    assignment_field = TEMPLATE_TYPE_TO_FIELD.get(template_type)
    if not assignment_field:
        logger.warning("find_impacted_sites_unknown_type", template_type=template_type)
        return []

    if template_type == "deviceprofiles":
        # Device profiles live on individual devices, not on site info.
        pipeline: list[dict[str, Any]] = [
            {
                "$match": {
                    "object_type": "devices",
                    "org_id": org_id,
                    "is_deleted": False,
                    "configuration.deviceprofile_id": template_id,
                }
            },
            {"$group": {"_id": "$site_id"}},
        ]
        site_ids: list[str] = []
        async for doc in BackupObject.aggregate(pipeline):
            sid = doc.get("_id")
            if sid:
                site_ids.append(sid)
        return site_ids

    # Site-level template assignments flow via site info.
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

    site_ids = []
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
# 4. compile_switch_config — new 5-input chain
# ---------------------------------------------------------------------------


def _apply_device_config(
    device_config: dict[str, Any],
    data: dict[str, Any],
) -> dict[str, Any]:
    """Merge the device-level raw config on top of ``data``.

    Device-level config is **not filtered** by NETWORK_TEMPLATE_FIELDS — every
    field the user set on the device flows through. ``port_config`` is still
    expanded via :func:`_process_switch_interface` so comma-list and range
    notation on the device-level match what the template provides. Mirrors
    the final ``for key, value in device_data.data.items()`` loop in the
    mistmcp reference at lines 1124-1137.
    """
    for key, value in device_config.items():
        _merge_template_field(data, key, value)
    return data


def compile_switch_config(
    network_template: dict[str, Any] | None,
    site_setting: dict[str, Any],
    device_profile: dict[str, Any] | None,
    device_config: dict[str, Any],
    site_vars: dict[str, Any],
) -> dict[str, Any]:
    """Compile effective switch configuration using Mist's real derivation order.

    Merge chain (top to bottom, later wins on conflict):

    1. ``network_template`` — filtered by :data:`NETWORK_TEMPLATE_FIELDS`, with
       ``switch_matching.rules`` evaluated against the switch's
       ``name`` / ``model`` / ``role``. First matching rule wins.
    2. ``site_setting`` — overlayed via the same filter (may also carry its own
       ``switch_matching`` block with site-level rules).
    3. ``device_profile`` — overlayed via the same filter.
    4. ``device_config`` — copied as-is (no field filter).

    ``port_config`` flows only via switch_matching rules and device_config —
    top-level template ``port_config`` is filtered out because it's not in
    :data:`NETWORK_TEMPLATE_FIELDS`. This matches the mistmcp reference.

    Variables are resolved against ``site_vars`` at the end so any
    ``{{site_vlan}}`` / ``{{site_name}}`` placeholders in merged fields are
    substituted once, after every overlay has landed.

    Reference: ``_get_computed_device_configuration`` +
    ``_process_switch_template`` in mistmcp lines 1103-1208.
    """
    data: dict[str, Any] = {}
    switch_name = str(device_config.get("name", ""))
    switch_model = str(device_config.get("model", ""))
    switch_role = str(device_config.get("role", ""))

    if network_template:
        _apply_network_template(network_template, switch_name, switch_model, switch_role, data)
    if site_setting:
        _apply_network_template(site_setting, switch_name, switch_model, switch_role, data)
    if device_profile:
        _apply_network_template(device_profile, switch_name, switch_model, switch_role, data)

    _apply_device_config(device_config, data)

    return resolve_vars(data, site_vars)


# ---------------------------------------------------------------------------
# 5. compile_gateway_config — filter-based chain
# ---------------------------------------------------------------------------


def _deep_merge_port_config(*configs: dict[str, Any] | None) -> dict[str, Any]:
    """Deep merge port_config dicts, per port.  Later configs win on field conflicts.

    Retained for backward compatibility with callers that still build
    compiled port_config incrementally. New code should use
    :func:`_merge_template_field` which handles the ``port_config`` special
    case (expansion + shallow per-port merge) and all other field types.
    """
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

    Merge chain: ``gw_template -> device_profile -> device_config``. Template
    and profile overlays are filtered by :data:`NETWORK_TEMPLATE_FIELDS` plus
    :data:`GATEWAY_EXTRA_FIELDS` (which carries ``ip_configs``, gateway-only).
    Device-level config is copied through without filtering.

    ``port_config`` is handled via :func:`_merge_template_field` which expands
    comma-list and range notation, same as switches.
    """
    data: dict[str, Any] = {}
    allowed = NETWORK_TEMPLATE_FIELDS | GATEWAY_EXTRA_FIELDS

    for key, value in (gw_template or {}).items():
        if key in allowed and key != "name":
            _merge_template_field(data, key, value)

    for key, value in (device_profile or {}).items():
        if key in allowed and key != "name":
            _merge_template_field(data, key, value)

    _apply_device_config(device_config, data)

    return resolve_vars(data, site_vars)


# ---------------------------------------------------------------------------
# 6. Site / template / device-profile loaders
# ---------------------------------------------------------------------------


async def _get_site_setting(site_id: str, org_id: str) -> dict[str, Any]:
    """Load the site's raw settings singleton from backup.

    This is the *raw* ``BackupObject(type="settings", site_id=...)`` — the
    site's own settings document. It does NOT contain the network template;
    the template must be loaded separately via :func:`_load_template` and
    layered on top by the caller.
    """
    from app.modules.backup.models import BackupObject

    backup = (
        await BackupObject.find(
            {
                "object_type": "settings",
                "site_id": site_id,
                "org_id": org_id,
                "is_deleted": False,
            }
        )
        .sort([("version", -1)])
        .first_or_none()
    )
    return backup.configuration if backup else {}


async def _get_site_info(site_id: str, org_id: str, state: dict[tuple, dict[str, Any]]) -> dict[str, Any]:
    """Load site info from virtual state with backward-compatible fallbacks.

    Mist site identity/template assignments can appear in backups as:
    - object_type="info", site-scoped singleton
    - object_type="site", legacy site-scoped singleton
    - object_type="sites", org-scoped list entries keyed by object_id
    """
    from app.modules.backup.models import BackupObject

    def _doc_config(doc: Any) -> dict[str, Any]:
        if not doc:
            return {}
        if isinstance(doc, dict):
            cfg = doc.get("configuration")
            return cfg if isinstance(cfg, dict) else {}
        cfg = getattr(doc, "configuration", None)
        return cfg if isinstance(cfg, dict) else {}

    site_info = state.get(("info", site_id, None), {})
    if site_info and not is_twin_deleted(site_info):
        return site_info

    info_backup = (
        await BackupObject.find(
            {
                "object_type": "info",
                "site_id": site_id,
                "org_id": org_id,
                "is_deleted": False,
            }
        )
        .sort([("version", -1)])
        .first_or_none()
    )
    info_cfg = _doc_config(info_backup)
    if info_cfg:
        return info_cfg

    legacy_site_backup = (
        await BackupObject.find(
            {
                "object_type": "site",
                "object_id": site_id,
                "org_id": org_id,
                "is_deleted": False,
            }
        )
        .sort([("version", -1)])
        .first_or_none()
    )
    legacy_cfg = _doc_config(legacy_site_backup)
    if legacy_cfg:
        return legacy_cfg

    org_sites_backup = (
        await BackupObject.find(
            {
                "object_type": "sites",
                "object_id": site_id,
                "org_id": org_id,
                "is_deleted": False,
            }
        )
        .sort([("version", -1)])
        .first_or_none()
    )
    return _doc_config(org_sites_backup)


# Module-level cache shape for template/profile pre-loading. Keyed by
# ``(object_type, object_id)`` with ``None`` used as a negative cache entry.
CompileCache = dict[tuple[str, str], dict[str, Any] | None]


async def _load_template(
    state: dict[tuple, dict[str, Any]],
    object_type: str,
    template_id: str | None,
    org_id: str,
    cache: CompileCache | None = None,
) -> dict[str, Any]:
    """Resolve a template (network/gateway/etc.) for compilation.

    Resolution order:

    1. If the virtual state carries a staged write for this template
       (``("{object_type}", None, template_id)``), return that. Deletion
       sentinel -> empty dict.
    2. If ``cache`` is provided and has an entry for the key, return it.
       Negative cache entries (``None``) return an empty dict.
    3. Otherwise query the latest backup and (if cache is provided) store the
       result for reuse.

    Passing ``template_id=None`` or an empty string returns ``{}``.
    """
    if not template_id:
        return {}

    tmpl_key = (object_type, None, template_id)
    if tmpl_key in state:
        staged = state[tmpl_key]
        return {} if is_twin_deleted(staged) else staged

    cache_key = (object_type, template_id)
    if cache is not None and cache_key in cache:
        cached = cache[cache_key]
        # Deep copy: downstream merges mutate nested dicts (port_config,
        # networks). A shallow copy shares nested refs with the cache entry,
        # which poisons subsequent baseline-vs-predicted compares when the
        # same template is loaded for multiple sites.
        return copy.deepcopy(cached) if cached else {}

    from app.modules.backup.models import BackupObject

    backup = (
        await BackupObject.find(
            {
                "object_type": object_type,
                "object_id": template_id,
                "org_id": org_id,
                "is_deleted": False,
            }
        )
        .sort([("version", -1)])
        .first_or_none()
    )
    config = copy.deepcopy(backup.configuration) if backup else None
    if cache is not None:
        cache[cache_key] = config
    return copy.deepcopy(config) if config else {}


async def _load_device_profile(
    device_config: dict[str, Any],
    org_id: str,
    state: dict[tuple, dict[str, Any]],
    cache: CompileCache | None = None,
) -> dict[str, Any] | None:
    """Resolve the device profile referenced by a device config, if any.

    Returns ``None`` when the device has no ``deviceprofile_id`` or the
    referenced profile can't be found. Same state -> cache -> backup
    resolution as :func:`_load_template`.
    """
    dp_id = device_config.get("deviceprofile_id")
    if not dp_id:
        return None

    dp_key = ("deviceprofiles", None, dp_id)
    if dp_key in state:
        staged = state[dp_key]
        return None if is_twin_deleted(staged) else staged

    cache_key = ("deviceprofiles", dp_id)
    if cache is not None and cache_key in cache:
        cached = cache[cache_key]
        return copy.deepcopy(cached) if cached else None

    from app.modules.backup.models import BackupObject

    backup = (
        await BackupObject.find(
            {
                "object_type": "deviceprofiles",
                "object_id": dp_id,
                "org_id": org_id,
                "is_deleted": False,
            }
        )
        .sort([("version", -1)])
        .first_or_none()
    )
    config = copy.deepcopy(backup.configuration) if backup else None
    if cache is not None:
        cache[cache_key] = config
    return copy.deepcopy(config) if config else None


# ---------------------------------------------------------------------------
# 7. _compile_site_devices
# ---------------------------------------------------------------------------


async def _compile_site_devices(
    state: dict[tuple, dict[str, Any]],
    site_id: str,
    org_id: str,
    template_changes: list[dict[str, str]],
    cache: CompileCache | None = None,
) -> None:
    """Compile effective config for every device in a site into ``state``.

    For each device, loads the appropriate chain of overlays from backup
    (respecting staged writes in ``state``) and calls
    :func:`compile_switch_config` or :func:`compile_gateway_config` to
    produce the effective config. The compiled result replaces the raw
    backup entry at ``state[("devices", site_id, device_id)]``.

    Chain by device type:

    - Switch: network_template (from ``site_info.networktemplate_id``) ->
      site_setting -> device_profile -> device_config
    - Gateway: gateway_template (from ``site_info.gatewaytemplate_id``) ->
      device_profile -> device_config
    - AP: pass-through (no compilation)

    The optional ``cache`` short-circuits repeated backup queries for
    templates/profiles shared across sites — used by
    :func:`compile_base_state` for bulk baseline compilation.
    """
    from app.modules.digital_twin.services.state_resolver import load_all_objects_of_type

    # ── Site context ──────────────────────────────────────────────────────
    site_info = await _get_site_info(site_id, org_id, state)
    site_setting = await _get_site_setting(site_id, org_id)

    # Layer any staged /sites/{site_id}/setting write on top of the raw
    # backup site setting. Shallow merge matches the behaviour the checks
    # (and test suite) historically assume.
    staged_site_setting = state.get(("settings", site_id, None), {})
    if staged_site_setting and not is_twin_deleted(staged_site_setting):
        site_setting = {**site_setting, **staged_site_setting}

    # Templates are loaded via _load_template, which automatically reads the
    # staged version from ``state`` when a template-targeting write exists.
    # The old ``template_changes`` special-case block is no longer needed
    # because the staged-in-state path handles it transparently.
    _ = template_changes  # preserved for API compatibility; used by _load_template via state
    networktemplate_id = site_info.get("networktemplate_id")
    gatewaytemplate_id = site_info.get("gatewaytemplate_id")
    network_template = await _load_template(state, "networktemplates", networktemplate_id, org_id, cache=cache)
    gw_template = await _load_template(state, "gatewaytemplates", gatewaytemplate_id, org_id, cache=cache)

    site_vars: dict[str, Any] = {str(k): str(v) for k, v in site_setting.get("vars", {}).items()}

    # ── Device set ────────────────────────────────────────────────────────
    # Mirror the old behaviour: compile every backed-up device for the site,
    # overlay staged device writes, and include POST-created devices that
    # only exist in virtual state.
    devices_to_compile: dict[tuple, dict[str, Any]] = {}

    backup_devices = await load_all_objects_of_type(org_id, "devices", site_id=site_id)
    for device_config in backup_devices:
        dev_id = device_config.get("id")
        if not dev_id:
            continue
        key = ("devices", site_id, dev_id)
        staged_config = state.get(key)
        if staged_config and is_twin_deleted(staged_config):
            continue
        devices_to_compile[key] = staged_config or device_config

    for key, config in list(state.items()):
        obj_type, obj_site, _obj_id = key
        if obj_type != "devices" or obj_site != site_id:
            continue
        if is_twin_deleted(config):
            continue
        devices_to_compile[key] = config

    # ── Compile ───────────────────────────────────────────────────────────
    for key, config in devices_to_compile.items():
        device_type = config.get("type", "")
        device_profile = await _load_device_profile(config, org_id, state, cache=cache)

        if device_type == "switch":
            compiled = compile_switch_config(
                network_template=network_template,
                site_setting=site_setting,
                device_profile=device_profile,
                device_config=config,
                site_vars=site_vars,
            )
        elif device_type == "gateway":
            compiled = compile_gateway_config(gw_template, device_profile or {}, config, site_vars)
        else:
            # APs: pass through — no template-level compilation happens.
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


# ---------------------------------------------------------------------------
# 9. compile_base_state
# ---------------------------------------------------------------------------


async def _preload_compile_cache(
    affected_sites: list[str],
    org_id: str,
) -> CompileCache:
    """Load every template and device profile referenced by the affected sites.

    Runs a first pass over the affected sites to discover which
    networktemplates / gatewaytemplates / deviceprofiles are referenced by
    ``site_info`` and the per-site device list, then fans out backup queries
    in parallel to populate a shared cache. Subsequent
    :func:`_compile_site_devices` calls short-circuit via
    :func:`_load_template` / :func:`_load_device_profile` instead of
    re-querying backup for templates already loaded by a sibling site.

    Returns a :data:`CompileCache` with an entry for every referenced
    ``(object_type, object_id)``. Missing templates are cached as ``None``
    (negative cache) so a subsequent lookup still short-circuits instead of
    retrying the backup query.
    """
    from app.modules.digital_twin.services.state_resolver import load_all_objects_of_type

    cache: CompileCache = {}
    if not affected_sites:
        return cache

    async def _site_refs(
        site_id: str,
    ) -> tuple[str | None, str | None, set[str]]:
        info = await _get_site_info(site_id, org_id, state={})
        nt_id = info.get("networktemplate_id")
        gt_id = info.get("gatewaytemplate_id")
        devices = await load_all_objects_of_type(org_id, "devices", site_id=site_id)
        dp_ids = {(d.get("deviceprofile_id") or "") for d in devices if d.get("deviceprofile_id")}
        return nt_id, gt_id, dp_ids

    per_site = await asyncio.gather(*[_site_refs(sid) for sid in affected_sites])

    nt_ids = {nt for nt, _, _ in per_site if nt}
    gt_ids = {gt for _, gt, _ in per_site if gt}
    dp_ids: set[str] = set()
    for _, _, dps in per_site:
        dp_ids |= dps

    from app.modules.backup.models import BackupObject

    async def _load_one(obj_type: str, obj_id: str) -> None:
        backup = (
            await BackupObject.find(
                {
                    "object_type": obj_type,
                    "object_id": obj_id,
                    "org_id": org_id,
                    "is_deleted": False,
                }
            )
            .sort([("version", -1)])
            .first_or_none()
        )
        cache[(obj_type, obj_id)] = dict(backup.configuration) if backup else None

    tasks: list[Any] = []
    tasks.extend(_load_one("networktemplates", i) for i in nt_ids)
    tasks.extend(_load_one("gatewaytemplates", i) for i in gt_ids)
    tasks.extend(_load_one("deviceprofiles", i) for i in dp_ids)
    if tasks:
        await asyncio.gather(*tasks)

    return cache


async def compile_base_state(
    affected_sites: list[str],
    org_id: str,
) -> dict[tuple, dict[str, Any]]:
    """Build a virtual_state dict of compiled per-device configs for the baseline.

    Used by the Twin to produce a baseline snapshot whose device configs are
    template-merged the same way the predicted snapshot is. Without this,
    the baseline reads raw backup device configs while the predicted path
    runs through :func:`compile_virtual_state`, producing asymmetric
    ``port_config`` / ``port_usages`` data that silently defeats diff-based
    port checks.

    Runs :func:`_preload_compile_cache` first so every network template,
    gateway template, and device profile referenced by the affected sites
    is fetched from backup exactly once, then reused across per-site
    compile calls.
    """
    state: dict[tuple, dict[str, Any]] = {}
    if not affected_sites:
        return state
    cache = await _preload_compile_cache(affected_sites, org_id)
    for site_id in affected_sites:
        await _compile_site_devices(state, site_id, org_id, [], cache=cache)
    return state
