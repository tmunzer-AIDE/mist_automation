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
from app.modules.digital_twin.services.topology_utils import resolve_vlan_id


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


def _extract_peer_ip(peer_info: dict[str, Any]) -> str:
    """Extract peer IP from heterogeneous telemetry field names."""
    for key in ("peer_ip", "neighbor_ip", "peer", "neighbor", "ip"):
        value = peer_info.get(key)
        if value:
            return str(value)
    return ""


def _network_requires_gateway(net_cfg: dict[str, Any]) -> bool:
    """Return True when a network config appears to require L3 gatewaying.

    Keep this conservative to avoid false positives on intentional L2-only
    VLANs: only treat a network as routed when an L3 indicator is present.
    """
    if not isinstance(net_cfg, dict):
        return False
    subnet = net_cfg.get("subnet")
    if subnet:
        return True
    for key in ("gateway", "ip_start", "ip_end", "prefix_length", "netmask"):
        if net_cfg.get(key):
            return True
    return False


def _wlan_vlan_context(snapshot: SiteSnapshot) -> tuple[dict[int, list[str]], list[str]]:
    """Return WLAN names grouped by explicit VLAN plus implicit-VLAN WLAN names.

    WLANs without a resolvable ``vlan_id`` are tracked separately because they
    may ride native/default VLAN behavior depending on AP uplink and switchport
    configuration.
    """
    vars_map = snapshot.site_setting.get("vars") or {}
    vlan_to_wlans: dict[int, list[str]] = {}
    implicit_wlans: list[str] = []

    for wlan in snapshot.wlans.values():
        if not wlan.get("enabled", True):
            continue
        name = str(wlan.get("ssid") or wlan.get("name") or "").strip()
        if not name:
            continue

        vid = resolve_vlan_id(wlan.get("vlan_id"), vars_map)
        if vid is None:
            implicit_wlans.append(name)
            continue

        vlan_to_wlans.setdefault(vid, []).append(name)

    for names in vlan_to_wlans.values():
        names.sort()
    implicit_wlans.sort()
    return vlan_to_wlans, implicit_wlans


def _format_route_gw_detail(
    network_name: str,
    network_cfg: dict[str, Any],
    vars_map: dict[str, Any],
    wlan_names_by_vlan: dict[int, list[str]],
    implicit_vlan_wlans: list[str],
) -> str:
    """Render a ROUTE-GW detail with VLAN/WLAN context for operators."""
    parts: list[str] = [f"Network '{network_name}' has no gateway L3 interface"]

    network_vlan = resolve_vlan_id(network_cfg.get("vlan_id"), vars_map)
    if network_vlan is None:
        parts.append("network VLAN is undefined")
    else:
        parts.append(f"network VLAN={network_vlan}")
        tied_wlans = wlan_names_by_vlan.get(network_vlan, [])
        if tied_wlans:
            parts.append(f"referenced by WLAN(s): {', '.join(tied_wlans)}")

    if implicit_vlan_wlans:
        parts.append(
            "WLAN(s) with implicit vlan_id may map through native/default VLAN: "
            f"{', '.join(implicit_vlan_wlans)}"
        )

    return "; ".join(parts)


# ---------------------------------------------------------------------------
# ROUTE-GW: Default Gateway Gap — Layer 3, error
# ---------------------------------------------------------------------------


