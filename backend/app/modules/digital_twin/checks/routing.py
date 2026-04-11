"""
Routing checks operating on baseline vs predicted SiteSnapshot pairs.

All functions are pure — no async, no DB access.

Checks:
  ROUTE-GW   — Default Gateway Gap (network without gateway L3 interface)
  ROUTE-OSPF — OSPF Adjacency Break (peer IP unreachable after change)
  ROUTE-BGP  — BGP Adjacency Break (peer IP unreachable after change)
  ROUTE-WAN  — WAN Failover Impact (removed WAN links on gateways)
"""

from __future__ import annotations

import ipaddress
from typing import Any

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _peer_reachable(peer_ip: str, ip_configs: dict[str, dict[str, Any]]) -> bool:
    """Check if peer_ip falls within any configured interface subnet.

    Builds an ipaddress.ip_network from each ip_config entry's ip + netmask,
    then checks if peer_ip is contained within it.
    """
    try:
        peer = ipaddress.ip_address(peer_ip)
    except (ValueError, TypeError):
        return False

    for _iface_name, cfg in ip_configs.items():
        ip_str = cfg.get("ip")
        netmask = cfg.get("netmask")
        if not ip_str or not netmask:
            continue
        try:
            iface = ipaddress.ip_interface(f"{ip_str}/{netmask}")
            if peer in iface.network:
                return True
        except (ValueError, TypeError):
            continue

    return False


def _collect_all_ip_configs(snap: SiteSnapshot) -> dict[str, dict[str, Any]]:
    """Merge ip_config from all devices in the snapshot into a single dict.

    Returns a flat dict: "device_name/iface_name" -> {ip, netmask, ...}.
    """
    merged: dict[str, dict[str, Any]] = {}
    for _dev_id, dev in snap.devices.items():
        for iface_name, cfg in dev.ip_config.items():
            key = f"{dev.name}/{iface_name}"
            merged[key] = cfg
    return merged


# ---------------------------------------------------------------------------
# ROUTE-GW: Default Gateway Gap — Layer 3, error
# ---------------------------------------------------------------------------


def _check_route_gw(predicted: SiteSnapshot) -> CheckResult:
    """Detect networks that have no gateway L3 interface in the predicted state.

    Collects all network names from predicted.networks, then checks whether
    any gateway device has an ip_config entry keyed by that network name.
    """
    # Collect all network names
    network_names: set[str] = set()
    for _net_id, net_cfg in predicted.networks.items():
        name = net_cfg.get("name", "")
        if name:
            network_names.add(name)

    if not network_names:
        return CheckResult(
            check_id="ROUTE-GW",
            check_name="Default Gateway Gap",
            layer=3,
            status="pass",
            summary="No networks defined -- gateway check not applicable.",
        )

    # Collect network names that have a gateway L3 interface
    gateway_covered: set[str] = set()
    for _dev_id, dev in predicted.devices.items():
        if dev.type != "gateway":
            continue
        for iface_name in dev.ip_config:
            gateway_covered.add(iface_name)

    missing = network_names - gateway_covered

    if not missing:
        return CheckResult(
            check_id="ROUTE-GW",
            check_name="Default Gateway Gap",
            layer=3,
            status="pass",
            summary="All networks have a gateway L3 interface.",
        )

    details: list[str] = []
    affected_objects: list[str] = []
    for name in sorted(missing):
        details.append(f"Network '{name}' has no gateway L3 interface")
        affected_objects.append(name)

    return CheckResult(
        check_id="ROUTE-GW",
        check_name="Default Gateway Gap",
        layer=3,
        status="error",
        summary=f"{len(missing)} network(s) missing a gateway L3 interface.",
        details=details,
        affected_objects=affected_objects,
        affected_sites=[predicted.site_id],
        remediation_hint="Add ip_config entries on a gateway device for each network that requires L3 routing.",
    )


# ---------------------------------------------------------------------------
# ROUTE-OSPF: OSPF Adjacency Break — Layer 3, critical
# ---------------------------------------------------------------------------


def _check_route_ospf(baseline: SiteSnapshot, predicted: SiteSnapshot) -> CheckResult:
    """Detect OSPF adjacency breaks caused by IP changes in predicted state.

    For each device_id in baseline.ospf_peers, check each peer's peer_ip
    against all predicted device ip_configs. If a peer_ip is no longer
    reachable from any subnet, flag the break.
    """
    if not baseline.ospf_peers:
        return CheckResult(
            check_id="ROUTE-OSPF",
            check_name="OSPF Adjacency Break",
            layer=3,
            status="pass",
            summary="No OSPF peers in baseline -- check not applicable.",
        )

    all_ip_configs = _collect_all_ip_configs(predicted)
    breaks: list[str] = []
    affected_objects: list[str] = []

    for device_id, peers in baseline.ospf_peers.items():
        dev = baseline.devices.get(device_id)
        dev_name = dev.name if dev else device_id

        for peer_info in peers:
            peer_ip = peer_info.get("peer_ip")
            if not peer_ip:
                continue
            if not _peer_reachable(peer_ip, all_ip_configs):
                breaks.append(f"{dev_name}: OSPF peer {peer_ip} is no longer reachable from any interface")
                if device_id not in affected_objects:
                    affected_objects.append(device_id)

    if not breaks:
        return CheckResult(
            check_id="ROUTE-OSPF",
            check_name="OSPF Adjacency Break",
            layer=3,
            status="pass",
            summary="All OSPF peer IPs remain reachable.",
        )

    return CheckResult(
        check_id="ROUTE-OSPF",
        check_name="OSPF Adjacency Break",
        layer=3,
        status="critical",
        summary=f"{len(breaks)} OSPF adjacency break(s) detected.",
        details=breaks,
        affected_objects=affected_objects,
        affected_sites=[baseline.site_id],
        remediation_hint="Verify that interface IP changes do not remove subnets used by OSPF peers.",
    )


