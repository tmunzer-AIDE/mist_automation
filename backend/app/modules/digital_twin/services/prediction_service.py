"""
Orchestrate validation checks and build PredictionReport.

Phase 1: Runs Layer 1 (config conflict) checks only.
Phase 2+: Will add topology, routing, security, and L2 checks.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import structlog

from app.modules.digital_twin.models import CheckResult, PredictionReport

logger = structlog.get_logger(__name__)

# Maps object_type to the set of check IDs that are relevant when that type is modified.
# Checks not in the relevant set are skipped (status="skipped").
# If no staged writes have a known type, all checks run as fallback.
CHECK_RELEVANCE: dict[str, set[str]] = {
    "wlans": {
        "L1-04", "L1-06", "L1-07", "L1-11", "L1-12", "L1-14",  # SSID, template, airtime, PSK, capacity
        "L4-01",  # Guest SSID security
    },
    "networks": {
        "L1-01", "L1-02", "L1-03", "L1-08", "L1-09", "L1-10",  # IP, subnet, VLAN, DHCP, DNS/NTP
        "L2-02",  # VLAN black hole
    },
    "setting": {
        "L1-06", "L1-07", "L1-10",  # Template override, unresolved vars, DNS/NTP
        "L3-01",  # Default gateway gap
    },
    "devices": {
        "L1-05",  # Port profile conflict
        "L1-15",  # Port profile disconnect risk (LLDP neighbors)
        "L2-01", "L2-03", "L2-04", "L2-05", "L2-06", "L2-07", "L2-08", "L2-09",  # Topology checks
        "L3-02", "L3-03", "L3-04", "L3-05",  # Routing checks
        "L5-01", "L5-02", "L5-03",  # L2 loop checks
    },
    "networktemplates": {
        "L1-01", "L1-02", "L1-03", "L1-06", "L1-07", "L1-08", "L1-09", "L1-10",
        "L2-02",
    },
    "rftemplates": {
        "L1-13",  # RF template impact
    },
    "gatewaytemplates": {
        "L1-05", "L1-06", "L1-07",
        "L3-01", "L3-02", "L3-03", "L3-04", "L3-05",
    },
    "deviceprofiles": {
        "L1-05", "L1-06", "L1-07",
    },
    "secpolicies": {
        "L4-04", "L4-05", "L4-06",  # Security policy checks
    },
    "servicepolicies": {
        "L4-04", "L4-05",
    },
    "services": {
        "L4-05",
    },
    "nacrules": {
        "L4-02", "L4-03",  # NAC checks
    },
    "nactags": {
        "L4-02", "L4-03",
    },
    "psks": {
        "L1-12",  # PSK rotation impact
    },
}


def compute_relevant_checks(staged_writes: list) -> set[str] | None:
    """Compute the set of relevant check IDs based on staged write object types.

    Returns None if all checks should run (fallback when no types are recognized).
    Returns a set of check IDs when filtering should be applied.
    """
    object_types = {w.object_type for w in staged_writes if w.object_type}
    if not object_types:
        return None  # No known types → run all checks

    relevant: set[str] = set()
    has_mapping = False
    for obj_type in object_types:
        checks = CHECK_RELEVANCE.get(obj_type)
        if checks:
            relevant |= checks
            has_mapping = True

    if not has_mapping:
        return None  # None of the types have mappings → run all as fallback

    return relevant


@dataclass
class SimulationContext:
    """Pre-fetched data shared across all check layers to avoid duplicate DB loads."""

    existing_networks: list[dict[str, Any]]
    existing_wlans: list[dict[str, Any]]
    existing_devices: list[dict[str, Any]]


async def _build_simulation_context(org_id: str) -> SimulationContext:
    """Pre-fetch shared backup data once for all check layers."""
    from app.modules.digital_twin.services.state_resolver import load_all_objects_of_type

    networks, wlans, devices = await asyncio.gather(
        load_all_objects_of_type(org_id, "networks"),
        load_all_objects_of_type(org_id, "wlans"),
        load_all_objects_of_type(org_id, "devices"),
    )
    return SimulationContext(
        existing_networks=networks,
        existing_wlans=wlans,
        existing_devices=devices,
    )


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


def _extract_poe_data_from_cache(site_id: str) -> tuple[dict[str, float], dict[str, list[str]]]:
    """Extract PoE budget and active PoE ports from telemetry cache.

    Returns:
        (poe_budgets, active_poe_ports)
        poe_budgets: {device_id: total_max_power_watts}
        active_poe_ports: {device_id: [port_ids delivering PoE]}
    """
    poe_budgets: dict[str, float] = {}
    active_poe_ports: dict[str, list[str]] = {}

    try:
        from app.modules.telemetry import _latest_cache

        if not _latest_cache:
            return poe_budgets, active_poe_ports

        cached_devices = _latest_cache.get_all_for_site(site_id, max_age_seconds=120)
        for stats in cached_devices:
            if stats.get("type") != "switch":
                continue
            device_id = stats.get("_id", stats.get("mac", ""))

            # Sum PoE budget across all modules (FPCs)
            total_max = 0.0
            for module in stats.get("module_stat", []):
                poe = module.get("poe", {})
                total_max += poe.get("max_power", 0)

            if total_max > 0:
                poe_budgets[device_id] = total_max

            # For active PoE ports, check clients with LLDP source
            # (Switch WS doesn't expose per-port PoE, so we track ports that are up
            # and connected to PoE devices like APs based on LLDP clients)
            active_ports: list[str] = []
            for client in stats.get("clients", []):
                if client.get("source") == "lldp":
                    active_ports.extend(client.get("port_ids", []))
            if active_ports:
                active_poe_ports[device_id] = active_ports
    except Exception:
        pass

    return poe_budgets, active_poe_ports


def _get_lldp_neighbors_for_device(site_id: str, device_mac: str) -> dict[str, str]:
    """Get LLDP neighbors from telemetry cache for a specific device.

    Returns dict mapping port_id -> neighbor_mac.
    """
    try:
        from app.modules.telemetry import _latest_cache

        if _latest_cache is None:
            return {}

        for device_stats in _latest_cache.get_all_for_site(site_id, max_age_seconds=120):
            if device_stats.get("mac") == device_mac:
                neighbors: dict[str, str] = {}
                for client in device_stats.get("clients", []):
                    if client.get("source") == "lldp":
                        port_id = client.get("port_id", "")
                        neighbor_mac = client.get("mac", "")
                        if port_id and neighbor_mac:
                            neighbors[port_id] = neighbor_mac
                return neighbors
    except Exception:
        pass
    return {}


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
        total_checks=len(results) - skipped,
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
    ctx: SimulationContext | None = None,
    relevant_checks: set[str] | None = None,
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
        check_port_profile_disconnect_risk,
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

    # Use pre-fetched context if available, otherwise load from backup
    if ctx:
        existing_networks_raw, existing_wlans_raw, existing_devices_raw = (
            ctx.existing_networks,
            ctx.existing_wlans,
            ctx.existing_devices,
        )
    else:
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
    if relevant_checks is None or "L1-01" in relevant_checks:
        results.append(check_ip_subnet_overlap(existing_networks, new_networks))
    else:
        results.append(CheckResult(check_id="L1-01", check_name="IP/Subnet Overlap", layer=1, status="skipped", summary="Not relevant for this change type"))

    # L1-02: Subnet collision within site
    combined_networks = existing_networks + new_networks
    if relevant_checks is None or "L1-02" in relevant_checks:
        results.append(check_subnet_collision_within_site(combined_networks))
    else:
        results.append(CheckResult(check_id="L1-02", check_name="Subnet Collision Within Site", layer=1, status="skipped", summary="Not relevant for this change type"))

    # L1-03: VLAN ID collision
    if relevant_checks is None or "L1-03" in relevant_checks:
        results.append(check_vlan_id_collision(combined_networks))
    else:
        results.append(CheckResult(check_id="L1-03", check_name="VLAN ID Collision", layer=1, status="skipped", summary="Not relevant for this change type"))

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
    if relevant_checks is None or "L1-04" in relevant_checks:
        results.append(check_duplicate_ssid(all_wlans))
    else:
        results.append(CheckResult(check_id="L1-04", check_name="Duplicate SSID", layer=1, status="skipped", summary="Not relevant for this change type"))

    # L1-11: SSID airtime overhead
    if relevant_checks is None or "L1-11" in relevant_checks:
        results.append(check_ssid_airtime_overhead(all_wlans))
    else:
        results.append(CheckResult(check_id="L1-11", check_name="SSID Airtime Overhead", layer=1, status="skipped", summary="Not relevant for this change type"))

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

    if relevant_checks is None or "L1-05" in relevant_checks:
        results.append(check_port_profile_conflict(existing_port_entries, new_port_entries))
    else:
        results.append(CheckResult(check_id="L1-05", check_name="Port Profile Conflict", layer=1, status="skipped", summary="Not relevant for this change type"))

    # ── L1-06 & L1-07: Template checks ────────────────────────────────
    affected_site_ids: set[str] = set()
    for w in staged_writes:
        if w.site_id:
            affected_site_ids.add(w.site_id)

    _run_l106 = relevant_checks is None or "L1-06" in relevant_checks
    _run_l107 = relevant_checks is None or "L1-07" in relevant_checks
    if not _run_l106:
        results.append(CheckResult(check_id="L1-06", check_name="Template Override Crush", layer=1, status="skipped", summary="Not relevant for this change type"))
    if not _run_l107:
        results.append(CheckResult(check_id="L1-07", check_name="Unresolved Template Variables", layer=1, status="skipped", summary="Not relevant for this change type"))

    for site_id in affected_site_ids:
        try:
            ctx = await get_site_template_context(org_id, site_id, virtual_state)
            site_vars = ctx["site_vars"]
            site_name = ctx["site_name"]

            for tmpl in ctx["assigned_templates"]:
                tmpl_config = tmpl["config"]
                tmpl_name = tmpl["template_name"]

                # L1-06: Template override crush
                if _run_l106:
                    site_setting = virtual_state.get(("setting", site_id, None), {})
                    if site_setting:
                        results.append(check_template_override_crush(site_setting, tmpl_config, site_name))

                # L1-07: Unresolved template variables
                if _run_l107:
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

    if relevant_checks is None or "L1-08" in relevant_checks:
        results.append(check_dhcp_scope_overlap(dhcp_configs))
    else:
        results.append(CheckResult(check_id="L1-08", check_name="DHCP Scope Overlap", layer=1, status="skipped", summary="Not relevant for this change type"))

    if relevant_checks is None or "L1-09" in relevant_checks:
        results.append(check_dhcp_server_misconfiguration(dhcp_configs))
    else:
        results.append(CheckResult(check_id="L1-09", check_name="DHCP Server Misconfiguration", layer=1, status="skipped", summary="Not relevant for this change type"))

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
    if relevant_checks is None or "L1-10" in relevant_checks:
        results.append(check_dns_ntp_consistency(device_dns_configs))
    else:
        results.append(CheckResult(check_id="L1-10", check_name="DNS/NTP Consistency", layer=1, status="skipped", summary="Not relevant for this change type"))

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
            if relevant_checks is None or "L1-12" in relevant_checks:
                results.append(check_psk_rotation_impact(old_config, new_config, active_clients, site_name))
            else:
                results.append(CheckResult(check_id="L1-12", check_name="PSK Rotation Client Impact", layer=1, status="skipped", summary="Not relevant for this change type"))

            # L1-14: Client capacity impact
            if relevant_checks is None or "L1-14" in relevant_checks:
                results.append(check_client_capacity_impact(old_config, new_config, active_clients, site_name))
            else:
                results.append(CheckResult(check_id="L1-14", check_name="Client Capacity Impact", layer=1, status="skipped", summary="Not relevant for this change type"))

        elif w.object_type == "rftemplates":
            # Count APs at affected sites from telemetry cache
            affected_ap_count = _count_aps_at_sites(device_cache, affected_site_ids)

            # L1-13: RF template impact
            if relevant_checks is None or "L1-13" in relevant_checks:
                results.append(check_rf_template_impact(old_config, new_config, affected_ap_count))
            else:
                results.append(CheckResult(check_id="L1-13", check_name="RF Template Impact", layer=1, status="skipped", summary="Not relevant for this change type"))

        elif w.object_type == "devices":
            device_mac = old_config.get("mac", "")
            device_name = old_config.get("name", device_mac or "unknown")
            lldp_neighbors = _get_lldp_neighbors_for_device(w.site_id or "", device_mac)

            # Compile old_config with derived site setting so it has the full
            # inherited port_config (backup stores raw overrides only).
            # new_config from virtual_state is already compiled.
            old_for_check = old_config
            if old_config.get("type") == "switch" and w.site_id:
                from app.modules.digital_twin.services.config_compiler import (
                    _get_derived_site_setting,
                    compile_switch_config,
                )

                derived = await _get_derived_site_setting(w.site_id, org_id)
                site_vars = {str(k): str(v) for k, v in derived.get("vars", {}).items()}
                old_compiled = compile_switch_config(derived, old_config, site_vars)
                old_for_check = {**old_config, **old_compiled}

            # L1-15: Port profile disconnect risk
            if relevant_checks is None or "L1-15" in relevant_checks:
                results.append(
                    check_port_profile_disconnect_risk(old_for_check, new_config, lldp_neighbors, device_name, site_name)
                )
            else:
                results.append(
                    CheckResult(
                        check_id="L1-15",
                        check_name="Port Profile Disconnect Risk",
                        layer=1,
                        status="skipped",
                        summary="Not relevant for this change type",
                    )
                )

    return results


async def run_layer2_checks(
    virtual_state: dict[tuple, dict[str, Any]],
    staged_writes: list,
    org_id: str,
    affected_site_ids: set[str],
    relevant_checks: set[str] | None = None,
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

            # PoE data from telemetry
            poe_budgets, active_poe_ports = _extract_poe_data_from_cache(site_id)

            # Port counts from predicted snapshot
            port_counts: dict[str, tuple[int, int]] = {}
            for dev_id, dev_info in predicted_snapshot.get("devices", {}).items():
                if dev_info.get("device_type") == "switch":
                    # Count used ports from connections + total from device model
                    used = sum(
                        1
                        for c in predicted_snapshot.get("connections", [])
                        if c.get("local_device_id") == dev_id or c.get("remote_device_id") == dev_id
                    )
                    # Estimate total ports from model (fallback: 48)
                    total = 48  # Default
                    port_counts[dev_id] = (used, total)

            # Run all L2 checks
            if relevant_checks is None or "L2-01" in relevant_checks:
                results.append(check_connectivity_loss(baseline_snapshot, predicted_snapshot))
            else:
                results.append(CheckResult(check_id="L2-01", check_name="Connectivity Loss", layer=2, status="skipped", summary="Not relevant for this change type"))
            if relevant_checks is None or "L2-02" in relevant_checks:
                results.append(check_vlan_black_hole(predicted_snapshot))
            else:
                results.append(CheckResult(check_id="L2-02", check_name="VLAN Black Hole", layer=2, status="skipped", summary="Not relevant for this change type"))
            if relevant_checks is None or "L2-03" in relevant_checks:
                results.append(check_lag_mclag_integrity(baseline_snapshot, predicted_snapshot))
            else:
                results.append(CheckResult(check_id="L2-03", check_name="LAG/MCLAG Integrity", layer=2, status="skipped", summary="Not relevant for this change type"))
            if relevant_checks is None or "L2-04" in relevant_checks:
                results.append(check_vc_integrity(baseline_snapshot, predicted_snapshot))
            else:
                results.append(CheckResult(check_id="L2-04", check_name="VC Integrity", layer=2, status="skipped", summary="Not relevant for this change type"))
            if relevant_checks is None or "L2-05" in relevant_checks:
                results.append(check_poe_budget_overrun(predicted_snapshot, poe_budgets))
            else:
                results.append(CheckResult(check_id="L2-05", check_name="PoE Budget Overrun", layer=2, status="skipped", summary="Not relevant for this change type"))
            if relevant_checks is None or "L2-06" in relevant_checks:
                results.append(check_poe_disable_on_active(baseline_snapshot, predicted_snapshot, active_poe_ports))
            else:
                results.append(CheckResult(check_id="L2-06", check_name="PoE Disable on Active Port", layer=2, status="skipped", summary="Not relevant for this change type"))
            if relevant_checks is None or "L2-07" in relevant_checks:
                results.append(check_port_capacity_saturation(predicted_snapshot, port_counts))
            else:
                results.append(CheckResult(check_id="L2-07", check_name="Port Capacity Saturation", layer=2, status="skipped", summary="Not relevant for this change type"))
            if relevant_checks is None or "L2-08" in relevant_checks:
                results.append(check_lacp_misconfiguration(predicted_snapshot))
            else:
                results.append(CheckResult(check_id="L2-08", check_name="LACP Misconfiguration", layer=2, status="skipped", summary="Not relevant for this change type"))
            if relevant_checks is None or "L2-09" in relevant_checks:
                results.append(check_mtu_mismatch(predicted_snapshot))
            else:
                results.append(CheckResult(check_id="L2-09", check_name="MTU Mismatch", layer=2, status="skipped", summary="Not relevant for this change type"))
        except Exception as e:
            logger.warning("l2_checks_failed", site_id=site_id, error=str(e))

    return results


async def run_layer3_checks(
    virtual_state: dict[tuple, dict[str, Any]],
    staged_writes: list,
    org_id: str,
    affected_site_ids: set[str],
    relevant_checks: set[str] | None = None,
) -> list[CheckResult]:
    """Run Layer 3 routing prediction checks."""
    from app.modules.digital_twin.services.routing_checks import (
        check_bgp_peer_break,
        check_default_gateway_gap,
        check_ospf_adjacency_break,
        check_vrf_consistency,
        check_wan_failover_impact,
    )
    from app.modules.impact_analysis.services.topology_service import (
        build_site_topology,
        capture_topology_snapshot,
    )

    results: list[CheckResult] = []

    # Build device configs and routing data from virtual state
    device_configs: dict[str, dict[str, Any]] = {}
    baseline_routing: dict[str, dict[str, Any]] = {}

    for (obj_type, _site_id, obj_id), config in virtual_state.items():
        if obj_type == "devices" and obj_id:
            device_configs[obj_id] = dict(config)

    # Load baseline routing from backup (OSPF/BGP peers)
    from app.modules.backup.models import BackupObject

    for dev_id, cfg in device_configs.items():
        if cfg.get("routing") or cfg.get("ospf") or cfg.get("bgp_peers"):
            baseline_routing[dev_id] = {
                "ospf_peers": cfg.get("routing", {}).get("ospf_peers", []),
                "bgp_peers": cfg.get("routing", {}).get("bgp_peers", []),
            }

    for site_id in affected_site_ids:
        try:
            topo = await build_site_topology(site_id, org_id)
            if topo:
                snapshot = capture_topology_snapshot(topo)
                if relevant_checks is None or "L3-01" in relevant_checks:
                    results.append(check_default_gateway_gap(snapshot, device_configs))
                else:
                    results.append(CheckResult(check_id="L3-01", check_name="Default Gateway Gap", layer=3, status="skipped", summary="Not relevant for this change type"))
        except Exception as e:
            logger.warning("l3_topology_check_failed", site_id=site_id, error=str(e))

    if relevant_checks is None or "L3-02" in relevant_checks:
        results.append(check_ospf_adjacency_break(baseline_routing, device_configs))
    else:
        results.append(CheckResult(check_id="L3-02", check_name="OSPF Adjacency Break", layer=3, status="skipped", summary="Not relevant for this change type"))
    if relevant_checks is None or "L3-03" in relevant_checks:
        results.append(check_bgp_peer_break(baseline_routing, device_configs))
    else:
        results.append(CheckResult(check_id="L3-03", check_name="BGP Peer Break", layer=3, status="skipped", summary="Not relevant for this change type"))
    if relevant_checks is None or "L3-04" in relevant_checks:
        results.append(check_vrf_consistency(device_configs))
    else:
        results.append(CheckResult(check_id="L3-04", check_name="VRF Consistency", layer=3, status="skipped", summary="Not relevant for this change type"))

    # Baseline configs for WAN failover comparison
    baseline_configs: dict[str, dict[str, Any]] = {}
    for dev_id in device_configs:
        backup = (
            await BackupObject.find({"object_type": "devices", "object_id": dev_id, "is_deleted": False})
            .sort([("version", -1)])
            .first_or_none()
        )
        if backup:
            baseline_configs[dev_id] = backup.configuration

    if relevant_checks is None or "L3-05" in relevant_checks:
        results.append(check_wan_failover_impact(baseline_configs, device_configs))
    else:
        results.append(CheckResult(check_id="L3-05", check_name="WAN Failover Impact", layer=3, status="skipped", summary="Not relevant for this change type"))

    return results


async def run_layer4_checks(
    virtual_state: dict[tuple, dict[str, Any]],
    staged_writes: list,
    org_id: str,
    ctx: SimulationContext | None = None,
    relevant_checks: set[str] | None = None,
) -> list[CheckResult]:
    """Run Layer 4 security policy checks."""
    from app.modules.digital_twin.services.security_checks import (
        check_firewall_rule_shadow,
        check_guest_ssid_security,
        check_nac_auth_server_dependency,
        check_nac_vlan_conflict,
        check_service_policy_references,
        check_unreachable_destination,
    )
    from app.modules.digital_twin.services.state_resolver import load_all_objects_of_type

    results: list[CheckResult] = []

    # Collect WLANs from virtual state
    all_wlans: list[dict[str, Any]] = []
    for (obj_type, site_id, _obj_id), config in virtual_state.items():
        if obj_type == "wlans":
            wlan_copy = dict(config)
            wlan_copy["_site_id"] = site_id
            all_wlans.append(wlan_copy)

    # Also include existing WLANs from backup (use ctx if available)
    existing_wlans = ctx.existing_wlans if ctx else await load_all_objects_of_type(org_id, "wlans")
    for w in existing_wlans:
        w_copy = dict(w)
        w_copy.setdefault("_site_id", w.get("site_id"))
        all_wlans.append(w_copy)

    if relevant_checks is None or "L4-01" in relevant_checks:
        results.append(check_guest_ssid_security(all_wlans))
    else:
        results.append(CheckResult(check_id="L4-01", check_name="Guest SSID Security", layer=4, status="skipped", summary="Not relevant for this change type"))

    # NAC rules and auth servers
    nac_rules: list[dict[str, Any]] = []
    for (obj_type, _site_id, _obj_id), config in virtual_state.items():
        if obj_type == "nacrules":
            nac_rules.append(dict(config))
    existing_nac = await load_all_objects_of_type(org_id, "nacrules")
    nac_rules.extend(existing_nac)

    auth_servers: list[dict[str, Any]] = []
    for (obj_type, _site_id, _obj_id), config in virtual_state.items():
        if obj_type in ("nacportals", "ssos"):
            auth_servers.append(dict(config))
    existing_nacportals = await load_all_objects_of_type(org_id, "nacportals")
    auth_servers.extend(existing_nacportals)
    existing_ssos = await load_all_objects_of_type(org_id, "ssos")
    auth_servers.extend(existing_ssos)

    if relevant_checks is None or "L4-02" in relevant_checks:
        results.append(check_nac_auth_server_dependency(nac_rules, auth_servers))
    else:
        results.append(CheckResult(check_id="L4-02", check_name="NAC Auth Server Dependency", layer=4, status="skipped", summary="Not relevant for this change type"))
    if relevant_checks is None or "L4-03" in relevant_checks:
        results.append(check_nac_vlan_conflict(nac_rules))
    else:
        results.append(CheckResult(check_id="L4-03", check_name="NAC VLAN Conflict", layer=4, status="skipped", summary="Not relevant for this change type"))

    # Security policies, networks, services
    security_policies: list[dict[str, Any]] = []
    for (obj_type, _site_id, _obj_id), config in virtual_state.items():
        if obj_type == "secpolicies":
            security_policies.append(dict(config))
    existing_sec = await load_all_objects_of_type(org_id, "secpolicies")
    security_policies.extend(existing_sec)

    networks: list[dict[str, Any]] = []
    for (obj_type, _site_id, _obj_id), config in virtual_state.items():
        if obj_type == "networks":
            networks.append(dict(config))
    existing_nets = ctx.existing_networks if ctx else await load_all_objects_of_type(org_id, "networks")
    networks.extend(existing_nets)

    services: list[dict[str, Any]] = []
    for (obj_type, _site_id, _obj_id), config in virtual_state.items():
        if obj_type == "services":
            services.append(dict(config))
    existing_svcs = await load_all_objects_of_type(org_id, "services")
    services.extend(existing_svcs)

    if relevant_checks is None or "L4-04" in relevant_checks:
        results.append(check_unreachable_destination(security_policies, networks, services))
    else:
        results.append(CheckResult(check_id="L4-04", check_name="Unreachable Destination", layer=4, status="skipped", summary="Not relevant for this change type"))

    service_policies: list[dict[str, Any]] = []
    for (obj_type, _site_id, _obj_id), config in virtual_state.items():
        if obj_type == "servicepolicies":
            service_policies.append(dict(config))
    existing_sps = await load_all_objects_of_type(org_id, "servicepolicies")
    service_policies.extend(existing_sps)

    if relevant_checks is None or "L4-05" in relevant_checks:
        results.append(check_service_policy_references(service_policies, services))
    else:
        results.append(CheckResult(check_id="L4-05", check_name="Service Policy References", layer=4, status="skipped", summary="Not relevant for this change type"))
    if relevant_checks is None or "L4-06" in relevant_checks:
        results.append(check_firewall_rule_shadow(security_policies))
    else:
        results.append(CheckResult(check_id="L4-06", check_name="Firewall Rule Shadow", layer=4, status="skipped", summary="Not relevant for this change type"))

    return results


async def run_layer5_checks(
    virtual_state: dict[tuple, dict[str, Any]],
    staged_writes: list,
    org_id: str,
    affected_site_ids: set[str],
    relevant_checks: set[str] | None = None,
) -> list[CheckResult]:
    """Run Layer 5 L2/STP prediction checks."""
    from app.modules.backup.models import BackupObject
    from app.modules.digital_twin.services.l2_checks import (
        check_bpdu_filter_on_trunk,
        check_l2_loop_risk,
        check_stp_root_bridge_shift,
    )
    from app.modules.digital_twin.services.predicted_topology import build_predicted_topology
    from app.modules.impact_analysis.services.topology_service import (
        build_site_topology,
        capture_topology_snapshot,
    )

    results: list[CheckResult] = []

    # Build device configs for STP checks
    predicted_configs: dict[str, dict[str, Any]] = {}
    for (obj_type, _site_id, obj_id), config in virtual_state.items():
        if obj_type == "devices" and obj_id:
            predicted_configs[obj_id] = dict(config)

    # Load baseline configs from backup
    baseline_configs: dict[str, dict[str, Any]] = {}
    for dev_id in predicted_configs:
        backup = (
            await BackupObject.find({"object_type": "devices", "object_id": dev_id, "is_deleted": False})
            .sort([("version", -1)])
            .first_or_none()
        )
        if backup:
            baseline_configs[dev_id] = backup.configuration

    for site_id in affected_site_ids:
        try:
            baseline_topo = await build_site_topology(site_id, org_id)
            if not baseline_topo:
                continue
            baseline_snapshot = capture_topology_snapshot(baseline_topo)

            predicted_topo = await build_predicted_topology(site_id, org_id, virtual_state)
            if not predicted_topo:
                continue
            predicted_snapshot = capture_topology_snapshot(predicted_topo)

            if relevant_checks is None or "L5-01" in relevant_checks:
                results.append(check_l2_loop_risk(baseline_snapshot, predicted_snapshot))
            else:
                results.append(CheckResult(check_id="L5-01", check_name="L2 Loop Risk", layer=5, status="skipped", summary="Not relevant for this change type"))
        except Exception as e:
            logger.warning("l5_topology_check_failed", site_id=site_id, error=str(e))

    if relevant_checks is None or "L5-02" in relevant_checks:
        results.append(check_bpdu_filter_on_trunk(predicted_configs))
    else:
        results.append(CheckResult(check_id="L5-02", check_name="BPDU Filter on Trunk", layer=5, status="skipped", summary="Not relevant for this change type"))
    if relevant_checks is None or "L5-03" in relevant_checks:
        results.append(check_stp_root_bridge_shift(baseline_configs, predicted_configs))
    else:
        results.append(CheckResult(check_id="L5-03", check_name="STP Root Bridge Shift", layer=5, status="skipped", summary="Not relevant for this change type"))

    return results
