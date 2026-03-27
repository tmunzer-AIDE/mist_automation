"""Validation service — runs post-change validation checks.

Checks by device type (after removing SLE #2 and alarm #7):
- AP: 1, 3-6, 8, 12
- Switch: 1, 3-6, 8-13, 15
- Gateway: 1, 3-6, 8, 9, 11, 12, 14, 15

Checks that target optional features (DHCP, VC, LAG/MCLAG, routing, PoE)
are automatically skipped when the feature is not configured on the device.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from app.modules.impact_analysis.services.topology_service import (
    bfs_path_exists,
    bfs_reachable,
    build_adjacency,
    device_name_from_topo,
    find_device_id_by_mac,
    find_gateways,
    get_topology_connections,
    get_topology_devices,
    get_topology_groups,
    safe_list,
)

if TYPE_CHECKING:
    from app.modules.impact_analysis.models import MonitoringSession

logger = structlog.get_logger(__name__)

# Which checks apply to which device types
# Check #2 (SLE Performance) removed — runs in the SLE monitoring branch
# Check #7 (Alarm Correlation) removed — replaced by webhook event routing
_CHECKS_BY_TYPE: dict[str, set[int]] = {
    "ap": {1, 3, 4, 5, 6, 8, 12},
    "switch": {1, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 15},
    "gateway": {1, 3, 4, 5, 6, 8, 9, 11, 12, 14, 15},
}


@dataclass
class ValidationData:
    """Lightweight data container for validation checks.

    Replaces the full SitePollData — only carries the fields that
    the remaining checks actually use. Pre-computed adjacency lists
    avoid redundant build_adjacency() calls across checks.
    """

    device_stats: list[dict[str, Any]] = field(default_factory=list)
    port_stats: list[dict[str, Any]] = field(default_factory=list)
    client_counts: dict[str, Any] | int | None = None
    config_events: list[dict[str, Any]] = field(default_factory=list)
    device_configs: list[dict[str, Any]] = field(default_factory=list)
    # Pre-computed adjacency lists from session topology snapshots
    baseline_adj: dict[str, list[str]] = field(default_factory=dict)
    latest_adj: dict[str, list[str]] = field(default_factory=dict)
    routing_current: dict[str, Any] = field(default_factory=dict)


# Client count drop thresholds
_CLIENT_WARN_THRESHOLD = 10.0  # percent drop
_CLIENT_FAIL_THRESHOLD = 25.0

# Port flapping: state changes exceeding this count = fail
_PORT_FLAP_THRESHOLD = 2


def _should_skip_check(
    check_num: int,
    session: MonitoringSession,
    site_data: ValidationData,
) -> bool:
    """Return True if the check should be skipped (feature not configured on device)."""
    device_mac = session.device_mac.lower()

    if check_num == 9:  # DHCP Health
        for topo in (session.topology_baseline, session.topology_latest):
            if not topo:
                continue
            for dev_data in (topo.get("devices") or {}).values():
                if dev_data.get("mac", "").lower() == device_mac:
                    dhcp = dev_data.get("dhcpd_config", {})
                    if dhcp and isinstance(dhcp, dict) and len(dhcp) > 0:
                        return False
        return True

    if check_num == 10:  # VC Integrity
        for topo in (session.topology_baseline, session.topology_latest):
            if not topo:
                continue
            for dev_data in (topo.get("devices") or {}).values():
                if dev_data.get("mac", "").lower() == device_mac:
                    if dev_data.get("is_virtual_chassis"):
                        return False
        return True

    if check_num == 15:  # LAG/MCLAG Integrity
        has_mclag = False
        has_ae = False
        for topo in (session.topology_baseline, session.topology_latest):
            if not topo:
                continue
            for dev_data in (topo.get("devices") or {}).values():
                if dev_data.get("mac", "").lower() == device_mac:
                    if dev_data.get("mclag_domain_id"):
                        has_mclag = True
            for conn in topo.get("connections", []):
                if conn.get("local_ae") or conn.get("remote_ae"):
                    has_ae = True
                    break
        for port in site_data.port_stats:
            if not isinstance(port, dict):
                continue
            if (port.get("mac") or port.get("device_mac") or "").lower() == device_mac:
                if port.get("port_id", "").startswith("ae"):
                    has_ae = True
                    break
        return not (has_mclag or has_ae)

    if check_num == 11:  # Routing Adjacency
        baseline = session.routing_baseline
        has_peers = False
        if baseline:
            has_peers = bool(baseline.get("ospf_peers")) or bool(baseline.get("bgp_peers"))
        routing_events = {"SW_OSPF_NEIGHBOR_DOWN", "GW_OSPF_NEIGHBOR_DOWN",
                          "SW_BGP_NEIGHBOR_DOWN", "GW_BGP_NEIGHBOR_DOWN"}
        has_incidents = any(i.event_type in routing_events for i in session.incidents)
        return not (has_peers or has_incidents)

    if check_num == 13:  # PoE Budget
        for port in site_data.port_stats:
            if not isinstance(port, dict):
                continue
            if (port.get("mac") or port.get("device_mac") or "").lower() == device_mac:
                if port.get("poe_enabled") or port.get("poe_on"):
                    return False
        return True

    return False


async def run_validations(
    session: MonitoringSession,
    *,
    device_stats: list[dict[str, Any]] | None = None,
    port_stats: list[dict[str, Any]] | None = None,
    device_configs: list[dict[str, Any]] | None = None,
    topology: Any = None,
    template_drift: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run all applicable validation checks for this session.

    Args:
        session: The MonitoringSession with baseline/latest topology, SLE delta,
                 incidents, and device context.
        device_stats: Device stats from listSiteDevicesStats.
        port_stats: Port stats from searchSiteSwOrGwPorts.
        device_configs: Device configs from searchSiteDeviceLastConfigs.
        topology: Live topology object (used to update topology_latest if not set).
        template_drift: Optional template drift results from template_service.

    Returns:
        Dict keyed by check name → {status, details, ...} plus overall_status.
    """
    device_type = session.device_type
    applicable = _CHECKS_BY_TYPE.get(device_type, set())
    results: dict[str, Any] = {}

    # Pre-compute adjacency lists once for all topology-based checks
    baseline_adj: dict[str, list[str]] = {}
    latest_adj: dict[str, list[str]] = {}
    if session.topology_baseline:
        baseline_adj = build_adjacency(get_topology_connections(session.topology_baseline))
    if session.topology_latest:
        latest_adj = build_adjacency(get_topology_connections(session.topology_latest))

    # Build validation data container (replaces full SitePollData)
    site_data = ValidationData(
        device_stats=device_stats or [],
        port_stats=port_stats or [],
        device_configs=device_configs or [],
        baseline_adj=baseline_adj,
        latest_adj=latest_adj,
    )

    # Pre-fetch current routing peers for baseline comparison (avoids async in sync check)
    if session.routing_baseline and session.device_type.value in ("switch", "gateway"):
        try:
            from app.modules.impact_analysis.workers.monitoring_worker import _fetch_routing_peers

            site_data.routing_current = await _fetch_routing_peers(
                session.org_id, session.site_id, session.device_mac, session.device_type.value
            )
        except Exception as e:
            logger.warning("routing_current_fetch_failed", error=str(e))

    overall_worst = "pass"

    check_functions: dict[int, tuple[str, Any]] = {
        1: ("connectivity", _check_connectivity),
        3: ("stability", _check_stability),
        4: ("loop_detection", _check_loops),
        5: ("black_holes", _check_black_holes),
        6: ("client_impact", _check_client_impact),
        8: ("port_flapping", _check_port_flapping),
        9: ("dhcp_health", _check_dhcp_health),
        10: ("vc_integrity", _check_vc_integrity),
        11: ("routing_adjacency", _check_routing_adjacency),
        12: ("config_drift", lambda s, sd: _check_config_drift(s, sd, template_drift)),
        13: ("poe_budget", _check_poe_budget),
        14: ("wan_failover", _check_wan_failover),
        15: ("lag_mclag_integrity", _check_lag_mclag),
    }

    for check_num, (name, func) in check_functions.items():
        if check_num not in applicable:
            continue
        if _should_skip_check(check_num, session, site_data):
            continue
        try:
            result = func(session, site_data)
            results[name] = result
            status = result.get("status", "pass")
            if status == "fail":
                overall_worst = "fail"
            elif status == "warn" and overall_worst == "pass":
                overall_worst = "warn"
        except Exception as e:
            logger.warning("validation_check_failed", check=name, error=str(e))
            results[name] = {"status": "error", "details": [f"Check '{name}' encountered an internal error"]}

    results["overall_status"] = overall_worst
    return results


