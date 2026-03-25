"""
Build SiteTopology from raw API data, classify links, and find BFS paths.

Pipeline:
  fetch_site_data() → RawSiteData → build_topology() → SiteTopology → render_*()

classify_links() steps:
  1. Expand port range expressions in device config
  2. Build port→ae map per device
  3. Classify each physical link (STANDALONE/LAG/MCLAG/VC_ICL/MCLAG_ICL/FABRIC)
  4. Merge physical links into Connection objects
  5. VLAN enrichment
"""

import re
from collections import defaultdict, deque
from typing import Any

import structlog

from .client import RawSiteData
from .models import (
    Connection,
    Device,
    LinkStatus,
    LinkType,
    LogicalGroup,
    PhysicalLink,
    SiteTopology,
    VCMember,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Variable resolution
# ---------------------------------------------------------------------------


def _resolve_vars(data: Any, vars: dict[str, str]) -> Any:
    """Recursively replace {{key}} placeholders with values from vars."""
    if not vars:
        return data
    if isinstance(data, str):
        for k, v in vars.items():
            data = data.replace(f"{{{{{k}}}}}", str(v))
        return data
    if isinstance(data, dict):
        return {k: _resolve_vars(v, vars) for k, v in data.items()}
    if isinstance(data, list):
        return [_resolve_vars(item, vars) for item in data]
    return data


# ---------------------------------------------------------------------------
# Port range expansion
# ---------------------------------------------------------------------------


def _expand_port_range(expr: str) -> list[str]:
    """
    Expand a Mist port config key into individual port names.

    Examples:
      "ge-0/0/0"           → ["ge-0/0/0"]
      "ge-0/0/0,ge-0/0/1"  → ["ge-0/0/0", "ge-0/0/1"]
      "ge-0/0/4-6"         → ["ge-0/0/4", "ge-0/0/5", "ge-0/0/6"]
      "ge-0/0/0,ge-0/0/4-6"→ ["ge-0/0/0", "ge-0/0/4", "ge-0/0/5", "ge-0/0/6"]
    """
    result: list[str] = []
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        range_match = re.match(r"^(.*?)(\d+)-(\d+)$", part)
        if range_match:
            prefix = range_match.group(1)
            start = int(range_match.group(2))
            end = int(range_match.group(3))
            for i in range(start, end + 1):
                result.append(f"{prefix}{i}")
        else:
            result.append(part)
    return result


# ---------------------------------------------------------------------------
# Template application (simplified)
# ---------------------------------------------------------------------------


def _apply_templates(devices: dict[str, Device], raw: RawSiteData) -> None:
    """
    Enrich each device's port_usages, networks, and dhcpd_config with template data.

    For switches: getSiteSettingDerived already merges the network template,
    so we just use site_setting directly as the base.

    For gateways: the gateway_template is the base (not merged into site_setting).

    Merge order (lowest → highest priority): template/site_setting → device config.
    After merging, substitute {{var}} placeholders from site_setting.vars.
    """
    vars_map: dict[str, str] = {}
    if raw.site_setting:
        vars_map = {str(k): str(v) for k, v in raw.site_setting.get("vars", {}).items()}

    for dev in devices.values():
        if dev.device_type == "switch":
            base_usages = dict(raw.site_setting.get("port_usages") or {})
            base_networks = dict(raw.site_setting.get("networks") or {})
            base_dhcp = dict(raw.site_setting.get("dhcpd_config") or {})
            dev.port_usages = {**base_usages, **dev.port_usages}
            dev.networks = {**base_networks, **dev.networks}
            dev.dhcpd_config = {**base_dhcp, **dev.dhcpd_config}

        elif dev.device_type == "gateway" and raw.gateway_template:
            base_usages = dict(raw.gateway_template.get("port_usages") or {})
            base_networks = dict(raw.gateway_template.get("networks") or {})
            base_dhcp = dict(raw.gateway_template.get("dhcpd_config") or {})
            dev.port_usages = {**base_usages, **dev.port_usages}
            dev.networks = {**base_networks, **dev.networks}
            dev.dhcpd_config = {**base_dhcp, **dev.dhcpd_config}

        dev.networks = _resolve_vars(dev.networks, vars_map)
        dev.dhcpd_config = _resolve_vars(dev.dhcpd_config, vars_map)


# ---------------------------------------------------------------------------
# Link classifier — Step 2: port→ae map
# ---------------------------------------------------------------------------


def _build_port_to_ae(device: Device) -> dict[str, str]:
    """Return {physical_port: ae_name} for all aggregated ports in device config."""
    port_to_ae: dict[str, str] = {}
    for port_expr, cfg in device.port_config.items():
        if not cfg.get("aggregated"):
            continue
        ae_idx = cfg.get("ae_idx")
        if ae_idx is None:
            continue
        ae_name = f"ae{ae_idx}"
        for port in _expand_port_range(port_expr):
            port_to_ae[port] = ae_name
    return port_to_ae


# ---------------------------------------------------------------------------
# Link classifier — Step 3: classify a single link
# ---------------------------------------------------------------------------


def _get_port_status(device: Device, port: str) -> LinkStatus:
    stat = device.raw_stats.get("port_stat", {}).get(port, {})
    if not stat:
        return LinkStatus.UNKNOWN
    return LinkStatus.UP if stat.get("up") else LinkStatus.DOWN


def _classify_link(
    dev_a: Device,
    port_a: str,
    dev_b: Device,
    port_b: str,
    port_to_ae: dict[str, dict[str, str]],
) -> tuple[LinkType, str | None, str | None]:
    ae_a = port_to_ae.get(dev_a.id, {}).get(port_a)
    ae_b = port_to_ae.get(dev_b.id, {}).get(port_b)

    # VC ICL detection
    if dev_a.is_virtual_chassis or dev_b.is_virtual_chassis:
        if dev_a.vc_mac and dev_a.vc_mac == dev_b.vc_mac:
            return LinkType.VC_ICL, ae_a, ae_b
        if dev_a.is_virtual_chassis and dev_b.vc_mac == dev_a.mac:
            return LinkType.VC_ICL, ae_a, ae_b
        if dev_b.is_virtual_chassis and dev_a.vc_mac == dev_b.mac:
            return LinkType.VC_ICL, ae_a, ae_b

    if ae_a:
        mclag_a = dev_a.port_config.get("_mclag", {})
        peer_links = set(_expand_port_range(mclag_a.get("peer_link_port", "")))
        if port_a in peer_links:
            return LinkType.MCLAG_ICL, ae_a, ae_b
        if mclag_a and dev_a.mclag_domain_id:
            return LinkType.MCLAG, ae_a, ae_b
        return LinkType.LAG, ae_a, ae_b

    if _is_fabric_link(dev_a, port_a):
        return LinkType.FABRIC, ae_a, ae_b

    return LinkType.STANDALONE, ae_a, ae_b


def _is_fabric_link(device: Device, port: str) -> bool:
    for port_expr, cfg in device.port_config.items():
        if port in _expand_port_range(port_expr):
            usage = cfg.get("usage", "")
            if usage and usage in device.port_usages:
                u = device.port_usages[usage]
                if u.get("vrf_name") or u.get("evpn_uplink"):
                    return True
    return False


# ---------------------------------------------------------------------------
# Link classifier — Step 4: merge into Connection objects
# ---------------------------------------------------------------------------


def _connection_key(
    dev_a_id: str, dev_b_id: str, ae_a: str | None, ae_b: str | None
) -> tuple[str, str, str | None, str | None]:
    if dev_a_id <= dev_b_id:
        return (dev_a_id, dev_b_id, ae_a, ae_b)
    return (dev_b_id, dev_a_id, ae_b, ae_a)


# ---------------------------------------------------------------------------
# Link classifier — Step 5: VLAN enrichment
# ---------------------------------------------------------------------------


def _resolve_network_name(name: str, networks: dict) -> str:
    """Resolve Mist network name to VLAN ID string via device.networks dict."""
    entry = networks.get(name)
    if isinstance(entry, dict):
        return str(entry.get("vlan_id", name))
    if entry is not None:
        return str(entry)
    return name


def _enrich_vlan(connection: Connection, dev_a: Device, port_a: str) -> None:
    """
    Populate VLAN fields on connection from dev_a's port_config and port_usages.

    Mist field names:
      port_config[port]["usage"]        → profile name
      port_usages[profile]["mode"]      → "access" | "trunk"
      port_usages[profile]["port_network"] → access VLAN name (access) or native (trunk)
      port_usages[profile]["networks"]  → list of trunk network names
      port_usages[profile]["all_networks"] → bool: trunk all site VLANs
      device.networks[name]["vlan_id"]  → integer VLAN ID
    """
    port_cfg: dict = {}
    usage_name = None
    for port_expr, cfg in dev_a.port_config.items():
        if port_a in _expand_port_range(port_expr):
            usage_name = cfg.get("usage")
            port_cfg = cfg
            break

    if not usage_name:
        return

    connection.port_profile = usage_name
    usage = dev_a.port_usages.get(usage_name, {})

    if not usage:
        # Gateways embed VLAN fields directly in port_config
        _VLAN_KEYS = ("mode", "networks", "port_network", "all_networks")
        if not any(k in port_cfg for k in _VLAN_KEYS):
            return
        usage = port_cfg

    vlan_mode = usage.get("mode")
    if vlan_mode is None and usage.get("networks"):
        vlan_mode = "trunk"

    connection.vlan_mode = vlan_mode
    nets = dev_a.networks
    _DEFAULT_NAMES = {"default", "default-vlan"}

    if vlan_mode == "access":
        net_name = usage.get("port_network", "")
        if net_name:
            connection.access_vlan = _resolve_network_name(net_name, nets)
    else:
        native_name = usage.get("port_network", "")
        if native_name and native_name not in _DEFAULT_NAMES:
            connection.native_vlan = _resolve_network_name(native_name, nets)
        if usage.get("all_networks"):
            connection.trunk_vlans = ["all"]
        else:
            trunk_names = usage.get("networks") or []
            connection.trunk_vlans = [_resolve_network_name(n, nets) for n in trunk_names if n]


# ---------------------------------------------------------------------------
# classify_links public API
# ---------------------------------------------------------------------------


def classify_links(
    raw_links: list[dict],
    devices: dict[str, Device],
) -> tuple[list[Connection], list[LogicalGroup]]:
    """
    Transform raw topology links + device configs into enriched Connection objects.

    Args:
        raw_links: [{node1, port_id, node2, port_id2}, ...]
        devices:   {device_id: Device}

    Returns:
        (connections, logical_groups)
    """
    port_to_ae: dict[str, dict[str, str]] = {dev_id: _build_port_to_ae(dev) for dev_id, dev in devices.items()}

    merged: dict[tuple, dict] = {}

    for link in raw_links:
        dev_a_id = link.get("node1", "")
        dev_b_id = link.get("node2", "")
        port_a = link.get("port_id", "")
        port_b = link.get("port_id2", "")

        dev_a = devices.get(dev_a_id)
        dev_b = devices.get(dev_b_id)
        if not dev_a or not dev_b:
            continue

        link_type, ae_a, ae_b = _classify_link(dev_a, port_a, dev_b, port_b, port_to_ae)
        status = _get_port_status(dev_a, port_a)
        physical = PhysicalLink(local_port=port_a, remote_port=port_b, status=status)

        key = _connection_key(dev_a_id, dev_b_id, ae_a, ae_b)
        if key not in merged:
            if dev_a_id <= dev_b_id:
                merged[key] = {
                    "local_device_id": dev_a_id,
                    "remote_device_id": dev_b_id,
                    "link_type": link_type,
                    "local_ae": ae_a,
                    "remote_ae": ae_b,
                    "physical_links": [physical],
                    "dev_a": dev_a,
                    "port_a": port_a,
                }
            else:
                swapped = PhysicalLink(local_port=port_b, remote_port=port_a, status=status)
                merged[key] = {
                    "local_device_id": dev_b_id,
                    "remote_device_id": dev_a_id,
                    "link_type": link_type,
                    "local_ae": ae_b,
                    "remote_ae": ae_a,
                    "physical_links": [swapped],
                    "dev_a": dev_b,
                    "port_a": port_b,
                }
        else:
            entry = merged[key]
            if entry["local_device_id"] == dev_a_id:
                entry["physical_links"].append(physical)
            else:
                swapped = PhysicalLink(local_port=port_b, remote_port=port_a, status=status)
                entry["physical_links"].append(swapped)

    connections: list[Connection] = []
    for entry in merged.values():
        conn = Connection(
            local_device_id=entry["local_device_id"],
            remote_device_id=entry["remote_device_id"],
            link_type=entry["link_type"],
            local_ae=entry["local_ae"],
            remote_ae=entry["remote_ae"],
            physical_links=entry["physical_links"],
        )

        dev = devices.get(entry["local_device_id"])
        if dev and conn.link_type in (LinkType.MCLAG, LinkType.MCLAG_ICL):
            conn.mclag_domain_id = dev.mclag_domain_id

        statuses = {pl.status for pl in conn.physical_links}
        if statuses == {LinkStatus.UP}:
            conn.status = LinkStatus.UP
        elif statuses == {LinkStatus.DOWN}:
            conn.status = LinkStatus.DOWN
        elif LinkStatus.UNKNOWN in statuses and len(statuses) == 1:
            conn.status = LinkStatus.UNKNOWN
        else:
            conn.status = LinkStatus.PARTIAL

        _enrich_vlan(conn, entry["dev_a"], entry["port_a"])
        if conn.vlan_mode is None and conn.physical_links:
            dev_b = devices.get(entry["remote_device_id"])
            if dev_b:
                _enrich_vlan(conn, dev_b, conn.physical_links[0].remote_port)

        connections.append(conn)

    logical_groups = _build_logical_groups(devices, connections)
    return connections, logical_groups


def _build_logical_groups(
    devices: dict[str, Device],
    connections: list[Connection],
) -> list[LogicalGroup]:
    groups: list[LogicalGroup] = []

    vc_map: dict[str, list[str]] = defaultdict(list)
    for dev in devices.values():
        if dev.vc_mac:
            vc_map[dev.vc_mac].append(dev.id)
    for vc_mac, member_ids in vc_map.items():
        if len(member_ids) > 1:
            groups.append(LogicalGroup(group_type="VC", group_id=vc_mac, member_ids=member_ids))
        else:
            dev = devices.get(member_ids[0])
            if dev and dev.is_virtual_chassis and dev.vc_members:
                groups.append(LogicalGroup(group_type="VC", group_id=vc_mac, member_ids=member_ids))

    mclag_map: dict[str, list[str]] = defaultdict(list)
    for dev in devices.values():
        if dev.mclag_domain_id:
            mclag_map[dev.mclag_domain_id].append(dev.id)
    for domain_id, member_ids in mclag_map.items():
        if len(member_ids) >= 2:
            groups.append(LogicalGroup(group_type="MCLAG", group_id=domain_id, member_ids=member_ids))

    fabric_ids: set[str] = set()
    for conn in connections:
        if conn.link_type == LinkType.FABRIC:
            fabric_ids.add(conn.local_device_id)
            fabric_ids.add(conn.remote_device_id)
    if fabric_ids:
        groups.append(LogicalGroup(group_type="FABRIC", group_id="ip_fabric", member_ids=list(fabric_ids)))

    return groups


# ---------------------------------------------------------------------------
# Main topology builder
# ---------------------------------------------------------------------------


def build_topology(site_id: str, raw: RawSiteData) -> SiteTopology:
    """
    Transform raw Mist API data into a SiteTopology.

    Steps:
      1. Parse device configs → Device objects
      2. Apply template enrichment (port_usages, networks, dhcpd_config)
      3. Merge device stats → Device objects
      4. Build raw_links from port_stats (LLDP data)
      5. Classify physical links → Connection objects + LogicalGroups
      6. Build adjacency index
    """
    devices = _parse_devices(raw.devices, site_id)

    if raw.site_setting or raw.gateway_template:
        _apply_templates(devices, raw)

    mac_to_id = {dev.mac.replace(":", "").lower(): dev_id for dev_id, dev in devices.items()}
    _merge_stats(devices, raw.devices_stats)
    if raw.alarms:
        _enrich_alarms(devices, raw.alarms)

    raw_links = _build_links_from_port_stats(raw.port_stats, devices, mac_to_id)
    connections, logical_groups = classify_links(raw_links, devices)

    topo = SiteTopology(
        site_id=site_id,
        devices=devices,
        connections=connections,
        logical_groups=logical_groups,
        vlan_map=_build_vlan_map(raw, devices),
        subnet_map=_build_subnet_map(raw.org_networks),
    )
    topo.build_adj()

    logger.info(
        "topology_built",
        site_id=site_id,
        device_count=topo.device_count,
        connection_count=topo.connection_count,
        group_count=len(logical_groups),
    )
    return topo


def _build_links_from_port_stats(
    port_stats: list[dict],
    devices: dict[str, Device],
    mac_to_id: dict[str, str],
) -> list[dict]:
    """Convert searchSiteSwOrGwPorts records into raw_links for classify_links."""
    dev_port_stats: dict[str, dict[str, dict]] = {}
    for ps in port_stats:
        dev_mac = ps.get("mac", "").lower()
        dev_id = mac_to_id.get(dev_mac)
        if not dev_id:
            continue
        port_id = ps.get("port_id", "")
        dev_port_stats.setdefault(dev_id, {})[port_id] = ps

    _enrich_port_config_from_stats(devices, dev_port_stats)

    raw_links: list[dict] = []
    seen: set[tuple] = set()

    for ps in port_stats:
        dev_mac = ps.get("mac", "").lower()
        neighbor_mac = ps.get("neighbor_mac", "").lower()
        if not dev_mac or not neighbor_mac:
            continue

        local_id = mac_to_id.get(dev_mac)
        remote_id = mac_to_id.get(neighbor_mac)
        if not local_id or not remote_id:
            continue

        local_port = ps.get("port_id", "")
        remote_port = ps.get("neighbor_port_desc", "")

        key = tuple(sorted([(local_id, local_port), (remote_id, remote_port)]))
        if key in seen:
            continue
        seen.add(key)

        raw_links.append(
            {
                "node1": local_id,
                "port_id": local_port,
                "node2": remote_id,
                "port_id2": remote_port,
                "_up": ps.get("up", False),
            }
        )

    return raw_links


def _enrich_port_config_from_stats(
    devices: dict[str, Device],
    dev_port_stats: dict[str, dict[str, dict]],
) -> None:
    """
    Augment each device's port_config with information from real port stats.

    1. LAG assignments: port_parent ("ae0") → aggregated=True + ae_idx.
    2. Effective port usage: port_usage from port_stats overrides placeholder entries.
    """
    _PLACEHOLDER_USAGES = {"", "default", "disabled"}

    for dev_id, port_map in dev_port_stats.items():
        dev = devices.get(dev_id)
        if not dev:
            continue

        for port_id, ps in port_map.items():
            parent = ps.get("port_parent", "")
            port_usage = ps.get("port_usage", "")

            existing_cfg: dict | None = None
            for expr, cfg in dev.port_config.items():
                if port_id in _expand_port_range(expr):
                    existing_cfg = cfg
                    break

            enrichment: dict = {}

            if parent:
                ae_match = re.match(r"ae(\d+)$", parent)
                if ae_match and not (existing_cfg and existing_cfg.get("aggregated")):
                    enrichment["aggregated"] = True
                    enrichment["ae_idx"] = int(ae_match.group(1))

            if port_usage:
                existing_usage = existing_cfg.get("usage", "") if existing_cfg else ""
                has_dynamic = bool(existing_cfg and existing_cfg.get("dynamic_usage"))
                if existing_usage in _PLACEHOLDER_USAGES or has_dynamic:
                    enrichment["usage"] = port_usage

            if not enrichment:
                continue

            if existing_cfg is not None:
                existing_cfg.update(enrichment)
            else:
                dev.port_config[port_id] = enrichment

        dev.raw_stats["port_stat"] = {
            pid: {"up": ps.get("up", False), "uplink": ps.get("uplink", False)} for pid, ps in port_map.items()
        }


def _parse_devices(raw_devices: list[dict], site_id: str) -> dict[str, Device]:
    devices: dict[str, Device] = {}

    for raw in raw_devices:
        dev_id = raw.get("id", "")
        if not dev_id:
            continue

        vc_members = []
        is_vc = False
        vc_mac = ""
        if raw.get("virtual_chassis"):
            is_vc = True
            vc_mac = raw.get("mac", "")
            for m in raw.get("virtual_chassis", {}).get("members", []):
                vc_members.append(
                    VCMember(
                        fpc_idx=m.get("member_id", m.get("fpc", 0)),
                        mac=m.get("mac", ""),
                        model=m.get("model", ""),
                        role=m.get("vc_role", m.get("role", "")),
                        status=m.get("status", "unknown"),
                    )
                )
        elif raw.get("vc_mac"):
            vc_mac = raw.get("vc_mac", "")

        mclag_domain_id = ""
        if raw.get("evpn_config") and raw["evpn_config"].get("role") == "collapsed-core":
            mclag_domain_id = raw["evpn_config"].get("evpn_id", dev_id)

        devices[dev_id] = Device(
            id=dev_id,
            name=raw.get("name") or f"{dev_id.rsplit('-', 1)[-1]}",
            mac=raw.get("mac", ""),
            model=raw.get("model", ""),
            site_id=site_id,
            ip=raw.get("ip", ""),
            serial=raw.get("serial", ""),
            status="unknown",
            device_type=raw.get("type", ""),
            is_virtual_chassis=is_vc,
            vc_members=vc_members,
            vc_mac=vc_mac,
            mclag_domain_id=mclag_domain_id,
            port_config=raw.get("port_config", {}),
            port_usages=raw.get("port_usages", {}),
            networks=raw.get("networks", {}),
            dhcpd_config=raw.get("dhcpd_config", {}),
        )

    return devices


def _merge_stats(devices: dict[str, Device], raw_stats: list[dict]) -> None:
    for stat in raw_stats:
        dev_id = stat.get("id", "")
        if dev_id not in devices:
            continue
        dev = devices[dev_id]
        dev.status = stat.get("status", "unknown")
        dev.uptime = stat.get("uptime", 0)
        dev.firmware = stat.get("version", "")
        dev.last_seen = int(stat.get("last_seen") or 0)
        dev.ip = dev.ip or stat.get("ip", "")
        dev.raw_stats = stat


def _enrich_alarms(devices: dict[str, Device], alarms: list[dict]) -> None:
    counts: dict[str, int] = {}
    for alarm in alarms:
        dev_id = alarm.get("device_id", "")
        if dev_id:
            counts[dev_id] = counts.get(dev_id, 0) + 1
    for dev_id, count in counts.items():
        if dev_id in devices:
            devices[dev_id].alarm_count = count


def _build_vlan_map(raw: RawSiteData, devices: dict) -> dict[str, str]:
    """
    Build bidirectional {name: vlan_id_str, vlan_id_str: name} map.

    Priority (highest wins): org_networks > site_setting.networks > device.networks
    """
    result: dict[str, str] = {}

    def _add(name: str, vid) -> None:
        if not name or vid is None:
            return
        vid_str = str(vid)
        result.setdefault(name, vid_str)
        result.setdefault(vid_str, name)

    for dev in devices.values():
        for name, info in dev.networks.items():
            if isinstance(info, dict):
                _add(name, info.get("vlan_id"))

    for name, info in (raw.site_setting.get("networks") or {}).items():
        if isinstance(info, dict):
            _add(name, info.get("vlan_id"))

    for net in raw.org_networks:
        name = net.get("name", "")
        vid = net.get("vlan_id")
        if name and vid is not None:
            vid_str = str(vid)
            result[name] = vid_str
            result[vid_str] = name

    return result


def _build_subnet_map(org_networks: list[dict]) -> dict[str, str]:
    result: dict[str, str] = {}
    for net in org_networks:
        name = net.get("name", "")
        subnet = net.get("subnet", "")
        if name and subnet:
            result[name] = subnet
    return result


# ---------------------------------------------------------------------------
# BFS path finder
# ---------------------------------------------------------------------------


def bfs_path(
    topo: SiteTopology,
    source_id: str,
    dest_id: str,
) -> tuple[list[Device], list[Connection]]:
    """
    BFS over adjacency list to find shortest path between two device IDs.

    Returns (path_devices, path_connections) or ([], []) if no path found.
    path_devices[0] = source, path_devices[-1] = destination.
    path_connections[i] connects path_devices[i] to path_devices[i+1].
    """
    if source_id == dest_id:
        dev = topo.devices.get(source_id)
        return ([dev] if dev else [], [])

    visited: set[str] = {source_id}
    predecessor: dict[str, tuple[str, Connection]] = {}
    queue: deque[str] = deque([source_id])

    while queue:
        current_id = queue.popleft()
        for conn in topo.neighbors(current_id):
            neighbor_id = conn.remote_device_id if conn.local_device_id == current_id else conn.local_device_id
            if neighbor_id in visited:
                continue
            visited.add(neighbor_id)
            predecessor[neighbor_id] = (current_id, conn)
            if neighbor_id == dest_id:
                return _reconstruct_path(topo, source_id, dest_id, predecessor)
            queue.append(neighbor_id)

    return ([], [])


def _reconstruct_path(
    topo: SiteTopology,
    source_id: str,
    dest_id: str,
    predecessor: dict[str, tuple[str, Connection]],
) -> tuple[list[Device], list[Connection]]:
    device_ids: list[str] = []
    connections: list[Connection] = []

    current_id = dest_id
    while current_id != source_id:
        device_ids.append(current_id)
        prev_id, conn = predecessor[current_id]
        connections.append(conn)
        current_id = prev_id

    device_ids.append(source_id)
    device_ids.reverse()
    connections.reverse()

    devices = [topo.devices[did] for did in device_ids if did in topo.devices]
    return (devices, connections)
