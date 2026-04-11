"""
Layer 5 L2/STP validation checks for the Digital Twin module.

All functions are pure — no async, no DB access.
Each returns a CheckResult with check_id, status, summary, details, and remediation_hint.
"""

from __future__ import annotations

import networkx as nx

from app.modules.digital_twin.models import CheckResult

# Default STP bridge priority when none is explicitly configured.
_DEFAULT_STP_PRIORITY = 32768

# Link types considered STP-protected (hardware-level redundancy, not STP needed).
_STP_PROTECTED_LINK_TYPES = {"LAG", "MCLAG", "VC"}

# Maximum number of cycles to collect before bailing out (guards against huge graphs).
_MAX_CYCLES = 100

# Keys used to identify STP priority in device configs.
_STP_PRIORITY_KEYS = ("stp_priority", "rstp_priority", "bridge_priority")

# Keys indicating BPDU filter is enabled on a port.
_BPDU_FILTER_KEYS = ("bpdu_filter", "stp_bpdu_filter")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_graph(connections: list[dict]) -> nx.Graph:
    """Build an undirected graph from a list of topology connections."""
    g: nx.Graph = nx.Graph()
    for conn in connections:
        local = conn.get("local_device_id", "")
        remote = conn.get("remote_device_id", "")
        link_type = conn.get("link_type", "STANDALONE")
        if local and remote:
            g.add_edge(local, remote, link_type=link_type)
    return g


def _cycles_from_graph(g: nx.Graph) -> list[list[str]]:
    """Return up to _MAX_CYCLES simple cycles from an undirected graph."""
    cycles: list[list[str]] = []
    for cycle in nx.simple_cycles(g):
        cycles.append(cycle)
        if len(cycles) >= _MAX_CYCLES:
            break
    return cycles


def _cycle_has_unprotected_links(g: nx.Graph, cycle: list[str]) -> bool:
    """Return True if any edge in the cycle is NOT a STP-protected link type."""
    for i, node in enumerate(cycle):
        next_node = cycle[(i + 1) % len(cycle)]
        edge_data = g.get_edge_data(node, next_node) or {}
        link_type = edge_data.get("link_type", "STANDALONE")
        if link_type not in _STP_PROTECTED_LINK_TYPES:
            return True
    return False


def _get_stp_priority(config: dict) -> int | None:
    """Extract STP priority from a device config using any known key."""
    for key in _STP_PRIORITY_KEYS:
        val = config.get(key)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass
    return None


def _find_root(priorities: dict[str, int]) -> str | None:
    """Return the device_id with the lowest STP priority (root bridge)."""
    if not priorities:
        return None
    return min(priorities, key=lambda dev: priorities[dev])


# ---------------------------------------------------------------------------
# L5-01  L2 loop risk
# ---------------------------------------------------------------------------


def check_l2_loop_risk(
    baseline_snapshot: dict,
    predicted_snapshot: dict,
) -> CheckResult:
    """
    Detect new L2 loops introduced by the predicted topology that are not
    present in the baseline.

    A cycle is flagged as critical if it contains at least one non-STP-
    protected link (i.e., not LAG/MCLAG/VC).
    """
    baseline_conns: list[dict] = baseline_snapshot.get("connections", [])
    predicted_conns: list[dict] = predicted_snapshot.get("connections", [])

    baseline_graph = _build_graph(baseline_conns)
    predicted_graph = _build_graph(predicted_conns)

    baseline_cycles = _cycles_from_graph(baseline_graph)
    predicted_cycles = _cycles_from_graph(predicted_graph)

    # Normalise cycles to frozensets for comparison (order-independent).
    baseline_cycle_sets = {frozenset(c) for c in baseline_cycles}
    predicted_cycle_sets = {frozenset(c) for c in predicted_cycles}

    new_cycle_sets = predicted_cycle_sets - baseline_cycle_sets

    if not new_cycle_sets:
        return CheckResult(
            check_id="L5-01",
            check_name="L2 Loop Risk",
            layer=5,
            status="pass",
            summary="No new L2 loops detected in predicted topology.",
        )

    # Check whether any new cycle has unprotected (non-LAG/VC) links.
    unprotected_cycles: list[frozenset[str]] = []
    for cycle_set in new_cycle_sets:
        # Re-find a matching cycle list for edge inspection.
        cycle_list = next((c for c in predicted_cycles if frozenset(c) == cycle_set), list(cycle_set))
        if _cycle_has_unprotected_links(predicted_graph, cycle_list):
            unprotected_cycles.append(cycle_set)

    if not unprotected_cycles:
        return CheckResult(
            check_id="L5-01",
            check_name="L2 Loop Risk",
            layer=5,
            status="pass",
            summary="New cycles detected but all involve STP-protected link types (LAG/VC).",
        )

    affected = sorted({node for cycle in unprotected_cycles for node in cycle})
    details = [f"New cycle involving: {', '.join(sorted(cycle))}" for cycle in unprotected_cycles]

    return CheckResult(
        check_id="L5-01",
        check_name="L2 Loop Risk",
        layer=5,
        status="critical",
        summary=f"{len(unprotected_cycles)} new L2 loop(s) detected without STP protection.",
        details=details,
        affected_objects=affected,
        remediation_hint=(
            "Enable STP/RSTP on all ports in the loop path, convert redundant links to LAG, "
            "or remove the redundant connection."
        ),
    )


# ---------------------------------------------------------------------------
# L5-02  BPDU filter on trunk
# ---------------------------------------------------------------------------