# ── Check 1: Connectivity ─────────────────────────────────────────────────


def _check_connectivity(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Check upstream/downstream connectivity via BFS paths to gateways.

    Compare topology_baseline vs topology_latest. Fail if any previously-reachable
    gateway is now unreachable from the changed device.
    """
    baseline = session.topology_baseline
    latest = session.topology_latest
    details: list[str] = []

    if not baseline or not latest:
        return {"status": "pass", "details": ["Insufficient topology data for connectivity check"]}

    baseline_devices = get_topology_devices(baseline)
    latest_devices = get_topology_devices(latest)

    # Find the changed device in both topologies
    device_id_baseline = find_device_id_by_mac(baseline_devices, session.device_mac)
    device_id_latest = find_device_id_by_mac(latest_devices, session.device_mac)

    if not device_id_baseline or not device_id_latest:
        return {
            "status": "pass",
            "details": ["Device has no infrastructure LLDP connections (standalone — not in topology)"],
        }

    # Find all gateways in baseline
    baseline_gateways = find_gateways(baseline_devices)
    if not baseline_gateways:
        return {"status": "pass", "details": ["No gateways in topology to check connectivity against"]}

    # Use pre-computed adjacency lists from ValidationData
    baseline_adj = site_data.baseline_adj
    latest_adj = site_data.latest_adj

    # Check BFS paths from changed device to each gateway
    lost_paths: list[str] = []
    for gw_id in baseline_gateways:
        was_reachable = bfs_path_exists(baseline_adj, device_id_baseline, gw_id)
        if was_reachable:
            # Check if the gateway still exists in the latest topology
            gw_latest_id = None
            gw_mac = baseline_devices.get(gw_id, {}).get("mac", "")
            if gw_mac:
                gw_latest_id = find_device_id_by_mac(latest_devices, gw_mac)
            # Fall back to same ID if MAC lookup fails
            if not gw_latest_id and gw_id in latest_devices:
                gw_latest_id = gw_id

            if not gw_latest_id:
                gw_name = device_name_from_topo(baseline_devices, gw_id)
                lost_paths.append(gw_name)
                details.append(f"Gateway '{gw_name}' no longer in topology")
            elif not bfs_path_exists(latest_adj, device_id_latest, gw_latest_id):
                gw_name = device_name_from_topo(latest_devices, gw_latest_id)
                lost_paths.append(gw_name)
                details.append(f"Path to gateway '{gw_name}' is broken")

    if lost_paths:
        return {"status": "fail", "details": details, "lost_paths": lost_paths}

    details.append(f"All {len(baseline_gateways)} gateway path(s) intact")
    return {"status": "pass", "details": details}


# ── Check 3: Stability ────────────────────────────────────────────────────


def _check_stability(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Count unresolved incidents. Fail if any unresolved disconnects. Warn if >2 resolved."""
    incidents = session.incidents
    if not incidents:
        return {"status": "pass", "details": ["No incidents during monitoring"], "incidents": []}

    unresolved = [i for i in incidents if not i.resolved]
    resolved = [i for i in incidents if i.resolved]

    # Check for unresolved disconnect events
    disconnect_types = {"AP_DISCONNECTED", "SW_DISCONNECTED", "GW_DISCONNECTED"}
    unresolved_disconnects = [i for i in unresolved if i.event_type in disconnect_types]

    incident_summaries = [
        {
            "event_type": i.event_type,
            "device_mac": i.device_mac,
            "severity": i.severity,
            "resolved": i.resolved,
            "is_revert": i.is_revert,
        }
        for i in incidents
    ]

    if unresolved_disconnects:
        return {
            "status": "fail",
            "details": [
                f"{len(unresolved_disconnects)} unresolved disconnect(s)",
                f"Total incidents: {len(incidents)} ({len(unresolved)} unresolved, {len(resolved)} resolved)",
            ],
            "incidents": incident_summaries,
        }

    if unresolved:
        return {
            "status": "fail",
            "details": [
                f"{len(unresolved)} unresolved incident(s)",
                f"Types: {', '.join({i.event_type for i in unresolved})}",
            ],
            "incidents": incident_summaries,
        }

    if len(resolved) > 2:
        return {
            "status": "warn",
            "details": [f"{len(resolved)} resolved incidents during monitoring (elevated activity)"],
            "incidents": incident_summaries,
        }

    return {
        "status": "pass",
        "details": [f"{len(resolved)} resolved incident(s), all stable"],
        "incidents": incident_summaries,
    }


# ── Check 4: Loop Detection ──────────────────────────────────────────────


def _check_loops(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Compare VLAN maps between topology_baseline and topology_latest.

    New VLANs appearing in unexpected segments = potential loop indicator.
    Also checks for connections that appear in both directions (A->B and B->A
    with same VLAN) which could indicate a loop.
    """
    baseline = session.topology_baseline
    latest = session.topology_latest
    details: list[str] = []

    if not baseline or not latest:
        return {"status": "pass", "details": ["Insufficient topology data for loop detection"]}

    # Compare VLAN maps
    baseline_vlans = baseline.get("vlan_map", {})
    latest_vlans = latest.get("vlan_map", {})

    new_vlans: list[str] = []
    for vlan_key, vlan_val in latest_vlans.items():
        if vlan_key not in baseline_vlans:
            new_vlans.append(f"{vlan_key}={vlan_val}")

    # Check connection VLAN summaries for unexpected propagation
    baseline_conns = get_topology_connections(baseline)
    latest_conns = get_topology_connections(latest)

    # Build a set of (local, remote, vlan_summary) tuples for comparison
    baseline_vlan_paths: set[tuple[str, str, str]] = set()
    for conn in baseline_conns:
        local = conn.get("local_device_id", "")
        remote = conn.get("remote_device_id", "")
        vlan_sum = conn.get("vlan_summary", "")
        if local and remote and vlan_sum:
            # Normalize: use sorted pair to avoid direction issues
            pair = tuple(sorted([local, remote]))
            baseline_vlan_paths.add((pair[0], pair[1], vlan_sum))

    new_vlan_paths: list[str] = []
    latest_devices = get_topology_devices(latest)
    for conn in latest_conns:
        local = conn.get("local_device_id", "")
        remote = conn.get("remote_device_id", "")
        vlan_sum = conn.get("vlan_summary", "")
        if local and remote and vlan_sum:
            pair = tuple(sorted([local, remote]))
            if (pair[0], pair[1], vlan_sum) not in baseline_vlan_paths:
                local_name = device_name_from_topo(latest_devices, local)
                remote_name = device_name_from_topo(latest_devices, remote)
                new_vlan_paths.append(f"{local_name} <-> {remote_name}: {vlan_sum}")

    if new_vlans:
        details.append(f"New VLAN entries: {', '.join(new_vlans[:5])}")
    if new_vlan_paths:
        details.append(f"New VLAN paths: {'; '.join(new_vlan_paths[:5])}")

    if new_vlan_paths:
        return {"status": "warn", "details": details}
    if new_vlans:
        return {"status": "warn", "details": details}

    return {"status": "pass", "details": ["No unexpected VLAN propagation detected"]}


# ── Check 5: Black Holes ─────────────────────────────────────────────────


def _check_black_holes(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """For each gateway, compute reachable devices via reverse BFS. Devices reachable
    in baseline but not in latest are potential traffic black holes.

    Uses O(G*(D+E)) reverse-BFS instead of O(D*G) per-device BFS.
    """
    baseline = session.topology_baseline
    latest = session.topology_latest

    if not baseline or not latest:
        return {"status": "pass", "details": ["Insufficient topology data for black hole detection"]}

    baseline_devices = get_topology_devices(baseline)
    latest_devices = get_topology_devices(latest)

    baseline_gateways = find_gateways(baseline_devices)
    if not baseline_gateways:
        return {"status": "pass", "details": ["No gateways found in baseline topology"]}

    # Use pre-computed adjacency lists from ValidationData
    baseline_adj = site_data.baseline_adj
    latest_adj = site_data.latest_adj

    # Build MAC-to-latest-ID mapping for resolving devices across topologies
    mac_to_latest_id: dict[str, str] = {}
    for dev_id, dev in latest_devices.items():
        mac = dev.get("mac", "").lower()
        if mac:
            mac_to_latest_id[mac] = dev_id

    def _resolve_latest_id(baseline_dev_id: str) -> str | None:
        """Resolve a baseline device ID to its latest topology ID via MAC."""
        dev = baseline_devices.get(baseline_dev_id, {})
        mac = dev.get("mac", "").lower()
        if mac and mac in mac_to_latest_id:
            return mac_to_latest_id[mac]
        if baseline_dev_id in latest_devices:
            return baseline_dev_id
        return None

    # Reverse BFS: for each gateway, find all reachable devices in baseline and latest
    broken_paths: list[dict[str, str]] = []
    for gw_id in baseline_gateways:
        baseline_reachable = bfs_reachable(baseline_adj, gw_id)

        # Resolve gateway ID in latest topology
        gw_latest_id = _resolve_latest_id(gw_id)
        latest_reachable: set[str] = set()
        if gw_latest_id:
            latest_reachable = bfs_reachable(latest_adj, gw_latest_id)

        # Check each non-gateway device that was reachable from this gateway
        for dev_id in baseline_reachable:
            if dev_id == gw_id:
                continue
            dev = baseline_devices.get(dev_id, {})
            if dev.get("device_type") == "gateway":
                continue

            dev_latest_id = _resolve_latest_id(dev_id)
            if not dev_latest_id or not gw_latest_id:
                continue

            if dev_latest_id not in latest_reachable:
                broken_paths.append(
                    {
                        "device": device_name_from_topo(baseline_devices, dev_id),
                        "gateway": device_name_from_topo(baseline_devices, gw_id),
                    }
                )

    if broken_paths:
        details = [f"{bp['device']} -> {bp['gateway']}" for bp in broken_paths[:10]]
        return {
            "status": "fail",
            "details": [f"{len(broken_paths)} broken path(s) detected (potential black holes)"] + details,
            "broken_paths": broken_paths,
        }

    return {"status": "pass", "details": ["All device-to-gateway paths intact"], "broken_paths": []}


# ── Check 6: Client Impact ───────────────────────────────────────────────


def _check_client_impact(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Compare client counts from site_data vs baseline stored in session.

    Warn if >10% drop, fail if >25% drop.
    """
    # Current client counts from site_data
    current_clients = getattr(site_data, "client_counts", None)
    current_count = 0
    baseline_count = 0

    if current_clients:
        clients_list = safe_list(current_clients)
        if clients_list:
            # Client count endpoints typically return a list of client objects
            current_count = len(clients_list)
        elif isinstance(current_clients, dict):
            # Could be {total: N} or {results: [...]}
            current_count = current_clients.get("total", 0)

    # Try to extract baseline client count from session's stored baseline
    # The session stores sle_baseline which may contain client data
    sle_baseline = session.sle_baseline
    if sle_baseline:
        baseline_metrics = sle_baseline.get("metrics", {})
        for metric_data in baseline_metrics.values():
            if isinstance(metric_data, dict):
                num_users = metric_data.get("num_users")
                if isinstance(num_users, (int, float)) and num_users > 0:
                    baseline_count = max(baseline_count, int(num_users))

    # If we have no meaningful counts, pass
    if baseline_count == 0 and current_count == 0:
        return {
            "status": "pass",
            "details": ["No client count data available for comparison"],
            "baseline_count": 0,
            "current_count": 0,
            "change_percent": 0,
        }

    # Calculate change
    if baseline_count > 0:
        change_percent = ((current_count - baseline_count) / baseline_count) * 100
    else:
        change_percent = 0.0

    result: dict[str, Any] = {
        "baseline_count": baseline_count,
        "current_count": current_count,
        "change_percent": round(change_percent, 1),
    }

    if change_percent <= -_CLIENT_FAIL_THRESHOLD:
        result["status"] = "fail"
        result["details"] = [f"Client count dropped {abs(change_percent):.1f}% ({baseline_count} -> {current_count})"]
    elif change_percent <= -_CLIENT_WARN_THRESHOLD:
        result["status"] = "warn"
        result["details"] = [f"Client count dropped {abs(change_percent):.1f}% ({baseline_count} -> {current_count})"]
    else:
        result["status"] = "pass"
        result["details"] = [f"Client count stable ({baseline_count} -> {current_count}, {change_percent:+.1f}%)"]

    return result


# ── Check 8: Port Flapping ───────────────────────────────────────────────


def _check_port_flapping(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Analyze incidents for repeated up/down on same port.

    >2 state changes on the same port/interface = fail.
    """
    incidents = session.incidents
    if not incidents:
        return {"status": "pass", "details": ["No incidents to analyze for port flapping"], "flapping_ports": []}

    # Port-related event types
    port_events = {
        "SW_VC_PORT_DOWN",
        "SW_VC_PORT_UP",
        "GW_VPN_PATH_DOWN",
        "GW_VPN_PATH_UP",
        "GW_TUNNEL_DOWN",
        "GW_TUNNEL_UP",
    }

    # Also count disconnect/connect cycles as port-level flapping
    connect_events = {
        "AP_DISCONNECTED",
        "AP_CONNECTED",
        "SW_DISCONNECTED",
        "SW_CONNECTED",
        "GW_DISCONNECTED",
        "GW_CONNECTED",
    }

    # Count state changes per event category
    # Group by base event type (strip _UP/_DOWN suffix)
    change_counts: Counter[str] = Counter()
    for incident in incidents:
        et = incident.event_type
        if et in port_events or et in connect_events:
            # Normalize: strip UP/DOWN/CONNECTED/DISCONNECTED suffix to get the base
            base = et
            for suffix in ("_UP", "_DOWN", "_CONNECTED", "_DISCONNECTED"):
                if et.endswith(suffix):
                    base = et[: -len(suffix)]
                    break
            change_counts[base] += 1

    flapping_ports: list[dict[str, Any]] = []
    for base_event, count in change_counts.items():
        if count > _PORT_FLAP_THRESHOLD:
            flapping_ports.append({"event_base": base_event, "state_changes": count})

    if flapping_ports:
        names = [f"{fp['event_base']} ({fp['state_changes']}x)" for fp in flapping_ports]
        return {
            "status": "fail",
            "details": [f"Port flapping detected: {', '.join(names)}"],
            "flapping_ports": flapping_ports,
        }

    return {"status": "pass", "details": ["No port flapping detected"], "flapping_ports": []}


# ── Check 9: DHCP Health ─────────────────────────────────────────────────


def _check_dhcp_health(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Compare DHCP config from topology baseline vs latest.

    Checks for DHCP scope changes, relay target changes on the changed device
    and its neighbors.
    """
    baseline = session.topology_baseline
    latest = session.topology_latest
    details: list[str] = []

    if not baseline or not latest:
        return {"status": "pass", "details": ["Insufficient topology data for DHCP health check"]}

    baseline_devices = get_topology_devices(baseline)
    latest_devices = get_topology_devices(latest)

    # Find the changed device and its neighbors
    device_id_baseline = find_device_id_by_mac(baseline_devices, session.device_mac)
    device_id_latest = find_device_id_by_mac(latest_devices, session.device_mac)

    if not device_id_baseline or not device_id_latest:
        return {"status": "pass", "details": ["Changed device not found in topology for DHCP check"]}

    # Get neighbor device IDs from baseline (use pre-computed adjacency)
    device_ids_to_check = {device_id_baseline}
    for neighbor_id in site_data.baseline_adj.get(device_id_baseline, []):
        device_ids_to_check.add(neighbor_id)

    # Compare DHCP configs
    dhcp_issues: list[str] = []

    for dev_id in device_ids_to_check:
        baseline_dev = baseline_devices.get(dev_id, {})
        baseline_dhcp = baseline_dev.get("dhcpd_config") if isinstance(baseline_dev, dict) else None

        # Find same device in latest topology by MAC
        dev_mac = baseline_dev.get("mac", "") if isinstance(baseline_dev, dict) else ""
        latest_dev_id = find_device_id_by_mac(latest_devices, dev_mac) if dev_mac else dev_id
        latest_dev = latest_devices.get(latest_dev_id or dev_id, {})
        latest_dhcp = latest_dev.get("dhcpd_config") if isinstance(latest_dev, dict) else None

        dev_name = baseline_dev.get("name", dev_id) if isinstance(baseline_dev, dict) else dev_id

        if not baseline_dhcp and not latest_dhcp:
            continue

        # DHCP was removed
        if baseline_dhcp and not latest_dhcp:
            dhcp_issues.append(f"DHCP config removed on {dev_name}")
            continue

        # DHCP was added (not necessarily bad)
        if not baseline_dhcp and latest_dhcp:
            details.append(f"DHCP config added on {dev_name}")
            continue

        # Both exist — compare scopes
        if isinstance(baseline_dhcp, dict) and isinstance(latest_dhcp, dict):
            # Check enabled state
            if baseline_dhcp.get("enabled") and not latest_dhcp.get("enabled"):
                dhcp_issues.append(f"DHCP disabled on {dev_name}")
                continue

            # Compare per-network DHCP scopes
            for network_key in baseline_dhcp:
                if network_key in ("enabled",):
                    continue
                b_scope = baseline_dhcp.get(network_key, {})
                l_scope = latest_dhcp.get(network_key, {})
                if not isinstance(b_scope, dict) or not isinstance(l_scope, dict):
                    continue

                # Check if scope was removed
                if b_scope and not l_scope and network_key in baseline_dhcp and network_key not in latest_dhcp:
                    dhcp_issues.append(f"DHCP scope '{network_key}' removed on {dev_name}")

                # Check relay target changes
                b_type = b_scope.get("type", "")
                l_type = l_scope.get("type", "")
                if b_type == "relay" and l_type == "relay":
                    b_servers = set(b_scope.get("servers", []))
                    l_servers = set(l_scope.get("servers", []))
                    if b_servers != l_servers:
                        dhcp_issues.append(f"DHCP relay targets changed on {dev_name}/{network_key}")

                # Check scope type change
                if b_type and l_type and b_type != l_type:
                    dhcp_issues.append(f"DHCP type changed on {dev_name}/{network_key}: {b_type} -> {l_type}")

    if dhcp_issues:
        return {"status": "fail", "details": dhcp_issues}

    if details:
        return {"status": "warn", "details": details}

    return {"status": "pass", "details": ["DHCP configuration stable"]}


# ── Check 10: VC Integrity ────────────────────────────────────────────────


def _check_vc_integrity(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Compare Virtual Chassis membership and ICL links in baseline vs latest."""
    baseline = session.topology_baseline
    latest = session.topology_latest
    if not baseline or not latest:
        return {"status": "pass", "details": ["Insufficient topology data for VC check"]}

    baseline_groups = [g for g in get_topology_groups(baseline) if g.get("group_type") == "VC"]
    latest_groups = [g for g in get_topology_groups(latest) if g.get("group_type") == "VC"]

    baseline_by_id = {g.get("group_id", ""): g for g in baseline_groups}
    latest_by_id = {g.get("group_id", ""): g for g in latest_groups}

    issues: list[str] = []
    info: list[str] = []

    for gid, b_group in baseline_by_id.items():
        l_group = latest_by_id.get(gid)
        if not l_group:
            issues.append(f"VC group '{gid}' no longer exists")
            continue
        b_members = set(b_group.get("member_ids", []))
        l_members = set(l_group.get("member_ids", []))
        lost = b_members - l_members
        gained = l_members - b_members
        if lost:
            issues.append(f"VC '{gid}' lost members: {', '.join(lost)}")
        if gained:
            info.append(f"VC '{gid}' gained members: {', '.join(gained)}")

    # Check VC ICL links
    baseline_conns = get_topology_connections(baseline)
    latest_conns = get_topology_connections(latest)

    baseline_icls: dict[tuple[str, str], str] = {}
    for conn in baseline_conns:
        if conn.get("link_type") == "VC_ICL":
            pair = tuple(sorted([conn.get("local_device_id", ""), conn.get("remote_device_id", "")]))
            baseline_icls[pair] = conn.get("status", "UNKNOWN")

    latest_icls: dict[tuple[str, str], str] = {}
    for conn in latest_conns:
        if conn.get("link_type") == "VC_ICL":
            pair = tuple(sorted([conn.get("local_device_id", ""), conn.get("remote_device_id", "")]))
            latest_icls[pair] = conn.get("status", "UNKNOWN")

    for pair, b_status in baseline_icls.items():
        l_status = latest_icls.get(pair)
        if l_status is None:
            issues.append(f"VC ICL link lost between {pair[0]} and {pair[1]}")
        elif b_status == "UP" and l_status != "UP":
            issues.append(f"VC ICL degraded between {pair[0]} and {pair[1]}: {b_status} -> {l_status}")

    if issues:
        return {"status": "fail", "details": issues}
    if info:
        return {"status": "warn", "details": info}
    return {"status": "pass", "details": ["VC integrity maintained"]}


# ── Check 15: LAG/MCLAG Integrity ─────────────────────────────────────────


def _check_lag_mclag(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Check LAG (ae) interface status and MCLAG group integrity."""
    baseline = session.topology_baseline
    latest = session.topology_latest
    device_mac = session.device_mac.lower()
    issues: list[str] = []
    info: list[str] = []

    # --- MCLAG group checks ---
    if baseline and latest:
        baseline_groups = [g for g in get_topology_groups(baseline) if g.get("group_type") == "MCLAG"]
        latest_groups = [g for g in get_topology_groups(latest) if g.get("group_type") == "MCLAG"]

        baseline_by_id = {g.get("group_id", ""): g for g in baseline_groups}
        latest_by_id = {g.get("group_id", ""): g for g in latest_groups}

        for gid, b_group in baseline_by_id.items():
            l_group = latest_by_id.get(gid)
            if not l_group:
                issues.append(f"MCLAG domain '{gid}' no longer exists")
                continue
            b_members = set(b_group.get("member_ids", []))
            l_members = set(l_group.get("member_ids", []))
            lost = b_members - l_members
            if lost:
                issues.append(f"MCLAG '{gid}' lost members: {', '.join(lost)}")

        # Check MCLAG ICL links
        baseline_conns = get_topology_connections(baseline)
        latest_conns = get_topology_connections(latest)

        baseline_icls: dict[tuple[str, str], str] = {}
        for conn in baseline_conns:
            if conn.get("link_type") == "MCLAG_ICL":
                pair = tuple(sorted([conn.get("local_device_id", ""), conn.get("remote_device_id", "")]))
                baseline_icls[pair] = conn.get("status", "UNKNOWN")

        latest_icls: dict[tuple[str, str], str] = {}
        for conn in latest_conns:
            if conn.get("link_type") == "MCLAG_ICL":
                pair = tuple(sorted([conn.get("local_device_id", ""), conn.get("remote_device_id", "")]))
                latest_icls[pair] = conn.get("status", "UNKNOWN")

        for pair, b_status in baseline_icls.items():
            l_status = latest_icls.get(pair)
            if l_status is None:
                issues.append(f"MCLAG ICL link lost between {pair[0]} and {pair[1]}")
            elif b_status == "UP" and l_status != "UP":
                issues.append(f"MCLAG ICL degraded: {b_status} -> {l_status}")

    # --- LAG (ae interface) checks from port_stats ---
    ae_ports: dict[str, dict[str, Any]] = {}
    for port in site_data.port_stats:
        if not isinstance(port, dict):
            continue
        if (port.get("mac") or port.get("device_mac") or "").lower() != device_mac:
            continue
        port_id = port.get("port_id", "")
        if port_id.startswith("ae"):
            ae_ports[port_id] = port

    for port_id, port_data in ae_ports.items():
        is_up = port_data.get("up", True)
        if not is_up:
            issues.append(f"LAG interface {port_id} is DOWN")
        else:
            speed = port_data.get("speed", 0)
            if speed:
                info.append(f"LAG {port_id}: UP at {speed}Mbps")

    if issues:
        return {"status": "fail", "details": issues}
    if info:
        return {"status": "pass", "details": info}
    return {"status": "pass", "details": ["LAG/MCLAG integrity maintained"]}


# ── Check 11: Routing Adjacency ──────────────────────────────────────────


def _check_routing_adjacency(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Check for BGP/OSPF neighbor events in incidents and topology changes.

    Fail if routing adjacency lost.
    """
    details: list[str] = []
    lost_adjacencies: list[dict[str, str]] = []

    # Check incidents for routing-related events
    routing_down_events = {
        "SW_OSPF_NEIGHBOR_DOWN",
        "GW_OSPF_NEIGHBOR_DOWN",
        "SW_BGP_NEIGHBOR_DOWN",
        "GW_BGP_NEIGHBOR_DOWN",
    }

    routing_incidents = [i for i in session.incidents if i.event_type in routing_down_events and not i.resolved]

    for incident in routing_incidents:
        lost_adjacencies.append(
            {
                "event_type": incident.event_type,
                "device_mac": incident.device_mac,
                "resolved": str(incident.resolved),
            }
        )

    # Proactive OSPF/BGP peer comparison (baseline vs current)
    baseline_routing = session.routing_baseline or {}
    current_routing = getattr(site_data, "routing_current", {}) or {}

    baseline_ospf = {p.get("neighbor_ip", ""): p for p in baseline_routing.get("ospf_peers", [])}
    current_ospf = {p.get("neighbor_ip", ""): p for p in current_routing.get("ospf_peers", [])}

    for ip, b_peer in baseline_ospf.items():
        if not ip:
            continue
        c_peer = current_ospf.get(ip)
        if not c_peer:
            lost_adjacencies.append({
                "event_type": "OSPF_PEER_LOST",
                "device_mac": session.device_mac,
                "resolved": "False",
                "neighbor_ip": ip,
                "area": b_peer.get("area", ""),
            })
        elif b_peer.get("state") == "full" and c_peer.get("state") != "full":
            details.append(f"OSPF peer {ip} state degraded: full -> {c_peer.get('state', 'unknown')}")

    baseline_bgp = {p.get("neighbor_ip", ""): p for p in baseline_routing.get("bgp_peers", [])}
    current_bgp = {p.get("neighbor_ip", ""): p for p in current_routing.get("bgp_peers", [])}

    for ip, b_peer in baseline_bgp.items():
        if not ip:
            continue
        c_peer = current_bgp.get(ip)
        if not c_peer:
            lost_adjacencies.append({
                "event_type": "BGP_PEER_LOST",
                "device_mac": session.device_mac,
                "resolved": "False",
                "neighbor_ip": ip,
                "remote_as": str(b_peer.get("remote_as", "")),
            })
        elif b_peer.get("state") == "established" and c_peer.get("state") != "established":
            details.append(
                f"BGP peer {ip} (AS{b_peer.get('remote_as', '?')}) state degraded: "
                f"established -> {c_peer.get('state', 'unknown')}"
            )

    # Also check config_events from site_data for routing events
    config_events = safe_list(getattr(site_data, "config_events", None))
    for event in config_events:
        if not isinstance(event, dict):
            continue
        event_type = event.get("type", "")
        if "OSPF" in event_type or "BGP" in event_type:
            details.append(f"Routing event: {event_type}")

    # Compare topology connections for routing-related link changes
    baseline = session.topology_baseline
    latest = session.topology_latest
    if baseline and latest:
        baseline_conns = get_topology_connections(baseline)
        latest_conns = get_topology_connections(latest)

        # Build connection sets by device pair
        def _conn_set(conns: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
            result: dict[tuple[str, str], str] = {}
            for c in conns:
                pair = tuple(sorted([c.get("local_device_id", ""), c.get("remote_device_id", "")]))
                result[pair] = c.get("status", "UNKNOWN")
            return result

        baseline_set = _conn_set(baseline_conns)
        latest_set = _conn_set(latest_conns)

        for pair, b_status in baseline_set.items():
            l_status = latest_set.get(pair)
            if l_status is None and b_status == "UP":
                details.append(f"Connection lost between {pair[0]} and {pair[1]}")

    if lost_adjacencies:
        adj_details = [f"{la['event_type']} on {la['device_mac']}" for la in lost_adjacencies]
        return {
            "status": "fail",
            "details": [f"Routing adjacency lost: {', '.join(adj_details)}"] + details,
            "lost_adjacencies": lost_adjacencies,
        }

    if details:
        return {
            "status": "warn",
            "details": details,
            "lost_adjacencies": [],
        }

    return {"status": "pass", "details": ["Routing adjacencies stable"], "lost_adjacencies": []}


# ── Check 12: Config Drift ───────────────────────────────────────────────


def _check_config_drift(
    session: MonitoringSession,
    site_data: Any,
    template_drift: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check device-level and template-level configuration drift.

    Device-level: flags failed config application, manual overrides, pushed/applied mismatch.
    Template-level: uses baseline vs end-of-monitoring comparison of org/site templates
    to detect template changes during the monitoring window, with correlation to
    device CONFIGURED events.
    """
    details: list[str] = []
    drifted_fields: list[str] = []
    template_changes: list[dict[str, Any]] = []
    has_device_failure = False

    # ── Device-level checks ──────────────────────────────────────────────
    device_configs = safe_list(getattr(site_data, "device_configs", None))
    device_mac = session.device_mac.lower()

    device_config_entries: list[dict[str, Any]] = []
    for config_entry in device_configs:
        if not isinstance(config_entry, dict):
            continue
        config_mac = (config_entry.get("mac") or config_entry.get("device_mac") or "").lower()
        if config_mac == device_mac:
            device_config_entries.append(config_entry)

    for entry in device_config_entries:
        config_status = entry.get("status", "")
        if config_status in ("failed", "error"):
            drifted_fields.append(f"Config application status: {config_status}")
            has_device_failure = True

        change_type = entry.get("type", "")
        if "CONFIG_CHANGED_BY_USER" in change_type or "CONFIG_CHANGED_BY_RRM" in change_type:
            drifted_fields.append(f"Config change detected: {change_type}")

        pushed = entry.get("config_pushed")
        applied = entry.get("config_applied")
        if pushed and applied and pushed != applied:
            drifted_fields.append("Applied config differs from pushed config")

    # ── Template-level checks ────────────────────────────────────────────
    if template_drift:
        for tmpl_type, tmpl_data in template_drift.get("templates", {}).items():
            changes = tmpl_data.get("changes", [])
            tmpl_name = tmpl_data.get("name", tmpl_type)
            related_events = tmpl_data.get("related_events", [])

            changed_paths = [c.get("path", "") for c in changes[:5]]
            path_summary = ", ".join(p for p in changed_paths if p) or "root"

            if related_events:
                event_summary = ", ".join(f"{e['event_type']} at {e['timestamp']}" for e in related_events[:2])
                details.append(
                    f"Template '{tmpl_name}' ({tmpl_type}) changed: [{path_summary}] "
                    f"— correlated with: {event_summary}"
                )
            else:
                details.append(
                    f"Template '{tmpl_name}' ({tmpl_type}) changed: [{path_summary}] "
                    f"— no correlated CONFIGURED event detected"
                )

            template_changes.append(
                {
                    "template_type": tmpl_type,
                    "template_name": tmpl_name,
                    "template_id": tmpl_data.get("id", ""),
                    "change_count": len(changes),
                    "changed_fields": changed_paths,
                    "related_events": related_events,
                }
            )

        # Site setting changes
        setting_changes = template_drift.get("site_setting_changes", [])
        if setting_changes:
            changed_paths = [c.get("path", "") for c in setting_changes[:5]]
            details.append(f"Site setting changed: [{', '.join(p for p in changed_paths if p)}]")

    # ── Awaiting config warnings ────────────────────────────────────────
    if session.awaiting_config_warnings:
        for warning in session.awaiting_config_warnings:
            details.append(f"Warning: {warning}")

    # ── Status determination ─────────────────────────────────────────────
    if has_device_failure:
        all_details = drifted_fields + details
        return {
            "status": "fail",
            "details": all_details,
            "drifted_fields": drifted_fields,
            "template_changes": template_changes,
        }

    if drifted_fields or details:
        all_details = drifted_fields + details
        return {
            "status": "warn",
            "details": all_details,
            "drifted_fields": drifted_fields,
            "template_changes": template_changes,
        }

    return {
        "status": "pass",
        "details": ["Config consistent with expected state"],
        "drifted_fields": [],
        "template_changes": [],
    }


# ── Check 13: PoE Budget ─────────────────────────────────────────────────


def _check_poe_budget(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Check port_stats for PoE data on switches.

    Flag budget changes or PoE-related issues.
    """
    port_stats = safe_list(getattr(site_data, "port_stats", None))
    device_mac = session.device_mac.lower()

    # Filter port stats for our device
    device_ports: list[dict[str, Any]] = []
    for port in port_stats:
        if not isinstance(port, dict):
            continue
        port_mac = (port.get("mac") or port.get("device_mac") or "").lower()
        if port_mac == device_mac:
            device_ports.append(port)

    if not device_ports:
        return {"status": "pass", "details": ["No port stats available for PoE check"]}

    total_poe_draw = 0.0
    total_poe_max = 0.0
    poe_issues: list[str] = []

    for port in device_ports:
        poe_enabled = port.get("poe_enabled") or port.get("poe_on")
        if not poe_enabled:
            continue

        poe_draw = port.get("poe_power_draw", 0) or port.get("poe_draw", 0) or 0
        poe_max = port.get("poe_max_power", 0) or port.get("poe_max", 0) or 0
        port_id = port.get("port_id", "unknown")

        if isinstance(poe_draw, (int, float)):
            total_poe_draw += float(poe_draw)
        if isinstance(poe_max, (int, float)):
            total_poe_max += float(poe_max)

        # Check for individual port PoE issues
        poe_fault = port.get("poe_fault")
        if poe_fault:
            poe_issues.append(f"PoE fault on port {port_id}: {poe_fault}")

        poe_status = port.get("poe_status", "")
        if poe_status in ("denied", "fault", "overload"):
            poe_issues.append(f"PoE status '{poe_status}' on port {port_id}")

    # Check overall budget utilization
    if total_poe_max > 0:
        utilization = (total_poe_draw / total_poe_max) * 100
        if utilization > 90:
            poe_issues.append(
                f"PoE budget utilization at {utilization:.1f}% ({total_poe_draw:.1f}W / {total_poe_max:.1f}W)"
            )
        elif utilization > 75:
            poe_issues.append(f"PoE budget utilization elevated at {utilization:.1f}%")

    if poe_issues:
        # Any fault or denied status is a fail, budget warnings are just warns
        has_faults = any("fault" in issue.lower() or "denied" in issue.lower() for issue in poe_issues)
        return {
            "status": "fail" if has_faults else "warn",
            "details": poe_issues,
        }

    return {"status": "pass", "details": ["PoE budget within normal range"]}


# ── Check 14: WAN Failover ───────────────────────────────────────────────


def _check_wan_failover(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Check gateway WAN path status from device_stats.

    Warn if primary WAN down and traffic on backup. Fail if all WAN paths down.
    """
    device_stats = safe_list(getattr(site_data, "device_stats", None))
    device_mac = session.device_mac.lower()

    # Find our gateway in device stats
    gw_stats: dict[str, Any] | None = None
    for stat in device_stats:
        if not isinstance(stat, dict):
            continue
        stat_mac = (stat.get("mac") or "").lower()
        if stat_mac == device_mac:
            gw_stats = stat
            break

    if not gw_stats:
        return {"status": "pass", "details": ["No device stats available for WAN check"], "wan_paths": []}

    # Extract WAN port information from port_stat or ports
    wan_paths: list[dict[str, Any]] = []
    port_stat = gw_stats.get("port_stat", {})

    if isinstance(port_stat, dict):
        for port_name, port_data in port_stat.items():
            if not isinstance(port_data, dict):
                continue
            # WAN ports typically have usage="wan"
            usage = port_data.get("usage", "")
            if usage != "wan":
                continue

            is_up = port_data.get("up", False)
            wan_type = port_data.get("wan_type", "")
            wan_paths.append(
                {
                    "port": port_name,
                    "up": is_up,
                    "wan_type": wan_type,
                    "speed": port_data.get("speed", 0),
                }
            )

    # Also check ip_stat for WAN interface status
    ip_stat = gw_stats.get("ip_stat", {})
    if isinstance(ip_stat, dict) and not wan_paths:
        for iface_name, iface_data in ip_stat.items():
            if not isinstance(iface_data, dict):
                continue
            is_up = iface_data.get("up", False)
            wan_paths.append(
                {
                    "port": iface_name,
                    "up": is_up,
                    "wan_type": "",
                    "ip": iface_data.get("ip", ""),
                }
            )

    if not wan_paths:
        # Try port stats from site_data
        port_stats = safe_list(getattr(site_data, "port_stats", None))
        for port in port_stats:
            if not isinstance(port, dict):
                continue
            port_mac = (port.get("mac") or port.get("device_mac") or "").lower()
            if port_mac == device_mac:
                usage = port.get("port_usage", "") or port.get("usage", "")
                if usage == "wan":
                    is_up = port.get("up", False)
                    wan_paths.append(
                        {
                            "port": port.get("port_id", "unknown"),
                            "up": is_up,
                            "wan_type": port.get("wan_type", ""),
                        }
                    )

    if not wan_paths:
        return {"status": "pass", "details": ["No WAN path data available"], "wan_paths": []}

    up_paths = [p for p in wan_paths if p.get("up")]
    down_paths = [p for p in wan_paths if not p.get("up")]

    if not up_paths:
        return {
            "status": "fail",
            "details": [f"All {len(wan_paths)} WAN path(s) down"],
            "wan_paths": wan_paths,
        }

    if down_paths:
        down_names = [p["port"] for p in down_paths]
        return {
            "status": "warn",
            "details": [
                f"{len(down_paths)}/{len(wan_paths)} WAN path(s) down: {', '.join(down_names)}",
                f"{len(up_paths)} path(s) still active (possible failover in effect)",
            ],
            "wan_paths": wan_paths,
        }

    return {
        "status": "pass",
        "details": [f"All {len(wan_paths)} WAN path(s) up"],
        "wan_paths": wan_paths,
    }