def _check_route_gw(predicted: SiteSnapshot) -> CheckResult:
    """Detect networks that have no gateway L3 interface in the predicted state.

    Collects all network names from predicted.networks, then checks whether
    any gateway device has an ip_config entry keyed by that network name.
    """
    # Collect routed network names only; intentional L2-only networks are
    # excluded to avoid false positives.
    routed_networks: dict[str, dict[str, Any]] = {}
    for _net_id, net_cfg in predicted.networks.items():
        name = net_cfg.get("name", "")
        if name and _network_requires_gateway(net_cfg):
            routed_networks.setdefault(name, net_cfg)
    network_names = set(routed_networks)

    if not network_names:
        return CheckResult(
            check_id="ROUTE-GW",
            check_name="Default Gateway Gap",
            layer=3,
            status="pass",
            summary="No routed networks defined -- gateway check not applicable.",
            description="Detects routed networks (with subnet/gateway config) that have no corresponding L3 interface on any gateway device.",
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
            description="Detects routed networks (with subnet/gateway config) that have no corresponding L3 interface on any gateway device.",
        )

    vars_map = predicted.site_setting.get("vars") or {}
    wlan_names_by_vlan, implicit_vlan_wlans = _wlan_vlan_context(predicted)

    details: list[str] = []
    affected_objects: list[str] = []
    for name in sorted(missing):
        details.append(
            _format_route_gw_detail(
                network_name=name,
                network_cfg=routed_networks.get(name, {}),
                vars_map=vars_map,
                wlan_names_by_vlan=wlan_names_by_vlan,
                implicit_vlan_wlans=implicit_vlan_wlans,
            )
        )
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
        description="Detects routed networks (with subnet/gateway config) that have no corresponding L3 interface on any gateway device.",
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
        has_ospf_config = any(
            dev.type == "gateway" and bool(dev.ospf_config)
            for dev in list(baseline.devices.values()) + list(predicted.devices.values())
        )
        if has_ospf_config:
            return CheckResult(
                check_id="ROUTE-OSPF",
                check_name="OSPF Adjacency Break",
                layer=3,
                status="skipped",
                summary="OSPF appears configured but live peer telemetry is unavailable.",
                affected_sites=[baseline.site_id],
                remediation_hint=(
                    "Ensure live telemetry exposes OSPF peers (peer_ip), then re-run simulation."
                ),
                description="Checks that OSPF peer IPs from live telemetry remain reachable within the predicted gateway interface subnets.",
            )
        return CheckResult(
            check_id="ROUTE-OSPF",
            check_name="OSPF Adjacency Break",
            layer=3,
            status="pass",
            summary="No OSPF peers in baseline -- check not applicable.",
            description="Checks that OSPF peer IPs from live telemetry remain reachable within the predicted gateway interface subnets.",
        )

    breaks: list[str] = []
    affected_objects: list[str] = []

    for device_id, peers in baseline.ospf_peers.items():
        dev = baseline.devices.get(device_id)
        dev_name = dev.name if dev else device_id
        predicted_dev = predicted.devices.get(device_id)

        if predicted_dev is None:
            for peer_info in peers:
                peer_ip = _extract_peer_ip(peer_info)
                if peer_ip:
                    breaks.append(f"{dev_name}: OSPF peer {peer_ip} is unreachable (device removed)")
            if device_id not in affected_objects:
                affected_objects.append(device_id)
            continue

        for peer_info in peers:
            peer_ip = _extract_peer_ip(peer_info)
            if not peer_ip:
                continue
            if not _peer_reachable(peer_ip, predicted_dev.ip_config):
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
            description="Checks that OSPF peer IPs from live telemetry remain reachable within the predicted gateway interface subnets.",
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
        description="Checks that OSPF peer IPs from live telemetry remain reachable within the predicted gateway interface subnets.",
    )


# ---------------------------------------------------------------------------
# ROUTE-BGP: BGP Adjacency Break — Layer 3, critical
# ---------------------------------------------------------------------------


def _check_route_bgp(baseline: SiteSnapshot, predicted: SiteSnapshot) -> CheckResult:
    """Detect BGP adjacency breaks caused by IP changes in predicted state.

    Same logic as OSPF but using baseline.bgp_peers.
    """
    if not baseline.bgp_peers:
        has_bgp_config = any(
            dev.type == "gateway" and bool(dev.bgp_config)
            for dev in list(baseline.devices.values()) + list(predicted.devices.values())
        )
        if has_bgp_config:
            return CheckResult(
                check_id="ROUTE-BGP",
                check_name="BGP Adjacency Break",
                layer=3,
                status="skipped",
                summary="BGP appears configured but live peer telemetry is unavailable.",
                affected_sites=[baseline.site_id],
                remediation_hint=(
                    "Ensure live telemetry exposes BGP peers (peer_ip), then re-run simulation."
                ),
                description="Checks that BGP peer IPs from live telemetry remain reachable within the predicted gateway interface subnets.",
            )
        return CheckResult(
            check_id="ROUTE-BGP",
            check_name="BGP Adjacency Break",
            layer=3,
            status="pass",
            summary="No BGP peers in baseline -- check not applicable.",
            description="Checks that BGP peer IPs from live telemetry remain reachable within the predicted gateway interface subnets.",
        )

    breaks: list[str] = []
    affected_objects: list[str] = []

    for device_id, peers in baseline.bgp_peers.items():
        dev = baseline.devices.get(device_id)
        dev_name = dev.name if dev else device_id
        predicted_dev = predicted.devices.get(device_id)

        if predicted_dev is None:
            for peer_info in peers:
                peer_ip = _extract_peer_ip(peer_info)
                if peer_ip:
                    breaks.append(f"{dev_name}: BGP peer {peer_ip} is unreachable (device removed)")
            if device_id not in affected_objects:
                affected_objects.append(device_id)
            continue

        for peer_info in peers:
            peer_ip = _extract_peer_ip(peer_info)
            if not peer_ip:
                continue
            if not _peer_reachable(peer_ip, predicted_dev.ip_config):
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
            description="Checks that BGP peer IPs from live telemetry remain reachable within the predicted gateway interface subnets.",
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
        description="Checks that BGP peer IPs from live telemetry remain reachable within the predicted gateway interface subnets.",
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
            description="Detects WAN ports removed from gateway devices, which reduces redundancy and available bandwidth.",
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
        description="Detects WAN ports removed from gateway devices, which reduces redundancy and available bandwidth.",
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
