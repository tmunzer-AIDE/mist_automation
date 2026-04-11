"""
Layer 2 topology validation checks for the Digital Twin module.

All functions are pure — no async, no DB access.
Each returns a CheckResult with check_id, status, summary, details, and remediation_hint.
"""

from __future__ import annotations

import networkx as nx

from app.modules.digital_twin.models import CheckResult
from app.modules.impact_analysis.services.topology_service import (
    bfs_reachable,
    build_adjacency,
    find_gateways,
)

# Default PoE draw per device type (watts) when exact draw is unknown.
_DEFAULT_POE_DRAW: dict[str, float] = {
    "ap": 15.4,
    "switch": 0.0,
    "gateway": 0.0,
}

# Port utilisation threshold for warning (90%).
_PORT_WARN_THRESHOLD = 0.90


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_vlans_from_summary(vlan_summary: str) -> set[str]:
    """Extract VLAN IDs from a vlan_summary string like 'trunk:100,200' or 'access:100'."""
    if not vlan_summary:
        return set()
    parts = vlan_summary.split(":", 1)
    if len(parts) < 2:
        return set()
    return {v.strip() for v in parts[1].split(",") if v.strip()}


def _device_name(devices: dict[str, dict], dev_id: str) -> str:
    """Get display name for a device, falling back to the ID."""
    return devices.get(dev_id, {}).get("name", dev_id)


def _connection_key(conn: dict) -> tuple[str, str, str]:
    """Build a stable key for matching connections across snapshots."""
    a, b = sorted([conn.get("local_device_id", ""), conn.get("remote_device_id", "")])
    ae = conn.get("local_ae") or conn.get("remote_ae") or ""
    return (a, b, ae)


# ---------------------------------------------------------------------------
# L2-01  Connectivity loss
# ---------------------------------------------------------------------------


def check_connectivity_loss(baseline_snapshot: dict, predicted_snapshot: dict) -> CheckResult:
    """Detect devices that lose all paths to a gateway after the change."""
    base_devices = baseline_snapshot.get("devices", {})
    pred_devices = predicted_snapshot.get("devices", {})
    base_conns = baseline_snapshot.get("connections", [])
    pred_conns = predicted_snapshot.get("connections", [])

    base_gateways = find_gateways(base_devices)
    pred_gateways = find_gateways(pred_devices)

    if not base_gateways and not pred_gateways:
        return CheckResult(
            check_id="L2-01",
            check_name="Connectivity loss",
            layer=2,
            status="skipped",
            summary="No gateways in topology — connectivity check not applicable.",
        )

    base_adj = build_adjacency(base_conns)
    pred_adj = build_adjacency(pred_conns)

    lost: list[str] = []
    for dev_id in base_devices:
        if dev_id in base_gateways:
            continue
        # Could it reach any gateway in baseline?
        base_reachable = bfs_reachable(base_adj, dev_id)
        had_path = any(gw in base_reachable for gw in base_gateways)
        if not had_path:
            continue  # already isolated in baseline

        # Can it still reach a gateway in predicted?
        pred_reachable = bfs_reachable(pred_adj, dev_id)
        has_path = any(gw in pred_reachable for gw in pred_gateways)
        if not has_path:
            lost.append(dev_id)

    if lost:
        names = [_device_name(base_devices, d) for d in lost]
        return CheckResult(
            check_id="L2-01",
            check_name="Connectivity loss",
            layer=2,
            status="critical",
            summary=f"{len(lost)} device(s) lost gateway reachability.",
            details=[f"{n} can no longer reach any gateway" for n in names],
            affected_objects=lost,
            affected_sites=[baseline_snapshot.get("site_id", "")],
            remediation_hint="Verify that uplink connections are maintained or add an alternate path.",
        )

    return CheckResult(
        check_id="L2-01",
        check_name="Connectivity loss",
        layer=2,
        status="pass",
        summary="All devices retain gateway reachability.",
    )


# ---------------------------------------------------------------------------
# L2-02  VLAN black hole
# ---------------------------------------------------------------------------


