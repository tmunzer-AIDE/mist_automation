"""
Layer 3 routing validation checks for the Digital Twin module.

All functions are pure — no async, no DB access.
Each returns a CheckResult with check_id, status, summary, details, and remediation_hint.
"""

from __future__ import annotations

import ipaddress

from app.modules.digital_twin.models import CheckResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ip_in_subnet(ip: str, network_ip: str, netmask: str) -> bool:
    """Return True if *ip* is within the subnet defined by network_ip/netmask."""
    try:
        net = ipaddress.IPv4Network(f"{network_ip}/{netmask}", strict=False)
        return ipaddress.IPv4Address(ip) in net
    except (ValueError, TypeError):
        return False


def _peer_reachable(peer_ip: str, ip_configs: dict[str, dict]) -> bool:
    """Check if peer_ip is reachable from any interface in ip_configs."""
    for iface_cfg in ip_configs.values():
        iface_ip = iface_cfg.get("ip", "")
        netmask = iface_cfg.get("netmask", "")
        if not iface_ip or not netmask:
            continue
        if _ip_in_subnet(peer_ip, iface_ip, netmask):
            return True
    return False


def _device_display(dev_id: str, devices: dict[str, dict]) -> str:
    """Get a human-readable device name from the snapshot."""
    name = devices.get(dev_id, {}).get("name", dev_id)
    return name or dev_id


# ---------------------------------------------------------------------------
# L3-01  Default gateway gap
# ---------------------------------------------------------------------------


def check_default_gateway_gap(
    predicted_snapshot: dict,
    device_configs: dict[str, dict],
) -> CheckResult:
    """Detect switches with IRB subnets but no routing toward a gateway.

    Args:
        predicted_snapshot: topology snapshot with 'devices' dict.
        device_configs: device_id -> config dict that may include 'networks' and 'routing'.

    Returns:
        CheckResult with status 'critical' if any switch has subnets but no routing, else 'pass'.
    """
    devices: dict[str, dict] = predicted_snapshot.get("devices", {})
    affected: list[str] = []
    details: list[str] = []

    for dev_id, dev in devices.items():
        device_type = dev.get("device_type", "switch")
        if device_type == "gateway":
            # Gateways are the routers — skip them
            continue

        cfg = device_configs.get(dev_id, {})
        networks: list[dict] = cfg.get("networks", [])
        subnets = [n.get("subnet", "") for n in networks if n.get("subnet")]

        if not subnets:
            # No subnets configured — nothing to route
            continue

        routing = cfg.get("routing", {})
        has_ospf = bool(routing.get("ospf", {}).get("areas"))
        has_bgp = bool(routing.get("bgp_peers"))
        has_static = bool(routing.get("static_routes"))

        if not (has_ospf or has_bgp or has_static):
            name = _device_display(dev_id, devices)
            affected.append(name)
            details.append(f"{name}: has subnet(s) {', '.join(subnets)} but no OSPF, BGP, or static route configured")

    if affected:
        return CheckResult(
            check_id="L3-01",
            check_name="Default gateway gap",
            layer=3,
            status="critical",
            summary=f"{len(affected)} switch(es) have IRB subnets with no routing path to a gateway.",
            details=details,
            affected_objects=affected,
            remediation_hint=(
                "Configure an OSPF area, BGP peer, or static default route on each flagged switch "
                "to ensure subnets are reachable beyond the local L2 domain."
            ),
        )

    return CheckResult(
        check_id="L3-01",
        check_name="Default gateway gap",
        layer=3,
        status="pass",
        summary="All switches with IRB subnets have at least one routing path configured.",
    )


# ---------------------------------------------------------------------------
# L3-02  OSPF adjacency break
# ---------------------------------------------------------------------------


def check_ospf_adjacency_break(
    baseline_routing: dict[str, dict],
    predicted_configs: dict[str, dict],
) -> CheckResult:
    """Detect OSPF peer relationships that would break after the config change.

    Args:
        baseline_routing: device_id -> {'ospf_peers': [{'ip', 'area', 'state'}]}
        predicted_configs: device_id -> predicted config with optional 'ip_configs' dict.

    Returns:
        CheckResult with status 'critical' if any OSPF adjacency would break, else 'pass'.
    """
    affected: list[str] = []
    details: list[str] = []

    for dev_id, routing in baseline_routing.items():
        peers: list[dict] = routing.get("ospf_peers", [])
        if not peers:
            continue

        predicted = predicted_configs.get(dev_id, {})
        ip_configs: dict[str, dict] = predicted.get("ip_configs", {})

        for peer in peers:
            peer_ip = peer.get("ip", "")
            if not peer_ip:
                continue
            if not _peer_reachable(peer_ip, ip_configs):
                label = f"{dev_id} -> OSPF peer {peer_ip} (area {peer.get('area', '?')})"
                affected.append(label)
                details.append(
                    f"{dev_id}: OSPF peer {peer_ip} (area {peer.get('area', '?')}) is no longer "
                    f"reachable from predicted interface config"
                )

    if affected:
        return CheckResult(
            check_id="L3-02",
            check_name="OSPF adjacency break",
            layer=3,
            status="critical",
            summary=f"{len(affected)} OSPF adjacency(ies) would break after this change.",
            details=details,
            affected_objects=affected,
            remediation_hint=(
                "Ensure the interface/subnet that was used to reach each OSPF peer IP is preserved "
                "in the predicted config, or update the OSPF neighbor address before removing the interface."
            ),
        )

    return CheckResult(
        check_id="L3-02",
        check_name="OSPF adjacency break",
        layer=3,
        status="pass",
        summary="All existing OSPF adjacencies remain reachable in the predicted config.",
    )


