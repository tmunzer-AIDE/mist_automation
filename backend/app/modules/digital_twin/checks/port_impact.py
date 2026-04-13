"""
Port impact checks: PORT-DISC (disconnect risk) and PORT-CLIENT (client impact estimation).

These are Layer 2 checks that compare baseline vs predicted SiteSnapshot objects
to detect port configuration changes that either disconnect LLDP neighbors or
remove VLAN reachability on existing LLDP links, and estimate the wireless
client impact of physically disconnected APs.
"""

from __future__ import annotations

import structlog

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot
from app.modules.digital_twin.services.topology_utils import (
    build_network_name_to_vlan,
    materialize_port_config_entry,
    merge_infra_neighbor_ports,
    normalize_port_id,
    resolve_port_config_entry,
)

logger = structlog.get_logger(__name__)


_SEVERITY_RANK: dict[str, int] = {
    "pass": 0,
    "warning": 1,
    "error": 2,
    "critical": 3,
}


def _max_severity(current: str, candidate: str) -> str:
    """Return the higher-priority severity."""
    if _SEVERITY_RANK.get(candidate, 0) > _SEVERITY_RANK.get(current, 0):
        return candidate
    return current


def _find_device_by_mac(snapshot: SiteSnapshot, mac: str) -> tuple[str, str, str]:
    """Find a device in the snapshot by its MAC address.

    Returns:
        (device_id, device_name, device_type) or ("", "", "") if not found.
    """
    for dev in snapshot.devices.values():
        if dev.mac == mac:
            return dev.device_id, dev.name, dev.type
    return "", "", ""