# ---------------------------------------------------------------------------
# ROUTE-BGP: BGP Adjacency Break — Layer 3, critical
# ---------------------------------------------------------------------------


def _check_route_bgp(baseline: SiteSnapshot, predicted: SiteSnapshot) -> CheckResult:
    """Detect BGP adjacency breaks caused by IP changes in predicted state.

    Same logic as OSPF but using baseline.bgp_peers.
    """
    if not baseline.bgp_peers:
        return CheckResult(
            check_id="ROUTE-BGP",
            check_name="BGP Adjacency Break",
            layer=3,
            status="pass",
            summary="No BGP peers in baseline -- check not applicable.",
        )

    all_ip_configs = _collect_all_ip_configs(predicted)
    breaks: list[str] = []
    affected_objects: list[str] = []

    for device_id, peers in baseline.bgp_peers.items():
        dev = baseline.devices.get(device_id)
        dev_name = dev.name if dev else device_id

        for peer_info in peers:
            peer_ip = peer_info.get("peer_ip")
            if not peer_ip:
                continue
            if not _peer_reachable(peer_ip, all_ip_configs):
                breaks.append(f"{dev_name}: BGP peer {peer_ip} is no longer reachable from any interface")
                if device_id not in affected_objects:
                    affected_objects.append(device_id)

    if not breaks:
        return CheckResult(
            check_id="ROUTE-BGP",
            check_name="BGP Adjacency Break",
            layer=3,
            status="pass",
            summary="All BGP peer IPs remain reachable.",
        )

    return CheckResult(
        check_id="ROUTE-BGP",
        check_name="BGP Adjacency Break",
        layer=3,
        status="critical",
        summary=f"{len(breaks)} BGP adjacency break(s) detected.",
        details=breaks,
        affected_objects=affected_objects,
        affected_sites=[baseline.site_id],
        remediation_hint="Verify that interface IP changes do not remove subnets used by BGP peers.",
    )


# ---------------------------------------------------------------------------
# ROUTE-WAN: WAN Failover Impact — Layer 3, warning/error
# ---------------------------------------------------------------------------


def _check_route_wan(baseline: SiteSnapshot, predicted: SiteSnapshot) -> CheckResult:
    """Detect removed WAN links on gateway devices.

    Compares port_config entries with usage == "wan" between baseline and
    predicted for each gateway device. Flags removed WAN links.

    Severity: warning if 1 link removed, error if multiple.
    """
    removed_details: list[str] = []
    affected_objects: list[str] = []

    for dev_id, baseline_dev in baseline.devices.items():
        if baseline_dev.type != "gateway":
            continue

        predicted_dev = predicted.devices.get(dev_id)
        if predicted_dev is None:
            # Device removed entirely -- handled by other checks
            continue

        # Find WAN ports in baseline
        baseline_wan_ports: dict[str, dict[str, Any]] = {}
        for port_name, port_cfg in baseline_dev.port_config.items():
            if port_cfg.get("usage") == "wan":
                baseline_wan_ports[port_name] = port_cfg

        # Find WAN ports in predicted
        predicted_wan_ports: set[str] = set()
        for port_name, port_cfg in predicted_dev.port_config.items():
            if port_cfg.get("usage") == "wan":
                predicted_wan_ports.add(port_name)

        # Detect removed WAN links
        for port_name, port_cfg in baseline_wan_ports.items():
            if port_name not in predicted_wan_ports:
                wan_type = port_cfg.get("wan_type", "unknown")
                removed_details.append(
                    f"{baseline_dev.name} port {port_name}: WAN link removed (wan_type={wan_type})"
                )
                if dev_id not in affected_objects:
                    affected_objects.append(dev_id)

    if not removed_details:
        return CheckResult(
            check_id="ROUTE-WAN",
            check_name="WAN Failover Impact",
            layer=3,
            status="pass",
            summary="No WAN links removed from gateway devices.",
        )

    status = "warning" if len(removed_details) == 1 else "error"

    return CheckResult(
        check_id="ROUTE-WAN",
        check_name="WAN Failover Impact",
        layer=3,
        status=status,
        summary=f"{len(removed_details)} WAN link(s) removed from gateway device(s).",
        details=removed_details,
        affected_objects=affected_objects,
        affected_sites=[baseline.site_id],
        remediation_hint="Verify that remaining WAN links provide sufficient redundancy and bandwidth.",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def check_routing(baseline: SiteSnapshot, predicted: SiteSnapshot) -> list[CheckResult]:
    """Run all routing checks (ROUTE-GW, ROUTE-OSPF, ROUTE-BGP, ROUTE-WAN).

    Returns a list of CheckResult items (one per check).
    """
    return [
        _check_route_gw(predicted),
        _check_route_ospf(baseline, predicted),
        _check_route_bgp(baseline, predicted),
        _check_route_wan(baseline, predicted),
    ]
