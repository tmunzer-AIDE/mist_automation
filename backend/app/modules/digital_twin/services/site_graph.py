"""
Site graph: L1 physical + per-VLAN L2 graph builders.

Provides:
- SiteGraph dataclass (physical graph, per-VLAN subgraphs, gateway metadata)
- build_site_graph() — assemble graph from a SiteSnapshot
- _resolve_port_vlan() — resolve VLAN membership of a single port
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import networkx as nx

from app.modules.digital_twin.services.site_snapshot import DeviceSnapshot, SiteSnapshot
from app.modules.digital_twin.services.topology_utils import (
    build_network_name_to_vlan,
    materialize_device_port_config,
    materialize_port_config_entry,
    merge_infra_neighbor_ports,
    resolve_port_config_entry,
    resolve_vlan_id,
)

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class SiteGraph:
    physical: nx.Graph  # L1: device MACs as nodes, LLDP links as edges
    vlan_graphs: dict[int, nx.Graph]  # L2: per-VLAN subgraph
    gateways: set[str]  # MACs of gateway devices
    gateway_vlans: dict[str, set[int]]  # gateway_mac -> set of VLANs with L3 interface


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_port_vlan(
    port_cfg: dict[str, Any],
    port_usages: dict[str, dict[str, Any]],
    network_name_to_vlan: dict[str, int],
) -> set[int]:
    """Resolve VLANs for one port via profile-flattened materialization."""
    materialized = materialize_port_config_entry(
        port_cfg,
        port_usages,
        network_name_to_vlan,
        site_vars={},
    )
    return {int(vid) for vid in materialized.get("resolved_vlan_ids", [])}


def _resolve_device_vlans(materialized_port_config: dict[str, dict[str, Any]]) -> set[int]:
    """Collect all VLANs a device participates in from materialized ports."""
    all_vlans: set[int] = set()
    for port_cfg in materialized_port_config.values():
        all_vlans |= {int(vid) for vid in port_cfg.get("resolved_vlan_ids", [])}

    return all_vlans


def _wlan_vlan_ids(wlans: dict[str, dict[str, Any]], site_vars: dict[str, Any]) -> set[int]:
    """Collect numeric vlan_ids from the site's WLAN configs.

    Handles both literal integers and Jinja variables (e.g. ``"{{wlan_vlan}}"``)
    resolved against the site's ``vars``. APs serving WLANs with a resolvable
    VLAN are treated as participants in that VLAN's L2 subgraph, which lets
    ``CONN-VLAN-PATH`` detect WLAN blackholes.
    """
    result: set[int] = set()
    for wlan in wlans.values():
        vid = resolve_vlan_id(wlan.get("vlan_id"), site_vars)
        if vid is not None:
            result.add(vid)
    return result


def _resolve_gateway_vlans(
    device: DeviceSnapshot,
    network_name_to_vlan: dict[str, int],
) -> set[int]:
    """Determine which VLANs a gateway has L3 interfaces on.

    Gateway ``ip_config`` keys are network names. Each present key with a
    matching network → VLAN mapping indicates the gateway has a L3 interface
    on that VLAN.
    """
    vlans: set[int] = set()
    for net_name in device.ip_config:
        if net_name in network_name_to_vlan:
            vlans.add(network_name_to_vlan[net_name])
    return vlans


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_site_graph(snapshot: SiteSnapshot) -> SiteGraph:
    """Build physical and per-VLAN graphs from a SiteSnapshot.

    - Physical graph: undirected, device MACs as nodes, LLDP links as edges.
    - VLAN graphs: per-VLAN subgraph with only devices participating in that VLAN.
    - Gateway metadata: which devices are gateways, which VLANs they have L3 on.
    """
    site_vars = snapshot.site_setting.get("vars") or {}
    network_name_to_vlan = build_network_name_to_vlan(snapshot.networks, site_vars)

    # -- Physical graph --
    physical = nx.Graph()
    gateways: set[str] = set()
    gw_vlans: dict[str, set[int]] = {}

    # Add all devices as nodes (keyed by MAC)
    for _dev_id, device in snapshot.devices.items():
        if not device.mac:
            continue
        physical.add_node(
            device.mac,
            name=device.name,
            type=device.type,
            device_id=device.device_id,
        )
        if device.type == "gateway":
            gateways.add(device.mac)
            gw_vlans[device.mac] = _resolve_gateway_vlans(device, network_name_to_vlan)

    # Add edges from LLDP neighbors, tracking each side's port so per-VLAN
    # subgraphs can honour port-level VLAN membership later on.
    #
    # ``edge_ports[(mac_a, mac_b)]`` (tuple always sorted) maps each endpoint
    # MAC to the LLDP-reported port on that side. Only one side is populated
    # for AP uplinks (APs don't expose LLDP neighbour tables). Switch-to-switch
    # links typically populate both sides.
    edge_ports: dict[tuple[str, str], dict[str, str]] = {}
    for src_mac, port_neighbors in merge_infra_neighbor_ports(snapshot).items():
        for src_port, neighbor_mac in port_neighbors.items():
            if src_mac in physical.nodes and neighbor_mac in physical.nodes:
                physical.add_edge(src_mac, neighbor_mac, src_port=src_port)
                key = tuple(sorted((src_mac, neighbor_mac)))
                edge_ports.setdefault(key, {})[src_mac] = src_port

    # -- Per-VLAN graphs --
    vlan_graphs: dict[int, nx.Graph] = {}

    if not network_name_to_vlan:
        # No networks defined — no VLAN graphs possible
        return SiteGraph(
            physical=physical,
            vlan_graphs=vlan_graphs,
            gateways=gateways,
            gateway_vlans=gw_vlans,
        )

    device_by_mac: dict[str, DeviceSnapshot] = {d.mac: d for d in snapshot.devices.values() if d.mac}
    materialized_ports_by_mac: dict[str, dict[str, dict[str, Any]]] = {}
    for device in snapshot.devices.values():
        if not device.mac:
            continue
        materialized_ports = device.resolved_port_config
        if materialized_ports is None:
            materialized_ports = materialize_device_port_config(
                device.port_config,
                snapshot.port_usages,
                device.port_usages,
                network_name_to_vlan,
                site_vars,
            )
        materialized_ports_by_mac[device.mac] = materialized_ports

    # Determine per-device VLAN membership
    ap_wlan_vlans = _wlan_vlan_ids(snapshot.wlans, site_vars)
    device_vlans: dict[str, set[int]] = {}  # mac -> set of VLAN IDs
    for _dev_id, device in snapshot.devices.items():
        if not device.mac:
            continue
        if device.type == "gateway":
            # Gateways participate in VLANs they have L3 interfaces on
            device_vlans[device.mac] = gw_vlans.get(device.mac, set())
        elif device.type == "ap":
            # APs don't trunk VLANs via port_config; they serve WLANs whose
            # vlan_id determines which VLANs they participate in. Treat every
            # site WLAN as applying to every AP — a conservative
            # over-approximation that catches WLAN blackholes without needing
            # per-AP WLAN filter modelling.
            device_vlans[device.mac] = set(ap_wlan_vlans)
        else:
            device_vlans[device.mac] = _resolve_device_vlans(materialized_ports_by_mac.get(device.mac, {}))

    def _switch_port_carries_vlan(
        mac: str,
        port: str | None,
        vlan_id: int,
    ) -> bool:
        """Return True iff the given switch's port carries ``vlan_id``.

        Returns True when the device is not a switch or the switch has no
        explicit profile on that port — in those cases we fall back to the
        permissive "device participates in VLAN" rule so empty test
        fixtures and legacy inherit-from-template cases keep working.
        """
        dev = device_by_mac.get(mac)
        if not dev or dev.type != "switch":
            return True
        if not port:
            return True

        materialized_port_cfg = resolve_port_config_entry(materialized_ports_by_mac.get(mac, {}), port)

        if not materialized_port_cfg.get("usage"):
            return True

        return vlan_id in {int(vid) for vid in materialized_port_cfg.get("resolved_vlan_ids", [])}

    # Collect all VLANs present across all devices
    all_vlans: set[int] = set()
    for vlans in device_vlans.values():
        all_vlans |= vlans

    # Build per-VLAN subgraph — nodes are devices that participate in the
    # VLAN, edges are included only when the specific LLDP port on each
    # switch side is actually trunking the VLAN. This is what lets
    # CONN-VLAN-PATH detect "the port profile changed so the uplink no
    # longer carries VLAN 10, even though the physical link is still up".
    for vlan_id in sorted(all_vlans):
        g = nx.Graph()

        for mac, vlans in device_vlans.items():
            if vlan_id in vlans:
                node_data = physical.nodes.get(mac, {})
                g.add_node(mac, **node_data)

        for u, v, edge_data in physical.edges(data=True):
            if u not in g.nodes or v not in g.nodes:
                continue
            key = tuple(sorted((u, v)))
            ports_on_edge = edge_ports.get(key, {})
            u_port = ports_on_edge.get(u)
            v_port = ports_on_edge.get(v)
            if not _switch_port_carries_vlan(u, u_port, vlan_id):
                continue
            if not _switch_port_carries_vlan(v, v_port, vlan_id):
                continue
            g.add_edge(u, v, **edge_data)

        vlan_graphs[vlan_id] = g

    return SiteGraph(
        physical=physical,
        vlan_graphs=vlan_graphs,
        gateways=gateways,
        gateway_vlans=gw_vlans,
    )
