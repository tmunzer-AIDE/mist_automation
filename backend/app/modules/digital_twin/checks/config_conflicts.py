"""
Configuration conflict checks operating on a SiteSnapshot.

All functions are pure — no async, no DB access.
Each helper returns one or more CheckResult items.
The top-level ``check_config_conflicts()`` aggregates results from all five helpers.

Checks:
  CFG-SUBNET  — IP subnet overlap (all-pairs on snap.networks)
  CFG-VLAN    — VLAN ID collision (>1 network name per vlan_id)
  CFG-SSID    — Duplicate SSID among enabled WLANs
  CFG-DHCP-RNG — DHCP scope overlap across devices
  CFG-DHCP-CFG — DHCP misconfiguration (gateway/range outside subnet)
"""

from __future__ import annotations

import ipaddress
from typing import Any

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot


# ---------------------------------------------------------------------------
# CFG-SUBNET: IP Subnet Overlap — Layer 1, critical
# ---------------------------------------------------------------------------


def _check_subnet_overlap(snap: SiteSnapshot) -> CheckResult:
    """All-pairs comparison on snap.networks subnets using ipaddress.ip_network().overlaps()."""
    conflicts: list[str] = []
    affected_objects: list[str] = []

    # Collect networks that have a valid subnet field
    parsed: list[tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, str, str]] = []
    for net_id, net in snap.networks.items():
        subnet_str = net.get("subnet")
        if not subnet_str:
            continue
        try:
            network = ipaddress.ip_network(subnet_str, strict=False)
        except (ValueError, TypeError):
            continue
        name = net.get("name", net_id)
        parsed.append((network, name, subnet_str))

    # All-pairs overlap check
    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            net_a, name_a, subnet_a = parsed[i]
            net_b, name_b, subnet_b = parsed[j]
            if net_a.overlaps(net_b):
                detail = f"'{name_a}' ({subnet_a}) overlaps with '{name_b}' ({subnet_b})"
                conflicts.append(detail)
                if name_a not in affected_objects:
                    affected_objects.append(name_a)
                if name_b not in affected_objects:
                    affected_objects.append(name_b)

    if conflicts:
        return CheckResult(
            check_id="CFG-SUBNET",
            check_name="IP Subnet Overlap",
            layer=1,
            status="critical",
            summary=f"Found {len(conflicts)} subnet overlap(s)",
            details=conflicts,
            affected_objects=affected_objects,
            affected_sites=[snap.site_id],
            remediation_hint="Assign non-overlapping subnets to each network.",
        )

    return CheckResult(
        check_id="CFG-SUBNET",
        check_name="IP Subnet Overlap",
        layer=1,
        status="pass",
        summary="No subnet overlaps detected",
    )


# ---------------------------------------------------------------------------
# CFG-VLAN: VLAN ID Collision — Layer 1, error
# ---------------------------------------------------------------------------


def _check_vlan_collision(snap: SiteSnapshot) -> CheckResult:
    """Group networks by vlan_id, flag any VLAN used by >1 network name."""
    vlan_map: dict[int, list[str]] = {}

    for net_id, net in snap.networks.items():
        vlan_id = net.get("vlan_id")
        if vlan_id is None:
            continue
        try:
            vid = int(vlan_id)
        except (ValueError, TypeError):
            continue
        name = net.get("name", net_id)
        vlan_map.setdefault(vid, []).append(name)

    conflicts: list[str] = []
    affected_objects: list[str] = []

    for vid, names in sorted(vlan_map.items()):
        unique_names = list(dict.fromkeys(names))
        if len(unique_names) > 1:
            detail = f"VLAN {vid} used by: {', '.join(unique_names)}"
            conflicts.append(detail)
            for n in unique_names:
                if n not in affected_objects:
                    affected_objects.append(n)

    if conflicts:
        return CheckResult(
            check_id="CFG-VLAN",
            check_name="VLAN ID Collision",
            layer=1,
            status="error",
            summary=f"Found {len(conflicts)} VLAN ID collision(s)",
            details=conflicts,
            affected_objects=affected_objects,
            affected_sites=[snap.site_id],
            remediation_hint="Assign unique VLAN IDs to each network, or merge networks that share the same VLAN.",
        )

    return CheckResult(
        check_id="CFG-VLAN",
        check_name="VLAN ID Collision",
        layer=1,
        status="pass",
        summary="No VLAN ID collisions detected",
    )


# ---------------------------------------------------------------------------
# CFG-SSID: Duplicate SSID — Layer 1, error
# ---------------------------------------------------------------------------


