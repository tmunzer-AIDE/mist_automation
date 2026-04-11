"""
Unit tests for Layer 3 routing prediction checks.
TDD: tests written before implementation.
"""

from app.modules.digital_twin.services.routing_checks import (
    check_bgp_peer_break,
    check_default_gateway_gap,
    check_ospf_adjacency_break,
    check_vrf_consistency,
    check_wan_failover_impact,
)

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------


def _dev(dev_id: str, device_type: str = "switch", **kwargs) -> dict:
    """Create a minimal device dict."""
    d = {
        "id": dev_id,
        "name": kwargs.get("name", dev_id.upper()),
        "device_type": device_type,
    }
    for k, v in kwargs.items():
        if k not in d:
            d[k] = v
    return d


def _make_snapshot(devices: dict | None = None, connections: list | None = None) -> dict:
    """Create a minimal topology snapshot dict."""
    return {
        "devices": devices or {},
        "connections": connections or [],
    }


def _routing_config(
    *,
    ospf_areas: list[str] | None = None,
    bgp_peers: list[dict] | None = None,
    static_routes: list[dict] | None = None,
) -> dict:
    """Create a routing section dict for device config."""
    r: dict = {}
    if ospf_areas is not None:
        r["ospf"] = {"areas": ospf_areas}
    if bgp_peers is not None:
        r["bgp_peers"] = bgp_peers
    if static_routes is not None:
        r["static_routes"] = static_routes
    return r


def _device_config(
    *,
    networks: list[dict] | None = None,
    routing: dict | None = None,
    ip_configs: dict | None = None,
    vrf: dict | None = None,
    port_config: dict | None = None,
    device_type: str = "switch",
) -> dict:
    """Build a device config dict."""
    cfg: dict = {"device_type": device_type}
    if networks is not None:
        cfg["networks"] = networks
    if routing is not None:
        cfg["routing"] = routing
    if ip_configs is not None:
        cfg["ip_configs"] = ip_configs
    if vrf is not None:
        cfg["vrf"] = vrf
    if port_config is not None:
        cfg["port_config"] = port_config
    return cfg


# ---------------------------------------------------------------------------
# L3-01  Default gateway gap
# ---------------------------------------------------------------------------


class TestDefaultGatewayGap:
    def test_pass_switch_with_ospf(self):
        """Switch with IRB subnet + OSPF area -> no gap."""
        snapshot = _make_snapshot(
            devices={"sw1": _dev("sw1", device_type="switch")},
        )
        device_configs = {
            "sw1": _device_config(
                networks=[{"name": "mgmt", "subnet": "192.168.10.0/24"}],
                routing=_routing_config(ospf_areas=["0.0.0.0"]),
            )
        }
        result = check_default_gateway_gap(snapshot, device_configs)
        assert result.check_id == "L3-01"
        assert result.layer == 3
        assert result.status == "pass"

    def test_pass_switch_with_static_route(self):
        """Switch with IRB subnet + static route -> no gap."""
        snapshot = _make_snapshot(
            devices={"sw1": _dev("sw1", device_type="switch")},
        )
        device_configs = {
            "sw1": _device_config(
                networks=[{"name": "corp", "subnet": "10.0.1.0/24"}],
                routing=_routing_config(static_routes=[{"prefix": "0.0.0.0/0", "nexthop": "10.0.0.1"}]),
            )
        }
        result = check_default_gateway_gap(snapshot, device_configs)
        assert result.status == "pass"

    def test_pass_switch_with_bgp_peer(self):
        """Switch with IRB subnet + BGP peer -> no gap."""
        snapshot = _make_snapshot(
            devices={"sw1": _dev("sw1", device_type="switch")},
        )
        device_configs = {
            "sw1": _device_config(
                networks=[{"name": "corp", "subnet": "10.0.1.0/24"}],
                routing=_routing_config(bgp_peers=[{"ip": "10.0.0.1", "asn": 65001}]),
            )
        }
        result = check_default_gateway_gap(snapshot, device_configs)
        assert result.status == "pass"

    def test_critical_switch_no_routing(self):
        """Switch with IRB subnets but no routing config -> critical."""
        snapshot = _make_snapshot(
            devices={"sw1": _dev("sw1", device_type="switch")},
        )
        device_configs = {
            "sw1": _device_config(
                networks=[{"name": "vlan10", "subnet": "10.10.0.0/24"}],
            )
        }
        result = check_default_gateway_gap(snapshot, device_configs)
        assert result.status == "critical"
        assert "sw1" in " ".join(result.affected_objects) or "SW1" in " ".join(result.affected_objects)
        assert result.remediation_hint is not None

    def test_critical_multiple_switches_missing_routing(self):
        """Two switches with subnets and no routing -> both flagged."""
        snapshot = _make_snapshot(
            devices={
                "sw1": _dev("sw1", device_type="switch"),
                "sw2": _dev("sw2", device_type="switch"),
            },
        )
        device_configs = {
            "sw1": _device_config(networks=[{"name": "v10", "subnet": "10.10.0.0/24"}]),
            "sw2": _device_config(networks=[{"name": "v20", "subnet": "10.20.0.0/24"}]),
        }
        result = check_default_gateway_gap(snapshot, device_configs)
        assert result.status == "critical"
        assert len(result.affected_objects) == 2

    def test_skipped_gateway_devices(self):
        """Gateway devices are skipped (they ARE the router)."""
        snapshot = _make_snapshot(
            devices={"gw1": _dev("gw1", device_type="gateway")},
        )
        device_configs = {
            "gw1": _device_config(
                device_type="gateway",
                networks=[{"name": "wan", "subnet": "1.2.3.0/30"}],
            )
        }
        result = check_default_gateway_gap(snapshot, device_configs)
        assert result.status == "pass"

    def test_skipped_no_subnets(self):
        """Switch with no networks configured is ignored."""
        snapshot = _make_snapshot(
            devices={"sw1": _dev("sw1", device_type="switch")},
        )
        device_configs = {"sw1": _device_config()}
        result = check_default_gateway_gap(snapshot, device_configs)
        assert result.status == "pass"

    def test_pass_empty_snapshot(self):
        """Empty snapshot -> pass (nothing to check)."""
        result = check_default_gateway_gap(_make_snapshot(), {})
        assert result.status == "pass"


