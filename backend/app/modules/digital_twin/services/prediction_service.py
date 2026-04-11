"""
Orchestrate validation checks and build PredictionReport.

Phase 1: Runs Layer 1 (config conflict) checks only.
Phase 2+: Will add topology, routing, security, and L2 checks.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.modules.digital_twin.models import CheckResult, PredictionReport

logger = structlog.get_logger(__name__)

_SEVERITY_ORDER = {"pass": 0, "skipped": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}
_SEVERITY_LABELS = {0: "clean", 1: "info", 2: "warning", 3: "error", 4: "critical"}


def compute_overall_severity(results: list[CheckResult]) -> str:
    """Compute worst severity from a list of check results."""
    worst = 0
    for r in results:
        level = _SEVERITY_ORDER.get(r.status, 0)
        if level > worst:
            worst = level
    return _SEVERITY_LABELS[worst]


def build_prediction_report(results: list[CheckResult]) -> PredictionReport:
    """Build a PredictionReport from a list of CheckResults."""
    passed = sum(1 for r in results if r.status == "pass")
    warnings = sum(1 for r in results if r.status == "warning")
    errors = sum(1 for r in results if r.status == "error")
    critical = sum(1 for r in results if r.status == "critical")
    skipped = sum(1 for r in results if r.status == "skipped")
    severity = compute_overall_severity(results)

    parts: list[str] = []
    if critical:
        parts.append(f"{critical} critical")
    if errors:
        parts.append(f"{errors} error(s)")
    if warnings:
        parts.append(f"{warnings} warning(s)")
    summary = ", ".join(parts) if parts else "All checks passed"

    return PredictionReport(
        total_checks=len(results),
        passed=passed,
        warnings=warnings,
        errors=errors,
        critical=critical,
        skipped=skipped,
        check_results=results,
        overall_severity=severity,
        summary=summary,
        execution_safe=(errors == 0 and critical == 0),
    )


async def run_layer1_checks(
    virtual_state: dict[tuple, dict[str, Any]],
    staged_writes: list,
    org_id: str,
) -> list[CheckResult]:
    """Run all Layer 1 config conflict checks against the virtual state.

    This is the main entry point for Phase 1 validation. It extracts the
    relevant config data from the virtual state and runs each check.
    """
    from app.modules.digital_twin.services.config_checks import (
        check_duplicate_ssid,
        check_ip_subnet_overlap,
        check_ssid_airtime_overhead,
        check_subnet_collision_within_site,
        check_vlan_id_collision,
    )
    from app.modules.digital_twin.services.state_resolver import load_all_objects_of_type

    results: list[CheckResult] = []

    # Collect all networks from virtual state
    all_networks: list[dict[str, Any]] = []
    for (obj_type, site_id, _obj_id), config in virtual_state.items():
        if obj_type == "networks":
            config_copy = dict(config)
            config_copy["_site_id"] = site_id
            config_copy["_site_name"] = site_id or "org"
            all_networks.append(config_copy)

    # Load existing networks from backup for cross-reference
    existing_networks_raw = await load_all_objects_of_type(org_id, "networks")
    existing_networks = []
    for net in existing_networks_raw:
        net_copy = dict(net)
        net_copy.setdefault("_site_name", "existing")
        net_copy.setdefault("_site_id", net.get("site_id"))
        existing_networks.append(net_copy)

    # Determine which networks are new (from staged writes)
    new_network_ids = set()
    for w in staged_writes:
        if w.object_type == "networks" and w.method == "POST":
            new_network_ids.add(w.object_id)
    new_networks = [
        n
        for n in all_networks
        if n.get("id") in new_network_ids or (n.get("id") or "").startswith("twin-")
    ]

    # L1-01: IP/subnet overlap (new vs existing)
    results.append(check_ip_subnet_overlap(existing_networks, new_networks))

    # L1-02: Subnet collision within site (all networks including new)
    combined_networks = existing_networks + new_networks
    results.append(check_subnet_collision_within_site(combined_networks))

    # L1-03: VLAN ID collision
    results.append(check_vlan_id_collision(combined_networks))

    # Collect WLANs
    all_wlans: list[dict[str, Any]] = []
    for (obj_type, site_id, _obj_id), config in virtual_state.items():
        if obj_type == "wlans":
            wlan_copy = dict(config)
            wlan_copy["_site_id"] = site_id
            all_wlans.append(wlan_copy)

    existing_wlans_raw = await load_all_objects_of_type(org_id, "wlans")
    for w in existing_wlans_raw:
        w_copy = dict(w)
        w_copy.setdefault("_site_id", w.get("site_id"))
        all_wlans.append(w_copy)

    # L1-04: Duplicate SSID
    results.append(check_duplicate_ssid(all_wlans))

    # L1-11: SSID airtime overhead
    results.append(check_ssid_airtime_overhead(all_wlans))

    return results
