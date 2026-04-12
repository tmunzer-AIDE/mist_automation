"""Shared topology helpers used by site_graph and port_impact checks."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from app.modules.digital_twin.services.site_snapshot import SiteSnapshot


def normalize_port_id(port_id: str | None) -> str:
    """Normalize live-data port IDs to the physical key used in configs.

    Handles:
    - Trailing unit/pic suffixes: 'ge-0/0/1.0', 'xe-0/0/0:0' -> 'ge-0/0/1'
    - Missing prefixes (stacks): '0/0/1' -> 'ge-0/0/1' (common for Juniper)
    - Case sensitivity: 'GE-0/0/1' -> 'ge-0/0/1'
    """
    if not port_id:
        return ""

    normalized = str(port_id).strip().lower()
    if not normalized:
        return ""

    # Remove unit/logical port suffixes
    if normalized.endswith(".0"):
        normalized = normalized[:-2]
    if normalized.endswith(":0"):
        normalized = normalized[:-2]

    # Handle common Juniper shorthand from some LLDP sources (0/0/1 -> ge-0/0/1)
    if normalized.count("/") == 2 and not normalized[0].isalpha():
        normalized = f"ge-{normalized}"

    return normalized


def port_lookup_candidates(port_id: str | None) -> list[str]:
    """Return equivalent config-key forms for a port identifier."""
    if not port_id:
        return []

    normalized = normalize_port_id(port_id)
    raw = str(port_id).strip()
    candidates: list[str] = []

    for candidate in (raw, normalized, f"{normalized}.0", f"{normalized}:0"):
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    # Also try without prefix if config uses shorthand (rare but possible)
    if "-" in normalized:
        shorthand = normalized.split("-", 1)[1]
        if shorthand and shorthand not in candidates:
            candidates.append(shorthand)

    return candidates


def resolve_port_config_entry(
    port_config: dict[str, dict[str, Any]],
    port_id: str | None,
) -> dict[str, Any]:
    """Resolve a port_config entry using tolerant port-id matching."""
    for candidate in port_lookup_candidates(port_id):
        if candidate in port_config:
            return port_config.get(candidate) or {}
    return {}


def merge_infra_neighbor_ports(
    snapshot: SiteSnapshot,
    *,
    include_unknown_lldp_neighbors: bool = False,
) -> dict[str, dict[str, str]]:
    """Merge LLDP + port_devices into per-device neighbor ports.

    - ``port_devices`` contributes only infra-to-infra links.
    - ``lldp_neighbors`` overlays port_devices.
    - Unknown LLDP neighbor MACs can optionally be kept for backwards-compatible
      checks that report unknown neighbors.
    """
    known_macs = {dev.mac for dev in snapshot.devices.values() if dev.mac}
    merged: dict[str, dict[str, str]] = {}

    def _add(source_map: dict[str, dict[str, str]], *, require_known_neighbor: bool) -> None:
        for src_mac, port_map in source_map.items():
            if src_mac not in known_macs:
                continue
            for raw_port, neighbor_mac in port_map.items():
                if require_known_neighbor and neighbor_mac not in known_macs:
                    continue
                port = normalize_port_id(raw_port)
                if not port:
                    continue
                merged.setdefault(src_mac, {})[port] = neighbor_mac

    _add(snapshot.port_devices, require_known_neighbor=True)
    _add(snapshot.lldp_neighbors, require_known_neighbor=not include_unknown_lldp_neighbors)
    return merged


def resolve_vlan_id(value: Any, site_vars: dict[str, Any] | None = None) -> int | None:
    """Resolve VLAN IDs from literals or simple Jinja variables."""
    if value is None:
        return None
    if isinstance(value, int):
        return value

    vars_map = site_vars or {}
    str_val = str(value)

    if "{{" in str_val and "}}" in str_val:
        match = re.search(r"\{\{\s*([^}\s]+)\s*\}\}", str_val)
        if match:
            resolved = vars_map.get(match.group(1))
            if resolved is not None:
                try:
                    return int(resolved)
                except (TypeError, ValueError):
                    pass

    try:
        return int(str_val)
    except (TypeError, ValueError):
        return None


def build_network_name_to_vlan(
    networks: dict[str, dict[str, Any]],
    site_vars: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Map network name -> resolved VLAN ID from snapshot networks."""
    vars_map = site_vars or {}
    mapping: dict[str, int] = {}
    for cfg in networks.values():
        name = cfg.get("name")
        if not name:
            continue
        vlan_id = resolve_vlan_id(cfg.get("vlan_id"), vars_map)
        if vlan_id is not None:
            mapping[str(name)] = vlan_id
    return mapping