# ---------------------------------------------------------------------------
# L3-02  OSPF adjacency break
# ---------------------------------------------------------------------------


class TestOspfAdjacencyBreak:
    def test_pass_peer_still_reachable(self):
        """OSPF peer IP is still in the predicted interface config -> pass."""
        baseline = {"sw1": {"ospf_peers": [{"ip": "10.0.0.2", "area": "0.0.0.0", "state": "full"}]}}
        predicted = {
            "sw1": {
                "ip_configs": {
                    "mgmt": {"ip": "10.0.0.1", "netmask": "255.255.255.0"},
                }
            }
        }
        result = check_ospf_adjacency_break(baseline, predicted)
        assert result.check_id == "L3-02"
        assert result.layer == 3
        assert result.status == "pass"

    def test_critical_peer_subnet_removed(self):
        """OSPF peer IP no longer reachable after interface change -> critical."""
        baseline = {"sw1": {"ospf_peers": [{"ip": "192.168.99.2", "area": "0.0.0.0", "state": "full"}]}}
        predicted = {
            "sw1": {
                "ip_configs": {
                    "mgmt": {"ip": "10.0.0.1", "netmask": "255.255.255.0"},
                }
            }
        }
        result = check_ospf_adjacency_break(baseline, predicted)
        assert result.status == "critical"
        assert result.remediation_hint is not None

    def test_critical_all_interfaces_removed(self):
        """Predicted config has no ip_configs at all -> all peers break."""
        baseline = {"sw1": {"ospf_peers": [{"ip": "10.0.0.2", "area": "0.0.0.0", "state": "full"}]}}
        predicted = {"sw1": {}}
        result = check_ospf_adjacency_break(baseline, predicted)
        assert result.status == "critical"

    def test_pass_no_ospf_in_baseline(self):
        """No OSPF peers in baseline -> pass (nothing to break)."""
        baseline = {"sw1": {"ospf_peers": []}}
        predicted = {"sw1": {"ip_configs": {}}}
        result = check_ospf_adjacency_break(baseline, predicted)
        assert result.status == "pass"

    def test_pass_empty_baseline(self):
        """Completely empty baseline routing -> pass."""
        result = check_ospf_adjacency_break({}, {})
        assert result.status == "pass"

    def test_critical_partial_break(self):
        """One peer stays up, another breaks -> critical with correct affected objects."""
        baseline = {
            "sw1": {
                "ospf_peers": [
                    {"ip": "10.0.0.2", "area": "0.0.0.0", "state": "full"},
                    {"ip": "172.16.0.2", "area": "0.0.0.0", "state": "full"},
                ]
            }
        }
        predicted = {
            "sw1": {
                "ip_configs": {
                    "core": {"ip": "10.0.0.1", "netmask": "255.255.255.0"},
                    # 172.16.0.x interface is gone
                }
            }
        }
        result = check_ospf_adjacency_break(baseline, predicted)
        assert result.status == "critical"
        # Only the broken peer should be flagged
        assert len(result.affected_objects) == 1