def check_vlan_black_hole(predicted_snapshot: dict) -> CheckResult:
    """Detect VLANs that cannot reach any gateway through the VLAN-aware subgraph."""
    devices = predicted_snapshot.get("devices", {})
    connections = predicted_snapshot.get("connections", [])
    vlan_map = predicted_snapshot.get("vlan_map", {})

    gateways = find_gateways(devices)
    if not gateways:
        return CheckResult(
            check_id="L2-02",
            check_name="VLAN black hole",
            layer=2,
            status="skipped",
            summary="No gateways in topology — VLAN reachability check not applicable.",
        )

    if not vlan_map:
        return CheckResult(
            check_id="L2-02",
            check_name="VLAN black hole",
            layer=2,
            status="skipped",
            summary="No VLANs defined — check not applicable.",
        )

    black_holes: list[str] = []
    details: list[str] = []

    for vlan_name, vlan_id in vlan_map.items():
        # Build a VLAN-specific graph: only connections carrying this VLAN
        g = nx.Graph()
        # Add all devices as nodes
        for dev_id in devices:
            g.add_node(dev_id)

        for conn in connections:
            conn_vlans = _parse_vlans_from_summary(conn.get("vlan_summary", ""))
            # A connection with no VLAN summary is treated as carrying all VLANs (untagged/native)
            if conn_vlans and vlan_id not in conn_vlans:
                continue
            local = conn.get("local_device_id", "")
            remote = conn.get("remote_device_id", "")
            if local and remote:
                g.add_edge(local, remote)

        # For each non-gateway device, check if it can reach any gateway in this VLAN subgraph
        for dev_id in devices:
            if dev_id in gateways:
                continue
            can_reach_gw = False
            for gw_id in gateways:
                if nx.has_path(g, dev_id, gw_id):
                    can_reach_gw = True
                    break
            if not can_reach_gw:
                # Only report if the device has edges at all (i.e., is connected somewhere for this VLAN)
                # or if the connection explicitly restricts VLANs
                has_any_conn = any(
                    conn.get("local_device_id") == dev_id or conn.get("remote_device_id") == dev_id
                    for conn in connections
                )
                if has_any_conn:
                    name = _device_name(devices, dev_id)
                    details.append(f"VLAN {vlan_id} ({vlan_name}) unreachable from {name} to any gateway")
                    if vlan_id not in black_holes:
                        black_holes.append(vlan_id)

    if black_holes:
        return CheckResult(
            check_id="L2-02",
            check_name="VLAN black hole",
            layer=2,
            status="error",
            summary=f"{len(black_holes)} VLAN(s) have unreachable segments.",
            details=details,
            affected_objects=black_holes,
            affected_sites=[predicted_snapshot.get("site_id", "")],
            remediation_hint="Ensure trunk links carry all required VLANs end-to-end to the gateway.",
        )

    return CheckResult(
        check_id="L2-02",
        check_name="VLAN black hole",
        layer=2,
        status="pass",
        summary="All VLANs can reach a gateway.",
    )


# ---------------------------------------------------------------------------
# L2-03  LAG / MCLAG integrity
# ---------------------------------------------------------------------------


def check_lag_mclag_integrity(baseline_snapshot: dict, predicted_snapshot: dict) -> CheckResult:
    """Detect LAG/MCLAG connections whose physical link count decreased."""
    base_conns = baseline_snapshot.get("connections", [])
    pred_conns = predicted_snapshot.get("connections", [])
    base_devices = baseline_snapshot.get("devices", {})

    lag_types = {"LAG", "MCLAG"}
    base_lags = {_connection_key(c): c for c in base_conns if c.get("link_type") in lag_types}
    pred_lags = {_connection_key(c): c for c in pred_conns if c.get("link_type") in lag_types}

    if not base_lags and not pred_lags:
        return CheckResult(
            check_id="L2-03",
            check_name="LAG/MCLAG integrity",
            layer=2,
            status="skipped",
            summary="No LAG/MCLAG connections — check not applicable.",
        )

    degraded: list[str] = []
    details: list[str] = []

    for key, base_conn in base_lags.items():
        pred_conn = pred_lags.get(key)
        if not pred_conn:
            # LAG completely removed
            a_name = _device_name(base_devices, base_conn.get("local_device_id", ""))
            b_name = _device_name(base_devices, base_conn.get("remote_device_id", ""))
            details.append(f"LAG between {a_name} and {b_name} removed entirely")
            degraded.append(key[2] or f"{key[0]}-{key[1]}")
            continue
        base_count = base_conn.get("physical_links_count", 0)
        pred_count = pred_conn.get("physical_links_count", 0)
        if pred_count < base_count:
            a_name = _device_name(base_devices, base_conn.get("local_device_id", ""))
            b_name = _device_name(base_devices, base_conn.get("remote_device_id", ""))
            details.append(f"LAG {a_name}<->{b_name}: {base_count} -> {pred_count} links")
            degraded.append(key[2] or f"{key[0]}-{key[1]}")

    if degraded:
        return CheckResult(
            check_id="L2-03",
            check_name="LAG/MCLAG integrity",
            layer=2,
            status="error",
            summary=f"{len(degraded)} LAG/MCLAG bundle(s) degraded.",
            details=details,
            affected_objects=degraded,
            affected_sites=[baseline_snapshot.get("site_id", "")],
            remediation_hint="Restore removed LAG member links or verify the change is intentional.",
        )

    return CheckResult(
        check_id="L2-03",
        check_name="LAG/MCLAG integrity",
        layer=2,
        status="pass",
        summary="All LAG/MCLAG bundles maintain their link count.",
    )


