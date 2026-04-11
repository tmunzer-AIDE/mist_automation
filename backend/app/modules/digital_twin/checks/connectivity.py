"""
Connectivity checks: physical reachability and VLAN gateway reachability.

CONN-PHYS — Detect devices that become isolated from all gateways.
CONN-VLAN — Detect VLANs that lose their gateway L3 interface.

All functions are pure — no async, no DB access.
"""

from __future__ import annotations

import networkx as nx

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.site_graph import SiteGraph, build_site_graph
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reachable_from_gateways(graph: SiteGraph) -> set[str]:
    """Return the set of MACs reachable from any gateway in the physical graph."""
    reachable: set[str] = set()
    for gw_mac in graph.gateways:
        if gw_mac in graph.physical.nodes:
            reachable |= nx.node_connected_component(graph.physical, gw_mac)
    return reachable


def _vlan_id_to_network_names(snapshot: SiteSnapshot) -> dict[int, list[str]]:
    """Build a reverse mapping from VLAN ID -> list of network names."""
    mapping: dict[int, list[str]] = {}
    for _net_id, net_cfg in snapshot.networks.items():
        name = net_cfg.get("name", "")
        vlan_id = net_cfg.get("vlan_id")
        if name and vlan_id is not None:
            try:
                vid = int(vlan_id)
            except (TypeError, ValueError):
                continue
            mapping.setdefault(vid, []).append(name)
    return mapping


def _all_gateway_vlans(graph: SiteGraph) -> set[int]:
    """Return the union of all VLANs that have at least one gateway L3 interface."""
    result: set[int] = set()
    for vlans in graph.gateway_vlans.values():
        result |= vlans
    return result


# ---------------------------------------------------------------------------
# CONN-PHYS: Physical Connectivity Loss
# ---------------------------------------------------------------------------


def _check_conn_phys(
    baseline: SiteSnapshot,
    predicted: SiteSnapshot,
    baseline_graph: SiteGraph,
    predicted_graph: SiteGraph,
) -> CheckResult:
    """Detect devices newly isolated from all gateways after the change."""
    if not baseline_graph.gateways and not predicted_graph.gateways:
        return CheckResult(
            check_id="CONN-PHYS",
            check_name="Physical connectivity loss",
            layer=2,
            status="skipped",
            summary="No gateways in topology -- connectivity check not applicable.",
        )

    baseline_reachable = _reachable_from_gateways(baseline_graph)
    predicted_reachable = _reachable_from_gateways(predicted_graph)

    # Nodes reachable before but not after = newly isolated
    newly_isolated = baseline_reachable - predicted_reachable - baseline_graph.gateways - predicted_graph.gateways

    if not newly_isolated:
        return CheckResult(
            check_id="CONN-PHYS",
            check_name="Physical connectivity loss",
            layer=2,
            status="pass",
            summary="All devices retain gateway reachability.",
        )

    details: list[str] = []
    affected_objects: list[str] = []
    has_critical = False

    for mac in sorted(newly_isolated):
        node_data = baseline_graph.physical.nodes.get(mac, {})
        name = node_data.get("name", mac)
        dtype = node_data.get("type", "unknown")
        device_id = node_data.get("device_id", "")

        if device_id:
            affected_objects.append(device_id)

        # Determine if this is a high-impact isolation
        client_count = baseline.ap_clients.get(device_id, 0)
        if dtype == "switch":
            has_critical = True
            details.append(f"{name} ({dtype}) isolated from all gateways")
        elif dtype == "ap" and client_count > 0:
            has_critical = True
            details.append(f"{name} ({dtype}, {client_count} clients) isolated from all gateways")
        else:
            details.append(f"{name} ({dtype}) isolated from all gateways")

    status = "critical" if has_critical else "error"

    return CheckResult(
        check_id="CONN-PHYS",
        check_name="Physical connectivity loss",
        layer=2,
        status=status,
        summary=f"{len(newly_isolated)} device(s) lost gateway reachability.",
        details=details,
        affected_objects=affected_objects,
        affected_sites=[baseline.site_id],
        remediation_hint="Verify that uplink connections are maintained or add an alternate path.",
    )


# ---------------------------------------------------------------------------
# CONN-VLAN: VLAN Gateway Reachability
# ---------------------------------------------------------------------------


def _check_conn_vlan(
    baseline: SiteSnapshot,
    predicted: SiteSnapshot,
    baseline_graph: SiteGraph,
    predicted_graph: SiteGraph,
) -> CheckResult:
    """Detect VLANs that had gateway L3 interfaces in baseline but not in predicted."""
    baseline_gw_vlans = _all_gateway_vlans(baseline_graph)
    predicted_gw_vlans = _all_gateway_vlans(predicted_graph)

    lost_vlans = baseline_gw_vlans - predicted_gw_vlans

    if not lost_vlans:
        return CheckResult(
            check_id="CONN-VLAN",
            check_name="VLAN gateway reachability",
            layer=2,
            status="pass",
            summary="All VLANs retain gateway L3 interfaces.",
        )

    # Map VLAN IDs back to network names for readable output
    vlan_to_names = _vlan_id_to_network_names(baseline)

    details: list[str] = []
    affected_objects: list[str] = []

    for vid in sorted(lost_vlans):
        names = vlan_to_names.get(vid, [])
        if names:
            label = ", ".join(sorted(names))
            details.append(f"VLAN {vid} ({label}) lost all gateway L3 interfaces")
        else:
            details.append(f"VLAN {vid} lost all gateway L3 interfaces")
        affected_objects.append(f"vlan-{vid}")

    return CheckResult(
        check_id="CONN-VLAN",
        check_name="VLAN gateway reachability",
        layer=2,
        status="critical",
        summary=f"{len(lost_vlans)} VLAN(s) lost gateway L3 reachability.",
        details=details,
        affected_objects=affected_objects,
        affected_sites=[baseline.site_id],
        remediation_hint="Ensure gateway retains ip_config entries for all required VLANs.",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def check_connectivity(baseline: SiteSnapshot, predicted: SiteSnapshot) -> list[CheckResult]:
    """Run all connectivity checks (CONN-PHYS + CONN-VLAN).

    Builds SiteGraphs from both snapshots, then runs each sub-check.
    """
    baseline_graph = build_site_graph(baseline)
    predicted_graph = build_site_graph(predicted)

    return [
        _check_conn_phys(baseline, predicted, baseline_graph, predicted_graph),
        _check_conn_vlan(baseline, predicted, baseline_graph, predicted_graph),
    ]
