"""Topology service adapter — bridges MistService to the topology builder."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

import mistapi
import structlog
from mistapi.api.v1.orgs import gatewaytemplates as org_gatewaytemplates
from mistapi.api.v1.orgs import networks as org_networks
from mistapi.api.v1.sites import alarms, devices, setting, stats

from app.modules.impact_analysis.topology.builder import bfs_path, build_topology
from app.modules.impact_analysis.topology.client import RawSiteData
from app.modules.impact_analysis.topology.models import SiteTopology
from app.services.mist_service_factory import create_mist_service

logger = structlog.get_logger(__name__)

# Per-site topology cache (TTL 30s)
_topology_cache: dict[str, tuple[float, SiteTopology]] = {}
_CACHE_TTL = 30.0


async def build_site_topology(site_id: str, org_id: str, pre_fetched: RawSiteData | None = None) -> SiteTopology | None:
    """Build site topology using MistService, with 30s TTL cache.

    Args:
        pre_fetched: Optional pre-fetched RawSiteData to avoid redundant API calls
                     (e.g. when the caller already has the data from another source).
    """
    # Check cache
    cached = _topology_cache.get(site_id)
    if cached and (time.monotonic() - cached[0]) < _CACHE_TTL:
        return cached[1]

    try:
        raw_data = pre_fetched or await _fetch_raw_data(site_id, org_id)
        topo = build_topology(site_id, raw_data)
        _topology_cache[site_id] = (time.monotonic(), topo)
        return topo
    except Exception as e:
        logger.error("topology_build_failed", site_id=site_id, error=str(e))
        return None


async def _safe_fetch(coro: Any, default: Any = None) -> Any:
    """Execute a coroutine and return its response data, with error handling."""
    try:
        resp = await coro
        if resp.status_code == 200:
            return resp.data if resp.data is not None else (default if default is not None else [])
        return default if default is not None else []
    except Exception as e:
        logger.warning("topology_fetch_partial_failure", error=str(e))
        return default if default is not None else []


def _normalize(data: Any, default: Any = None) -> Any:
    """Unwrap Mist API {"results": [...]} wrapper if present."""
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    if isinstance(data, list):
        return data
    return default if default is not None else []


async def _fetch_raw_data(site_id: str, org_id: str) -> RawSiteData:
    """Fetch all data needed for topology building via mistapi."""
    mist = await create_mist_service()
    session = mist.get_session()

    # Parallel fetch - matches what the topology builder expects
    results = await asyncio.gather(
        _safe_fetch(mistapi.arun(stats.searchSiteSwOrGwPorts, session, site_id, limit=1000), []),
        _safe_fetch(mistapi.arun(devices.listSiteDevices, session, site_id, limit=1000), []),
        _safe_fetch(mistapi.arun(stats.listSiteDevicesStats, session, site_id, limit=1000), []),
        _safe_fetch(mistapi.arun(setting.getSiteSettingDerived, session, site_id), {}),
        _safe_fetch(mistapi.arun(alarms.searchSiteAlarms, session, site_id, duration="1h", limit=1000), []),
        _safe_fetch(mistapi.arun(org_networks.listOrgNetworks, session, org_id, limit=1000), []),
        return_exceptions=True,
    )

    # Handle individual failures gracefully
    def _safe_result(r: Any, default: Any = None) -> Any:
        if isinstance(r, Exception):
            logger.warning("topology_fetch_partial_failure", error=str(r))
            return default
        return r

    port_stats = _safe_result(results[0], [])
    devices_list = _safe_result(results[1], [])
    device_stats = _safe_result(results[2], [])
    site_setting_data = _safe_result(results[3], {})
    alarms_data = _safe_result(results[4], [])
    org_networks_data = _safe_result(results[5], [])

    # Normalize results — API responses may be wrapped in {"results": [...]}
    port_stats = _normalize(port_stats, [])
    devices_list = _normalize(devices_list, [])
    device_stats = _normalize(device_stats, [])
    alarms_data = _normalize(alarms_data, [])
    org_networks_data = _normalize(org_networks_data, [])

    # Check if site references a gateway template
    gw_template_id = None
    if isinstance(site_setting_data, dict):
        gw_template_id = site_setting_data.get("gatewaytemplate_id")

    gw_template = None
    if gw_template_id:
        try:
            resp = await mistapi.arun(org_gatewaytemplates.getOrgGatewayTemplate, session, org_id, gw_template_id)
            gw_template = resp.data if resp.status_code == 200 else None
        except Exception as e:
            logger.warning("topology_gw_template_fetch_failed", error=str(e))

    return RawSiteData(
        port_stats=port_stats or [],
        devices=devices_list or [],
        devices_stats=device_stats or [],
        site_setting=site_setting_data or {},
        alarms=alarms_data or [],
        org_networks=org_networks_data or [],
        gateway_template=gw_template,
    )


def capture_topology_snapshot(topology: SiteTopology) -> dict[str, Any]:
    """Serialize a SiteTopology to a dict for MongoDB storage."""
    return {
        "site_id": topology.site_id,
        "site_name": topology.site_name,
        "device_count": topology.device_count,
        "connection_count": topology.connection_count,
        "devices": {
            dev_id: {
                "id": dev.id,
                "name": dev.name,
                "mac": dev.mac,
                "model": dev.model,
                "device_type": dev.device_type,
                "status": dev.status,
                "ip": dev.ip,
                "is_virtual_chassis": dev.is_virtual_chassis,
                "alarm_count": dev.alarm_count,
            }
            for dev_id, dev in topology.devices.items()
        },
        "connections": [
            {
                "local_device_id": conn.local_device_id,
                "remote_device_id": conn.remote_device_id,
                "link_type": conn.link_type.value,
                "status": conn.status.value,
                "local_ae": conn.local_ae,
                "remote_ae": conn.remote_ae,
                "vlan_summary": conn.vlan_summary(),
                "physical_links_count": len(conn.physical_links),
            }
            for conn in topology.connections
        ],
        "logical_groups": [
            {"group_type": g.group_type, "group_id": g.group_id, "member_ids": g.member_ids}
            for g in topology.logical_groups
        ],
        "vlan_map": topology.vlan_map,
    }


def compute_topology_diff(
    baseline: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare two topology snapshots for changes."""
    if not baseline or not current:
        return {"has_changes": False, "details": []}

    details: list[dict[str, str]] = []

    # Compare devices
    baseline_devices = set(baseline.get("devices", {}).keys())
    current_devices = set(current.get("devices", {}).keys())

    for dev_id in current_devices - baseline_devices:
        dev = current["devices"][dev_id]
        details.append({"type": "device_added", "device": dev.get("name", dev_id)})

    for dev_id in baseline_devices - current_devices:
        dev = baseline["devices"][dev_id]
        details.append({"type": "device_removed", "device": dev.get("name", dev_id)})

    # Check device status changes
    for dev_id in baseline_devices & current_devices:
        b_dev = baseline["devices"][dev_id]
        c_dev = current["devices"][dev_id]
        if b_dev.get("status") != c_dev.get("status"):
            details.append(
                {
                    "type": "device_status_changed",
                    "device": c_dev.get("name", dev_id),
                    "from": b_dev.get("status", "unknown"),
                    "to": c_dev.get("status", "unknown"),
                }
            )

    # Compare connection counts
    b_conn_count = baseline.get("connection_count", 0)
    c_conn_count = current.get("connection_count", 0)
    if b_conn_count != c_conn_count:
        details.append(
            {
                "type": "connection_count_changed",
                "from": str(b_conn_count),
                "to": str(c_conn_count),
            }
        )

    # Compare connections by link status
    baseline_conns = {
        tuple(sorted((c["local_device_id"], c["remote_device_id"]))): c for c in baseline.get("connections", [])
    }
    current_conns = {
        tuple(sorted((c["local_device_id"], c["remote_device_id"]))): c for c in current.get("connections", [])
    }

    for key in baseline_conns:
        if key not in current_conns:
            b = baseline_conns[key]
            details.append({"type": "connection_lost", "link_type": b.get("link_type", ""), "status": "removed"})

    for key in current_conns:
        if key not in baseline_conns:
            c = current_conns[key]
            details.append(
                {
                    "type": "connection_added",
                    "link_type": c.get("link_type", ""),
                    "status": c.get("status", ""),
                }
            )

    for key in baseline_conns.keys() & current_conns.keys():
        b_status = baseline_conns[key].get("status")
        c_status = current_conns[key].get("status")
        if b_status != c_status:
            details.append(
                {
                    "type": "connection_status_changed",
                    "link_type": current_conns[key].get("link_type", ""),
                    "from": b_status or "unknown",
                    "to": c_status or "unknown",
                }
            )

    return {"has_changes": len(details) > 0, "details": details}