# ---------------------------------------------------------------------------
# L2-04  VC integrity
# ---------------------------------------------------------------------------


def check_vc_integrity(baseline_snapshot: dict, predicted_snapshot: dict) -> CheckResult:
    """Detect Virtual Chassis groups that lost members."""
    base_groups = [g for g in baseline_snapshot.get("logical_groups", []) if g.get("group_type") == "VC"]
    pred_groups = [g for g in predicted_snapshot.get("logical_groups", []) if g.get("group_type") == "VC"]
    base_devices = baseline_snapshot.get("devices", {})

    if not base_groups and not pred_groups:
        return CheckResult(
            check_id="L2-04",
            check_name="VC integrity",
            layer=2,
            status="skipped",
            summary="No Virtual Chassis groups — check not applicable.",
        )

    pred_by_id = {g["group_id"]: g for g in pred_groups}
    lost_members: list[str] = []
    details: list[str] = []

    for base_g in base_groups:
        gid = base_g["group_id"]
        base_members = set(base_g.get("member_ids", []))
        pred_g = pred_by_id.get(gid)
        pred_members = set(pred_g.get("member_ids", [])) if pred_g else set()
        removed = base_members - pred_members
        if removed:
            for m in removed:
                name = _device_name(base_devices, m)
                details.append(f"VC {gid}: member {name} removed")
                lost_members.append(m)

    if lost_members:
        return CheckResult(
            check_id="L2-04",
            check_name="VC integrity",
            layer=2,
            status="critical",
            summary=f"{len(lost_members)} VC member(s) removed.",
            details=details,
            affected_objects=lost_members,
            affected_sites=[baseline_snapshot.get("site_id", "")],
            remediation_hint="Removing VC members causes a topology reconvergence. Verify this is intentional.",
        )

    return CheckResult(
        check_id="L2-04",
        check_name="VC integrity",
        layer=2,
        status="pass",
        summary="All Virtual Chassis groups retain their members.",
    )


# ---------------------------------------------------------------------------
# L2-05  PoE budget overrun
# ---------------------------------------------------------------------------


def check_poe_budget_overrun(
    predicted_snapshot: dict,
    poe_budgets: dict[str, float],
) -> CheckResult:
    """Detect switches whose PoE load exceeds available budget."""
    if not poe_budgets:
        return CheckResult(
            check_id="L2-05",
            check_name="PoE budget overrun",
            layer=2,
            status="skipped",
            summary="No PoE budget data provided — check not applicable.",
        )

    devices = predicted_snapshot.get("devices", {})
    connections = predicted_snapshot.get("connections", [])

    # Build per-device PoE draw: count connected devices and sum default draw
    poe_load: dict[str, float] = dict.fromkeys(poe_budgets, 0.0)
    for conn in connections:
        local = conn.get("local_device_id", "")
        remote = conn.get("remote_device_id", "")
        # If the local device is a PoE source, count the remote's draw
        if local in poe_budgets:
            remote_type = devices.get(remote, {}).get("device_type", "")
            poe_load[local] += _DEFAULT_POE_DRAW.get(remote_type, 0.0)
        if remote in poe_budgets:
            local_type = devices.get(local, {}).get("device_type", "")
            poe_load[remote] += _DEFAULT_POE_DRAW.get(local_type, 0.0)

    overrun: list[str] = []
    details: list[str] = []

    for dev_id, budget in poe_budgets.items():
        load = poe_load.get(dev_id, 0.0)
        if load > budget:
            name = _device_name(devices, dev_id)
            details.append(f"{name}: {load:.1f}W load exceeds {budget:.1f}W budget")
            overrun.append(dev_id)

    if overrun:
        return CheckResult(
            check_id="L2-05",
            check_name="PoE budget overrun",
            layer=2,
            status="error",
            summary=f"{len(overrun)} switch(es) exceed PoE budget.",
            details=details,
            affected_objects=overrun,
            affected_sites=[predicted_snapshot.get("site_id", "")],
            remediation_hint="Reduce PoE load or use higher-capacity PoE switches.",
        )

    return CheckResult(
        check_id="L2-05",
        check_name="PoE budget overrun",
        layer=2,
        status="pass",
        summary="All switches within PoE budget.",
    )


