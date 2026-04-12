"""Shared topology helpers used by site_graph and port_impact checks."""

from __future__ import annotations

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
