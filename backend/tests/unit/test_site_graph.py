"""
Unit tests for site_graph: SiteGraph dataclass and build_site_graph() builder.
"""

from __future__ import annotations

from app.modules.digital_twin.services.site_graph import (
    SiteGraph,
    _resolve_port_vlan,
    build_site_graph,
)
from app.modules.digital_twin.services.site_snapshot import DeviceSnapshot, SiteSnapshot

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_device(
    device_id: str,
    mac: str,
    name: str,
    dtype: str = "switch",
    port_config: dict | None = None,
    ip_config: dict | None = None,
    port_usages: dict | None = None,
) -> DeviceSnapshot:
    return DeviceSnapshot(
        device_id=device_id,
        mac=mac,
        name=name,
        type=dtype,
        model="test-model",
        port_config=port_config or {},
        ip_config=ip_config or {},
        dhcpd_config={},
        port_usages=port_usages,
    )


def _make_snapshot(
    devices: dict[str, DeviceSnapshot] | None = None,
    networks: dict[str, dict] | None = None,
    port_usages: dict[str, dict] | None = None,
    lldp_neighbors: dict[str, dict[str, str]] | None = None,
    wlans: dict[str, dict] | None = None,
) -> SiteSnapshot:
    return SiteSnapshot(
        site_id="site-1",
        site_name="Test Site",
        site_setting={},
        networks=networks or {},
        wlans=wlans or {},
        devices=devices or {},
        port_usages=port_usages or {},
        lldp_neighbors=lldp_neighbors or {},
        port_status={},
        ap_clients={},
        port_devices={},
    )


# ---------------------------------------------------------------------------
# TestResolvePortVlan
# ---------------------------------------------------------------------------


class TestResolvePortVlan:
    def test_trunk_usage_returns_all_vlans(self):
        net_map = {"mgmt": 100, "data": 200, "voice": 300}
        result = _resolve_port_vlan({"usage": "trunk"}, {}, net_map)
        assert result == {100, 200, 300}

    def test_disabled_returns_empty(self):
        net_map = {"mgmt": 100}
        result = _resolve_port_vlan({"usage": "disabled"}, {}, net_map)
        assert result == set()

    def test_named_usage_access_mode_with_port_network(self):
        port_usages = {"cameras": {"mode": "access", "port_network": "security"}}
        net_map = {"security": 400, "data": 200}
        result = _resolve_port_vlan({"usage": "cameras"}, port_usages, net_map)
        assert result == {400}

    def test_named_usage_trunk_mode_returns_all_vlans(self):
        port_usages = {"uplink": {"mode": "trunk"}}
        net_map = {"mgmt": 100, "data": 200}
        result = _resolve_port_vlan({"usage": "uplink"}, port_usages, net_map)
        assert result == {100, 200}

    def test_named_usage_trunk_all_networks_true_returns_all_vlans(self):
        port_usages = {"uplink": {"mode": "trunk", "all_networks": True}}
        net_map = {"mgmt": 100, "data": 200, "voice": 300}
        result = _resolve_port_vlan({"usage": "uplink"}, port_usages, net_map)
        assert result == {100, 200, 300}

    def test_named_usage_trunk_all_networks_false_uses_explicit_networks(self):
        port_usages = {
            "uplink": {
                "mode": "trunk",
                "all_networks": False,
                "networks": ["mgmt", "voice"],
            }
        }
        net_map = {"mgmt": 100, "data": 200, "voice": 300}
        result = _resolve_port_vlan({"usage": "uplink"}, port_usages, net_map)
        assert result == {100, 300}

    def test_named_usage_with_direct_vlan_id(self):
        port_usages = {"legacy": {"mode": "access", "vlan_id": 999}}
        net_map = {"data": 200}
        result = _resolve_port_vlan({"usage": "legacy"}, port_usages, net_map)
        assert result == {999}

    def test_named_usage_with_both_port_network_and_vlan_id(self):
        """Both port_network and vlan_id are present — both VLANs included."""
        port_usages = {"hybrid": {"mode": "access", "port_network": "data", "vlan_id": 999}}
        net_map = {"data": 200}
        result = _resolve_port_vlan({"usage": "hybrid"}, port_usages, net_map)
        assert result == {200, 999}

    def test_unknown_usage_returns_empty(self):
        net_map = {"data": 200}
        result = _resolve_port_vlan({"usage": "nonexistent"}, {}, net_map)
        assert result == set()

    def test_empty_port_config(self):
        result = _resolve_port_vlan({}, {}, {"data": 200})
        assert result == set()

    def test_trunk_with_no_networks(self):
        result = _resolve_port_vlan({"usage": "trunk"}, {}, {})
        assert result == set()


