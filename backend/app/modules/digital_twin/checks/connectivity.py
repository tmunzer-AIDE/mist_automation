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


def _vlan_id_to_wlan_names(snapshot: SiteSnapshot) -> dict[int, list[str]]:
    """Build a reverse mapping from VLAN ID -> list of WLAN SSIDs/names.

    Used by CONN-VLAN-PATH to label affected VLANs with the WLAN(s) that
    ride on them, so messages like ``VLAN 10 (Guest/Corp)`` are obvious to
    operators.
    """
    mapping: dict[int, list[str]] = {}
    for wlan in snapshot.wlans.values():
        name = wlan.get("ssid") or wlan.get("name") or ""
        vid = wlan.get("vlan_id")
        if not name or vid is None:
            continue
        try:
            key = int(vid)
        except (TypeError, ValueError):
            continue
        mapping.setdefault(key, []).append(name)
    return mapping


def _all_gateway_vlans(graph: SiteGraph) -> set[int]:
    """Return the union of all VLANs that have at least one gateway L3 interface."""
    result: set[int] = set()
    for vlans in graph.gateway_vlans.values():
        result |= vlans
    return result


def _reachable_in_vlan_subgraph(vlan_graph: nx.Graph, gateways: set[str]) -> set[str]:
    """Return MACs reachable from any gateway within a single VLAN subgraph."""
    reachable: set[str] = set()
    for gw_mac in gateways:
        if gw_mac in vlan_graph.nodes:
            reachable |= nx.node_connected_component(vlan_graph, gw_mac)
    return reachable


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
# CONN-VLAN-PATH: Per-VLAN gateway path reachability
# ---------------------------------------------------------------------------


