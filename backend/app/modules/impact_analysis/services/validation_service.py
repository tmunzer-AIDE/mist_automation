"""Validation service — runs 14 post-change validation checks.

Checks by device type:
- AP: 1-8, 12
- Switch: 1-13
- Gateway: 1-8, 11, 12, 14

All checks are synchronous and operate purely on data already in the session
and site_data. No API calls are made.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from app.modules.impact_analysis.models import MonitoringSession

logger = structlog.get_logger(__name__)

# Which checks apply to which device types
_CHECKS_BY_TYPE: dict[str, set[int]] = {
    "ap": {1, 2, 3, 4, 5, 6, 7, 8, 12},
    "switch": {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13},
    "gateway": {1, 2, 3, 4, 5, 6, 7, 8, 11, 12, 14},
}

# Client count drop thresholds
_CLIENT_WARN_THRESHOLD = 10.0  # percent drop
_CLIENT_FAIL_THRESHOLD = 25.0

# Port flapping: state changes exceeding this count = fail
_PORT_FLAP_THRESHOLD = 2


async def run_validations(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Run all applicable validation checks for this session.

    Args:
        session: The MonitoringSession with baseline/latest topology, SLE delta,
                 incidents, and device context.
        site_data: SitePollData from the SiteDataCoordinator, with attributes:
                   topology, sle_overview, device_stats, alarms, client_counts,
                   config_events, port_stats, device_configs, fetched_at.

    Returns:
        Dict keyed by check name → {status, details, ...} plus overall_status.
    """
    device_type = session.device_type
    applicable = _CHECKS_BY_TYPE.get(device_type, set())
    results: dict[str, Any] = {}

    overall_worst = "pass"

    check_functions: dict[int, tuple[str, Any]] = {
        1: ("connectivity", _check_connectivity),
        2: ("performance", _check_performance),
        3: ("stability", _check_stability),
        4: ("loop_detection", _check_loops),
        5: ("black_holes", _check_black_holes),
        6: ("client_impact", _check_client_impact),
        7: ("alarm_correlation", _check_alarm_correlation),
        8: ("port_flapping", _check_port_flapping),
        9: ("dhcp_health", _check_dhcp_health),
        10: ("vc_mclag_integrity", _check_vc_mclag),
        11: ("routing_adjacency", _check_routing_adjacency),
        12: ("config_drift", _check_config_drift),
        13: ("poe_budget", _check_poe_budget),
        14: ("wan_failover", _check_wan_failover),
    }

    for check_num, (name, func) in check_functions.items():
        if check_num not in applicable:
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


# ── Helpers ────────────────────────────────────────────────────────────────