# ---------------------------------------------------------------------------
# L3-03  BGP peer break
# ---------------------------------------------------------------------------


class TestBgpPeerBreak:
    def test_pass_peer_still_reachable(self):
        """BGP peer IP is reachable from predicted config -> pass."""
        baseline = {"gw1": {"bgp_peers": [{"ip": "203.0.113.2", "asn": 65001, "state": "established"}]}}
        predicted = {
            "gw1": {
                "ip_configs": {
                    "wan": {"ip": "203.0.113.1", "netmask": "255.255.255.252"},
                }
            }
        }
        result = check_bgp_peer_break(baseline, predicted)
        assert result.check_id == "L3-03"
        assert result.layer == 3
        assert result.status == "pass"

    def test_critical_peer_ip_unreachable(self):
        """BGP peer IP no longer reachable after WAN interface change -> critical."""
        baseline = {"gw1": {"bgp_peers": [{"ip": "203.0.113.2", "asn": 65001, "state": "established"}]}}
        predicted = {
            "gw1": {
                "ip_configs": {
                    "wan": {"ip": "198.51.100.1", "netmask": "255.255.255.252"},
                }
            }
        }
        result = check_bgp_peer_break(baseline, predicted)
        assert result.status == "critical"
        assert result.remediation_hint is not None

    def test_critical_no_ip_configs_in_predicted(self):
        """Predicted config stripped all interfaces -> BGP peers break."""
        baseline = {"gw1": {"bgp_peers": [{"ip": "10.0.0.1", "asn": 65002, "state": "established"}]}}
        predicted = {"gw1": {}}
        result = check_bgp_peer_break(baseline, predicted)
        assert result.status == "critical"

    def test_pass_no_bgp_in_baseline(self):
        """No BGP peers in baseline -> pass."""
        baseline = {"gw1": {"bgp_peers": []}}
        predicted = {"gw1": {"ip_configs": {}}}
        result = check_bgp_peer_break(baseline, predicted)
        assert result.status == "pass"

    def test_pass_empty_baseline(self):
        """Completely empty baseline -> pass."""
        result = check_bgp_peer_break({}, {})
        assert result.status == "pass"

    def test_critical_multiple_devices(self):
        """Two devices lose BGP sessions -> both in affected_objects."""
        baseline = {
            "gw1": {"bgp_peers": [{"ip": "1.2.3.2", "asn": 65001, "state": "established"}]},
            "gw2": {"bgp_peers": [{"ip": "5.6.7.2", "asn": 65002, "state": "established"}]},
        }
        predicted = {
            "gw1": {"ip_configs": {"wan": {"ip": "9.9.9.1", "netmask": "255.255.255.252"}}},
            "gw2": {"ip_configs": {"wan": {"ip": "9.9.9.5", "netmask": "255.255.255.252"}}},
        }
        result = check_bgp_peer_break(baseline, predicted)
        assert result.status == "critical"
        assert len(result.affected_objects) == 2


# ---------------------------------------------------------------------------
# L3-04  VRF consistency
# ---------------------------------------------------------------------------


class TestVrfConsistency:
    def test_skipped_no_vrf(self):
        """No VRFs configured anywhere -> skipped."""
        predicted = {"sw1": _device_config(networks=[{"name": "corp", "subnet": "10.0.1.0/24"}])}
        result = check_vrf_consistency(predicted)
        assert result.check_id == "L3-04"
        assert result.layer == 3
        assert result.status == "skipped"

    def test_pass_valid_vrf(self):
        """VRF references only networks that exist -> pass."""
        predicted = {
            "sw1": _device_config(
                networks=[
                    {"name": "corp", "subnet": "10.0.1.0/24"},
                    {"name": "guest", "subnet": "10.0.2.0/24"},
                ],
                vrf={
                    "CORP": {"networks": ["corp"]},
                    "GUEST": {"networks": ["guest"]},
                },
            )
        }
        result = check_vrf_consistency(predicted)
        assert result.status == "pass"

    def test_error_vrf_references_nonexistent_network(self):
        """VRF references a network name that doesn't exist in device config -> error."""
        predicted = {
            "sw1": _device_config(
                networks=[{"name": "corp", "subnet": "10.0.1.0/24"}],
                vrf={"CORP": {"networks": ["corp", "missing_net"]}},
            )
        }
        result = check_vrf_consistency(predicted)
        assert result.status == "error"
        assert result.remediation_hint is not None

    def test_error_duplicate_network_across_vrfs(self):
        """Same network assigned to two VRFs on the same device -> error."""
        predicted = {
            "sw1": _device_config(
                networks=[
                    {"name": "corp", "subnet": "10.0.1.0/24"},
                    {"name": "guest", "subnet": "10.0.2.0/24"},
                ],
                vrf={
                    "CORP": {"networks": ["corp", "guest"]},
                    "GUEST": {"networks": ["guest"]},
                },
            )
        }
        result = check_vrf_consistency(predicted)
        assert result.status == "error"

    def test_pass_empty_predicted(self):
        """Empty predicted config dict -> skipped (no VRFs)."""
        result = check_vrf_consistency({})
        assert result.status == "skipped"


