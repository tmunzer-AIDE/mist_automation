"""
Orchestrate validation checks and build PredictionReport.

Phase 1: Runs Layer 1 (config conflict) checks only.
Phase 2+: Will add topology, routing, security, and L2 checks.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.modules.digital_twin.models import CheckResult, PredictionReport

logger = structlog.get_logger(__name__)


# ── Telemetry cache helpers (graceful when telemetry is not running) ────


def _get_client_cache():
    """Get the telemetry client cache, or None if telemetry is not active."""
    try:
        from app.modules.telemetry import _client_cache

        return _client_cache
    except ImportError:
        return None


def _get_device_cache():
    """Get the telemetry device cache, or None if telemetry is not active."""
    try:
        from app.modules.telemetry import _latest_cache

        return _latest_cache
    except ImportError:
        return None


def _count_clients_on_ssid(client_cache, site_id: str | None, ssid: str) -> int:
    """Count active clients on a specific SSID from the telemetry client cache."""
    if not client_cache or not site_id or not ssid:
        return 0
    try:
        entries = client_cache.get_all_for_site(site_id, max_age_seconds=120)
        return sum(1 for e in entries if e.get("ssid") == ssid)
    except Exception:
        return 0


def _count_aps_at_sites(device_cache, site_ids: set[str]) -> int:
    """Count APs across affected sites from the telemetry device cache."""
    if not device_cache or not site_ids:
        return 0
    total = 0
    try:
        for site_id in site_ids:
            devices = device_cache.get_all_for_site(site_id, max_age_seconds=60)
            total += sum(1 for d in devices if d.get("type") == "ap" or d.get("device_type") == "ap")
    except Exception:
        pass
    return total


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
    """Run all 14 Layer 1 config conflict checks against the virtual state."""
    from app.modules.backup.models import BackupObject
    from app.modules.digital_twin.services.config_checks import (
        check_client_capacity_impact,
        check_dhcp_scope_overlap,
        check_dhcp_server_misconfiguration,
        check_dns_ntp_consistency,
        check_duplicate_ssid,
        check_ip_subnet_overlap,
        check_port_profile_conflict,
        check_psk_rotation_impact,
        check_rf_template_impact,
        check_ssid_airtime_overhead,
        check_subnet_collision_within_site,
        check_template_override_crush,
        check_unresolved_template_variables,
        check_vlan_id_collision,
    )
    from app.modules.digital_twin.services.state_resolver import load_all_objects_of_type
    from app.modules.digital_twin.services.template_resolver import get_site_template_context

    results: list[CheckResult] = []

    # ── Collect networks ───────────────────────────────────────────────
    all_networks: list[dict[str, Any]] = []
    for (obj_type, site_id, _obj_id), config in virtual_state.items():
        if obj_type == "networks":
            config_copy = dict(config)
            config_copy["_site_id"] = site_id
            config_copy["_site_name"] = site_id or "org"
            all_networks.append(config_copy)

    # Parallel load from backup
    existing_networks_raw, existing_wlans_raw, existing_devices_raw = await asyncio.gather(
        load_all_objects_of_type(org_id, "networks"),
        load_all_objects_of_type(org_id, "wlans"),
        load_all_objects_of_type(org_id, "devices"),
    )

    existing_networks = []
    for net in existing_networks_raw:
        net_copy = dict(net)
        net_copy.setdefault("_site_name", "existing")
        net_copy.setdefault("_site_id", net.get("site_id"))
        existing_networks.append(net_copy)

    new_network_ids = set()
    for w in staged_writes:
        if w.object_type == "networks" and w.method == "POST":
            new_network_ids.add(w.object_id)
    new_networks = [
        n for n in all_networks if n.get("id") in new_network_ids or (n.get("id") or "").startswith("twin-")
    ]

    # L1-01: IP/subnet overlap
    results.append(check_ip_subnet_overlap(existing_networks, new_networks))

    # L1-02: Subnet collision within site
    combined_networks = existing_networks + new_networks
    results.append(check_subnet_collision_within_site(combined_networks))

    # L1-03: VLAN ID collision
    results.append(check_vlan_id_collision(combined_networks))

    # ── Collect WLANs ──────────────────────────────────────────────────
    all_wlans: list[dict[str, Any]] = []
    for (obj_type, site_id, _obj_id), config in virtual_state.items():
        if obj_type == "wlans":
            wlan_copy = dict(config)
            wlan_copy["_site_id"] = site_id
            all_wlans.append(wlan_copy)

    for w in existing_wlans_raw:
        w_copy = dict(w)
        w_copy.setdefault("_site_id", w.get("site_id"))
        all_wlans.append(w_copy)

    # L1-04: Duplicate SSID
    results.append(check_duplicate_ssid(all_wlans))

    # L1-11: SSID airtime overhead
    results.append(check_ssid_airtime_overhead(all_wlans))

    # ── L1-05: Port profile conflict ───────────────────────────────────
    existing_port_entries: list[dict[str, Any]] = []
    for dev in existing_devices_raw:
        port_config = dev.get("port_config")
        if not port_config or not isinstance(port_config, dict):
            continue
        device_name = dev.get("name", dev.get("mac", "?"))
        for port_name, port_cfg in port_config.items():
            if not isinstance(port_cfg, dict):
                continue
            existing_port_entries.append(
                {
                    "_device_name": device_name,
                    "_site_id": dev.get("site_id"),
                    "port": port_name,
                    "profile": port_cfg.get("usage", port_cfg.get("profile", "")),
                }
            )

    new_port_entries: list[dict[str, Any]] = []
    for w in staged_writes:
        if w.object_type == "devices" and w.method in ("PUT", "POST") and w.body:
            port_config = w.body.get("port_config")
            if not port_config or not isinstance(port_config, dict):
                continue
            device_name = w.body.get("name", w.object_id or "?")
            for port_name, port_cfg in port_config.items():
                if not isinstance(port_cfg, dict):
                    continue
                new_port_entries.append(
                    {
                        "_device_name": device_name,
                        "_site_id": w.site_id,
                        "port": port_name,
                        "profile": port_cfg.get("usage", port_cfg.get("profile", "")),
                    }
                )

    results.append(check_port_profile_conflict(existing_port_entries, new_port_entries))

    # ── L1-06 & L1-07: Template checks ────────────────────────────────
    affected_site_ids: set[str] = set()
    for w in staged_writes:
        if w.site_id:
            affected_site_ids.add(w.site_id)

    for site_id in affected_site_ids:
        try:
            ctx = await get_site_template_context(org_id, site_id, virtual_state)
            site_vars = ctx["site_vars"]
            site_name = ctx["site_name"]

            for tmpl in ctx["assigned_templates"]:
                tmpl_config = tmpl["config"]
                tmpl_name = tmpl["template_name"]

                # L1-06: Template override crush
                site_setting = virtual_state.get(("setting", site_id, None), {})
                if site_setting:
                    results.append(check_template_override_crush(site_setting, tmpl_config, site_name))

                # L1-07: Unresolved template variables
                results.append(check_unresolved_template_variables(tmpl_config, site_vars, tmpl_name, site_name))
        except Exception as e:
            logger.warning("template_check_failed", site_id=site_id, error=str(e))

    # ── L1-08 & L1-09: DHCP checks ────────────────────────────────────
    dhcp_configs: list[dict[str, Any]] = []

    for (obj_type, site_id, _obj_id), config in virtual_state.items():
        if obj_type not in ("devices", "setting"):
            continue
        dhcpd = config.get("dhcpd_config")
        if not dhcpd or not isinstance(dhcpd, dict):
            continue
        if not dhcpd.get("enabled", True):
            continue
        device_name = config.get("name", config.get("mac", _obj_id or "?"))
        for network_name, scope in dhcpd.items():
            if network_name in ("enabled",) or not isinstance(scope, dict):
                continue
            if scope.get("type") != "local":
                continue
            # Try to find subnet from network definitions if not in scope
            subnet = scope.get("subnet", "")
            if not subnet:
                for (nt, ns, _ni), ncfg in virtual_state.items():
                    if nt == "networks" and ns == site_id and ncfg.get("name") == network_name:
                        subnet = ncfg.get("subnet", "")
                        break
            dhcp_configs.append(
                {
                    "_device_name": device_name,
                    "_site_id": site_id,
                    "network": network_name,
                    "subnet": subnet,
                    "ip_start": scope.get("ip_start", ""),
                    "ip_end": scope.get("ip_end", ""),
                    "gateway": scope.get("gateway", ""),
                }
            )

    results.append(check_dhcp_scope_overlap(dhcp_configs))
    results.append(check_dhcp_server_misconfiguration(dhcp_configs))

    # ── L1-10: DNS/NTP consistency ─────────────────────────────────────
    device_dns_configs: list[dict[str, Any]] = []
    for (obj_type, site_id, _obj_id), config in virtual_state.items():
        if obj_type in ("devices", "setting"):
            device_dns_configs.append(
                {
                    "_device_name": config.get("name", _obj_id or "?"),
                    "_site_id": site_id,
                    "dns_servers": config.get("dns_servers", config.get("dns", [])),
                    "ntp_servers": config.get("ntp_servers", config.get("ntp", [])),
                }
            )
    results.append(check_dns_ntp_consistency(device_dns_configs))

    # ── Per-write comparison checks (L1-12, L1-13, L1-14) ─────────────
    # Try to load live client/device stats from telemetry cache
    client_cache = _get_client_cache()
    device_cache = _get_device_cache()

    for w in staged_writes:
        if w.method != "PUT" or not w.object_id:
            continue

        # Load old config from backup
        old_backup = (
            await BackupObject.find({"object_type": w.object_type, "object_id": w.object_id, "is_deleted": False})
            .sort([("version", -1)])
            .first_or_none()
        )
        old_config = old_backup.configuration if old_backup else {}

        # New config from virtual state
        new_config = virtual_state.get((w.object_type, w.site_id, w.object_id), {})

        site_name = w.site_id or "org"

        if w.object_type == "wlans":
            # Count active clients on this SSID from telemetry cache
            active_clients = _count_clients_on_ssid(client_cache, w.site_id, old_config.get("ssid", ""))

            # L1-12: PSK rotation impact
            results.append(check_psk_rotation_impact(old_config, new_config, active_clients, site_name))

            # L1-14: Client capacity impact
            results.append(check_client_capacity_impact(old_config, new_config, active_clients, site_name))

        elif w.object_type == "rftemplates":
            # Count APs at affected sites from telemetry cache
            affected_ap_count = _count_aps_at_sites(device_cache, affected_site_ids)

            # L1-13: RF template impact
            results.append(check_rf_template_impact(old_config, new_config, affected_ap_count))

    return results


async def run_layer2_checks(
    virtual_state: dict[tuple, dict[str, Any]],
    staged_writes: list,
    org_id: str,
    affected_site_ids: set[str],
) -> list[CheckResult]:
    """Run Layer 2 topology prediction checks for each affected site."""
    from app.modules.digital_twin.services.predicted_topology import build_predicted_topology
    from app.modules.digital_twin.services.topology_checks import (
        check_connectivity_loss,
        check_lacp_misconfiguration,
        check_lag_mclag_integrity,
        check_mtu_mismatch,
        check_poe_budget_overrun,
        check_poe_disable_on_active,
        check_port_capacity_saturation,
        check_vc_integrity,
        check_vlan_black_hole,
    )
    from app.modules.impact_analysis.services.topology_service import (
        build_site_topology,
        capture_topology_snapshot,
    )

    results: list[CheckResult] = []

    for site_id in affected_site_ids:
        try:
            # Build baseline topology (current live state)
            baseline_topo = await build_site_topology(site_id, org_id)
            if not baseline_topo:
                continue
            baseline_snapshot = capture_topology_snapshot(baseline_topo)

            # Build predicted topology (after changes applied)
            predicted_topo = await build_predicted_topology(site_id, org_id, virtual_state)
            if not predicted_topo:
                continue
            predicted_snapshot = capture_topology_snapshot(predicted_topo)

            # Run all L2 checks
            results.append(check_connectivity_loss(baseline_snapshot, predicted_snapshot))
            results.append(check_vlan_black_hole(predicted_snapshot))
            results.append(check_lag_mclag_integrity(baseline_snapshot, predicted_snapshot))
            results.append(check_vc_integrity(baseline_snapshot, predicted_snapshot))
            results.append(check_poe_budget_overrun(predicted_snapshot, {}))
            results.append(check_poe_disable_on_active(baseline_snapshot, predicted_snapshot, {}))
            results.append(check_port_capacity_saturation(predicted_snapshot, {}))
            results.append(check_lacp_misconfiguration(predicted_snapshot))
            results.append(check_mtu_mismatch(predicted_snapshot))
        except Exception as e:
            logger.warning("l2_checks_failed", site_id=site_id, error=str(e))

    return results