def find_impact_radius(topology: SiteTopology, device_id: str, max_hops: int = 3) -> list[str]:
    """BFS from the changed device to find all potentially affected device IDs within N hops."""
    if device_id not in topology.devices:
        # Try to resolve by MAC or name
        dev = topology.resolve_device(device_id)
        if dev:
            device_id = dev.id
        else:
            return []

    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(device_id, 0)])
    result: list[str] = []

    while queue:
        current_id, depth = queue.popleft()
        if current_id in visited:
            continue
        visited.add(current_id)
        result.append(current_id)

        if depth >= max_hops:
            continue

        for conn in topology.neighbors(current_id):
            neighbor_id = conn.remote_device_id if conn.local_device_id == current_id else conn.local_device_id
            if neighbor_id not in visited:
                queue.append((neighbor_id, depth + 1))

    return result


def check_connectivity(topology: SiteTopology, source_id: str, dest_id: str) -> dict[str, Any]:
    """Check connectivity between two devices using BFS path finding."""
    path_devices, path_connections = bfs_path(topology, source_id, dest_id)
    if not path_devices:
        return {"reachable": False, "hops": -1, "path": []}

    return {
        "reachable": True,
        "hops": len(path_connections),
        "path": [dev.name for dev in path_devices],
    }


def invalidate_cache(site_id: str | None = None) -> None:
    """Invalidate topology cache for a specific site or all sites."""
    if site_id:
        _topology_cache.pop(site_id, None)
    else:
        _topology_cache.clear()