# ---------------------------------------------------------------------------
# L2-06  PoE disable on active port
# ---------------------------------------------------------------------------


def check_poe_disable_on_active(
    baseline_snapshot: dict,
    predicted_snapshot: dict,
    active_poe_ports: dict[str, list[str]],
) -> CheckResult:
    """Detect ports where PoE is being disabled but currently delivering power."""
    if not active_poe_ports:
        return CheckResult(
            check_id="L2-06",
            check_name="PoE disable on active port",
            layer=2,
            status="skipped",
            summary="No active PoE port data provided — check not applicable.",
        )

    base_devices = baseline_snapshot.get("devices", {})
    pred_devices = predicted_snapshot.get("devices", {})
    conflicts: list[str] = []
    details: list[str] = []

    for dev_id, active_ports in active_poe_ports.items():
        if not active_ports:
            continue
        base_disabled = set(base_devices.get(dev_id, {}).get("poe_disabled_ports", []))
        pred_disabled = set(pred_devices.get(dev_id, {}).get("poe_disabled_ports", []))
        newly_disabled = pred_disabled - base_disabled
        affected = newly_disabled & set(active_ports)
        if affected:
            name = _device_name(pred_devices, dev_id)
            for port in sorted(affected):
                details.append(f"{name}: PoE disabled on active port {port}")
            conflicts.extend(f"{dev_id}:{p}" for p in sorted(affected))

    if conflicts:
        return CheckResult(
            check_id="L2-06",
            check_name="PoE disable on active port",
            layer=2,
            status="critical",
            summary=f"{len(conflicts)} active PoE port(s) will lose power.",
            details=details,
            affected_objects=conflicts,
            affected_sites=[predicted_snapshot.get("site_id", "")],
            remediation_hint="The affected ports are currently powering devices. Disabling PoE will cause an outage.",
        )

    return CheckResult(
        check_id="L2-06",
        check_name="PoE disable on active port",
        layer=2,
        status="pass",
        summary="No active PoE ports affected by the change.",
    )


# ---------------------------------------------------------------------------
# L2-07  Port capacity saturation
# ---------------------------------------------------------------------------


def check_port_capacity_saturation(
    predicted_snapshot: dict,
    port_counts: dict[str, tuple[int, int]],
) -> CheckResult:
    """Detect switches where used ports exceed or approach total capacity."""
    if not port_counts:
        return CheckResult(
            check_id="L2-07",
            check_name="Port capacity saturation",
            layer=2,
            status="skipped",
            summary="No port count data provided — check not applicable.",
        )

    devices = predicted_snapshot.get("devices", {})
    errors: list[str] = []
    warnings: list[str] = []
    details: list[str] = []

    for dev_id, (used, total) in port_counts.items():
        if total <= 0:
            continue
        name = _device_name(devices, dev_id)
        if used > total:
            details.append(f"{name}: {used}/{total} ports used (oversubscribed)")
            errors.append(dev_id)
        elif used / total >= _PORT_WARN_THRESHOLD:
            details.append(f"{name}: {used}/{total} ports used ({used * 100 // total}%)")
            warnings.append(dev_id)

    if errors:
        return CheckResult(
            check_id="L2-07",
            check_name="Port capacity saturation",
            layer=2,
            status="error",
            summary=f"{len(errors)} switch(es) oversubscribed on ports.",
            details=details,
            affected_objects=errors,
            affected_sites=[predicted_snapshot.get("site_id", "")],
            remediation_hint="Add switches or redistribute connections to stay within port limits.",
        )

    if warnings:
        return CheckResult(
            check_id="L2-07",
            check_name="Port capacity saturation",
            layer=2,
            status="warning",
            summary=f"{len(warnings)} switch(es) approaching port capacity.",
            details=details,
            affected_objects=warnings,
            affected_sites=[predicted_snapshot.get("site_id", "")],
            remediation_hint="Consider capacity planning — these switches are above 90% port utilisation.",
        )

    return CheckResult(
        check_id="L2-07",
        check_name="Port capacity saturation",
        layer=2,
        status="pass",
        summary="All switches within port capacity.",
    )


