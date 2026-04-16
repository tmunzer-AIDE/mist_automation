"""
STP checks: root bridge shift, BPDU filter on trunk, and L2 loop risk.

STP-ROOT — Detect root bridge shifts caused by priority changes.
STP-BPDU — Detect BPDU filter enabled on trunk ports (disables STP protection).
STP-LOOP — Detect new L2 cycles in the physical graph.

All functions are pure — no async, no DB access.
"""

from __future__ import annotations

import networkx as nx

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.site_graph import build_site_graph
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot, normalize_mac

# Default STP bridge priority when none is explicitly configured.
_DEFAULT_STP_PRIORITY = 32768

# Keys used to identify STP priority in device stp_config.
_STP_PRIORITY_KEYS = ("bridge_priority", "stp_priority", "rstp_priority")

# Keys indicating BPDU filter is enabled on a port.
_BPDU_FILTER_KEYS = ("bpdu_filter", "stp_bpdu_filter")

# Maximum number of new cycles to report.
_MAX_REPORTED_CYCLES = 5


# ---------------------------------------------------------------------------
# STP-ROOT helpers
# ---------------------------------------------------------------------------


def _get_stp_priority(device_stp_config: dict | None) -> int | None:
    """Extract STP priority from a device's stp_config using any known key."""
    if not device_stp_config:
        return None
    for key in _STP_PRIORITY_KEYS:
        val = device_stp_config.get(key)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass
    return None


def _find_root(priorities: dict[str, tuple[int, str, str]]) -> tuple[str, int, str] | None:
    """Find root bridge: lowest priority, then lowest MAC as tiebreak.

    Args:
        priorities: device_id -> (priority, normalized_mac, name)

    Returns:
        (device_id, priority, name) of root or None if empty.
    """
    if not priorities:
        return None
    # MAC tiebreak must use a normalized form (lowercase, colons/dashes stripped)
    # so the chosen root is deterministic regardless of ingest format.
    root_id = min(priorities, key=lambda dev: (priorities[dev][0], priorities[dev][1]))
    prio, _mac, name = priorities[root_id]
    return root_id, prio, name


# ---------------------------------------------------------------------------
# STP-ROOT: Root Bridge Shift — Layer 5, warning
# ---------------------------------------------------------------------------