# ---------------------------------------------------------------------------
# TestBuildSiteGraph
# ---------------------------------------------------------------------------


class TestBuildSiteGraph:
    def test_physical_graph_from_lldp(self):
        """3 devices (2 switches + 1 gateway), 2 LLDP links -> 3 nodes, 2 edges."""
        sw1 = _make_device("d1", "aa:bb:cc:00:00:01", "switch-1", "switch")
        sw2 = _make_device("d2", "aa:bb:cc:00:00:02", "switch-2", "switch")
        gw = _make_device("d3", "aa:bb:cc:00:00:03", "gateway-1", "gateway")

        lldp = {
            "aa:bb:cc:00:00:01": {"ge-0/0/0": "aa:bb:cc:00:00:02"},
            "aa:bb:cc:00:00:02": {"ge-0/0/1": "aa:bb:cc:00:00:03"},
        }

        snapshot = _make_snapshot(
            devices={"d1": sw1, "d2": sw2, "d3": gw},
            lldp_neighbors=lldp,
        )
        graph = build_site_graph(snapshot)

        assert isinstance(graph, SiteGraph)
        assert len(graph.physical.nodes) == 3
        assert len(graph.physical.edges) == 2
        assert "aa:bb:cc:00:00:03" in graph.gateways
        assert "aa:bb:cc:00:00:01" not in graph.gateways
        assert "aa:bb:cc:00:00:02" not in graph.gateways

        # Verify node attributes
        node_data = graph.physical.nodes["aa:bb:cc:00:00:01"]
        assert node_data["name"] == "switch-1"
        assert node_data["type"] == "switch"
        assert node_data["device_id"] == "d1"

        # Verify edge attributes
        edge_data = graph.physical.edges["aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02"]
        assert edge_data["src_port"] == "ge-0/0/0"

    def test_empty_lldp_gives_disconnected_nodes(self):
        """1 device, no LLDP -> 1 node, 0 edges."""
        sw = _make_device("d1", "aa:bb:cc:00:00:01", "switch-1", "switch")
        snapshot = _make_snapshot(devices={"d1": sw}, lldp_neighbors={})
        graph = build_site_graph(snapshot)

        assert len(graph.physical.nodes) == 1
        assert len(graph.physical.edges) == 0
        assert graph.gateways == set()

    def test_vlan_graph_from_port_config(self):
        """Switch with trunk + named port, gateway with ip_config -> VLAN graph exists."""
        sw = _make_device(
            "d1",
            "aa:bb:cc:00:00:01",
            "switch-1",
            "switch",
            port_config={
                "ge-0/0/0": {"usage": "trunk"},
                "ge-0/0/1": {"usage": "cameras"},
            },
        )
        gw = _make_device(
            "d2",
            "aa:bb:cc:00:00:02",
            "gateway-1",
            "gateway",
            ip_config={"data": {"ip": "10.0.0.1", "netmask": "255.255.255.0"}},
        )

        networks = {
            "net-1": {"name": "data", "vlan_id": 100},
            "net-2": {"name": "security", "vlan_id": 200},
        }
        port_usages = {"cameras": {"mode": "access", "port_network": "security"}}
        lldp = {"aa:bb:cc:00:00:01": {"ge-0/0/0": "aa:bb:cc:00:00:02"}}

        snapshot = _make_snapshot(
            devices={"d1": sw, "d2": gw},
            networks=networks,
            port_usages=port_usages,
            lldp_neighbors=lldp,
        )
        graph = build_site_graph(snapshot)

        # VLAN 100 (data): switch has trunk (all VLANs), gateway has L3 on data
        assert 100 in graph.vlan_graphs
        vlan_100 = graph.vlan_graphs[100]
        assert "aa:bb:cc:00:00:01" in vlan_100.nodes
        assert "aa:bb:cc:00:00:02" in vlan_100.nodes
        assert len(vlan_100.edges) == 1  # physical edge between them

        # VLAN 200 (security): switch has trunk + cameras profile, gateway has no L3
        assert 200 in graph.vlan_graphs
        vlan_200 = graph.vlan_graphs[200]
        assert "aa:bb:cc:00:00:01" in vlan_200.nodes
        # Gateway does NOT have L3 on security VLAN
        assert "aa:bb:cc:00:00:02" not in vlan_200.nodes

        # Gateway VLAN metadata
        assert graph.gateway_vlans["aa:bb:cc:00:00:02"] == {100}

    def test_no_networks_no_vlan_graphs(self):
        """No networks defined -> vlan_graphs == {}."""
        sw = _make_device("d1", "aa:bb:cc:00:00:01", "switch-1", "switch")
        snapshot = _make_snapshot(devices={"d1": sw})
        graph = build_site_graph(snapshot)

        assert graph.vlan_graphs == {}

    def test_device_without_mac_excluded(self):
        """Devices with empty MAC are excluded from the graph."""
        sw = _make_device("d1", "", "switch-no-mac", "switch")
        snapshot = _make_snapshot(devices={"d1": sw})
        graph = build_site_graph(snapshot)

        assert len(graph.physical.nodes) == 0

    def test_lldp_to_unknown_device_ignored(self):
        """LLDP neighbors referencing MACs not in the device list are skipped."""
        sw = _make_device("d1", "aa:bb:cc:00:00:01", "switch-1", "switch")
        lldp = {"aa:bb:cc:00:00:01": {"ge-0/0/0": "ff:ff:ff:ff:ff:ff"}}
        snapshot = _make_snapshot(devices={"d1": sw}, lldp_neighbors=lldp)
        graph = build_site_graph(snapshot)

        assert len(graph.physical.nodes) == 1
        assert len(graph.physical.edges) == 0

    def test_multiple_gateways(self):
        """Multiple gateways are all tracked."""
        gw1 = _make_device("d1", "aa:bb:cc:00:00:01", "gw-1", "gateway")
        gw2 = _make_device("d2", "aa:bb:cc:00:00:02", "gw-2", "gateway")
        snapshot = _make_snapshot(devices={"d1": gw1, "d2": gw2})
        graph = build_site_graph(snapshot)

        assert graph.gateways == {"aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02"}

    def test_device_level_port_usages_override(self):
        """Device-level port_usages override site-level."""
        sw = _make_device(
            "d1",
            "aa:bb:cc:00:00:01",
            "switch-1",
            "switch",
            port_config={"ge-0/0/0": {"usage": "custom"}},
            port_usages={"custom": {"mode": "access", "port_network": "voice"}},
        )
        networks = {
            "net-1": {"name": "data", "vlan_id": 100},
            "net-2": {"name": "voice", "vlan_id": 300},
        }
        # Site-level profile maps custom to data, device overrides to voice
        site_port_usages = {"custom": {"mode": "access", "port_network": "data"}}

        snapshot = _make_snapshot(
            devices={"d1": sw},
            networks=networks,
            port_usages=site_port_usages,
        )
        graph = build_site_graph(snapshot)

        # Device override should win: VLAN 300 (voice), not 100 (data)
        assert 300 in graph.vlan_graphs
        assert "aa:bb:cc:00:00:01" in graph.vlan_graphs[300].nodes

    def test_vlan_graph_edges_only_between_participating_devices(self):
        """VLAN subgraph edges only exist between devices in the same VLAN."""
        sw1 = _make_device(
            "d1",
            "aa:bb:cc:00:00:01",
            "switch-1",
            "switch",
            port_config={"ge-0/0/0": {"usage": "trunk"}},
        )
        sw2 = _make_device(
            "d2",
            "aa:bb:cc:00:00:02",
            "switch-2",
            "switch",
            port_config={"ge-0/0/0": {"usage": "access_only"}},
        )
        networks = {
            "net-1": {"name": "data", "vlan_id": 100},
            "net-2": {"name": "mgmt", "vlan_id": 200},
        }
        port_usages = {"access_only": {"mode": "access", "port_network": "data"}}
        lldp = {"aa:bb:cc:00:00:01": {"ge-0/0/0": "aa:bb:cc:00:00:02"}}

        snapshot = _make_snapshot(
            devices={"d1": sw1, "d2": sw2},
            networks=networks,
            port_usages=port_usages,
            lldp_neighbors=lldp,
        )
        graph = build_site_graph(snapshot)

        # VLAN 100: both devices participate
        assert "aa:bb:cc:00:00:01" in graph.vlan_graphs[100].nodes
        assert "aa:bb:cc:00:00:02" in graph.vlan_graphs[100].nodes
        assert len(graph.vlan_graphs[100].edges) == 1

        # VLAN 200: only sw1 (trunk) participates, sw2 is access on data only
        assert "aa:bb:cc:00:00:01" in graph.vlan_graphs[200].nodes
        assert "aa:bb:cc:00:00:02" not in graph.vlan_graphs[200].nodes
        assert len(graph.vlan_graphs[200].edges) == 0

    def test_gateway_vlans_from_ip_config(self):
        """Gateway VLAN membership comes from ip_config keys, not port_config."""
        gw = _make_device(
            "d1",
            "aa:bb:cc:00:00:01",
            "gateway-1",
            "gateway",
            ip_config={
                "data": {"ip": "10.0.0.1", "netmask": "255.255.255.0"},
                "mgmt": {"ip": "10.0.1.1", "netmask": "255.255.255.0"},
            },
        )
        networks = {
            "net-1": {"name": "data", "vlan_id": 100},
            "net-2": {"name": "mgmt", "vlan_id": 200},
            "net-3": {"name": "guest", "vlan_id": 300},
        }
        snapshot = _make_snapshot(devices={"d1": gw}, networks=networks)
        graph = build_site_graph(snapshot)

        # Gateway has L3 on data (100) and mgmt (200) but NOT guest (300)
        assert graph.gateway_vlans["aa:bb:cc:00:00:01"] == {100, 200}
        assert 100 in graph.vlan_graphs
        assert 200 in graph.vlan_graphs
        # Guest VLAN not present because no device participates
        assert 300 not in graph.vlan_graphs