def _check_duplicate_ssid(snap: SiteSnapshot) -> CheckResult:
    """Count SSIDs among enabled WLANs, flag duplicates. Skip disabled WLANs."""
    ssid_count: dict[str, int] = {}

    for _wlan_id, wlan in snap.wlans.items():
        if not wlan.get("enabled", True):
            continue
        ssid = wlan.get("ssid", "")
        if ssid:
            ssid_count[ssid] = ssid_count.get(ssid, 0) + 1

    conflicts: list[str] = []
    affected_objects: list[str] = []

    for ssid, count in sorted(ssid_count.items()):
        if count > 1:
            detail = f"SSID '{ssid}' appears {count} times among enabled WLANs"
            conflicts.append(detail)
            if ssid not in affected_objects:
                affected_objects.append(ssid)

    if conflicts:
        return CheckResult(
            check_id="CFG-SSID",
            check_name="Duplicate SSID",
            layer=1,
            status="error",
            summary=f"Found {len(conflicts)} duplicate SSID(s)",
            details=conflicts,
            affected_objects=affected_objects,
            affected_sites=[snap.site_id],
            remediation_hint="Remove or rename duplicate SSIDs. Each SSID should be unique within a site.",
        )

    return CheckResult(
        check_id="CFG-SSID",
        check_name="Duplicate SSID",
        layer=1,
        status="pass",
        summary="No duplicate SSIDs detected",
    )


# ---------------------------------------------------------------------------
# CFG-DHCP-RNG: DHCP Scope Overlap — Layer 1, error
# ---------------------------------------------------------------------------


def _collect_dhcp_ranges(snap: SiteSnapshot) -> list[dict[str, Any]]:
    """Collect DHCP ranges from all devices' dhcpd_config where enabled=True and type='local'."""
    ranges: list[dict[str, Any]] = []

    def _canonical_network_name(name: str) -> str:
        # Mist DHCP keys can appear as "<gateway>/<network>" aliases.
        # Normalize to the final segment to compare equivalent scopes.
        raw = str(name or "").strip()
        if "/" in raw:
            return raw.rsplit("/", 1)[-1]
        return raw

    for dev_id, dev in snap.devices.items():
        dhcpd = dev.dhcpd_config
        if not dhcpd:
            continue
        # Top-level enabled flag
        if not dhcpd.get("enabled", False):
            continue

        for net_name, net_cfg in dhcpd.items():
            if not isinstance(net_cfg, dict):
                continue
            if net_cfg.get("type") != "local":
                continue
            ip_start = net_cfg.get("ip_start")
            ip_end = net_cfg.get("ip_end")
            if ip_start and ip_end:
                ranges.append(
                    {
                        "device_id": dev_id,
                        "device_name": dev.name,
                        "network_name": net_name,
                        "network_name_canonical": _canonical_network_name(net_name),
                        "ip_start": ip_start,
                        "ip_end": ip_end,
                        "gateway": net_cfg.get("gateway"),
                    }
                )

    # Deduplicate equivalent entries from template/device aliasing.
    deduped: list[dict[str, Any]] = []
    seen_by_device: set[tuple[str, str, str, str, str]] = set()
    named_scope_keys: set[tuple[str, str, str, str]] = set()

    for entry in ranges:
        device_key = (
            entry.get("device_id", ""),
            entry.get("network_name_canonical", ""),
            str(entry.get("ip_start", "")),
            str(entry.get("ip_end", "")),
            str(entry.get("gateway") or ""),
        )
        if device_key in seen_by_device:
            continue
        seen_by_device.add(device_key)

        if str(entry.get("device_name", "")).strip():
            named_scope_keys.add(device_key[1:])

        deduped.append(entry)

    # If the same DHCP scope appears both with and without a device name,
    # keep the named version and drop the anonymous shadow entry.
    filtered: list[dict[str, Any]] = []
    for entry in deduped:
        scope_key = (
            entry.get("network_name_canonical", ""),
            str(entry.get("ip_start", "")),
            str(entry.get("ip_end", "")),
            str(entry.get("gateway") or ""),
        )
        if not str(entry.get("device_name", "")).strip() and scope_key in named_scope_keys:
            continue
        filtered.append(entry)

    return filtered