def _check_stp_root(baseline: SiteSnapshot, predicted: SiteSnapshot) -> CheckResult:
    """Detect STP root bridge shifts caused by priority changes."""
    # Collect priorities from switch devices in each snapshot
    baseline_prios: dict[str, tuple[int, str, str]] = {}
    predicted_prios: dict[str, tuple[int, str, str]] = {}

    for dev_id, dev in baseline.devices.items():
        if dev.type != "switch":
            continue
        prio = _get_stp_priority(dev.stp_config)
        if prio is not None:
            baseline_prios[dev_id] = (prio, normalize_mac(dev.mac), dev.name)

    for dev_id, dev in predicted.devices.items():
        if dev.type != "switch":
            continue
        prio = _get_stp_priority(dev.stp_config)
        if prio is not None:
            predicted_prios[dev_id] = (prio, normalize_mac(dev.mac), dev.name)

    # If no STP priority configured anywhere, skip
    if not baseline_prios and not predicted_prios:
        return CheckResult(
            check_id="STP-ROOT",
            check_name="Root Bridge Shift",
            layer=5,
            status="skipped",
            summary="No STP priority configured on any switch — skipping root bridge check.",
            description="Detects STP root bridge shifts caused by bridge priority changes, which trigger network-wide reconvergence.",
        )

    # Fill missing devices with default priority for fair comparison
    all_switch_ids: set[str] = set()
    for dev_id, dev in baseline.devices.items():
        if dev.type == "switch":
            all_switch_ids.add(dev_id)
    for dev_id, dev in predicted.devices.items():
        if dev.type == "switch":
            all_switch_ids.add(dev_id)

    for dev_id in all_switch_ids:
        if dev_id not in baseline_prios:
            dev = baseline.devices.get(dev_id) or predicted.devices.get(dev_id)
            if dev:
                baseline_prios[dev_id] = (_DEFAULT_STP_PRIORITY, normalize_mac(dev.mac), dev.name)
        if dev_id not in predicted_prios:
            dev = predicted.devices.get(dev_id) or baseline.devices.get(dev_id)
            if dev:
                predicted_prios[dev_id] = (_DEFAULT_STP_PRIORITY, normalize_mac(dev.mac), dev.name)

    baseline_root = _find_root(baseline_prios)
    predicted_root = _find_root(predicted_prios)

    if baseline_root is None or predicted_root is None:
        return CheckResult(
            check_id="STP-ROOT",
            check_name="Root Bridge Shift",
            layer=5,
            status="skipped",
            summary="Cannot determine STP root bridge — insufficient data.",
            description="Detects STP root bridge shifts caused by bridge priority changes, which trigger network-wide reconvergence.",
        )

    baseline_root_id, baseline_root_prio, baseline_root_name = baseline_root
    predicted_root_id, predicted_root_prio, predicted_root_name = predicted_root

    if baseline_root_id == predicted_root_id:
        return CheckResult(
            check_id="STP-ROOT",
            check_name="Root Bridge Shift",
            layer=5,
            status="pass",
            summary=f"STP root bridge remains '{baseline_root_name}' — no reconvergence expected.",
            description="Detects STP root bridge shifts caused by bridge priority changes, which trigger network-wide reconvergence.",
        )

    details = [
        f"Old root: {baseline_root_name} (priority {baseline_root_prio})",
        f"New root: {predicted_root_name} (priority {predicted_root_prio})",
    ]

    return CheckResult(
        check_id="STP-ROOT",
        check_name="Root Bridge Shift",
        layer=5,
        status="warning",
        summary=(
            f"STP root bridge shifts from '{baseline_root_name}' to "
            f"'{predicted_root_name}' — reconvergence storm possible."
        ),
        details=details,
        affected_objects=[baseline_root_id, predicted_root_id],
        affected_sites=[baseline.site_id],
        remediation_hint=(
            "Review STP priority changes carefully. If the root shift is intentional, "
            "schedule during a maintenance window."
        ),
        description="Detects STP root bridge shifts caused by bridge priority changes, which trigger network-wide reconvergence.",
    )


# ---------------------------------------------------------------------------
# STP-BPDU helpers
# ---------------------------------------------------------------------------


def _is_bpdu_filter_enabled(port_cfg: dict) -> bool:
    """Return True if any BPDU filter key is truthy in the port config."""
    return any(port_cfg.get(k) for k in _BPDU_FILTER_KEYS)


def _is_trunk_port(
    port_cfg: dict,
    port_usages: dict[str, dict],
) -> bool:
    """Return True if the port is a trunk port.

    Checks both direct ``usage == "trunk"`` and port_usages profile ``mode == "trunk"``.
    """
    usage = port_cfg.get("usage", "")
    if usage == "trunk":
        return True
    # Lookup in port_usages profiles
    profile = port_usages.get(usage, {})
    return profile.get("mode") == "trunk"


# ---------------------------------------------------------------------------
# STP-BPDU: BPDU Filter on Trunk — Layer 5, warning
# ---------------------------------------------------------------------------


def _check_stp_bpdu(predicted: SiteSnapshot) -> CheckResult:
    """Detect BPDU filter enabled on trunk ports in switch devices."""
    violations: list[str] = []
    affected_objects: list[str] = []

    for dev_id, dev in predicted.devices.items():
        if dev.type != "switch":
            continue

        # Merge site-level and device-level port_usages
        effective_usages = dict(predicted.port_usages)
        if dev.port_usages:
            effective_usages.update(dev.port_usages)

        for port_name, port_cfg in dev.port_config.items():
            if _is_bpdu_filter_enabled(port_cfg) and _is_trunk_port(port_cfg, effective_usages):
                violations.append(f"{dev.name} port {port_name}: BPDU filter enabled on trunk")
                if dev_id not in affected_objects:
                    affected_objects.append(dev_id)

    if not violations:
        return CheckResult(
            check_id="STP-BPDU",
            check_name="BPDU Filter on Trunk",
            layer=5,
            status="pass",
            summary="No BPDU filter enabled on trunk ports.",
            description="Flags trunk ports with BPDU filter enabled, which disables STP loop protection on switch-to-switch uplinks.",
        )

    return CheckResult(
        check_id="STP-BPDU",
        check_name="BPDU Filter on Trunk",
        layer=5,
        status="warning",
        summary=f"{len(violations)} trunk port(s) with BPDU filter — STP protection disabled.",
        details=violations,
        affected_objects=sorted(affected_objects),
        affected_sites=[predicted.site_id],
        remediation_hint=(
            "Remove BPDU filter from trunk ports. BPDU filter should only be used on "
            "edge/access ports, never on switch-to-switch uplinks."
        ),
        description="Flags trunk ports with BPDU filter enabled, which disables STP loop protection on switch-to-switch uplinks.",
    )