def _resolve_bool_var(value: Any, site_vars: dict[str, Any]) -> bool | None:
    """Resolve booleans from literals, strings, or simple Jinja variables."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if value is None:
        return None

    if isinstance(value, str):
        s = value.strip()
        if "{{" in s and "}}" in s:
            match = re.search(r"\{\{\s*([^}\s]+)\s*\}\}", s)
            if match:
                return _resolve_bool_var(site_vars.get(match.group(1)), site_vars)

        lowered = s.lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False

    return None


def _collect_explicit_profile_vlans(
    profile: dict[str, Any],
    network_name_to_vlan: dict[str, int],
    site_vars: dict[str, Any],
) -> set[int]:
    """Collect explicitly listed VLANs from profile fields."""
    vlans: set[int] = set()

    explicit_networks = profile.get("networks")
    if isinstance(explicit_networks, list):
        for net_name in explicit_networks:
            if isinstance(net_name, str) and net_name in network_name_to_vlan:
                vlans.add(network_name_to_vlan[net_name])
    elif isinstance(explicit_networks, dict):
        for net_name in explicit_networks:
            if isinstance(net_name, str) and net_name in network_name_to_vlan:
                vlans.add(network_name_to_vlan[net_name])

    port_network = profile.get("port_network")
    if isinstance(port_network, str) and port_network in network_name_to_vlan:
        vlans.add(network_name_to_vlan[port_network])

    vlan_id = resolve_vlan_id(profile.get("vlan_id"), site_vars)
    if vlan_id is not None:
        vlans.add(vlan_id)

    return vlans


def materialize_port_config_entry(
    port_cfg: dict[str, Any],
    port_usages: dict[str, dict[str, Any]],
    network_name_to_vlan: dict[str, int],
    site_vars: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Flatten profile attributes onto one interface and attach explicit VLANs.

    Output fields include:
    - every inherited profile attribute copied onto the interface config
    - ``resolved_vlan_ids``: sorted list of numeric VLAN IDs carried by port
    - ``resolved_mode``: effective forwarding mode after profile expansion
    """
    vars_map = site_vars or {}
    usage = str(port_cfg.get("usage", "") or "")

    profile: dict[str, Any] = {}
    if usage and usage not in {"trunk", "disabled"}:
        candidate = port_usages.get(usage)
        if isinstance(candidate, dict):
            profile = candidate

    materialized: dict[str, Any] = {}
    if profile:
        materialized.update(deepcopy(profile))
    materialized.update(deepcopy(port_cfg))
    if usage:
        materialized["usage"] = usage

    mode = str(materialized.get("mode", "") or "")
    if usage == "trunk":
        mode = "trunk"
    elif usage == "disabled":
        mode = "disabled"

    disabled = usage == "disabled" or bool(materialized.get("disabled"))
    vlans: set[int] = set()

    if not disabled:
        if mode == "trunk":
            all_networks = _resolve_bool_var(materialized.get("all_networks"), vars_map)
            if all_networks is None:
                all_networks = True
            if all_networks:
                vlans = set(network_name_to_vlan.values())
            else:
                vlans = _collect_explicit_profile_vlans(materialized, network_name_to_vlan, vars_map)
        else:
            vlans = _collect_explicit_profile_vlans(materialized, network_name_to_vlan, vars_map)

    materialized["resolved_mode"] = mode
    materialized["resolved_vlan_ids"] = sorted(vlans)
    return materialized


def materialize_device_port_config(
    port_config: dict[str, dict[str, Any]],
    site_port_usages: dict[str, dict[str, Any]],
    device_port_usages: dict[str, dict[str, Any]] | None,
    network_name_to_vlan: dict[str, int],
    site_vars: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Expand every interface with inherited profile fields and VLAN memberships."""
    effective_usages = dict(site_port_usages or {})
    if device_port_usages:
        effective_usages.update(device_port_usages)

    return {
        port_name: materialize_port_config_entry(
            cfg or {},
            effective_usages,
            network_name_to_vlan,
            site_vars,
        )
        for port_name, cfg in (port_config or {}).items()
    }