def _is_bpdu_filter_enabled(port_cfg: dict) -> bool:
    """Return True if any BPDU filter key is set to True in the port config."""
    return any(port_cfg.get(k) is True for k in _BPDU_FILTER_KEYS)


def _is_trunk_port(port_cfg: dict) -> bool:
    """
    Return True if the port config indicates trunk mode.
    Checks vlan_mode == "trunk" (port_config style) and mode == "trunk" (port_usages style).
    """
    vlan_mode = port_cfg.get("vlan_mode", "")
    mode = port_cfg.get("mode", "")
    return vlan_mode == "trunk" or mode == "trunk"


def check_bpdu_filter_on_trunk(
    predicted_configs: dict[str, dict],
) -> CheckResult:
    """
    Detect BPDU filter enabled on trunk ports, which disables STP protection
    and creates a loop risk.
    """
    violations: list[str] = []
    affected_devices: list[str] = []

    for device_id, config in predicted_configs.items():
        # Check port_config (individual port entries).
        port_config: dict = config.get("port_config", {})
        for port_name, port_cfg in port_config.items():
            if _is_bpdu_filter_enabled(port_cfg) and _is_trunk_port(port_cfg):
                violations.append(f"Device {device_id}: port {port_name} has BPDU filter enabled on trunk")
                if device_id not in affected_devices:
                    affected_devices.append(device_id)

        # Check port_usages (profile-level entries).
        port_usages: dict = config.get("port_usages", {})
        for profile_name, profile_cfg in port_usages.items():
            if _is_bpdu_filter_enabled(profile_cfg) and _is_trunk_port(profile_cfg):
                violations.append(f"Device {device_id}: port_usage profile '{profile_name}' has BPDU filter on trunk")
                if device_id not in affected_devices:
                    affected_devices.append(device_id)

    if not violations:
        return CheckResult(
            check_id="L5-02",
            check_name="BPDU Filter on Trunk",
            layer=5,
            status="pass",
            summary="No BPDU filter enabled on trunk ports.",
        )

    return CheckResult(
        check_id="L5-02",
        check_name="BPDU Filter on Trunk",
        layer=5,
        status="critical",
        summary=f"{len(violations)} trunk port(s) with BPDU filter enabled — STP protection disabled.",
        details=violations,
        affected_objects=sorted(affected_devices),
        remediation_hint=(
            "Remove bpdu_filter from trunk ports. BPDU filter should only be used on "
            "edge/access ports facing end-user devices, never on switch-to-switch uplinks."
        ),
    )


# ---------------------------------------------------------------------------
# L5-03  STP root bridge shift
# ---------------------------------------------------------------------------


def check_stp_root_bridge_shift(
    baseline_configs: dict[str, dict],
    predicted_configs: dict[str, dict],
) -> CheckResult:
    """
    Detect STP bridge priority changes that would elect a new root bridge,
    causing an STP reconvergence storm across the network.
    """
    # Extract priorities from baseline.
    baseline_priorities: dict[str, int] = {}
    for dev_id, cfg in baseline_configs.items():
        prio = _get_stp_priority(cfg)
        if prio is not None:
            baseline_priorities[dev_id] = prio

    # Extract priorities from predicted.
    predicted_priorities: dict[str, int] = {}
    for dev_id, cfg in predicted_configs.items():
        prio = _get_stp_priority(cfg)
        if prio is not None:
            predicted_priorities[dev_id] = prio

    # If no STP priority is configured anywhere, skip.
    if not baseline_priorities and not predicted_priorities:
        return CheckResult(
            check_id="L5-03",
            check_name="STP Root Bridge Shift",
            layer=5,
            status="skipped",
            summary="No STP priority configured — skipping root bridge shift check.",
        )

    # Fill missing devices with the default priority for comparison.
    all_devices = set(baseline_configs) | set(predicted_configs)
    baseline_full = {dev: baseline_priorities.get(dev, _DEFAULT_STP_PRIORITY) for dev in all_devices}
    predicted_full = {dev: predicted_priorities.get(dev, _DEFAULT_STP_PRIORITY) for dev in all_devices}

    baseline_root = _find_root(baseline_full)
    predicted_root = _find_root(predicted_full)

    if baseline_root == predicted_root:
        return CheckResult(
            check_id="L5-03",
            check_name="STP Root Bridge Shift",
            layer=5,
            status="pass",
            summary=f"STP root bridge remains '{baseline_root}' — no reconvergence expected.",
        )

    # Root shifted — collect changed devices.
    changed: list[str] = [
        dev
        for dev in all_devices
        if baseline_full.get(dev, _DEFAULT_STP_PRIORITY) != predicted_full.get(dev, _DEFAULT_STP_PRIORITY)
    ]

    details = [
        f"Root shift: '{baseline_root}' (priority {baseline_full.get(baseline_root)}) "
        f"→ '{predicted_root}' (priority {predicted_full.get(predicted_root)})"
    ]
    for dev in sorted(changed):
        old_p = baseline_full.get(dev, _DEFAULT_STP_PRIORITY)
        new_p = predicted_full.get(dev, _DEFAULT_STP_PRIORITY)
        if old_p != new_p:
            details.append(f"  {dev}: priority {old_p} → {new_p}")

    return CheckResult(
        check_id="L5-03",
        check_name="STP Root Bridge Shift",
        layer=5,
        status="warning",
        summary=f"STP root bridge would shift from '{baseline_root}' to '{predicted_root}' — reconvergence storm possible.",
        details=details,
        affected_objects=sorted(changed),
        remediation_hint=(
            "Review STP priority changes carefully. If the root shift is intentional, "
            "schedule during a maintenance window. Consider using RSTP to minimise convergence time."
        ),
    )