# ---------------------------------------------------------------------------
# STP-LOOP helpers
# ---------------------------------------------------------------------------


def _normalize_cycle(cycle: list[str]) -> frozenset[str]:
    """Normalize a cycle to a frozenset for order-independent comparison."""
    return frozenset(cycle)


# ---------------------------------------------------------------------------
# STP-LOOP: L2 Loop Risk — Layer 5, warning
# ---------------------------------------------------------------------------


def _check_stp_loop(baseline: SiteSnapshot, predicted: SiteSnapshot) -> CheckResult:
    """Detect new L2 cycles in the physical graph."""
    baseline_graph = build_site_graph(baseline)
    predicted_graph = build_site_graph(predicted)

    baseline_cycles = nx.cycle_basis(baseline_graph.physical)
    predicted_cycles = nx.cycle_basis(predicted_graph.physical)

    baseline_cycle_sets = {_normalize_cycle(c) for c in baseline_cycles}
    predicted_cycle_sets = {_normalize_cycle(c) for c in predicted_cycles}

    new_cycles = predicted_cycle_sets - baseline_cycle_sets

    if not new_cycles:
        return CheckResult(
            check_id="STP-LOOP",
            check_name="L2 Loop Risk",
            layer=5,
            status="pass",
            summary="No new L2 loops detected in predicted topology.",
            description="Detects new L2 cycles introduced in the physical topology graph that could cause broadcast storms.",
        )

    # Resolve MACs to device names for readable output. Fall back to the MAC
    # when a device has no name (avoids rendering "a ->  -> b" with an empty
    # cell in the detail string). Note: the previous ``mac_to_name.get(mac, mac)``
    # call wasn't enough because ``dev.name`` can be stored as an empty string,
    # which is still a *present* key and suppresses the default.
    mac_to_name: dict[str, str] = {}
    for dev in predicted.devices.values():
        if dev.mac:
            mac_to_name[dev.mac] = dev.name or dev.mac

    def _label(mac: str) -> str:
        return mac_to_name.get(mac) or mac

    details: list[str] = []
    all_affected: set[str] = set()

    for cycle_set in sorted(new_cycles, key=lambda s: sorted(s))[:_MAX_REPORTED_CYCLES]:
        names = [_label(mac) for mac in sorted(cycle_set)]
        details.append(f"New cycle: {' -> '.join(names)}")
        all_affected |= cycle_set

    affected_names = sorted({_label(mac) for mac in all_affected if mac})

    return CheckResult(
        check_id="STP-LOOP",
        check_name="L2 Loop Risk",
        layer=5,
        status="warning",
        summary=f"{len(new_cycles)} new L2 loop(s) detected — potential broadcast storm risk.",
        details=details,
        affected_objects=affected_names,
        affected_sites=[baseline.site_id],
        remediation_hint=(
            "Enable STP/RSTP on all ports in the loop path, convert redundant links to LAG, "
            "or remove the redundant connection."
        ),
        description="Detects new L2 cycles introduced in the physical topology graph that could cause broadcast storms.",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def check_stp(baseline: SiteSnapshot, predicted: SiteSnapshot) -> list[CheckResult]:
    """Run all STP checks (STP-ROOT + STP-BPDU + STP-LOOP).

    Returns:
        A list of three CheckResult objects.
    """
    return [
        _check_stp_root(baseline, predicted),
        _check_stp_bpdu(predicted),
        _check_stp_loop(baseline, predicted),
    ]