def _get_topology_devices(topo: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Extract devices dict from a serialized topology snapshot."""
    if not topo:
        return {}
    return topo.get("devices", {})


def _get_topology_connections(topo: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Extract connections list from a serialized topology snapshot."""
    if not topo:
        return []
    return topo.get("connections", [])


def _get_topology_groups(topo: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Extract logical groups from a serialized topology snapshot."""
    if not topo:
        return []
    return topo.get("logical_groups", [])


def _find_gateways(devices: dict[str, dict[str, Any]]) -> list[str]:
    """Return list of device IDs that are gateways."""
    return [dev_id for dev_id, dev in devices.items() if dev.get("device_type") == "gateway"]


def _find_device_id_by_mac(devices: dict[str, dict[str, Any]], mac: str) -> str | None:
    """Resolve a device MAC address to its device ID in a topology snapshot."""
    mac_lower = mac.lower()
    for dev_id, dev in devices.items():
        if dev.get("mac", "").lower() == mac_lower:
            return dev_id
    return None


def _build_adjacency(connections: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build adjacency list from serialized connections."""
    adj: dict[str, list[str]] = {}
    for conn in connections:
        local = conn.get("local_device_id", "")
        remote = conn.get("remote_device_id", "")
        if local and remote:
            adj.setdefault(local, []).append(remote)
            adj.setdefault(remote, []).append(local)
    return adj


def _bfs_reachable(adj: dict[str, list[str]], source: str) -> set[str]:
    """BFS from source, returns all reachable device IDs."""
    visited: set[str] = set()
    queue = [source]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for neighbor in adj.get(current, []):
            if neighbor not in visited:
                queue.append(neighbor)
    return visited


def _bfs_path_exists(adj: dict[str, list[str]], source: str, dest: str) -> bool:
    """Check if a BFS path exists from source to dest."""
    if source == dest:
        return True
    return dest in _bfs_reachable(adj, source)


def _safe_list(data: Any) -> list:
    """Safely extract a list from data that might be wrapped in {results: [...]}."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "results" in data:
            return data["results"] if isinstance(data["results"], list) else []
        return []
    return []


def _device_name_from_topo(devices: dict[str, dict[str, Any]], dev_id: str) -> str:
    """Get device name from topology devices dict, falling back to ID."""
    dev = devices.get(dev_id, {})
    return dev.get("name", dev_id)


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

    baseline_devices = _get_topology_devices(baseline)
    latest_devices = _get_topology_devices(latest)
    baseline_conns = _get_topology_connections(baseline)
    latest_conns = _get_topology_connections(latest)

    # Find the changed device in both topologies
    device_id_baseline = _find_device_id_by_mac(baseline_devices, session.device_mac)
    device_id_latest = _find_device_id_by_mac(latest_devices, session.device_mac)

    if not device_id_baseline or not device_id_latest:
        return {"status": "warn", "details": ["Changed device not found in topology"]}

    # Find all gateways in baseline
    baseline_gateways = _find_gateways(baseline_devices)
    if not baseline_gateways:
        return {"status": "pass", "details": ["No gateways in topology to check connectivity against"]}

    # Build adjacency lists
    baseline_adj = _build_adjacency(baseline_conns)
    latest_adj = _build_adjacency(latest_conns)

    # Check BFS paths from changed device to each gateway
    lost_paths: list[str] = []
    for gw_id in baseline_gateways:
        was_reachable = _bfs_path_exists(baseline_adj, device_id_baseline, gw_id)
        if was_reachable:
            # Check if the gateway still exists in the latest topology
            gw_latest_id = None
            gw_mac = baseline_devices.get(gw_id, {}).get("mac", "")
            if gw_mac:
                gw_latest_id = _find_device_id_by_mac(latest_devices, gw_mac)
            # Fall back to same ID if MAC lookup fails
            if not gw_latest_id and gw_id in latest_devices:
                gw_latest_id = gw_id

            if not gw_latest_id:
                gw_name = _device_name_from_topo(baseline_devices, gw_id)
                lost_paths.append(gw_name)
                details.append(f"Gateway '{gw_name}' no longer in topology")
            elif not _bfs_path_exists(latest_adj, device_id_latest, gw_latest_id):
                gw_name = _device_name_from_topo(latest_devices, gw_latest_id)
                lost_paths.append(gw_name)
                details.append(f"Path to gateway '{gw_name}' is broken")

    if lost_paths:
        return {"status": "fail", "details": details, "lost_paths": lost_paths}

    details.append(f"All {len(baseline_gateways)} gateway path(s) intact")
    return {"status": "pass", "details": details}


# ── Check 2: Performance (SLE) ────────────────────────────────────────────


def _check_performance(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Check SLE delta — if overall_degraded is True, status=fail.

    If any single metric degraded, status=warn.
    """
    sle_delta = session.sle_delta
    if not sle_delta:
        return {"status": "pass", "details": ["No SLE delta data available"], "degraded_metrics": []}

    overall_degraded = sle_delta.get("overall_degraded", False)
    degraded_names = sle_delta.get("degraded_metric_names", [])
    metrics = sle_delta.get("metrics", [])

    degraded_details: list[dict[str, Any]] = []
    for m in metrics:
        if m.get("degraded"):
            degraded_details.append(
                {
                    "name": m.get("name", "unknown"),
                    "baseline_value": m.get("baseline_value"),
                    "current_value": m.get("current_value"),
                    "change_percent": m.get("change_percent"),
                }
            )

    if overall_degraded:
        return {
            "status": "fail",
            "details": [f"SLE degradation detected: {', '.join(degraded_names)}"],
            "degraded_metrics": degraded_details,
        }

    if degraded_names:
        return {
            "status": "warn",
            "details": [f"Minor SLE degradation: {', '.join(degraded_names)}"],
            "degraded_metrics": degraded_details,
        }

    return {"status": "pass", "details": ["SLE metrics stable"], "degraded_metrics": []}


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
    baseline_conns = _get_topology_connections(baseline)
    latest_conns = _get_topology_connections(latest)

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
    latest_devices = _get_topology_devices(latest)
    for conn in latest_conns:
        local = conn.get("local_device_id", "")
        remote = conn.get("remote_device_id", "")
        vlan_sum = conn.get("vlan_summary", "")
        if local and remote and vlan_sum:
            pair = tuple(sorted([local, remote]))
            if (pair[0], pair[1], vlan_sum) not in baseline_vlan_paths:
                local_name = _device_name_from_topo(latest_devices, local)
                remote_name = _device_name_from_topo(latest_devices, remote)
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
    """For each gateway reachable in baseline, verify BFS path still exists in latest.

    Broken paths = potential traffic black holes.
    """
    baseline = session.topology_baseline
    latest = session.topology_latest

    if not baseline or not latest:
        return {"status": "pass", "details": ["Insufficient topology data for black hole detection"]}

    baseline_devices = _get_topology_devices(baseline)
    latest_devices = _get_topology_devices(latest)
    baseline_conns = _get_topology_connections(baseline)
    latest_conns = _get_topology_connections(latest)

    baseline_gateways = _find_gateways(baseline_devices)
    if not baseline_gateways:
        return {"status": "pass", "details": ["No gateways found in baseline topology"]}

    baseline_adj = _build_adjacency(baseline_conns)
    latest_adj = _build_adjacency(latest_conns)

    # Check all device-to-gateway paths, not just the changed device
    broken_paths: list[dict[str, str]] = []
    for dev_id, dev in baseline_devices.items():
        if dev.get("device_type") == "gateway":
            continue

        for gw_id in baseline_gateways:
            was_reachable = _bfs_path_exists(baseline_adj, dev_id, gw_id)
            if not was_reachable:
                continue

            # Resolve IDs in latest topology via MAC
            dev_mac = dev.get("mac", "")
            dev_latest_id = _find_device_id_by_mac(latest_devices, dev_mac) if dev_mac else None
            if not dev_latest_id and dev_id in latest_devices:
                dev_latest_id = dev_id

            gw_mac = baseline_devices.get(gw_id, {}).get("mac", "")
            gw_latest_id = _find_device_id_by_mac(latest_devices, gw_mac) if gw_mac else None
            if not gw_latest_id and gw_id in latest_devices:
                gw_latest_id = gw_id

            if dev_latest_id and gw_latest_id:
                if not _bfs_path_exists(latest_adj, dev_latest_id, gw_latest_id):
                    broken_paths.append(
                        {
                            "device": _device_name_from_topo(baseline_devices, dev_id),
                            "gateway": _device_name_from_topo(baseline_devices, gw_id),
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
        clients_list = _safe_list(current_clients)
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


# ── Check 7: Alarm Correlation ────────────────────────────────────────────


def _check_alarm_correlation(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Filter alarms from site_data for device_mac. New alarms post-change = flag."""
    current_alarms = _safe_list(getattr(site_data, "alarms", None))
    device_mac = session.device_mac.lower()

    # Filter alarms to those related to the monitored device
    device_alarms: list[dict[str, Any]] = []
    for alarm in current_alarms:
        if not isinstance(alarm, dict):
            continue
        alarm_mac = (alarm.get("mac") or alarm.get("device_mac") or "").lower()
        if alarm_mac == device_mac:
            device_alarms.append(alarm)

    new_alarms: list[dict[str, Any]] = []
    for alarm in device_alarms:
        new_alarms.append(
            {
                "type": alarm.get("type", "unknown"),
                "severity": alarm.get("severity", "info"),
                "count": alarm.get("count", 1),
            }
        )

    if not new_alarms:
        return {"status": "pass", "details": ["No alarms for monitored device"], "new_alarms": []}

    # Determine severity based on alarm severity
    has_critical = any(a.get("severity") == "critical" for a in new_alarms)
    has_warning = any(a.get("severity") in ("warn", "warning", "major") for a in new_alarms)

    if has_critical:
        status = "fail"
    elif has_warning:
        status = "warn"
    else:
        status = "warn"

    alarm_types = [a["type"] for a in new_alarms]
    return {
        "status": status,
        "details": [f"{len(new_alarms)} alarm(s) for device: {', '.join(alarm_types[:5])}"],
        "new_alarms": new_alarms,
    }


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

    baseline_devices = _get_topology_devices(baseline)
    latest_devices = _get_topology_devices(latest)

    # Find the changed device and its neighbors
    device_id_baseline = _find_device_id_by_mac(baseline_devices, session.device_mac)
    device_id_latest = _find_device_id_by_mac(latest_devices, session.device_mac)

    if not device_id_baseline or not device_id_latest:
        return {"status": "pass", "details": ["Changed device not found in topology for DHCP check"]}

    # Get neighbor device IDs from baseline
    baseline_adj = _build_adjacency(_get_topology_connections(baseline))
    device_ids_to_check = {device_id_baseline}
    for neighbor_id in baseline_adj.get(device_id_baseline, []):
        device_ids_to_check.add(neighbor_id)

    # Compare DHCP configs
    dhcp_issues: list[str] = []

    for dev_id in device_ids_to_check:
        baseline_dev = baseline_devices.get(dev_id, {})
        baseline_dhcp = baseline_dev.get("dhcpd_config") if isinstance(baseline_dev, dict) else None

        # Find same device in latest topology by MAC
        dev_mac = baseline_dev.get("mac", "") if isinstance(baseline_dev, dict) else ""
        latest_dev_id = _find_device_id_by_mac(latest_devices, dev_mac) if dev_mac else dev_id
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


# ── Check 10: VC/MCLAG Integrity ─────────────────────────────────────────


def _check_vc_mclag(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Compare VC/MCLAG groups in topology baseline vs latest.

    Member changes, role changes, or ICL link loss = fail.
    """
    baseline = session.topology_baseline
    latest = session.topology_latest
    details: list[str] = []

    if not baseline or not latest:
        return {"status": "pass", "details": ["Insufficient topology data for VC/MCLAG check"]}

    baseline_groups = _get_topology_groups(baseline)
    latest_groups = _get_topology_groups(latest)

    # Index groups by (type, id)
    baseline_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for g in baseline_groups:
        key = (g.get("group_type", ""), g.get("group_id", ""))
        baseline_by_key[key] = g

    latest_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for g in latest_groups:
        key = (g.get("group_type", ""), g.get("group_id", ""))
        latest_by_key[key] = g

    issues: list[str] = []

    # Check for groups that existed in baseline but are missing or changed
    for key, b_group in baseline_by_key.items():
        group_type, group_id = key
        l_group = latest_by_key.get(key)

        if not l_group:
            issues.append(f"{group_type} group '{group_id}' no longer exists")
            continue

        b_members = set(b_group.get("member_ids", []))
        l_members = set(l_group.get("member_ids", []))

        lost_members = b_members - l_members
        new_members = l_members - b_members

        if lost_members:
            issues.append(f"{group_type} '{group_id}' lost members: {', '.join(lost_members)}")
        if new_members:
            details.append(f"{group_type} '{group_id}' gained members: {', '.join(new_members)}")

    # Check for ICL link status changes
    baseline_conns = _get_topology_connections(baseline)
    latest_conns = _get_topology_connections(latest)

    icl_types = {"VC_ICL", "MCLAG_ICL"}

    baseline_icls: dict[tuple[str, str], str] = {}
    for conn in baseline_conns:
        if conn.get("link_type") in icl_types:
            pair = tuple(sorted([conn.get("local_device_id", ""), conn.get("remote_device_id", "")]))
            baseline_icls[pair] = conn.get("status", "UNKNOWN")

    latest_icls: dict[tuple[str, str], str] = {}
    for conn in latest_conns:
        if conn.get("link_type") in icl_types:
            pair = tuple(sorted([conn.get("local_device_id", ""), conn.get("remote_device_id", "")]))
            latest_icls[pair] = conn.get("status", "UNKNOWN")

    for pair, b_status in baseline_icls.items():
        l_status = latest_icls.get(pair)
        if l_status is None:
            issues.append(f"ICL link lost between {pair[0]} and {pair[1]}")
        elif b_status == "UP" and l_status != "UP":
            issues.append(f"ICL link degraded between {pair[0]} and {pair[1]}: {b_status} -> {l_status}")

    if issues:
        return {"status": "fail", "details": issues}

    if details:
        return {"status": "warn", "details": details}

    return {"status": "pass", "details": ["VC/MCLAG integrity maintained"]}


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

    # Also check config_events from site_data for routing events
    config_events = _safe_list(getattr(site_data, "config_events", None))
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
        baseline_conns = _get_topology_connections(baseline)
        latest_conns = _get_topology_connections(latest)

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


def _check_config_drift(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Check device_configs for the device_mac.

    Flag if applied config differs from last known good.
    """
    device_configs = _safe_list(getattr(site_data, "device_configs", None))
    device_mac = session.device_mac.lower()

    # Find configs for our device
    device_config_entries: list[dict[str, Any]] = []
    for config_entry in device_configs:
        if not isinstance(config_entry, dict):
            continue
        config_mac = (config_entry.get("mac") or config_entry.get("device_mac") or "").lower()
        if config_mac == device_mac:
            device_config_entries.append(config_entry)

    if not device_config_entries:
        return {"status": "pass", "details": ["No config data available for drift detection"], "drifted_fields": []}

    drifted_fields: list[str] = []

    # Check for config change indicators
    for entry in device_config_entries:
        # Look for config status indicators
        config_status = entry.get("status", "")
        if config_status in ("failed", "error"):
            drifted_fields.append(f"Config application status: {config_status}")

        # Check for config_changed_by_user events (indicates manual override)
        change_type = entry.get("type", "")
        if "CONFIG_CHANGED_BY_USER" in change_type:
            drifted_fields.append(f"Manual config change detected: {change_type}")

        # Compare pushed vs applied config if available
        pushed = entry.get("config_pushed")
        applied = entry.get("config_applied")
        if pushed and applied and pushed != applied:
            drifted_fields.append("Applied config differs from pushed config")

    if drifted_fields:
        return {
            "status": "warn",
            "details": drifted_fields,
            "drifted_fields": drifted_fields,
        }

    return {"status": "pass", "details": ["Config consistent with expected state"], "drifted_fields": []}


# ── Check 13: PoE Budget ─────────────────────────────────────────────────


def _check_poe_budget(session: MonitoringSession, site_data: Any) -> dict[str, Any]:
    """Check port_stats for PoE data on switches.

    Flag budget changes or PoE-related issues.
    """
    port_stats = _safe_list(getattr(site_data, "port_stats", None))
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

    # Also check alarms for PoE-related alarms
    alarms = _safe_list(getattr(site_data, "alarms", None))
    for alarm in alarms:
        if not isinstance(alarm, dict):
            continue
        alarm_mac = (alarm.get("mac") or alarm.get("device_mac") or "").lower()
        alarm_type = (alarm.get("type") or "").lower()
        if alarm_mac == device_mac and "poe" in alarm_type:
            poe_issues.append(f"PoE alarm: {alarm.get('type', 'unknown')}")

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
    device_stats = _safe_list(getattr(site_data, "device_stats", None))
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
        port_stats = _safe_list(getattr(site_data, "port_stats", None))
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