# ---------------------------------------------------------------------------
# AP WLAN VLAN membership + port-aware edge filtering
# ---------------------------------------------------------------------------


class TestApWlanVlanMembership:
    """APs should land in vlan_graphs for every WLAN they serve, so
    CONN-VLAN-PATH can detect WLAN blackholes.
    """

    def test_ap_participates_in_wlan_vlans(self):
        gw = _make_device(
            "gw",
            "aa:bb:cc:00:00:01",
            "gw-1",
            "gateway",
            ip_config={"data": {"ip": "10.0.10.1", "netmask": "255.255.255.0"}},
        )
        sw = _make_device(
            "sw",
            "aa:bb:cc:00:00:02",
            "sw-1",
            "switch",
            port_config={
                "ge-0/0/0": {"usage": "trunk"},
                "ge-0/0/9": {"usage": "trunk"},
            },
        )
        ap = _make_device("ap", "aa:bb:cc:00:00:03", "ap-1", "ap")
        snapshot = _make_snapshot(
            devices={"gw": gw, "sw": sw, "ap": ap},
            networks={"n1": {"name": "data", "vlan_id": 10}},
            wlans={"w1": {"id": "w1", "ssid": "Corp", "vlan_id": 10}},
            lldp_neighbors={
                "aa:bb:cc:00:00:01": {"ge-0/0/0": "aa:bb:cc:00:00:02"},
                "aa:bb:cc:00:00:02": {
                    "ge-0/0/0": "aa:bb:cc:00:00:01",
                    "ge-0/0/9": "aa:bb:cc:00:00:03",
                },
            },
        )

        graph = build_site_graph(snapshot)

        assert "aa:bb:cc:00:00:03" in graph.vlan_graphs[10].nodes
        # Full path gw -- sw -- ap in VLAN 10
        assert graph.vlan_graphs[10].has_edge("aa:bb:cc:00:00:02", "aa:bb:cc:00:00:03")

    def test_ap_excluded_when_wlan_vlan_is_jinja(self):
        ap = _make_device("ap", "aa:bb:cc:00:00:03", "ap-1", "ap")
        snapshot = _make_snapshot(
            devices={"ap": ap},
            networks={"n1": {"name": "data", "vlan_id": 10}},
            wlans={"w1": {"id": "w1", "ssid": "Corp", "vlan_id": "{{wlan_vlan}}"}},
        )

        graph = build_site_graph(snapshot)

        # Unresolved Jinja vlan_id is skipped -> no VLAN subgraphs generated
        # by WLAN participation, and AP has no other VLAN source.
        assert 10 not in graph.vlan_graphs or "aa:bb:cc:00:00:03" not in graph.vlan_graphs[10].nodes

    def test_switch_port_drops_vlan_excludes_edge(self):
        """If a switch port's profile only carries VLAN 20, the LLDP edge on
        that port is NOT added to vlan_graphs[10] even though both endpoints
        otherwise participate in VLAN 10.
        """
        port_usages = {
            "ap": {"mode": "trunk"},
            "iot": {"mode": "access", "vlan_id": 20, "port_network": "iot"},
        }
        networks = {
            "n1": {"name": "data", "vlan_id": 10},
            "n2": {"name": "iot", "vlan_id": 20},
        }
        gw = _make_device(
            "gw",
            "aa:bb:cc:00:00:01",
            "gw-1",
            "gateway",
            ip_config={
                "data": {"ip": "10.0.10.1", "netmask": "255.255.255.0"},
                "iot": {"ip": "10.0.20.1", "netmask": "255.255.255.0"},
            },
        )
        sw = _make_device(
            "sw",
            "aa:bb:cc:00:00:02",
            "sw-1",
            "switch",
            port_config={
                "ge-0/0/0": {"usage": "ap"},  # uplink to gw: full trunk
                "ge-0/0/9": {"usage": "iot"},  # to AP: only VLAN 20
            },
        )
        ap = _make_device("ap", "aa:bb:cc:00:00:03", "ap-1", "ap")
        snapshot = _make_snapshot(
            devices={"gw": gw, "sw": sw, "ap": ap},
            networks=networks,
            port_usages=port_usages,
            wlans={"w1": {"id": "w1", "ssid": "Corp", "vlan_id": 10}},
            lldp_neighbors={
                "aa:bb:cc:00:00:01": {"ge-0/0/0": "aa:bb:cc:00:00:02"},
                "aa:bb:cc:00:00:02": {
                    "ge-0/0/0": "aa:bb:cc:00:00:01",
                    "ge-0/0/9": "aa:bb:cc:00:00:03",
                },
            },
        )

        graph = build_site_graph(snapshot)

        # sw still in VLAN 10 (because ge-0/0/0 is full trunk via "ap" profile)
        assert "aa:bb:cc:00:00:02" in graph.vlan_graphs[10].nodes
        # ap still in VLAN 10 (from WLAN)
        assert "aa:bb:cc:00:00:03" in graph.vlan_graphs[10].nodes
        # BUT the edge from sw to ap is excluded from VLAN 10 subgraph because
        # sw's ge-0/0/9 is "iot" (only VLAN 20)
        assert not graph.vlan_graphs[10].has_edge("aa:bb:cc:00:00:02", "aa:bb:cc:00:00:03")
        # gw -- sw edge is still in VLAN 10 (both sides trunk)
        assert graph.vlan_graphs[10].has_edge("aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02")