# ---------------------------------------------------------------------------
# L3-05  WAN failover impact
# ---------------------------------------------------------------------------


class TestWanFailoverImpact:
    def test_skipped_no_gateways(self):
        """No gateway devices in configs -> skipped."""
        baseline = {"sw1": _device_config(device_type="switch")}
        predicted = {"sw1": _device_config(device_type="switch")}
        result = check_wan_failover_impact(baseline, predicted)
        assert result.check_id == "L3-05"
        assert result.layer == 3
        assert result.status == "skipped"

    def test_skipped_no_wan_interfaces(self):
        """Gateway has no WAN port_config entries -> skipped."""
        baseline = {
            "gw1": _device_config(
                device_type="gateway",
                port_config={"ge-0/0/0": {"usage": "lan", "ip": "10.0.0.1"}},
            )
        }
        predicted = {
            "gw1": _device_config(
                device_type="gateway",
                port_config={"ge-0/0/0": {"usage": "lan", "ip": "10.0.0.1"}},
            )
        }
        result = check_wan_failover_impact(baseline, predicted)
        assert result.status == "skipped"

    def test_pass_wan_unchanged(self):
        """WAN interface config is identical -> pass."""
        port_cfg = {
            "ge-0/0/0": {"usage": "wan", "wan_type": "broadband", "priority": 0},
            "ge-0/0/1": {"usage": "wan", "wan_type": "lte", "priority": 1},
        }
        baseline = {"gw1": _device_config(device_type="gateway", port_config=port_cfg)}
        predicted = {"gw1": _device_config(device_type="gateway", port_config=port_cfg)}
        result = check_wan_failover_impact(baseline, predicted)
        assert result.status == "pass"

    def test_warning_wan_link_disabled(self):
        """Primary WAN link disabled in predicted config -> warning."""
        baseline = {
            "gw1": _device_config(
                device_type="gateway",
                port_config={
                    "ge-0/0/0": {"usage": "wan", "wan_type": "broadband", "disabled": False, "priority": 0},
                },
            )
        }
        predicted = {
            "gw1": _device_config(
                device_type="gateway",
                port_config={
                    "ge-0/0/0": {"usage": "wan", "wan_type": "broadband", "disabled": True, "priority": 0},
                },
            )
        }
        result = check_wan_failover_impact(baseline, predicted)
        assert result.status == "warning"
        assert result.remediation_hint is not None

    def test_warning_wan_priority_changed(self):
        """WAN interface priority changed -> warning."""
        baseline = {
            "gw1": _device_config(
                device_type="gateway",
                port_config={
                    "ge-0/0/0": {"usage": "wan", "wan_type": "broadband", "priority": 0},
                },
            )
        }
        predicted = {
            "gw1": _device_config(
                device_type="gateway",
                port_config={
                    "ge-0/0/0": {"usage": "wan", "wan_type": "broadband", "priority": 5},
                },
            )
        }
        result = check_wan_failover_impact(baseline, predicted)
        assert result.status == "warning"

    def test_warning_wan_link_removed(self):
        """WAN interface removed in predicted config -> warning."""
        baseline = {
            "gw1": _device_config(
                device_type="gateway",
                port_config={
                    "ge-0/0/0": {"usage": "wan", "wan_type": "broadband", "priority": 0},
                    "ge-0/0/1": {"usage": "wan", "wan_type": "lte", "priority": 1},
                },
            )
        }
        predicted = {
            "gw1": _device_config(
                device_type="gateway",
                port_config={
                    "ge-0/0/1": {"usage": "wan", "wan_type": "lte", "priority": 1},
                },
            )
        }
        result = check_wan_failover_impact(baseline, predicted)
        assert result.status == "warning"

    def test_pass_empty_configs(self):
        """Empty configs -> skipped."""
        result = check_wan_failover_impact({}, {})
        assert result.status == "skipped"
