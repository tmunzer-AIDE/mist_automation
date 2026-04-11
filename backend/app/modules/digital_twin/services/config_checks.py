"""
Layer 1 validation checks for the Digital Twin module.

All functions are pure — no async, no DB access.
Each returns a CheckResult with check_id, status, summary, details, and remediation_hint.
"""

from __future__ import annotations

import re
from typing import Any

import netaddr

from app.modules.digital_twin.models import CheckResult

# Regex to find Jinja2-style template variables: {{ var_name }}
_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_vars(value: Any) -> set[str]:
    """Recursively find all {{ var }} references in a dict/list/string."""
    found: set[str] = set()
    if isinstance(value, str):
        found.update(_VAR_RE.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            found.update(_extract_vars(v))
    elif isinstance(value, list):
        for item in value:
            found.update(_extract_vars(item))
    return found


def _networks_overlap(net_a: netaddr.IPNetwork, net_b: netaddr.IPNetwork) -> bool:
    """Return True if either network contains the other's network address."""
    return net_a.network in net_b or net_b.network in net_a


def _int_ip(addr: str) -> int:
    """Convert an IP address string to integer for range comparison."""
    return int(netaddr.IPAddress(addr))


# ---------------------------------------------------------------------------
# L1-01: IP/subnet overlap (org-wide, cross-site)
# ---------------------------------------------------------------------------


def check_ip_subnet_overlap(existing_networks: list[dict], new_networks: list[dict]) -> CheckResult:
    """Detect IP subnet overlaps across sites (cross-site org-wide check)."""
    conflicts: list[str] = []
    affected_objects: list[str] = []
    affected_sites: list[str] = []

    # Only networks that have a subnet field
    existing_with_subnet = [n for n in existing_networks if n.get("subnet")]
    new_with_subnet = [n for n in new_networks if n.get("subnet")]

    for new_net in new_with_subnet:
        try:
            new_cidr = netaddr.IPNetwork(new_net["subnet"])
        except (netaddr.AddrFormatError, ValueError):
            continue

        for existing_net in existing_with_subnet:
            try:
                existing_cidr = netaddr.IPNetwork(existing_net["subnet"])
            except (netaddr.AddrFormatError, ValueError):
                continue

            if _networks_overlap(new_cidr, existing_cidr):
                new_site = new_net.get("_site_name", new_net.get("_site_id", "unknown"))
                existing_site = existing_net.get("_site_name", existing_net.get("_site_id", "unknown"))
                detail = (
                    f"{new_net['subnet']} ({new_site}) overlaps with " f"{existing_net['subnet']} ({existing_site})"
                )
                conflicts.append(detail)
                if new_site not in affected_sites:
                    affected_sites.append(new_site)
                if existing_site not in affected_sites:
                    affected_sites.append(existing_site)
                obj_name = new_net.get("name", new_net["subnet"])
                if obj_name not in affected_objects:
                    affected_objects.append(obj_name)

    if conflicts:
        return CheckResult(
            check_id="L1-01",
            check_name="IP/Subnet Overlap",
            layer=1,
            status="critical",
            summary=f"Found {len(conflicts)} cross-site subnet overlap(s)",
            details=conflicts,
            affected_objects=affected_objects,
            affected_sites=affected_sites,
            remediation_hint="Assign non-overlapping subnets across sites to avoid routing conflicts.",
        )

    return CheckResult(
        check_id="L1-01",
        check_name="IP/Subnet Overlap",
        layer=1,
        status="pass",
        summary="No cross-site subnet overlaps detected",
    )


# ---------------------------------------------------------------------------
# L1-02: Subnet collision within site
# ---------------------------------------------------------------------------


def check_subnet_collision_within_site(all_networks: list[dict]) -> CheckResult:
    """Detect overlapping subnets assigned to different networks on the same site."""
    # Group by site
    by_site: dict[str, list[dict]] = {}
    for net in all_networks:
        if not net.get("subnet"):
            continue
        site_id = net.get("_site_id", "__no_site__")
        by_site.setdefault(site_id, []).append(net)

    conflicts: list[str] = []
    affected_objects: list[str] = []
    affected_sites: list[str] = []

    for site_id, nets in by_site.items():
        parsed: list[tuple[netaddr.IPNetwork, dict]] = []
        for net in nets:
            try:
                parsed.append((netaddr.IPNetwork(net["subnet"]), net))
            except (netaddr.AddrFormatError, ValueError):
                continue

        for i in range(len(parsed)):
            for j in range(i + 1, len(parsed)):
                cidr_a, net_a = parsed[i]
                cidr_b, net_b = parsed[j]
                if _networks_overlap(cidr_a, cidr_b):
                    site_name = net_a.get("_site_name", site_id)
                    detail = (
                        f"[{site_name}] {net_a.get('name', net_a['subnet'])} ({net_a['subnet']}) "
                        f"overlaps with {net_b.get('name', net_b['subnet'])} ({net_b['subnet']})"
                    )
                    conflicts.append(detail)
                    if site_name not in affected_sites:
                        affected_sites.append(site_name)
                    for obj in (net_a.get("name", net_a["subnet"]), net_b.get("name", net_b["subnet"])):
                        if obj not in affected_objects:
                            affected_objects.append(obj)

    if conflicts:
        return CheckResult(
            check_id="L1-02",
            check_name="Subnet Collision Within Site",
            layer=1,
            status="critical",
            summary=f"Found {len(conflicts)} intra-site subnet collision(s)",
            details=conflicts,
            affected_objects=affected_objects,
            affected_sites=affected_sites,
            remediation_hint="Ensure each network on a site uses a unique, non-overlapping subnet.",
        )

    return CheckResult(
        check_id="L1-02",
        check_name="Subnet Collision Within Site",
        layer=1,
        status="pass",
        summary="No intra-site subnet collisions detected",
    )


# ---------------------------------------------------------------------------
# L1-03: VLAN ID collision
# ---------------------------------------------------------------------------


def check_vlan_id_collision(all_networks: list[dict]) -> CheckResult:
    """Detect same VLAN ID with different network name on the same site."""
    # Map (site_id, vlan_id) -> list of network names
    vlan_map: dict[tuple[str, int], list[str]] = {}

    for net in all_networks:
        vlan_id = net.get("vlan_id")
        if vlan_id is None:
            continue
        site_id = net.get("_site_id", "__no_site__")
        name = net.get("name", "")
        key = (site_id, int(vlan_id))
        vlan_map.setdefault(key, []).append(name)

    conflicts: list[str] = []
    affected_objects: list[str] = []
    affected_sites: list[str] = []

    for (site_id, vlan_id), names in vlan_map.items():
        unique_names = list(dict.fromkeys(names))  # preserve order, deduplicate
        if len(unique_names) > 1:
            # Find the site_name
            site_name = site_id
            for net in all_networks:
                if net.get("_site_id") == site_id:
                    site_name = net.get("_site_name", site_id)
                    break
            detail = f"[{site_name}] VLAN {vlan_id} used by: {', '.join(unique_names)}"
            conflicts.append(detail)
            if site_name not in affected_sites:
                affected_sites.append(site_name)
            for n in unique_names:
                if n not in affected_objects:
                    affected_objects.append(n)

    if conflicts:
        return CheckResult(
            check_id="L1-03",
            check_name="VLAN ID Collision",
            layer=1,
            status="error",
            summary=f"Found {len(conflicts)} VLAN ID collision(s)",
            details=conflicts,
            affected_objects=affected_objects,
            affected_sites=affected_sites,
            remediation_hint="Assign unique VLAN IDs per site, or ensure different network names don't share the same VLAN.",
        )

    return CheckResult(
        check_id="L1-03",
        check_name="VLAN ID Collision",
        layer=1,
        status="pass",
        summary="No VLAN ID collisions detected",
    )


# ---------------------------------------------------------------------------
# L1-04: Duplicate SSID
# ---------------------------------------------------------------------------


def check_duplicate_ssid(all_wlans: list[dict]) -> CheckResult:
    """Detect duplicate SSID names on the same site."""
    # Map (site_id, ssid) -> count
    ssid_map: dict[tuple[str, str], int] = {}
    for wlan in all_wlans:
        ssid = wlan.get("ssid", "")
        site_id = wlan.get("_site_id", "__no_site__")
        key = (site_id, ssid)
        ssid_map[key] = ssid_map.get(key, 0) + 1

    conflicts: list[str] = []
    affected_objects: list[str] = []
    affected_sites: list[str] = []

    for (site_id, ssid), count in ssid_map.items():
        if count > 1:
            site_name = site_id
            for wlan in all_wlans:
                if wlan.get("_site_id") == site_id:
                    site_name = wlan.get("_site_name", site_id)
                    break
            detail = f"[{site_name}] SSID '{ssid}' appears {count} times"
            conflicts.append(detail)
            if site_name not in affected_sites:
                affected_sites.append(site_name)
            if ssid not in affected_objects:
                affected_objects.append(ssid)

    if conflicts:
        return CheckResult(
            check_id="L1-04",
            check_name="Duplicate SSID",
            layer=1,
            status="error",
            summary=f"Found {len(conflicts)} duplicate SSID(s)",
            details=conflicts,
            affected_objects=affected_objects,
            affected_sites=affected_sites,
            remediation_hint="Remove or rename duplicate SSIDs on the same site.",
        )

    return CheckResult(
        check_id="L1-04",
        check_name="Duplicate SSID",
        layer=1,
        status="pass",
        summary="No duplicate SSIDs detected",
    )


# ---------------------------------------------------------------------------
# L1-05: Port profile physical conflict
# ---------------------------------------------------------------------------


def check_port_profile_conflict(existing_port_configs: list[dict], new_port_configs: list[dict]) -> CheckResult:
    """Detect two profiles claiming the same physical port on a device."""
    # Map (device_name, port) -> profile
    existing_map: dict[tuple[str, str], str] = {}
    for cfg in existing_port_configs:
        device = cfg.get("_device_name", "")
        port = cfg.get("port", "")
        profile = cfg.get("profile", "")
        if device and port:
            existing_map[(device, port)] = profile

    conflicts: list[str] = []
    affected_objects: list[str] = []

    for cfg in new_port_configs:
        device = cfg.get("_device_name", "")
        port = cfg.get("port", "")
        new_profile = cfg.get("profile", "")
        if not device or not port:
            continue
        key = (device, port)
        if key in existing_map and existing_map[key] != new_profile:
            detail = (
                f"Device '{device}' port '{port}': "
                f"existing profile '{existing_map[key]}' conflicts with new profile '{new_profile}'"
            )
            conflicts.append(detail)
            obj = f"{device}:{port}"
            if obj not in affected_objects:
                affected_objects.append(obj)

    if conflicts:
        return CheckResult(
            check_id="L1-05",
            check_name="Port Profile Physical Conflict",
            layer=1,
            status="error",
            summary=f"Found {len(conflicts)} port profile conflict(s)",
            details=conflicts,
            affected_objects=affected_objects,
            remediation_hint="Resolve conflicting port profile assignments before deploying.",
        )

    return CheckResult(
        check_id="L1-05",
        check_name="Port Profile Physical Conflict",
        layer=1,
        status="pass",
        summary="No port profile conflicts detected",
    )


# ---------------------------------------------------------------------------
# L1-06: Template override crush
# ---------------------------------------------------------------------------


def check_template_override_crush(site_settings: dict, template_config: dict, site_name: str) -> CheckResult:
    """Detect site-level customisations that a template push would overwrite."""
    overwritten: list[str] = []

    for key in template_config:
        if key in site_settings:
            overwritten.append(key)

    if overwritten:
        details = [f"[{site_name}] Template will overwrite site field: '{k}'" for k in overwritten]
        return CheckResult(
            check_id="L1-06",
            check_name="Template Override Crush",
            layer=1,
            status="warning",
            summary=f"Template push would overwrite {len(overwritten)} site-level customisation(s) on '{site_name}'",
            details=details,
            affected_sites=[site_name],
            remediation_hint="Review site-level overrides that conflict with template fields. Use site vars instead of direct overrides.",
        )

    return CheckResult(
        check_id="L1-06",
        check_name="Template Override Crush",
        layer=1,
        status="pass",
        summary=f"No site-level customisations crushed by template on '{site_name}'",
    )


# ---------------------------------------------------------------------------
# L1-07: Unresolved template variables
# ---------------------------------------------------------------------------


def check_unresolved_template_variables(
    template_config: dict, site_vars: dict, template_name: str, site_name: str
) -> CheckResult:
    """Detect template variables that are not defined in site_vars."""
    all_vars = _extract_vars(template_config)
    missing = sorted(all_vars - set(site_vars.keys()))

    if missing:
        details = [f"[{site_name}] Unresolved variable '{{{{ {v} }}}}' in template '{template_name}'" for v in missing]
        return CheckResult(
            check_id="L1-07",
            check_name="Unresolved Template Variables",
            layer=1,
            status="error",
            summary=f"Template '{template_name}' has {len(missing)} unresolved variable(s) for site '{site_name}'",
            details=details,
            affected_sites=[site_name],
            affected_objects=[template_name],
            remediation_hint=f"Define missing variables in site vars for '{site_name}': {', '.join(missing)}",
        )

    return CheckResult(
        check_id="L1-07",
        check_name="Unresolved Template Variables",
        layer=1,
        status="pass",
        summary=f"All template variables resolved for site '{site_name}'",
    )


# ---------------------------------------------------------------------------
# L1-08: DHCP scope overlap
# ---------------------------------------------------------------------------


def check_dhcp_scope_overlap(dhcp_configs: list[dict]) -> CheckResult:
    """Detect overlapping DHCP ranges on the same subnet/site."""
    # Group by (site_id, subnet)
    by_scope: dict[tuple[str, str], list[dict]] = {}
    for cfg in dhcp_configs:
        subnet = cfg.get("subnet", "")
        site_id = cfg.get("_site_id", "__no_site__")
        if not subnet:
            continue
        key = (site_id, subnet)
        by_scope.setdefault(key, []).append(cfg)

    conflicts: list[str] = []
    affected_sites: list[str] = []

    for (site_id, subnet), scopes in by_scope.items():
        # Convert ranges to integer pairs for overlap detection
        parsed: list[tuple[int, int, dict]] = []
        for scope in scopes:
            try:
                start = _int_ip(scope["ip_start"])
                end = _int_ip(scope["ip_end"])
                parsed.append((start, end, scope))
            except (KeyError, netaddr.AddrFormatError, ValueError):
                continue

        for i in range(len(parsed)):
            for j in range(i + 1, len(parsed)):
                start_a, end_a, scope_a = parsed[i]
                start_b, end_b, scope_b = parsed[j]
                # Ranges overlap if start_a <= end_b and start_b <= end_a
                if start_a <= end_b and start_b <= end_a:
                    site_name = scope_a.get("_site_name", site_id)
                    detail = (
                        f"[{site_name}] DHCP ranges overlap on {subnet}: "
                        f"{scope_a['ip_start']}-{scope_a['ip_end']} vs {scope_b['ip_start']}-{scope_b['ip_end']}"
                    )
                    conflicts.append(detail)
                    if site_name not in affected_sites:
                        affected_sites.append(site_name)

    if conflicts:
        return CheckResult(
            check_id="L1-08",
            check_name="DHCP Scope Overlap",
            layer=1,
            status="error",
            summary=f"Found {len(conflicts)} overlapping DHCP scope(s)",
            details=conflicts,
            affected_sites=affected_sites,
            remediation_hint="Ensure DHCP ranges on the same subnet do not overlap.",
        )

    return CheckResult(
        check_id="L1-08",
        check_name="DHCP Scope Overlap",
        layer=1,
        status="pass",
        summary="No overlapping DHCP scopes detected",
    )


# ---------------------------------------------------------------------------
# L1-09: DHCP server misconfiguration
# ---------------------------------------------------------------------------


def check_dhcp_server_misconfiguration(dhcp_configs: list[dict]) -> CheckResult:
    """Detect gateway outside subnet, or DHCP range outside subnet."""
    errors: list[str] = []
    affected_sites: list[str] = []

    for cfg in dhcp_configs:
        subnet = cfg.get("subnet")
        gateway = cfg.get("gateway")
        ip_start = cfg.get("ip_start")
        ip_end = cfg.get("ip_end")
        site_id = cfg.get("_site_id", "__no_site__")
        site_name = cfg.get("_site_name", site_id)

        if not subnet:
            continue

        try:
            net = netaddr.IPNetwork(subnet)
        except (netaddr.AddrFormatError, ValueError):
            continue

        if gateway:
            try:
                gw_addr = netaddr.IPAddress(gateway)
                if gw_addr not in net:
                    errors.append(f"[{site_name}] Gateway {gateway} is outside subnet {subnet}")
                    if site_name not in affected_sites:
                        affected_sites.append(site_name)
            except (netaddr.AddrFormatError, ValueError):
                errors.append(f"[{site_name}] Invalid gateway address: {gateway}")

        if ip_start:
            try:
                start_addr = netaddr.IPAddress(ip_start)
                if start_addr not in net:
                    errors.append(f"[{site_name}] DHCP ip_start {ip_start} is outside subnet {subnet}")
                    if site_name not in affected_sites:
                        affected_sites.append(site_name)
            except (netaddr.AddrFormatError, ValueError):
                errors.append(f"[{site_name}] Invalid ip_start address: {ip_start}")

        if ip_end:
            try:
                end_addr = netaddr.IPAddress(ip_end)
                if end_addr not in net:
                    errors.append(f"[{site_name}] DHCP ip_end {ip_end} is outside subnet {subnet}")
                    if site_name not in affected_sites:
                        affected_sites.append(site_name)
            except (netaddr.AddrFormatError, ValueError):
                errors.append(f"[{site_name}] Invalid ip_end address: {ip_end}")

    if errors:
        return CheckResult(
            check_id="L1-09",
            check_name="DHCP Server Misconfiguration",
            layer=1,
            status="error",
            summary=f"Found {len(errors)} DHCP misconfiguration(s)",
            details=errors,
            affected_sites=affected_sites,
            remediation_hint="Ensure gateway and DHCP range are within the configured subnet.",
        )

    return CheckResult(
        check_id="L1-09",
        check_name="DHCP Server Misconfiguration",
        layer=1,
        status="pass",
        summary="No DHCP misconfigurations detected",
    )


# ---------------------------------------------------------------------------
# L1-10: DNS/NTP consistency
# ---------------------------------------------------------------------------


def check_dns_ntp_consistency(device_configs: list[dict]) -> CheckResult:
    """Warn about devices missing DNS or NTP configuration."""
    missing_dns: list[str] = []
    missing_ntp: list[str] = []

    for dev in device_configs:
        name = dev.get("_device_name", "unknown")
        dns = dev.get("dns_servers")
        ntp = dev.get("ntp_servers")

        if not dns:
            missing_dns.append(name)
        if not ntp:
            missing_ntp.append(name)

    details: list[str] = []
    if missing_dns:
        details.append(f"Missing DNS servers on: {', '.join(missing_dns)}")
    if missing_ntp:
        details.append(f"Missing NTP servers on: {', '.join(missing_ntp)}")

    if details:
        return CheckResult(
            check_id="L1-10",
            check_name="DNS/NTP Consistency",
            layer=1,
            status="warning",
            summary=f"{len(missing_dns)} device(s) missing DNS, {len(missing_ntp)} device(s) missing NTP",
            details=details,
            affected_objects=list(dict.fromkeys(missing_dns + missing_ntp)),
            remediation_hint="Configure DNS and NTP servers on all devices to ensure proper time sync and name resolution.",
        )

    return CheckResult(
        check_id="L1-10",
        check_name="DNS/NTP Consistency",
        layer=1,
        status="pass",
        summary="All devices have DNS and NTP configured",
    )


# ---------------------------------------------------------------------------
# L1-11: SSID airtime overhead
# ---------------------------------------------------------------------------


def check_ssid_airtime_overhead(all_wlans: list[dict]) -> CheckResult:
    """Warn (>4 SSIDs) or error (>6 SSIDs) on airtime overhead from beacon frames."""
    # Count SSIDs per site (unique by SSID name)
    by_site: dict[str, set[str]] = {}
    site_names: dict[str, str] = {}
    for wlan in all_wlans:
        site_id = wlan.get("_site_id", "__no_site__")
        ssid = wlan.get("ssid", "")
        by_site.setdefault(site_id, set()).add(ssid)
        if "_site_name" in wlan:
            site_names[site_id] = wlan["_site_name"]

    worst_status = "pass"
    details: list[str] = []
    affected_sites: list[str] = []

    for site_id, ssids in by_site.items():
        count = len(ssids)
        site_name = site_names.get(site_id, site_id)
        if count > 6:
            details.append(f"[{site_name}] {count} SSIDs — high beacon overhead (~{count * 3}% airtime)")
            if site_name not in affected_sites:
                affected_sites.append(site_name)
            worst_status = "error"
        elif count > 4:
            details.append(f"[{site_name}] {count} SSIDs — moderate beacon overhead (~{count * 3}% airtime)")
            if site_name not in affected_sites:
                affected_sites.append(site_name)
            if worst_status != "error":
                worst_status = "warning"

    if worst_status != "pass":
        return CheckResult(
            check_id="L1-11",
            check_name="SSID Airtime Overhead",
            layer=1,
            status=worst_status,
            summary=f"SSID airtime overhead concern on {len(affected_sites)} site(s)",
            details=details,
            affected_sites=affected_sites,
            remediation_hint="Keep SSIDs per site to 4 or fewer. Combine SSIDs with VLAN assignment or dynamic VLAN (802.1X) instead.",
        )

    return CheckResult(
        check_id="L1-11",
        check_name="SSID Airtime Overhead",
        layer=1,
        status="pass",
        summary="SSID count within acceptable airtime limits",
    )


# ---------------------------------------------------------------------------
# L1-12: PSK rotation client impact
# ---------------------------------------------------------------------------


def check_psk_rotation_impact(old_wlan: dict, new_wlan: dict, active_clients: int, site_name: str) -> CheckResult:
    """Warn when a PSK change will disconnect active clients."""
    old_psk = old_wlan.get("psk")
    new_psk = new_wlan.get("psk")
    ssid = new_wlan.get("ssid", old_wlan.get("ssid", "unknown"))

    psk_changed = old_psk != new_psk and new_psk is not None

    if psk_changed and active_clients > 0:
        return CheckResult(
            check_id="L1-12",
            check_name="PSK Rotation Client Impact",
            layer=1,
            status="warning",
            summary=f"PSK change on '{ssid}' will disconnect {active_clients} active client(s) on '{site_name}'",
            details=[
                f"[{site_name}] SSID '{ssid}': PSK changed, {active_clients} client(s) currently connected will be disconnected"
            ],
            affected_sites=[site_name],
            affected_objects=[ssid],
            remediation_hint="Schedule PSK rotation during a maintenance window to minimise client disruption.",
        )

    return CheckResult(
        check_id="L1-12",
        check_name="PSK Rotation Client Impact",
        layer=1,
        status="pass",
        summary=f"No client disruption from PSK change on '{ssid}'",
    )


# ---------------------------------------------------------------------------
# L1-13: RF template impact
# ---------------------------------------------------------------------------


def check_rf_template_impact(old_rf: dict, new_rf: dict, affected_ap_count: int) -> CheckResult:
    """Warn when RF template changes (channel/power) affect active APs."""
    if affected_ap_count == 0:
        return CheckResult(
            check_id="L1-13",
            check_name="RF Template Impact",
            layer=1,
            status="pass",
            summary="No active APs affected by RF template change",
        )

    changes: list[str] = []

    def _diff_band(band_key: str) -> None:
        old_band = old_rf.get(band_key, {})
        new_band = new_rf.get(band_key, {})
        if not old_band and not new_band:
            return
        for field in ("channel", "power", "channels", "min_txpower", "max_txpower"):
            old_val = old_band.get(field)
            new_val = new_band.get(field)
            if old_val != new_val and (old_val is not None or new_val is not None):
                changes.append(f"{band_key}.{field}: {old_val!r} → {new_val!r}")

    _diff_band("band_24")
    _diff_band("band_5")
    _diff_band("band_6")

    # Also check top-level scalar fields
    for field in ("country_code",):
        old_val = old_rf.get(field)
        new_val = new_rf.get(field)
        if old_val != new_val and (old_val is not None or new_val is not None):
            changes.append(f"{field}: {old_val!r} → {new_val!r}")

    if not changes:
        return CheckResult(
            check_id="L1-13",
            check_name="RF Template Impact",
            layer=1,
            status="pass",
            summary="No RF parameter changes detected",
        )

    return CheckResult(
        check_id="L1-13",
        check_name="RF Template Impact",
        layer=1,
        status="warning",
        summary=f"RF template changes will affect {affected_ap_count} AP(s): {len(changes)} parameter(s) changed",
        details=[f"Changed: {c}" for c in changes] + [f"Affected APs: {affected_ap_count}"],
        remediation_hint="Schedule RF template changes during low-traffic periods. APs will re-scan channels after applying new settings.",
    )


# ---------------------------------------------------------------------------
# L1-14: Client capacity impact
# ---------------------------------------------------------------------------


def check_client_capacity_impact(old_wlan: dict, new_wlan: dict, current_clients: int, site_name: str) -> CheckResult:
    """Warn/error when max_clients is reduced near or below the current client count."""
    old_max = old_wlan.get("max_clients")
    new_max = new_wlan.get("max_clients")
    ssid = new_wlan.get("ssid", old_wlan.get("ssid", "unknown"))

    if new_max is None or old_max is None:
        return CheckResult(
            check_id="L1-14",
            check_name="Client Capacity Impact",
            layer=1,
            status="pass" if new_max is None else "skipped",
            summary=f"No max_clients limit configured on '{ssid}'",
        )

    if new_max >= old_max:
        return CheckResult(
            check_id="L1-14",
            check_name="Client Capacity Impact",
            layer=1,
            status="pass",
            summary=f"max_clients increased or unchanged on '{ssid}'",
        )

    # new_max < old_max — limit was reduced
    if current_clients < new_max:
        # Still within new limit with headroom — pass (no impact)
        return CheckResult(
            check_id="L1-14",
            check_name="Client Capacity Impact",
            layer=1,
            status="pass",
            summary=f"max_clients reduced to {new_max} on '{ssid}' but current {current_clients} client(s) are within limit",
        )

    # current_clients >= new_max — at or over capacity
    if current_clients >= new_max:
        excess = current_clients - new_max
        status: str = "error" if excess > new_max * 0.5 else "warning"
        return CheckResult(
            check_id="L1-14",
            check_name="Client Capacity Impact",
            layer=1,
            status=status,
            summary=(
                f"max_clients reduced from {old_max} to {new_max} on '{ssid}' ({site_name}): "
                f"{current_clients} current client(s) exceed new limit by {excess}"
            ),
            details=[
                f"[{site_name}] SSID '{ssid}': max_clients {old_max} → {new_max}, "
                f"current clients: {current_clients} ({excess} over new limit)"
            ],
            affected_sites=[site_name],
            affected_objects=[ssid],
            remediation_hint=f"Increase max_clients above {current_clients} or schedule the change during a low-usage period.",
        )

    return CheckResult(
        check_id="L1-14",
        check_name="Client Capacity Impact",
        layer=1,
        status="pass",
        summary=f"Client capacity change on '{ssid}' is within acceptable bounds",
    )


# ---------------------------------------------------------------------------
# L1-15: Port profile disconnect risk
# ---------------------------------------------------------------------------


def check_port_profile_disconnect_risk(
    old_device_config: dict[str, Any],
    new_device_config: dict[str, Any],
    lldp_neighbors: dict[str, str],
    device_name: str,
    site_name: str,
) -> CheckResult:
    """Detect port profile changes that would disconnect active LLDP neighbors."""
    if not lldp_neighbors:
        return CheckResult(
            check_id="L1-15",
            check_name="Port Profile Disconnect Risk",
            layer=1,
            status="pass",
            summary="No LLDP neighbor data available for comparison.",
        )

    old_port_config = old_device_config.get("port_config", {}) or {}
    new_port_config = new_device_config.get("port_config", {}) or {}

    conflicts: list[str] = []
    details: list[str] = []
    affected_objects: list[str] = []

    for port_id, neighbor_mac in lldp_neighbors.items():
        old_profile = old_port_config.get(port_id, {})
        new_profile = new_port_config.get(port_id, {})

        if not new_profile and old_profile:
            # Port config removed entirely — device loses connectivity
            details.append(
                f"{device_name} port {port_id}: config removed, active neighbor {neighbor_mac} will be disconnected"
            )
            conflicts.append(port_id)
            affected_objects.append(f"{device_name}:{port_id}")
            continue

        old_usage = old_profile.get("usage", "")
        new_usage = new_profile.get("usage", "")
        new_profile_name = new_profile.get("port_network", new_profile.get("profile", ""))

        # Detect disabling changes
        is_disabling = False
        change_desc = ""

        if new_usage == "" and old_usage != "":
            is_disabling = True
            change_desc = f"usage cleared (was '{old_usage}')"
        elif new_profile_name and "disabled" in new_profile_name.lower():
            is_disabling = True
            change_desc = f"profile changed to '{new_profile_name}'"
        elif old_usage and new_usage and old_usage != new_usage:
            # Usage changed (e.g., "ap" -> something else) — flag as critical
            is_disabling = True
            change_desc = f"usage changed from '{old_usage}' to '{new_usage}'"

        if is_disabling:
            details.append(
                f"{device_name} port {port_id}: {change_desc}, active neighbor {neighbor_mac} will be disconnected"
            )
            conflicts.append(port_id)
            affected_objects.append(f"{device_name}:{port_id}")

    if conflicts:
        return CheckResult(
            check_id="L1-15",
            check_name="Port Profile Disconnect Risk",
            layer=1,
            status="critical",
            summary=f"{len(conflicts)} port(s) on {device_name} with active neighbors will be affected by profile changes",
            details=details,
            affected_objects=affected_objects,
            affected_sites=[site_name],
            remediation_hint="These ports have active LLDP neighbors (APs, switches). Changing the port profile will disconnect them. Verify this is intentional.",
        )

    return CheckResult(
        check_id="L1-15",
        check_name="Port Profile Disconnect Risk",
        layer=1,
        status="pass",
        summary="No active neighbors affected by port profile changes.",
    )
