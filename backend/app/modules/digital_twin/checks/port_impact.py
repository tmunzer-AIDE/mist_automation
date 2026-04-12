"""
Port impact checks: PORT-DISC (disconnect risk) and PORT-CLIENT (client impact estimation).

These are Layer 2 checks that compare baseline vs predicted SiteSnapshot objects
to detect port configuration changes that would disconnect LLDP neighbors and
estimate the wireless client impact of disconnected APs.
"""

from __future__ import annotations

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot


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
    predicted. For ports with LLDP neighbors, detect removals, disabling, and usage
    changes that would disconnect the neighbor.

    PORT-CLIENT (Layer 2): For each disconnected AP found by PORT-DISC, sum the
    wireless clients from baseline.ap_clients and report the impact.

    When baseline has switches/gateways but no LLDP data, both checks return
    ``skipped`` — this signals that live telemetry was unavailable rather than
    giving a false "all clear".

    Returns:
        A list of two CheckResult objects: [PORT-DISC result, PORT-CLIENT result].
    """
    has_l2_device = any(dev.type in ("switch", "gateway") for dev in baseline.devices.values())
    if has_l2_device and not baseline.lldp_neighbors:
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
            ),
            CheckResult(
                check_id="PORT-CLIENT",
                check_name="Client Impact Estimation",
                layer=2,
                status="skipped",
                summary="Live LLDP data unavailable — client impact was not estimated.",
                affected_sites=[baseline.site_id],
                remediation_hint=skipped_hint,
            ),
        ]

    disc_details: list[str] = []
    disc_affected: list[str] = []
    disc_max_severity: str = "pass"
    disconnected_ap_ids: list[str] = []

    for dev_id, baseline_dev in baseline.devices.items():
        predicted_dev = predicted.devices.get(dev_id)
        if predicted_dev is None:
            # Device removed entirely — handled by other checks
            continue

        mac = baseline_dev.mac
        lldp_for_device = baseline.lldp_neighbors.get(mac, {})
        if not lldp_for_device:
            continue

        old_port_config = baseline_dev.port_config
        new_port_config = predicted_dev.port_config

        for port, neighbor_mac in lldp_for_device.items():
            old_cfg = old_port_config.get(port, {})
            new_cfg = new_port_config.get(port, {})

            old_usage = old_cfg.get("usage", "")
            new_usage = new_cfg.get("usage", "")

            disconnect = False

            if old_cfg and not new_cfg:
                # Port removed from predicted config
                disconnect = True
            elif new_usage == "disabled":
                # Port explicitly disabled
                disconnect = True
            elif old_usage and new_usage and old_usage != new_usage:
                # Usage changed to a different value
                disconnect = True

            if not disconnect:
                continue

            # Resolve connected device info
            connected_id, connected_name, connected_type = _find_device_by_mac(baseline, neighbor_mac)
            if not connected_name:
                connected_name = neighbor_mac
            if not connected_type:
                connected_type = "unknown"

            # Determine severity based on connected device type
            if connected_type in ("ap", "switch"):
                severity = "critical"
            else:
                severity = "error"

            if severity == "critical" or (severity == "error" and disc_max_severity != "critical"):
                disc_max_severity = severity

            detail_usage_old = old_usage or "(none)"
            detail_usage_new = new_usage or "(removed)"
            detail = (
                f"{baseline_dev.name} port {port}: '{detail_usage_old}' -> '{detail_usage_new}', "
                f"disconnects {connected_name} ({connected_type})"
            )
            disc_details.append(detail)
            disc_affected.append(f"{baseline_dev.name}:{port}")

            # Track disconnected APs for PORT-CLIENT
            if connected_type == "ap" and connected_id:
                disconnected_ap_ids.append(connected_id)

    # Build PORT-DISC result
    if disc_details:
        disc_summary = f"{len(disc_details)} port change(s) will disconnect active LLDP neighbors"
    else:
        disc_summary = "No port changes affect connected LLDP neighbors"

    port_disc = CheckResult(
        check_id="PORT-DISC",
        check_name="Port Profile Disconnect Risk",
        layer=2,
        status=disc_max_severity,
        summary=disc_summary,
        details=disc_details,
        affected_objects=disc_affected,
        affected_sites=[baseline.site_id] if disc_details else [],
        remediation_hint=(
            "Review port profile changes and verify no critical infrastructure is connected to affected ports."
            if disc_details
            else None
        ),
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
    )

    return [port_disc, port_client]