# ---------------------------------------------------------------------------
# L3-03  BGP peer break
# ---------------------------------------------------------------------------


def check_bgp_peer_break(
    baseline_routing: dict[str, dict],
    predicted_configs: dict[str, dict],
) -> CheckResult:
    """Detect BGP sessions that would break after the config change.

    Args:
        baseline_routing: device_id -> {'bgp_peers': [{'ip', 'asn', 'state'}]}
        predicted_configs: device_id -> predicted config with optional 'ip_configs' dict.

    Returns:
        CheckResult with status 'critical' if any BGP session would break, else 'pass'.
    """
    affected_devices: set[str] = set()
    details: list[str] = []

    for dev_id, routing in baseline_routing.items():
        peers: list[dict] = routing.get("bgp_peers", [])
        if not peers:
            continue

        predicted = predicted_configs.get(dev_id, {})
        ip_configs: dict[str, dict] = predicted.get("ip_configs", {})

        for peer in peers:
            peer_ip = peer.get("ip", "")
            if not peer_ip:
                continue
            if not _peer_reachable(peer_ip, ip_configs):
                affected_devices.add(dev_id)
                details.append(
                    f"{dev_id}: BGP peer {peer_ip} (ASN {peer.get('asn', '?')}) is no longer "
                    f"reachable from predicted interface config"
                )

    if affected_devices:
        return CheckResult(
            check_id="L3-03",
            check_name="BGP peer break",
            layer=3,
            status="critical",
            summary=f"{len(affected_devices)} device(s) would lose BGP peer sessions after this change.",
            details=details,
            affected_objects=sorted(affected_devices),
            remediation_hint=(
                "Preserve the local IP/interface used to establish each BGP session, or update the "
                "BGP peer address configuration to match the new interface IP before removing the old one."
            ),
        )

    return CheckResult(
        check_id="L3-03",
        check_name="BGP peer break",
        layer=3,
        status="pass",
        summary="All existing BGP peer sessions remain reachable in the predicted config.",
    )


# ---------------------------------------------------------------------------
# L3-04  VRF consistency
# ---------------------------------------------------------------------------


def check_vrf_consistency(
    predicted_configs: dict[str, dict],
) -> CheckResult:
    """Detect VRF misconfiguration: dangling network references or duplicate VRF memberships.

    Args:
        predicted_configs: device_id -> config with optional 'networks' list and 'vrf' dict.

    Returns:
        CheckResult with 'error' for misconfigs, 'skipped' if no VRFs present, else 'pass'.
    """
    any_vrf = False
    affected: list[str] = []
    details: list[str] = []

    for dev_id, cfg in predicted_configs.items():
        vrf_cfg: dict[str, dict] = cfg.get("vrf", {})
        if not vrf_cfg:
            continue

        any_vrf = True
        defined_networks: set[str] = {n.get("name", "") for n in cfg.get("networks", []) if n.get("name")}

        # Track network -> [vrf names] for duplicate detection
        network_to_vrfs: dict[str, list[str]] = {}

        for vrf_name, vrf_data in vrf_cfg.items():
            member_networks: list[str] = vrf_data.get("networks", [])
            for net_name in member_networks:
                # Check if network exists
                if net_name not in defined_networks:
                    label = f"{dev_id}:{vrf_name}:{net_name}"
                    affected.append(label)
                    details.append(
                        f"{dev_id}: VRF '{vrf_name}' references network '{net_name}' "
                        f"which is not defined in device networks"
                    )
                # Track for duplicate detection
                network_to_vrfs.setdefault(net_name, []).append(vrf_name)

        for net_name, vrf_list in network_to_vrfs.items():
            if len(vrf_list) > 1:
                label = f"{dev_id}:{net_name}"
                if label not in affected:
                    affected.append(label)
                details.append(f"{dev_id}: network '{net_name}' is assigned to multiple VRFs: {', '.join(vrf_list)}")

    if not any_vrf:
        return CheckResult(
            check_id="L3-04",
            check_name="VRF consistency",
            layer=3,
            status="skipped",
            summary="No VRF configuration found — check not applicable.",
        )

    if affected:
        return CheckResult(
            check_id="L3-04",
            check_name="VRF consistency",
            layer=3,
            status="error",
            summary=f"{len(affected)} VRF consistency issue(s) detected.",
            details=details,
            affected_objects=affected,
            remediation_hint=(
                "Ensure all VRF member networks are defined in the device config, and that each "
                "network is assigned to exactly one VRF to prevent route leaking."
            ),
        )

    return CheckResult(
        check_id="L3-04",
        check_name="VRF consistency",
        layer=3,
        status="pass",
        summary="All VRF configurations are consistent.",
    )


