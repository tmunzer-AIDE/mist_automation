"""Markdown and Mermaid renderers for topology output."""

import datetime
import re
from collections import defaultdict

from .models import Connection, Device, LinkType, SiteTopology

_LINK_TYPE_LABELS: dict[str, str] = {
    "STANDALONE": "Direct",
    "LAG": "LAG",
    "MCLAG": "MCLAG",
    "VC_ICL": "VC-ICL",
    "MCLAG_ICL": "MCLAG-ICL",
    "FABRIC": "Fabric",
}

_MAX_DEVICES_MERMAID = 40


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------


def _fmt_last_seen(epoch: int) -> str:
    if not epoch:
        return "unknown"
    return datetime.datetime.fromtimestamp(epoch, tz=datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")


def _get_port_uplink(device: Device, port_id: str) -> bool:
    return device.raw_stats.get("port_stat", {}).get(port_id, {}).get("uplink", False)


def _format_vlan_entry(entry: str, vlan_map: dict[str, str]) -> str:
    other = vlan_map.get(entry, "")
    if not other or other == entry:
        return entry
    if entry.isdigit():
        return f"{other}({entry})"
    return f"{entry}({other})"


def _format_vlan_summary(conn: Connection, vlan_map: dict[str, str]) -> str:
    if conn.port_profile == "uplink" and conn.vlan_mode is None:
        return "(trunk-all)"
    if conn.vlan_mode == "access" and conn.access_vlan:
        return f"access:{_format_vlan_entry(conn.access_vlan, vlan_map)}"
    parts = []
    if conn.trunk_vlans:
        if conn.trunk_vlans == ["all"]:
            parts.append("trunk:all")
        else:
            parts.append("trunk:" + ",".join(_format_vlan_entry(v, vlan_map) for v in conn.trunk_vlans))
    if conn.native_vlan:
        parts.append(f"native:{_format_vlan_entry(conn.native_vlan, vlan_map)}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Markdown renderers
# ---------------------------------------------------------------------------


def render_site_list(sites: list[dict]) -> str:
    if not sites:
        return "_No sites found._"
    rows = ["| Site Name | Site ID |", "| --- | --- |"]
    for site in sorted(sites, key=lambda s: s.get("name", "")):
        rows.append(f"| {site.get('name', 'Unknown')} | `{site.get('id', 'Unknown')}` |")
    return "\n".join(rows)


def render_topology_summary(topo: SiteTopology) -> str:
    lines = [
        f"## Site: {topo.site_name or topo.site_id}",
        "",
        f"**Devices:** {topo.device_count}  |  **Connections:** {topo.connection_count}",
        "",
    ]

    statuses: dict[str, int] = {}
    total_alarms = 0
    for dev in topo.devices.values():
        statuses[dev.status] = statuses.get(dev.status, 0) + 1
        total_alarms += dev.alarm_count
    if statuses:
        status_str = "  ".join(f"{k}: {v}" for k, v in sorted(statuses.items()))
        lines.append(f"**Device Status:** {status_str}")
    if total_alarms:
        lines.append(f"**Active Alarms:** {total_alarms}")
    if statuses:
        lines.append("")

    disconnected = [dev for dev in topo.devices.values() if dev.status == "disconnected"]
    if disconnected:
        lines += ["### Disconnected Devices", "", "| Device | Last Seen |", "| --- | --- |"]
        for dev in sorted(disconnected, key=lambda d: d.name):
            alarm_flag = " \u26a0" if dev.alarm_count else ""
            lines.append(f"| {dev.name}{alarm_flag} | {_fmt_last_seen(dev.last_seen)} |")
        lines.append("")

    if topo.logical_groups:
        lines += ["### Logical Groups", "", "| Type | Group ID | Members |", "| --- | --- | --- |"]
        for grp in topo.logical_groups:
            member_parts = []
            for mid in grp.member_ids:
                dev = topo.devices.get(mid)
                if not dev:
                    member_parts.append(mid)
                elif grp.group_type == "VC" and dev.is_virtual_chassis and dev.vc_members:
                    roles = ", ".join(
                        f"FPC{m.fpc_idx}({m.role})" for m in sorted(dev.vc_members, key=lambda m: m.fpc_idx)
                    )
                    member_parts.append(f"{dev.name} [{roles}]")
                else:
                    member_parts.append(dev.name)
            lines.append(f"| {grp.group_type} | `{grp.group_id}` | {', '.join(member_parts)} |")
        lines.append("")

    type_counts: dict[str, int] = {}
    for conn in topo.connections:
        type_counts[conn.link_type.value] = type_counts.get(conn.link_type.value, 0) + 1
    if type_counts:
        lines += ["### Link Types", "", "| Type | Count |", "| --- | --- |"]
        for lt, cnt in sorted(type_counts.items()):
            lines.append(f"| {lt} | {cnt} |")

    return "\n".join(lines)


def render_device_neighbors(
    device: Device,
    connections: list[Connection],
    topo: SiteTopology,
) -> str:
    if not connections:
        return f"_No neighbors found for **{device.name}**._"

    vlan_map = topo.vlan_map
    ip_part = f"  |  IP: {device.ip}" if device.ip else ""
    fw_part = f"  |  Firmware: {device.firmware}" if device.firmware else ""
    alarm_part = f"  |  Alarms: {device.alarm_count}" if device.alarm_count else ""
    lines = [
        f"## Neighbors of {device.name}",
        "",
        (
            f"Device ID: `{device.id}`  |  Model: {device.model}  |  Status: {device.status}"
            f"{ip_part}{fw_part}{alarm_part}"
        ),
        "",
        "| Local Port | Remote Device | Remote Port | Type | Profile | VLAN Config | Uplink | Status |",  # noqa: E501
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for conn in connections:
        if conn.local_device_id == device.id:
            remote_id = conn.remote_device_id
            local_port = conn.local_ae_display
            remote_port = conn.remote_ae_display
            raw_local_port = conn.physical_links[0].local_port if conn.physical_links else ""
        else:
            remote_id = conn.local_device_id
            local_port = conn.remote_ae_display
            remote_port = conn.local_ae_display
            raw_local_port = conn.physical_links[0].remote_port if conn.physical_links else ""

        remote_dev = topo.devices.get(remote_id)
        if remote_dev:
            if remote_dev.is_virtual_chassis and remote_dev.vc_members:
                remote_name = f"{remote_dev.name} (VC/{len(remote_dev.vc_members)})"
            else:
                remote_name = remote_dev.name
        else:
            remote_name = remote_id

        profile = conn.port_profile or ""
        vlan = _format_vlan_summary(conn, vlan_map)
        is_uplink = "Yes" if _get_port_uplink(device, raw_local_port) else ""
        link_label = _LINK_TYPE_LABELS.get(conn.link_type.value, conn.link_type.value)

        lines.append(
            f"| {local_port} | {remote_name} | {remote_port} "
            f"| {link_label} | {profile} | {vlan} | {is_uplink} | {conn.status.value} |"
        )

    return "\n".join(lines)


def render_path(
    path_devices: list[Device],
    path_connections: list[Connection],
    source_name: str,
    dest_name: str,
) -> str:
    if not path_devices:
        return f"_No path found between **{source_name}** and **{dest_name}**._"

    lines = [
        f"## Path: {source_name} \u2192 {dest_name}",
        "",
        f"**Hops:** {len(path_connections)}",
        "",
        "| Hop | Device | Local Port | Remote Port | Link Type | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for i, (conn, dev) in enumerate(zip(path_connections, path_devices[:-1], strict=False)):
        next_dev = path_devices[i + 1]
        if conn.local_device_id == dev.id:
            local_port = conn.local_ae_display
            remote_port = conn.remote_ae_display
        else:
            local_port = conn.remote_ae_display
            remote_port = conn.local_ae_display
        lines.append(
            f"| {i + 1} | {dev.name} \u2192 {next_dev.name} "
            f"| {local_port} | {remote_port} | {conn.link_type.value} | {conn.status.value} |"
        )

    return "\n".join(lines)


def render_segment(vlan_id: str, connections: list[Connection], topo: SiteTopology) -> str:
    if not connections:
        return f"_No links found carrying VLAN **{vlan_id}**._"

    vlan_name = topo.vlan_map.get(vlan_id, vlan_id)
    subnet = topo.subnet_map.get(vlan_name, "") or topo.subnet_map.get(vlan_id, "")
    if "{{" in subnet:
        subnet = ""

    subnet_line = f"  |  Subnet: `{subnet}`" if subnet else ""
    lines = [
        f"## VLAN {vlan_id} Segment",
        "",
        f"**Links carrying this VLAN:** {len(connections)}{subnet_line}",
        "",
        "| Device A | Port A | Device B | Port B | VLAN Config | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for conn in connections:
        dev_a = topo.devices.get(conn.local_device_id)
        dev_b = topo.devices.get(conn.remote_device_id)
        name_a = dev_a.name if dev_a else conn.local_device_id
        name_b = dev_b.name if dev_b else conn.remote_device_id
        lines.append(
            f"| {name_a} | {conn.local_ae_display} "
            f"| {name_b} | {conn.remote_ae_display} "
            f"| {conn.vlan_summary()} | {conn.status.value} |"
        )

    return "\n".join(lines)


def render_site_health(topo: SiteTopology) -> str:
    total = topo.device_count
    connected = sum(1 for d in topo.devices.values() if d.status == "connected")
    disconnected_devs = [d for d in topo.devices.values() if d.status == "disconnected"]
    unknown = total - connected - len(disconnected_devs)
    total_alarms = sum(d.alarm_count for d in topo.devices.values())
    alarmed = [d for d in topo.devices.values() if d.alarm_count > 0]

    if disconnected_devs and total_alarms:
        health = "DEGRADED + ALERTS"
    elif disconnected_devs:
        health = "DEGRADED"
    elif total_alarms:
        health = "ALERTS"
    else:
        health = "HEALTHY"

    lines = [
        f"## Site Health: {topo.site_name or topo.site_id}",
        "",
        f"**Status:** {health}  |  **Devices:** {total}",
        "",
        "| Connected | Disconnected | Unknown | Active Alarms |",
        "| --- | --- | --- | --- |",
        f"| {connected} | {len(disconnected_devs)} | {unknown} | {total_alarms} |",
    ]

    if disconnected_devs:
        lines += [
            "",
            "### Disconnected Devices",
            "",
            "| Device | Model | Last Seen |",
            "| --- | --- | --- |",
        ]
        for dev in sorted(disconnected_devs, key=lambda d: d.name):
            alarm_flag = " \u26a0" if dev.alarm_count else ""
            lines.append(f"| {dev.name}{alarm_flag} | {dev.model} | {_fmt_last_seen(dev.last_seen)} |")

    if alarmed:
        lines += [
            "",
            "### Devices with Active Alarms",
            "",
            "| Device | Status | Alarm Count |",
            "| --- | --- | --- |",
        ]
        for dev in sorted(alarmed, key=lambda d: (-d.alarm_count, d.name)):
            lines.append(f"| {dev.name} | {dev.status} | {dev.alarm_count} |")

    return "\n".join(lines)


def render_dhcp_info(devices: dict, topo: SiteTopology) -> str:
    rows: list[tuple[str, str, str, str, str]] = []

    for dev in sorted(devices.values(), key=lambda d: d.name):
        dhcp_cfg = dev.dhcpd_config
        if not dhcp_cfg or not isinstance(dhcp_cfg, dict):
            continue

        for net_name, cfg in sorted(dhcp_cfg.items()):
            if not isinstance(cfg, dict):
                continue
            dhcp_type = cfg.get("type", "local")
            if dhcp_type == "relay":
                servers = cfg.get("servers", [])
                details = "relay\u2192" + ", ".join(servers) if servers else "relay"
                mode = "relay"
            else:
                mode = "server"
                parts = []
                if cfg.get("ip_start") and cfg.get("ip_end"):
                    parts.append(f"pool: {cfg['ip_start']}\u2013{cfg['ip_end']}")
                if cfg.get("gateway"):
                    parts.append(f"gw: {cfg['gateway']}")
                dns = cfg.get("dns_servers", [])
                if dns:
                    parts.append(f"dns: {', '.join(dns[:2])}")
                if cfg.get("lease_time"):
                    parts.append(f"lease: {cfg['lease_time']}s")
                details = " | ".join(parts) if parts else ""

            rows.append((dev.name, dev.status, net_name, mode, details))

    if not rows:
        return "_No DHCP configuration found on any device._"

    lines = [
        "## DHCP Configuration",
        "",
        "| Device | Status | Network | Mode | Details |",
        "| --- | --- | --- | --- | --- |",
    ]
    for dev_name, dev_status, net_name, mode, details in rows:
        lines.append(f"| {dev_name} | {dev_status} | {net_name} | {mode} | {details} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mermaid renderers
# ---------------------------------------------------------------------------


def _node_id(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "_", name).upper()


def _edge_label(conn: Connection) -> str:
    parts = []
    if conn.local_ae and conn.remote_ae:
        parts.append(f"{conn.local_ae}\u2194{conn.remote_ae}")
    parts.append(conn.link_type.value)
    vlan = conn.vlan_summary()
    if vlan:
        parts.append(vlan)
    return "\\n".join(parts)


def render_topology_mermaid(topo: SiteTopology) -> str:
    if topo.device_count > _MAX_DEVICES_MERMAID:
        return (
            f"_(Mermaid diagram omitted: site has {topo.device_count} devices "
            f"> {_MAX_DEVICES_MERMAID} limit. Use neighbors for scoped views.)_"
        )

    lines = ["```mermaid", "graph LR"]

    mclag_pairs: dict[str, list[str]] = defaultdict(list)
    for grp in topo.logical_groups:
        if grp.group_type == "MCLAG":
            for mid in grp.member_ids:
                mclag_pairs[grp.group_id].append(mid)

    rendered_in_subgraph: set[str] = set()
    for group_id, member_ids in mclag_pairs.items():
        sg_id = f"MCLAG_{_node_id(group_id)}"
        lines.append(f'  subgraph {sg_id}["MCLAG: {group_id}"]')
        for mid in member_ids:
            dev = topo.devices.get(mid)
            if dev:
                nid = _node_id(dev.name)
                lines.append(f'    {nid}["{dev.name}\\n{dev.model}"]')
                rendered_in_subgraph.add(mid)
        lines.append("  end")

    vc_rendered: set[str] = set()
    for grp in topo.logical_groups:
        if grp.group_type == "VC":
            master = next((topo.devices[mid] for mid in grp.member_ids if topo.devices.get(mid)), None)
            if master and master.id not in vc_rendered:
                nid = _node_id(master.name)
                lines.append(f'  {nid}["(VC) {master.name}\\n{master.model}"]')
                for mid in grp.member_ids:
                    vc_rendered.add(mid)

    for dev_id, dev in topo.devices.items():
        if dev_id in rendered_in_subgraph or dev_id in vc_rendered:
            continue
        nid = _node_id(dev.name)
        lines.append(f'  {nid}["{dev.name}\\n{dev.model}"]')

    rendered_edges: set[tuple[str, str]] = set()
    for conn in topo.connections:
        if conn.link_type == LinkType.VC_ICL:
            continue
        dev_a = topo.devices.get(conn.local_device_id)
        dev_b = topo.devices.get(conn.remote_device_id)
        if not dev_a or not dev_b:
            continue
        nid_a = _node_id(dev_a.name)
        nid_b = _node_id(dev_b.name)
        edge_key = tuple(sorted([nid_a, nid_b]))
        if edge_key in rendered_edges:
            continue
        rendered_edges.add(edge_key)
        label = _edge_label(conn)
        if conn.link_type == LinkType.MCLAG_ICL:
            lines.append(f'  {nid_a} -. "{label}" .- {nid_b}')
        else:
            lines.append(f'  {nid_a} -- "{label}" --> {nid_b}')

    lines.append("```")
    return "\n".join(lines)


def render_neighbor_mermaid(
    device: Device,
    connections: list[Connection],
    topo: SiteTopology,
) -> str:
    lines = ["```mermaid", "graph LR"]
    center_nid = _node_id(device.name)
    lines.append(f'  {center_nid}["{device.name}\\n{device.model}"]')

    for conn in connections:
        remote_id = conn.remote_device_id if conn.local_device_id == device.id else conn.local_device_id
        remote = topo.devices.get(remote_id)
        if not remote:
            continue
        remote_nid = _node_id(remote.name)
        lines.append(f'  {remote_nid}["{remote.name}\\n{remote.model}"]')
        label = _edge_label(conn)
        if conn.link_type == LinkType.MCLAG_ICL:
            lines.append(f'  {center_nid} -. "{label}" .- {remote_nid}')
        else:
            lines.append(f'  {center_nid} -- "{label}" --> {remote_nid}')

    lines.append("```")
    return "\n".join(lines)


def render_path_mermaid(
    path_devices: list[Device],
    path_connections: list[Connection],
) -> str:
    if not path_devices:
        return ""
    lines = ["```mermaid", "graph LR"]
    for dev in path_devices:
        nid = _node_id(dev.name)
        lines.append(f'  {nid}["{dev.name}"]')
    for i, conn in enumerate(path_connections):
        dev_a = path_devices[i]
        dev_b = path_devices[i + 1]
        nid_a = _node_id(dev_a.name)
        nid_b = _node_id(dev_b.name)
        label = _edge_label(conn)
        lines.append(f'  {nid_a} -- "{label}" --> {nid_b}')
    lines.append("```")
    return "\n".join(lines)