# ── Serialized topology dict helpers ──────────────────────────────────────
# These operate on the dict snapshots stored in MonitoringSession
# (topology_baseline / topology_latest), NOT on live SiteTopology objects.


def get_topology_devices(topo: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Extract devices dict from a serialized topology snapshot."""
    if not topo:
        return {}
    return topo.get("devices", {})


def get_topology_connections(topo: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Extract connections list from a serialized topology snapshot."""
    if not topo:
        return []
    return topo.get("connections", [])


def get_topology_groups(topo: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Extract logical groups from a serialized topology snapshot."""
    if not topo:
        return []
    return topo.get("logical_groups", [])


def find_device_id_by_mac(devices: dict[str, dict[str, Any]], mac: str) -> str | None:
    """Resolve a device MAC address to its device ID in a topology snapshot."""
    mac_lower = mac.lower()
    for dev_id, dev in devices.items():
        if dev.get("mac", "").lower() == mac_lower:
            return dev_id
    return None


def build_adjacency(connections: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build adjacency list from serialized connections."""
    adj: dict[str, list[str]] = {}
    for conn in connections:
        local = conn.get("local_device_id", "")
        remote = conn.get("remote_device_id", "")
        if local and remote:
            adj.setdefault(local, []).append(remote)
            adj.setdefault(remote, []).append(local)
    return adj


def bfs_reachable(adj: dict[str, list[str]], source: str) -> set[str]:
    """BFS from source, returns all reachable device IDs."""
    visited: set[str] = set()
    queue: deque[str] = deque([source])
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for neighbor in adj.get(current, []):
            if neighbor not in visited:
                queue.append(neighbor)
    return visited


def bfs_path_exists(adj: dict[str, list[str]], source: str, dest: str) -> bool:
    """Check if a BFS path exists from source to dest."""
    if source == dest:
        return True
    return dest in bfs_reachable(adj, source)


def find_gateways(devices: dict[str, dict[str, Any]]) -> list[str]:
    """Return list of device IDs that are gateways."""
    return [dev_id for dev_id, dev in devices.items() if dev.get("device_type") == "gateway"]


def device_name_from_topo(devices: dict[str, dict[str, Any]], dev_id: str) -> str:
    """Get device name from topology devices dict, falling back to ID."""
    dev = devices.get(dev_id, {})
    return dev.get("name", dev_id)


def safe_list(data: Any) -> list:
    """Safely extract a list from data that might be wrapped in {results: [...]}."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "results" in data:
            return data["results"] if isinstance(data["results"], list) else []
        return []
    return []