# ---------------------------------------------------------------------------
# L3-05  WAN failover path impact
# ---------------------------------------------------------------------------


def check_wan_failover_impact(
    baseline_configs: dict[str, dict],
    predicted_configs: dict[str, dict],
) -> CheckResult:
    """Detect WAN interface changes on gateway devices that could affect failover.

    Args:
        baseline_configs: device_id -> baseline config with optional 'port_config' and 'device_type'.
        predicted_configs: device_id -> predicted config with optional 'port_config' and 'device_type'.

    Returns:
        CheckResult with 'warning' if WAN failover could be affected, 'skipped' if no WAN ports, else 'pass'.
    """
    affected: list[str] = []
    details: list[str] = []
    has_wan = False

    # Collect all device IDs across both configs
    all_device_ids = set(baseline_configs.keys()) | set(predicted_configs.keys())

    for dev_id in all_device_ids:
        base_cfg = baseline_configs.get(dev_id, {})
        pred_cfg = predicted_configs.get(dev_id, {})

        # Only process gateway devices
        device_type = base_cfg.get("device_type") or pred_cfg.get("device_type", "")
        if device_type != "gateway":
            continue

        base_ports: dict[str, dict] = base_cfg.get("port_config", {})
        pred_ports: dict[str, dict] = pred_cfg.get("port_config", {})

        # Collect WAN ports from baseline
        base_wan = {iface: cfg for iface, cfg in base_ports.items() if cfg.get("usage") == "wan"}
        pred_wan = {iface: cfg for iface, cfg in pred_ports.items() if cfg.get("usage") == "wan"}

        if not base_wan and not pred_wan:
            continue

        has_wan = True

        # Check for removed WAN links
        for iface in base_wan:
            if iface not in pred_wan:
                affected.append(f"{dev_id}:{iface}")
                details.append(f"{dev_id}: WAN interface '{iface}' was removed — failover path may be lost")

        # Check for priority or disabled state changes on existing WAN links
        for iface, pred_port_cfg in pred_wan.items():
            base_port_cfg = base_wan.get(iface, {})
            if not base_port_cfg:
                # New WAN interface added — not a concern
                continue

            base_disabled = base_port_cfg.get("disabled", False)
            pred_disabled = pred_port_cfg.get("disabled", False)
            if not base_disabled and pred_disabled:
                label = f"{dev_id}:{iface}"
                if label not in affected:
                    affected.append(label)
                details.append(f"{dev_id}: WAN interface '{iface}' was disabled — primary failover path may be lost")

            base_priority = base_port_cfg.get("priority")
            pred_priority = pred_port_cfg.get("priority")
            if base_priority is not None and pred_priority is not None and base_priority != pred_priority:
                label = f"{dev_id}:{iface}"
                if label not in affected:
                    affected.append(label)
                details.append(
                    f"{dev_id}: WAN interface '{iface}' priority changed "
                    f"from {base_priority} to {pred_priority} — failover order may change"
                )

    if not has_wan:
        return CheckResult(
            check_id="L3-05",
            check_name="WAN failover path impact",
            layer=3,
            status="skipped",
            summary="No WAN interfaces found on gateway devices — check not applicable.",
        )

    if affected:
        return CheckResult(
            check_id="L3-05",
            check_name="WAN failover path impact",
            layer=3,
            status="warning",
            summary=f"{len(affected)} WAN interface change(s) could affect failover behavior.",
            details=details,
            affected_objects=affected,
            remediation_hint=(
                "Review WAN interface changes on gateway devices. Ensure at least one active WAN "
                "link remains and that failover priority order is intentional."
            ),
        )

    return CheckResult(
        check_id="L3-05",
        check_name="WAN failover path impact",
        layer=3,
        status="pass",
        summary="No WAN failover impact detected — WAN interface configuration is unchanged.",
    )