# ---------------------------------------------------------------------------
# L2-08  LACP misconfiguration
# ---------------------------------------------------------------------------


def check_lacp_misconfiguration(predicted_snapshot: dict) -> CheckResult:
    """Flag LAG connections with suspicious configuration (e.g. single-link LAG)."""
    connections = predicted_snapshot.get("connections", [])
    devices = predicted_snapshot.get("devices", {})

    lag_conns = [c for c in connections if c.get("link_type") in ("LAG", "MCLAG")]
    if not lag_conns:
        return CheckResult(
            check_id="L2-08",
            check_name="LACP misconfiguration",
            layer=2,
            status="skipped",
            summary="No LAG connections — check not applicable.",
        )

    suspicious: list[str] = []
    details: list[str] = []

    for conn in lag_conns:
        link_count = conn.get("physical_links_count", 0)
        if link_count < 2:
            a_name = _device_name(devices, conn.get("local_device_id", ""))
            b_name = _device_name(devices, conn.get("remote_device_id", ""))
            ae = conn.get("local_ae") or conn.get("remote_ae") or "unknown"
            details.append(f"LAG {ae} ({a_name}<->{b_name}): only {link_count} physical link(s)")
            suspicious.append(ae)

    if suspicious:
        return CheckResult(
            check_id="L2-08",
            check_name="LACP misconfiguration",
            layer=2,
            status="warning",
            summary=f"{len(suspicious)} LAG(s) with suspicious link count.",
            details=details,
            affected_objects=suspicious,
            affected_sites=[predicted_snapshot.get("site_id", "")],
            remediation_hint="A LAG with fewer than 2 physical links provides no redundancy. "
            "Verify LACP is negotiating correctly on all member ports.",
        )

    return CheckResult(
        check_id="L2-08",
        check_name="LACP misconfiguration",
        layer=2,
        status="pass",
        summary="All LAG bundles have 2+ physical links.",
    )


# ---------------------------------------------------------------------------
# L2-09  MTU mismatch
# ---------------------------------------------------------------------------


def check_mtu_mismatch(predicted_snapshot: dict) -> CheckResult:
    """Detect connected device pairs with mismatched MTU settings."""
    devices = predicted_snapshot.get("devices", {})
    connections = predicted_snapshot.get("connections", [])

    mismatches: list[str] = []
    details: list[str] = []

    for conn in connections:
        local_id = conn.get("local_device_id", "")
        remote_id = conn.get("remote_device_id", "")
        local_dev = devices.get(local_id, {})
        remote_dev = devices.get(remote_id, {})
        local_mtu = local_dev.get("mtu")
        remote_mtu = remote_dev.get("mtu")

        # Only flag when both devices have an explicit MTU and they differ
        if local_mtu is not None and remote_mtu is not None and local_mtu != remote_mtu:
            a_name = _device_name(devices, local_id)
            b_name = _device_name(devices, remote_id)
            details.append(f"{a_name} (MTU {local_mtu}) <-> {b_name} (MTU {remote_mtu})")
            mismatches.append(f"{local_id}-{remote_id}")

    if mismatches:
        return CheckResult(
            check_id="L2-09",
            check_name="MTU mismatch",
            layer=2,
            status="warning",
            summary=f"{len(mismatches)} connection(s) with MTU mismatch.",
            details=details,
            affected_objects=mismatches,
            affected_sites=[predicted_snapshot.get("site_id", "")],
            remediation_hint="Mismatched MTU causes fragmentation or dropped jumbo frames. "
            "Align MTU settings on both ends of each link.",
        )

    return CheckResult(
        check_id="L2-09",
        check_name="MTU mismatch",
        layer=2,
        status="pass",
        summary="No MTU mismatches detected.",
    )