def _check_dhcp_scope_overlap(snap: SiteSnapshot) -> CheckResult:
    """All-pairs check on DHCP ranges: start_a <= end_b and start_b <= end_a."""
    ranges = _collect_dhcp_ranges(snap)

    # Parse IP addresses to integers for comparison
    parsed: list[tuple[int, int, dict[str, Any]]] = []
    for r in ranges:
        try:
            start = int(ipaddress.ip_address(r["ip_start"]))
            end = int(ipaddress.ip_address(r["ip_end"]))
            parsed.append((start, end, r))
        except (ValueError, TypeError):
            continue

    conflicts: list[str] = []
    affected_objects: list[str] = []

    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            start_a, end_a, range_a = parsed[i]
            start_b, end_b, range_b = parsed[j]
            if start_a <= end_b and start_b <= end_a:
                detail = (
                    f"DHCP range overlap: {range_a['device_name']}/{range_a['network_name']} "
                    f"({range_a['ip_start']}-{range_a['ip_end']}) vs "
                    f"{range_b['device_name']}/{range_b['network_name']} "
                    f"({range_b['ip_start']}-{range_b['ip_end']})"
                )
                conflicts.append(detail)
                obj_a = f"{range_a['device_name']}/{range_a['network_name']}"
                obj_b = f"{range_b['device_name']}/{range_b['network_name']}"
                if obj_a not in affected_objects:
                    affected_objects.append(obj_a)
                if obj_b not in affected_objects:
                    affected_objects.append(obj_b)

    if conflicts:
        return CheckResult(
            check_id="CFG-DHCP-RNG",
            check_name="DHCP Scope Overlap",
            layer=1,
            status="error",
            summary=f"Found {len(conflicts)} overlapping DHCP scope(s)",
            details=conflicts,
            affected_objects=affected_objects,
            affected_sites=[snap.site_id],
            remediation_hint="Ensure DHCP ranges do not overlap across devices.",
        )

    return CheckResult(
        check_id="CFG-DHCP-RNG",
        check_name="DHCP Scope Overlap",
        layer=1,
        status="pass",
        summary="No overlapping DHCP scopes detected",
    )


# ---------------------------------------------------------------------------
# CFG-DHCP-CFG: DHCP Misconfiguration — Layer 1, error
# ---------------------------------------------------------------------------


def _check_dhcp_misconfiguration(snap: SiteSnapshot) -> CheckResult:
    """For each local DHCP config: validate gateway, ip_start, ip_end within the network's subnet."""
    ranges = _collect_dhcp_ranges(snap)

    # Build a name -> subnet lookup from snap.networks
    network_subnets: dict[str, ipaddress.IPv4Network | ipaddress.IPv6Network] = {}
    for _net_id, net in snap.networks.items():
        name = net.get("name", "")
        subnet_str = net.get("subnet")
        if name and subnet_str:
            try:
                network_subnets[name] = ipaddress.ip_network(subnet_str, strict=False)
            except (ValueError, TypeError):
                continue

    errors: list[str] = []
    affected_objects: list[str] = []

    for r in ranges:
        net_name = r["network_name"]
        subnet = network_subnets.get(net_name)
        if not subnet:
            continue

        device_label = f"{r['device_name']}/{net_name}"

        # Check gateway
        gateway = r.get("gateway")
        if gateway:
            try:
                gw_addr = ipaddress.ip_address(gateway)
                if gw_addr not in subnet:
                    errors.append(f"{device_label}: gateway {gateway} is outside subnet {subnet}")
                    if device_label not in affected_objects:
                        affected_objects.append(device_label)
            except (ValueError, TypeError):
                errors.append(f"{device_label}: invalid gateway address '{gateway}'")
                if device_label not in affected_objects:
                    affected_objects.append(device_label)

        # Check ip_start
        try:
            start_addr = ipaddress.ip_address(r["ip_start"])
            if start_addr not in subnet:
                errors.append(f"{device_label}: ip_start {r['ip_start']} is outside subnet {subnet}")
                if device_label not in affected_objects:
                    affected_objects.append(device_label)
        except (ValueError, TypeError):
            errors.append(f"{device_label}: invalid ip_start '{r['ip_start']}'")

        # Check ip_end
        try:
            end_addr = ipaddress.ip_address(r["ip_end"])
            if end_addr not in subnet:
                errors.append(f"{device_label}: ip_end {r['ip_end']} is outside subnet {subnet}")
                if device_label not in affected_objects:
                    affected_objects.append(device_label)
        except (ValueError, TypeError):
            errors.append(f"{device_label}: invalid ip_end '{r['ip_end']}'")

    if errors:
        return CheckResult(
            check_id="CFG-DHCP-CFG",
            check_name="DHCP Misconfiguration",
            layer=1,
            status="error",
            summary=f"Found {len(errors)} DHCP misconfiguration(s)",
            details=errors,
            affected_objects=affected_objects,
            affected_sites=[snap.site_id],
            remediation_hint="Ensure DHCP gateway and address range are within the network's subnet.",
        )

    return CheckResult(
        check_id="CFG-DHCP-CFG",
        check_name="DHCP Misconfiguration",
        layer=1,
        status="pass",
        summary="No DHCP misconfigurations detected",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def check_config_conflicts(predicted: SiteSnapshot) -> list[CheckResult]:
    """Run all configuration conflict checks against the predicted SiteSnapshot.

    Returns a list of CheckResult items (one per check).
    """
    return [
        _check_subnet_overlap(predicted),
        _check_vlan_collision(predicted),
        _check_duplicate_ssid(predicted),
        _check_dhcp_scope_overlap(predicted),
        _check_dhcp_misconfiguration(predicted),
    ]
