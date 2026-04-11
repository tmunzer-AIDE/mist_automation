"""
Site snapshot: dataclasses + builders for the new check engine.

Provides:
- DeviceSnapshot / LiveSiteData / SiteSnapshot dataclasses
- fetch_live_data() — one org-level API call for LLDP, port status, client counts
- build_site_snapshot() — assemble snapshot from backup + live data + optional overrides
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.modules.digital_twin.services.state_resolver import (
    StateKey,
    canonicalize_object_type,
    load_all_objects_of_type,
)

logger = structlog.get_logger(__name__)

_DELETED_SENTINEL_KEY = "__twin_deleted__"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DeviceSnapshot:
    device_id: str
    mac: str
    name: str
    type: str  # "ap" | "switch" | "gateway"
    model: str
    port_config: dict[str, dict[str, Any]]  # port_name -> {usage, vlan_id, ...}
    ip_config: dict[str, dict[str, Any]]  # network_name -> {ip, netmask, type}
    dhcpd_config: dict[str, Any]
    oob_ip_config: dict[str, Any] | None = None
    port_usages: dict[str, dict[str, Any]] | None = None  # device-level overrides
    ospf_config: dict[str, Any] | None = None
    bgp_config: dict[str, Any] | None = None
    extra_routes: list[dict[str, Any]] | None = None
    stp_config: dict[str, Any] | None = None


@dataclass
class LiveSiteData:
    lldp_neighbors: dict[str, dict[str, str]]  # device_mac -> {port_id -> neighbor_mac}
    port_status: dict[str, dict[str, bool]]  # device_mac -> {port_id -> up/down}
    ap_clients: dict[str, int]  # device_id -> wireless client count
    port_devices: dict[str, dict[str, str]]  # device_mac -> {port_id -> connected_mac}
    ospf_peers: dict[str, list[dict]] = field(default_factory=dict)
    bgp_peers: dict[str, list[dict]] = field(default_factory=dict)


@dataclass
class SiteSnapshot:
    site_id: str
    site_name: str
    site_setting: dict[str, Any]
    networks: dict[str, dict[str, Any]]  # network_id -> config
    wlans: dict[str, dict[str, Any]]  # wlan_id -> config
    devices: dict[str, DeviceSnapshot]  # device_id -> compiled device
    port_usages: dict[str, dict[str, Any]]  # profile_name -> profile config
    lldp_neighbors: dict[str, dict[str, str]]
    port_status: dict[str, dict[str, bool]]
    ap_clients: dict[str, int]
    port_devices: dict[str, dict[str, str]]
    ospf_peers: dict[str, list[dict]] = field(default_factory=dict)
    bgp_peers: dict[str, list[dict]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Live data extraction helpers
# ---------------------------------------------------------------------------


def _extract_lldp_from_stats(device_stats: dict[str, Any]) -> dict[str, str]:
    """Extract LLDP neighbor map from a device stats payload.

    Mist ``clients[]`` entries with ``source == "lldp"`` have a ``port_ids``
    field (plural, list of port names) -- NOT ``port_id`` (singular).

    Returns:
        dict mapping port_id -> neighbor_mac
    """
    neighbors: dict[str, str] = {}
    for client in device_stats.get("clients", []):
        if client.get("source") == "lldp":
            neighbor_mac = client.get("mac", "")
            if not neighbor_mac:
                continue
            for port_id in client.get("port_ids", []):
                if port_id:
                    neighbors[port_id] = neighbor_mac
    return neighbors


def _extract_port_status(device_stats: dict[str, Any]) -> dict[str, bool]:
    """Extract port up/down from ``if_stat`` field.

    Returns:
        dict mapping port_id -> True (up) / False (down)
    """
    result: dict[str, bool] = {}
    if_stat = device_stats.get("if_stat")
    if not if_stat or not isinstance(if_stat, dict):
        return result
    for port_id, stat in if_stat.items():
        if isinstance(stat, dict):
            result[port_id] = stat.get("up", False)
    return result


def _extract_client_count(device_stats: dict[str, Any]) -> int:
    """Extract wireless client count from ``clients_stats.total`` or ``num_clients``.

    Returns:
        Client count (0 when missing).
    """
    clients_stats = device_stats.get("clients_stats")
    if isinstance(clients_stats, dict):
        total = clients_stats.get("total")
        if total is not None:
            try:
                return int(total)
            except (TypeError, ValueError):
                pass

    num_clients = device_stats.get("num_clients", 0) or 0
    try:
        return int(num_clients)
    except (TypeError, ValueError):
        return 0


def _extract_port_devices(device_stats: dict[str, Any]) -> dict[str, str]:
    """Extract connected device MACs from LLDP clients, keyed by port.

    Unlike _extract_lldp_from_stats which is neighbour-centric, this maps
    every LLDP client to the port it occupies regardless of source.
    """
    result: dict[str, str] = {}
    for client in device_stats.get("clients", []):
        mac = client.get("mac", "")
        if not mac:
            continue
        for port_id in client.get("port_ids", []):
            if port_id:
                result[port_id] = mac
    return result


# ---------------------------------------------------------------------------
# fetch_live_data — single org-level API call
# ---------------------------------------------------------------------------


async def fetch_live_data(site_id: str, org_id: str) -> LiveSiteData:
    """Fetch live device stats for a site via one org-level API call.

    Falls back to an empty LiveSiteData on any error.
    """
    lldp_neighbors: dict[str, dict[str, str]] = {}
    port_status: dict[str, dict[str, bool]] = {}
    ap_clients: dict[str, int] = {}
    port_devices: dict[str, dict[str, str]] = {}

    try:
        import mistapi
        from mistapi.api.v1.orgs import stats as org_stats

        from app.services.mist_service_factory import create_mist_service

        mist = await create_mist_service()
        resp = await mistapi.arun(
            org_stats.listOrgDevicesStats,
            mist.get_session(),
            org_id,
            site_id=site_id,
            fields="*",
        )

        if resp.status_code != 200:
            logger.warning("live_data_api_error", site_id=site_id, status=resp.status_code)
            return LiveSiteData(
                lldp_neighbors=lldp_neighbors,
                port_status=port_status,
                ap_clients=ap_clients,
                port_devices=port_devices,
            )

        devices_list: list[dict[str, Any]] = []
        if resp.data:
            devices_list = resp.data if isinstance(resp.data, list) else resp.data.get("results", [])

        for device_stats in devices_list:
            mac = device_stats.get("mac", "")
            device_id = device_stats.get("id", "")

            if mac:
                neighbors = _extract_lldp_from_stats(device_stats)
                if neighbors:
                    lldp_neighbors[mac] = neighbors

                ports = _extract_port_status(device_stats)
                if ports:
                    port_status[mac] = ports

                pd = _extract_port_devices(device_stats)
                if pd:
                    port_devices[mac] = pd

            if device_id:
                count = _extract_client_count(device_stats)
                if count > 0:
                    ap_clients[device_id] = count

    except Exception:
        logger.exception("live_data_fetch_failed", site_id=site_id)

    return LiveSiteData(
        lldp_neighbors=lldp_neighbors,
        port_status=port_status,
        ap_clients=ap_clients,
        port_devices=port_devices,
    )


# ---------------------------------------------------------------------------
# Snapshot builder helpers
# ---------------------------------------------------------------------------


async def _load_site_objects(
    org_id: str,
    object_type: str,
    site_id: str | None = None,
) -> list[dict[str, Any]]:
    """Thin wrapper around state_resolver.load_all_objects_of_type()."""
    canonical_type = canonicalize_object_type(object_type) or object_type

    # For inherited networks, only include org-scoped networks. Without this
    # filter, site-scoped network backups from other sites pollute the snapshot.
    org_level_only = canonical_type == "networks" and site_id is None
    return await load_all_objects_of_type(
        org_id,
        canonical_type,
        site_id=site_id,
        org_level_only=org_level_only,
    )


def _build_device_snapshot(config: dict[str, Any]) -> DeviceSnapshot:
    """Convert a raw/compiled device config dict into a DeviceSnapshot.

    Handles both ``ip_config`` and ``ip_configs`` field names (Mist uses both).
    """
    # Mist uses ip_configs (plural) on gateways, ip_config on others
    ip_config = config.get("ip_config") or config.get("ip_configs") or {}

    return DeviceSnapshot(
        device_id=config.get("id", ""),
        mac=config.get("mac", ""),
        name=config.get("name", ""),
        type=config.get("type", ""),
        model=config.get("model", ""),
        port_config=config.get("port_config") or {},
        ip_config=ip_config,
        dhcpd_config=config.get("dhcpd_config") or {},
        oob_ip_config=config.get("oob_ip_config"),
        port_usages=config.get("port_usages"),
        ospf_config=config.get("ospf_config"),
        bgp_config=config.get("bgp_config"),
        extra_routes=config.get("extra_routes"),
        stp_config=config.get("stp_config"),
    )


# ---------------------------------------------------------------------------
# build_site_snapshot
# ---------------------------------------------------------------------------


async def build_site_snapshot(
    site_id: str,
    org_id: str,
    live_data: LiveSiteData,
    state_overrides: dict[StateKey, dict[str, Any]] | None = None,
) -> SiteSnapshot:
    """Assemble a full SiteSnapshot from backup data, live data, and optional overrides.

    Args:
        site_id: Mist site ID.
        org_id: Mist org ID.
        live_data: Pre-fetched live data from fetch_live_data().
        state_overrides: Optional dict of (object_type, site_id, object_id) -> config
            to replace backup values (e.g. from staged writes).
    """
    overrides = state_overrides or {}

    # Load all backup objects in parallel
    (
        site_devices,
        site_networks,
        org_networks,
        site_wlans,
        site_settings_list,
        site_info_list,
    ) = await asyncio.gather(
        _load_site_objects(org_id, "devices", site_id=site_id),
        _load_site_objects(org_id, "networks", site_id=site_id),
        _load_site_objects(org_id, "networks"),  # org-level (inherited)
        _load_site_objects(org_id, "wlans", site_id=site_id),
        _load_site_objects(org_id, "settings", site_id=site_id),
        _load_site_objects(org_id, "info", site_id=site_id),
    )

    def _iter_overrides(
        object_type: str,
        scope_site_id: str | None,
    ) -> list[tuple[str | None, dict[str, Any]]]:
        canonical_target = canonicalize_object_type(object_type) or object_type
        matched: list[tuple[str | None, dict[str, Any]]] = []

        for (ov_type, ov_site_id, ov_object_id), ov_config in overrides.items():
            canonical_override = canonicalize_object_type(ov_type) or ov_type
            if canonical_override != canonical_target:
                continue
            if ov_site_id != scope_site_id:
                continue
            matched.append((ov_object_id, ov_config))

        return matched

    # Apply state overrides to collection objects (devices/networks/wlans):
    # replace changed objects, append new ones (POST), and remove deleted ones.
    def _apply_overrides(
        objects: list[dict[str, Any]],
        object_type: str,
        scope_site_id: str | None,
    ) -> list[dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}
        for obj in objects:
            obj_id = obj.get("id")
            if obj_id:
                by_id[obj_id] = obj

        for ov_object_id, ov_config in _iter_overrides(object_type, scope_site_id):
            if not ov_object_id:
                continue
            if ov_config.get(_DELETED_SENTINEL_KEY):
                by_id.pop(ov_object_id, None)
            else:
                by_id[ov_object_id] = ov_config

        return list(by_id.values())

    # Apply state override to singleton objects (settings/info).
    def _apply_singleton_override(
        objects: list[dict[str, Any]],
        object_type: str,
        scope_site_id: str | None,
    ) -> list[dict[str, Any]]:
        singleton_override: dict[str, Any] | None = None

        for ov_object_id, ov_config in _iter_overrides(object_type, scope_site_id):
            if ov_object_id is None:
                singleton_override = ov_config

        if singleton_override is None:
            return objects
        if singleton_override.get(_DELETED_SENTINEL_KEY):
            return []
        return [singleton_override]

    site_devices = _apply_overrides(site_devices, "devices", site_id)
    site_networks = _apply_overrides(site_networks, "networks", site_id)
    org_networks = _apply_overrides(org_networks, "networks", None)
    site_wlans = _apply_overrides(site_wlans, "wlans", site_id)
    site_settings_list = _apply_singleton_override(site_settings_list, "settings", site_id)
    site_info_list = _apply_singleton_override(site_info_list, "info", site_id)

    # Extract site info
    site_name = ""
    if site_info_list:
        site_name = site_info_list[0].get("name", "")

    # Extract site setting
    site_setting = site_settings_list[0] if site_settings_list else {}

    # Extract port_usages from site_setting
    port_usages: dict[str, dict[str, Any]] = site_setting.get("port_usages") or {}

    # Build network map — org networks as base, site networks override
    networks: dict[str, dict[str, Any]] = {}
    for net in org_networks:
        net_id = net.get("id", "")
        if net_id:
            networks[net_id] = net
    for net in site_networks:
        net_id = net.get("id", "")
        if net_id:
            networks[net_id] = net

    # Build WLAN map
    wlans: dict[str, dict[str, Any]] = {}
    for wlan in site_wlans:
        wlan_id = wlan.get("id", "")
        if wlan_id:
            wlans[wlan_id] = wlan

    # Build device snapshots
    devices: dict[str, DeviceSnapshot] = {}
    for dev_config in site_devices:
        dev_id = dev_config.get("id", "")
        if dev_id:
            devices[dev_id] = _build_device_snapshot(dev_config)

    return SiteSnapshot(
        site_id=site_id,
        site_name=site_name,
        site_setting=site_setting,
        networks=networks,
        wlans=wlans,
        devices=devices,
        port_usages=port_usages,
        lldp_neighbors=live_data.lldp_neighbors,
        port_status=live_data.port_status,
        ap_clients=live_data.ap_clients,
        port_devices=live_data.port_devices,
        ospf_peers=live_data.ospf_peers,
        bgp_peers=live_data.bgp_peers,
    )