def _check_conn_vlan_path(
    baseline: SiteSnapshot,
    predicted: SiteSnapshot,
    baseline_graph: SiteGraph,
    predicted_graph: SiteGraph,
) -> CheckResult:
    """Detect devices that lost gateway reachability inside a VLAN subgraph.

    For each VLAN present in both baseline and predicted, compute the set of
    device MACs that are connected to any gateway within that VLAN's nx
    subgraph. Any device that was reachable in baseline but not in predicted is
    treated as blackholed inside that VLAN. This is the canonical detection for
    "a port profile change on an AP uplink removes the AP's WLAN VLAN from the
    switchport trunk" — the AP and its clients can no longer reach the gateway
    on that VLAN even though the physical link is still up.

    Status:
        - ``critical`` when any AP is affected (wireless blackhole)
        - ``error`` otherwise (switch or other device lost a VLAN path)
        - ``pass`` when every baseline-reachable device is still reachable

    Fallback mode:
        When a VLAN graph has no gateway node, we still detect VLAN path loss
        by checking baseline VLAN edges that disappear in predicted while the
        physical LLDP edge remains up. This catches inter-switch trunk changes
        that silently drop VLAN carriage on still-up links.
    """
    baseline_vlans = baseline_graph.vlan_graphs
    predicted_vlans = predicted_graph.vlan_graphs

    vlan_ids = sorted(set(baseline_vlans) & set(predicted_vlans))
    if not vlan_ids:
        return CheckResult(
            check_id="CONN-VLAN-PATH",
            check_name="Per-VLAN gateway path reachability",
            layer=2,
            status="pass",
            summary="No VLAN subgraphs to compare.",
        )

    vlan_to_names = _vlan_id_to_network_names(baseline)
    vlan_to_wlan_names = _vlan_id_to_wlan_names(baseline)

    details: list[str] = []
    affected_objects: list[str] = []
    affected_macs: set[str] = set()
    has_ap_impact = False
    seen_edge_losses: set[tuple[int, str, str]] = set()

    mac_to_device_id = {
        dev.mac: dev.device_id
        for dev in baseline.devices.values()
        if dev.mac and dev.device_id
    }

    def _vlan_label(vid: int) -> str:
        label_parts: list[str] = []
        net_names = vlan_to_names.get(vid, [])
        if net_names:
            label_parts.append("/".join(sorted(net_names)))
        wlan_names = vlan_to_wlan_names.get(vid, [])
        if wlan_names:
            label_parts.append(f"WLAN {'/'.join(sorted(wlan_names))}")
        label = f"VLAN {vid}"
        if label_parts:
            label += f" ({', '.join(label_parts)})"
        return label

    for vid in vlan_ids:
        b_graph = baseline_vlans[vid]
        p_graph = predicted_vlans[vid]

        b_reachable = _reachable_in_vlan_subgraph(b_graph, baseline_graph.gateways)
        p_reachable = _reachable_in_vlan_subgraph(p_graph, predicted_graph.gateways)

        lost = b_reachable - p_reachable - baseline_graph.gateways - predicted_graph.gateways
        label = _vlan_label(vid)

        if lost:
            for mac in sorted(lost):
                node_data = b_graph.nodes.get(mac) or baseline_graph.physical.nodes.get(mac, {})
                name = node_data.get("name") or mac
                dtype = node_data.get("type", "unknown")
                device_id = node_data.get("device_id", "")
                details.append(f"{name} ({dtype}) lost gateway path on {label}")
                if device_id and device_id not in affected_objects:
                    affected_objects.append(device_id)
                affected_macs.add(mac)
                if dtype == "ap":
                    has_ap_impact = True

        # Fallback path-loss detection when no gateway participates in this VLAN.
        has_baseline_gateway_anchor = any(gw in b_graph.nodes for gw in baseline_graph.gateways)
        if has_baseline_gateway_anchor:
            continue

        for u, v in b_graph.edges:
            edge_key = tuple(sorted((u, v)))
            if p_graph.has_edge(u, v) or p_graph.has_edge(v, u):
                continue
            if not predicted_graph.physical.has_edge(u, v):
                # Physical link also down; CONN-PHYS already captures this.
                continue
            if (vid, edge_key[0], edge_key[1]) in seen_edge_losses:
                continue
            seen_edge_losses.add((vid, edge_key[0], edge_key[1]))

            u_node = b_graph.nodes.get(u) or baseline_graph.physical.nodes.get(u, {})
            v_node = b_graph.nodes.get(v) or baseline_graph.physical.nodes.get(v, {})
            u_name = u_node.get("name") or u
            v_name = v_node.get("name") or v
            u_type = u_node.get("type", "unknown")
            v_type = v_node.get("type", "unknown")

            details.append(f"{u_name} ({u_type}) <-> {v_name} ({v_type}) lost L2 path on {label}")

            for mac in (u, v):
                if mac not in affected_macs:
                    affected_macs.add(mac)
                dev_id = mac_to_device_id.get(mac)
                if dev_id and dev_id not in affected_objects:
                    affected_objects.append(dev_id)

            if u_type == "ap" or v_type == "ap":
                has_ap_impact = True

    if not details:
        return CheckResult(
            check_id="CONN-VLAN-PATH",
            check_name="Per-VLAN gateway path reachability",
            layer=2,
            status="pass",
            summary="All VLANs retain device-to-gateway L2 paths.",
        )

    return CheckResult(
        check_id="CONN-VLAN-PATH",
        check_name="Per-VLAN gateway path reachability",
        layer=2,
        status="critical" if has_ap_impact else "error",
        summary=(f"{len(affected_macs)} device(s) lost gateway reachability on one or more VLANs."),
        details=details,
        affected_objects=affected_objects,
        affected_sites=[baseline.site_id],
        remediation_hint=(
            "Verify switch port profiles still trunk every VLAN that the "
            "downstream APs / devices require. Changing an AP-facing port to a "
            "profile that omits a WLAN's VLAN will blackhole clients on that WLAN."
        ),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def check_connectivity(baseline: SiteSnapshot, predicted: SiteSnapshot) -> list[CheckResult]:
    """Run all connectivity checks (CONN-PHYS + CONN-VLAN + CONN-VLAN-PATH).

    Builds SiteGraphs from both snapshots, then runs each sub-check.
    """
    baseline_graph = build_site_graph(baseline)
    predicted_graph = build_site_graph(predicted)

    return [
        _check_conn_phys(baseline, predicted, baseline_graph, predicted_graph),
        _check_conn_vlan(baseline, predicted, baseline_graph, predicted_graph),
        _check_conn_vlan_path(baseline, predicted, baseline_graph, predicted_graph),
    ]
