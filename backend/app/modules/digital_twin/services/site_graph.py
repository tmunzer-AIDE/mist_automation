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


def _build_network_name_to_vlan(networks: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Map network name -> VLAN ID from the snapshot networks dict.

    Networks are keyed by network_id and contain ``name`` and ``vlan_id`` fields.
    Entries without a ``vlan_id`` are skipped.
    """
    mapping: dict[str, int] = {}
    for _net_id, net_cfg in networks.items():
        name = net_cfg.get("name", "")
        vlan_id = net_cfg.get("vlan_id")
        if name and vlan_id is not None:
            try:
                mapping[name] = int(vlan_id)
            except (TypeError, ValueError):
                continue
    return mapping


def _resolve_port_vlan(
    port_cfg: dict[str, Any],
    port_usages: dict[str, dict[str, Any]],
    network_name_to_vlan: dict[str, int],
) -> set[int]:
    """Resolve which VLANs a port participates in.

    Args:
        port_cfg: Single port entry from ``DeviceSnapshot.port_config``.
        port_usages: Site-level or device-level port usage profiles.
        network_name_to_vlan: Mapping from network name to VLAN ID.

    Returns:
        Set of VLAN IDs the port carries. An empty set means the port carries
        no tagged VLANs (disabled or unresolvable).
    """
    usage = port_cfg.get("usage", "")

    # Direct trunk — carries all VLANs
    if usage == "trunk":
        return set(network_name_to_vlan.values())

    # Disabled port — no VLANs
    if usage == "disabled":
        return set()

    # Named usage — look up in port_usages profiles
    profile = port_usages.get(usage)
    if profile is None:
        # Unknown usage — cannot resolve, treat as no VLANs
        return set()

    mode = profile.get("mode", "")
    vlans: set[int] = set()

    if mode == "trunk":
        # Trunk profile — carries all VLANs
        return set(network_name_to_vlan.values())

    # Access or other mode — check port_network and vlan_id
    port_network = profile.get("port_network", "")
    if port_network and port_network in network_name_to_vlan:
        vlans.add(network_name_to_vlan[port_network])

    # Some profiles specify vlan_id directly
    vlan_id = profile.get("vlan_id")
    if vlan_id is not None:
        try:
            vlans.add(int(vlan_id))
        except (TypeError, ValueError):
            pass

    return vlans


def _resolve_device_vlans(
    device: DeviceSnapshot,
    site_port_usages: dict[str, dict[str, Any]],
    network_name_to_vlan: dict[str, int],
) -> set[int]:
    """Collect all VLANs a device participates in from its port_config."""
    # Merge site-level and device-level port_usages (device overrides)
    effective_usages = {**site_port_usages}
    if device.port_usages:
        effective_usages.update(device.port_usages)

    all_vlans: set[int] = set()
    for _port_name, port_cfg in device.port_config.items():
        all_vlans |= _resolve_port_vlan(port_cfg, effective_usages, network_name_to_vlan)

    return all_vlans


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
    network_name_to_vlan = _build_network_name_to_vlan(snapshot.networks)

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

    # Add edges from LLDP neighbors
    for src_mac, port_neighbors in snapshot.lldp_neighbors.items():
        for src_port, neighbor_mac in port_neighbors.items():
            # Only add edges between known devices
            if src_mac in physical.nodes and neighbor_mac in physical.nodes:
                physical.add_edge(src_mac, neighbor_mac, src_port=src_port)

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

    # Determine per-device VLAN membership
    device_vlans: dict[str, set[int]] = {}  # mac -> set of VLAN IDs
    for _dev_id, device in snapshot.devices.items():
        if not device.mac:
            continue
        if device.type == "gateway":
            # Gateways participate in VLANs they have L3 interfaces on
            device_vlans[device.mac] = gw_vlans.get(device.mac, set())
        else:
            device_vlans[device.mac] = _resolve_device_vlans(
                device, snapshot.port_usages, network_name_to_vlan
            )

    # Collect all VLANs present across all devices
    all_vlans: set[int] = set()
    for vlans in device_vlans.values():
        all_vlans |= vlans

    # Build per-VLAN subgraph
    for vlan_id in sorted(all_vlans):
        g = nx.Graph()

        # Add only devices that participate in this VLAN
        for mac, vlans in device_vlans.items():
            if vlan_id in vlans:
                node_data = physical.nodes.get(mac, {})
                g.add_node(mac, **node_data)

        # Add physical edges between participating devices
        for u, v, edge_data in physical.edges(data=True):
            if u in g.nodes and v in g.nodes:
                g.add_edge(u, v, **edge_data)

        vlan_graphs[vlan_id] = g

    return SiteGraph(
        physical=physical,
        vlan_graphs=vlan_graphs,
        gateways=gateways,
        gateway_vlans=gw_vlans,
    )