def check_port_impact(baseline: SiteSnapshot, predicted: SiteSnapshot) -> list[CheckResult]:
    """Run PORT-DISC and PORT-CLIENT checks on baseline vs predicted snapshots.

    PORT-DISC (Layer 2): For each device, compare port_config between baseline and
    predicted. For ports with LLDP neighbors, detect:
    - physical disconnect risk (port removed/disabled), and
    - VLAN isolation risk (the port stops carrying one or more baseline VLANs).

    PORT-CLIENT (Layer 2): For each disconnected AP found by PORT-DISC, sum the
    wireless clients from baseline.ap_clients and report the impact.

    When baseline has switches/gateways but no LLDP data, both checks return
    ``skipped`` — this signals that live telemetry was unavailable rather than
    giving a false "all clear".

    Returns:
        A list of two CheckResult objects: [PORT-DISC result, PORT-CLIENT result].
    """
    has_l2_device = any(dev.type in ("switch", "gateway") for dev in baseline.devices.values())
    neighbor_ports = merge_infra_neighbor_ports(baseline, include_unknown_lldp_neighbors=True)
    if has_l2_device and not any(neighbor_ports.values()):
        skipped_summary = (
            "Live LLDP data unavailable — cannot verify which ports connect to neighbors. "
            "Port disconnect impact was not evaluated."
        )
        skipped_hint = (
            "Re-run the simulation once live device telemetry is reachable. "
            "Check that listOrgDevicesStats returns clients[] with source='lldp' for this site."
        )
        return [
            CheckResult(
                check_id="PORT-DISC",
                check_name="Port Profile Disconnect Risk",
                layer=2,
                status="skipped",
                summary=skipped_summary,
                affected_sites=[baseline.site_id],
                remediation_hint=skipped_hint,
                description="Compares switch/gateway port profiles to find LLDP-confirmed neighbors that would be disconnected or lose VLAN membership.",
            ),
            CheckResult(
                check_id="PORT-CLIENT",
                check_name="Client Impact Estimation",
                layer=2,
                status="skipped",
                summary="Live LLDP data unavailable — client impact was not estimated.",
                affected_sites=[baseline.site_id],
                remediation_hint=skipped_hint,
                description="Estimates the number of wireless clients affected by APs disconnected by port profile changes.",
            ),
        ]

    disc_details: list[str] = []
    disc_affected: list[str] = []
    disc_max_severity: str = "pass"
    disconnected_ap_ids: list[str] = []
    has_physical_disconnect = False
    has_vlan_isolation = False
    baseline_site_vars = baseline.site_setting.get("vars") or {}
    predicted_site_vars = predicted.site_setting.get("vars") or {}
    baseline_network_map = build_network_name_to_vlan(baseline.networks, baseline_site_vars)
    predicted_network_map = build_network_name_to_vlan(predicted.networks, predicted_site_vars)

    for dev_id, baseline_dev in baseline.devices.items():
        predicted_dev = predicted.devices.get(dev_id)
        if predicted_dev is None:
            # Device removed entirely — handled by other checks
            continue

        mac = baseline_dev.mac
        neighbors_for_device = neighbor_ports.get(mac, {})

        old_port_config = baseline_dev.port_config
        new_port_config = predicted_dev.port_config

        # Diagnostic: when a staged write touches a port_config on a device
        # that has live LLDP data, log what PORT-DISC is actually comparing
        # so we can tell whether the check is silently missing a port change
        # because the LLDP table is empty for that port (MAC/port_id mismatch)
        # or because the baseline's port_config doesn't carry the usage
        # (compile_base_state didn't surface it). Fires only when the device's
        # compiled port_config actually differs between baseline and predicted.
        all_ports = {
            normalize_port_id(p)
            for p in set(old_port_config) | set(new_port_config)
            if normalize_port_id(p)
        }
        changed_ports = sorted(
            {
                p
                for p in all_ports
                if resolve_port_config_entry(old_port_config, p).get("usage")
                != resolve_port_config_entry(new_port_config, p).get("usage")
            }
        )
        if changed_ports:
            logger.debug(
                "port_disc_diagnostic",
                device=baseline_dev.name,
                mac=mac,
                changed_ports=changed_ports,
                lldp_ports_for_device=sorted(neighbors_for_device.keys()),
                missing_lldp_for_changed_ports=sorted(set(changed_ports) - set(neighbors_for_device.keys())),
                baseline_usage={p: resolve_port_config_entry(old_port_config, p).get("usage", "") for p in changed_ports},
                predicted_usage={p: resolve_port_config_entry(new_port_config, p).get("usage", "") for p in changed_ports},
            )

        if not neighbors_for_device:
            continue

        for port, neighbor_mac in neighbors_for_device.items():
            old_cfg = resolve_port_config_entry(old_port_config, port)
            new_cfg = resolve_port_config_entry(new_port_config, port)

            old_usage = old_cfg.get("usage", "")
            new_usage = new_cfg.get("usage", "")

            old_effective_usages = dict(baseline.port_usages)
            if baseline_dev.port_usages:
                old_effective_usages.update(baseline_dev.port_usages)
            new_effective_usages = dict(predicted.port_usages)
            if predicted_dev.port_usages:
                new_effective_usages.update(predicted_dev.port_usages)

            old_materialized = materialize_port_config_entry(
                old_cfg,
                old_effective_usages,
                baseline_network_map,
                baseline_site_vars,
            )
            new_materialized = materialize_port_config_entry(
                new_cfg,
                new_effective_usages,
                predicted_network_map,
                predicted_site_vars,
            )
            old_vlans = {int(vlan) for vlan in old_materialized.get("resolved_vlan_ids", [])}
            new_vlans = {int(vlan) for vlan in new_materialized.get("resolved_vlan_ids", [])}
            removed_vlans = sorted(old_vlans - new_vlans)

            physical_disconnect = False
            change_label_old = old_usage or "(none)"
            change_label_new = new_usage or "(removed)"

            if old_cfg and not new_cfg:
                # Port removed from predicted config
                physical_disconnect = True
            elif old_usage != "disabled" and (new_usage == "disabled" or bool(new_materialized.get("disabled"))):
                # Port transitioned to disabled in predicted state.
                physical_disconnect = True

            if not physical_disconnect and not removed_vlans:
                continue

            # Resolve connected device info
            connected_id, connected_name, connected_type = _find_device_by_mac(baseline, neighbor_mac)
            if not connected_name:
                connected_name = neighbor_mac
            if not connected_type:
                connected_type = "unknown"

            if physical_disconnect:
                has_physical_disconnect = True
                # Determine severity based on connected device type
                if connected_type in ("ap", "switch"):
                    severity = "critical"
                else:
                    severity = "error"
                disc_max_severity = _max_severity(disc_max_severity, severity)

                detail = (
                    f"{baseline_dev.name} port {port}: '{change_label_old}' -> '{change_label_new}', "
                    f"disconnects {connected_name} ({connected_type})"
                )
                disc_details.append(detail)
                disc_affected.append(f"{baseline_dev.name}:{port}")

                # Track physically disconnected APs for PORT-CLIENT.
                if connected_type == "ap" and connected_id:
                    disconnected_ap_ids.append(connected_id)

            elif removed_vlans:
                has_vlan_isolation = True
                if connected_type in ("ap", "switch"):
                    severity = "critical"
                else:
                    severity = "warning"
                disc_max_severity = _max_severity(disc_max_severity, severity)

                detail = (
                    f"{baseline_dev.name} port {port}: '{change_label_old}' -> '{change_label_new}', "
                    f"no longer carries VLAN(s) {removed_vlans}; may isolate VLAN traffic with "
                    f"{connected_name} ({connected_type})"
                )
                disc_details.append(detail)
                disc_affected.append(f"{baseline_dev.name}:{port}")

    # Keep a stable check_id for UI grouping/filtering; express scenario via
    # check_name/summary instead of changing the ID.
    disc_check_id = "PORT-DISC"
    disc_check_name = "Port Profile Disconnect Risk"

    if has_vlan_isolation and not has_physical_disconnect:
        disc_check_name = "Port VLAN Isolation Risk"
    elif has_vlan_isolation and has_physical_disconnect:
        disc_check_name = "Port Link and VLAN Reachability Risk"

    if disc_details:
        if has_vlan_isolation and not has_physical_disconnect:
            disc_summary = f"{len(disc_details)} port change(s) may isolate VLAN traffic on active LLDP neighbors"
        elif has_physical_disconnect and not has_vlan_isolation:
            disc_summary = f"{len(disc_details)} port change(s) will disconnect active LLDP neighbors"
        else:
            disc_summary = f"{len(disc_details)} port change(s) may disconnect LLDP neighbors or isolate VLAN traffic"
    else:
        disc_summary = "No port changes disconnect connected LLDP neighbors or remove VLAN reachability"

    port_disc = CheckResult(
        check_id=disc_check_id,
        check_name=disc_check_name,
        layer=2,
        status=disc_max_severity,
        summary=disc_summary,
        details=disc_details,
        affected_objects=disc_affected,
        affected_sites=[baseline.site_id] if disc_details else [],
        remediation_hint=(
            "Review port/profile changes and verify affected links still carry required VLANs for downstream devices."
            if disc_details
            else None
        ),
        description="Compares switch/gateway port profiles to find LLDP-confirmed neighbors that would be disconnected or lose VLAN membership.",
    )

    # Build PORT-CLIENT result
    total_clients = 0
    client_details: list[str] = []
    for ap_id in disconnected_ap_ids:
        count = baseline.ap_clients.get(ap_id, 0)
        total_clients += count
        if count > 0:
            # Find AP name
            ap_dev = baseline.devices.get(ap_id)
            ap_name = ap_dev.name if ap_dev else ap_id
            client_details.append(f"{ap_name}: {count} wireless client(s)")

    if total_clients == 0 and not disconnected_ap_ids:
        client_status = "pass"
        client_summary = "No wireless client impact from port changes"
    elif total_clients == 0:
        client_status = "pass"
        client_summary = f"{len(disconnected_ap_ids)} AP(s) disconnected but no wireless clients currently associated"
    elif total_clients >= 50:
        client_status = "critical"
        client_summary = f"{total_clients} wireless client(s) affected by AP disconnection(s)"
    else:
        client_status = "warning"
        client_summary = f"{total_clients} wireless client(s) affected by AP disconnection(s)"

    port_client = CheckResult(
        check_id="PORT-CLIENT",
        check_name="Client Impact Estimation",
        layer=2,
        status=client_status,
        summary=client_summary,
        details=client_details,
        affected_objects=[f"ap:{ap_id}" for ap_id in disconnected_ap_ids] if disconnected_ap_ids else [],
        affected_sites=[baseline.site_id] if disconnected_ap_ids else [],
        remediation_hint=(
            "Schedule port changes during a maintenance window to minimize client disruption."
            if total_clients > 0
            else None
        ),
        description="Estimates the number of wireless clients affected by APs disconnected by port profile changes.",
    )

    return [port_disc, port_client]
