"""
Unit tests for routing checks (ROUTE-GW, ROUTE-OSPF, ROUTE-BGP, ROUTE-WAN).

These checks compare baseline vs predicted SiteSnapshot objects.
"""

from __future__ import annotations

from app.modules.digital_twin.checks.routing import check_routing
from app.modules.digital_twin.services.site_snapshot import DeviceSnapshot, SiteSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dev(dev_id: str, mac: str, name: str, dtype: str = "switch", **kw) -> DeviceSnapshot:
    return DeviceSnapshot(
        device_id=dev_id,
        mac=mac,
        name=name,
        type=dtype,
        model="SRX345" if dtype == "gateway" else "EX4100",
        port_config=kw.get("port_config", {}),
        ip_config=kw.get("ip_config", {}),
        dhcpd_config=kw.get("dhcpd_config", {}),
        port_usages=kw.get("port_usages"),
        ospf_config=kw.get("ospf_config"),
        bgp_config=kw.get("bgp_config"),
        stp_config=kw.get("stp_config"),
        extra_routes=kw.get("extra_routes"),
    )


def _snap(
    devices=None,
    lldp=None,
    networks=None,
    wlans=None,
    port_usages=None,
    site_setting=None,
    ap_clients=None,
    port_status=None,
    port_devices=None,
    ospf_peers=None,
    bgp_peers=None,
) -> SiteSnapshot:
    return SiteSnapshot(
        site_id="site-1",
        site_name="Test Site",
        site_setting=site_setting or {},
        networks=networks or {},
        wlans=wlans or {},
        devices=devices or {},
        port_usages=port_usages or {},
        lldp_neighbors=lldp or {},
        port_status=port_status or {},
        ap_clients=ap_clients or {},
        port_devices=port_devices or {},
        ospf_peers=ospf_peers or {},
        bgp_peers=bgp_peers or {},
    )


def _get_result(results, check_id):
    """Extract a specific check result by check_id."""
    for r in results:
        if r.check_id == check_id:
            return r
    return None


# ---------------------------------------------------------------------------
# TestRouteGw
# ---------------------------------------------------------------------------


class TestRouteGw:
    def test_network_without_gateway_error(self):
        """A network with no gateway ip_config entry should produce an error."""
        baseline = _snap(
            networks={"net-1": {"name": "Corp", "subnet": "10.0.0.0/24", "vlan_id": 10}},
            devices={
                "gw-1": _dev(
                    "gw-1",
                    "aa:bb:cc:dd:ee:01",
                    "GW-1",
                    dtype="gateway",
                    ip_config={"Corp": {"ip": "10.0.0.1", "netmask": "255.255.255.0", "type": "static"}},
                ),
            },
        )
        predicted = _snap(
            networks={"net-1": {"name": "Corp", "subnet": "10.0.0.0/24", "vlan_id": 10}},
            devices={
                "gw-1": _dev(
                    "gw-1",
                    "aa:bb:cc:dd:ee:01",
                    "GW-1",
                    dtype="gateway",
                    ip_config={},  # Gateway L3 interface removed
                ),
            },
        )
        results = check_routing(baseline, predicted)
        r = _get_result(results, "ROUTE-GW")
        assert r is not None
        assert r.status == "error"
        assert len(r.details) == 1
        assert "Corp" in r.details[0]
        assert "no gateway L3 interface" in r.details[0]

    def test_all_networks_have_gateway_passes(self):
        """All networks covered by gateway ip_config should pass."""
        baseline = _snap(
            networks={
                "net-1": {"name": "Corp", "subnet": "10.0.0.0/24", "vlan_id": 10},
                "net-2": {"name": "Guest", "subnet": "10.0.1.0/24", "vlan_id": 20},
            },
            devices={
                "gw-1": _dev(
                    "gw-1",
                    "aa:bb:cc:dd:ee:01",
                    "GW-1",
                    dtype="gateway",
                    ip_config={
                        "Corp": {"ip": "10.0.0.1", "netmask": "255.255.255.0", "type": "static"},
                        "Guest": {"ip": "10.0.1.1", "netmask": "255.255.255.0", "type": "static"},
                    },
                ),
            },
        )
        predicted = _snap(
            networks={
                "net-1": {"name": "Corp", "subnet": "10.0.0.0/24", "vlan_id": 10},
                "net-2": {"name": "Guest", "subnet": "10.0.1.0/24", "vlan_id": 20},
            },
            devices={
                "gw-1": _dev(
                    "gw-1",
                    "aa:bb:cc:dd:ee:01",
                    "GW-1",
                    dtype="gateway",
                    ip_config={
                        "Corp": {"ip": "10.0.0.1", "netmask": "255.255.255.0", "type": "static"},
                        "Guest": {"ip": "10.0.1.1", "netmask": "255.255.255.0", "type": "static"},
                    },
                ),
            },
        )
        results = check_routing(baseline, predicted)
        r = _get_result(results, "ROUTE-GW")
        assert r is not None
        assert r.status == "pass"

    def test_no_networks_passes(self):
        """An empty network list should pass (not applicable)."""
        baseline = _snap()
        predicted = _snap()
        results = check_routing(baseline, predicted)
        r = _get_result(results, "ROUTE-GW")
        assert r is not None
        assert r.status == "pass"

    def test_multiple_missing_networks(self):
        """Multiple networks without gateway coverage should all be listed."""
        predicted = _snap(
            networks={
                "net-1": {"name": "Corp", "subnet": "10.0.0.0/24"},
                "net-2": {"name": "Guest", "subnet": "10.0.1.0/24"},
            },
            devices={
                "gw-1": _dev("gw-1", "aa:bb:cc:dd:ee:01", "GW-1", dtype="gateway", ip_config={}),
            },
        )
        baseline = _snap()
        results = check_routing(baseline, predicted)
        r = _get_result(results, "ROUTE-GW")
        assert r.status == "error"
        assert len(r.details) == 2


# ---------------------------------------------------------------------------
# TestRouteOspf
# ---------------------------------------------------------------------------


class TestRouteOspf:
    def test_adjacency_break_when_ip_changes(self):
        """OSPF peer becomes unreachable when the interface subnet changes."""
        baseline = _snap(
            devices={
                "gw-1": _dev(
                    "gw-1",
                    "aa:bb:cc:dd:ee:01",
                    "GW-1",
                    dtype="gateway",
                    ip_config={"Corp": {"ip": "10.0.0.1", "netmask": "255.255.255.0"}},
                ),
            },
            ospf_peers={
                "gw-1": [{"peer_ip": "10.0.0.2"}],
            },
        )
        predicted = _snap(
            devices={
                "gw-1": _dev(
                    "gw-1",
                    "aa:bb:cc:dd:ee:01",
                    "GW-1",
                    dtype="gateway",
                    ip_config={"Corp": {"ip": "192.168.1.1", "netmask": "255.255.255.0"}},
                ),
            },
        )
        results = check_routing(baseline, predicted)
        r = _get_result(results, "ROUTE-OSPF")
        assert r is not None
        assert r.status == "critical"
        assert len(r.details) == 1
        assert "10.0.0.2" in r.details[0]

    def test_no_peers_passes(self):
        """No OSPF peers in baseline should produce a pass."""
        baseline = _snap()
        predicted = _snap()
        results = check_routing(baseline, predicted)
        r = _get_result(results, "ROUTE-OSPF")
        assert r is not None
        assert r.status == "pass"

    def test_peer_still_reachable_passes(self):
        """OSPF peer that remains within a configured subnet should pass."""
        baseline = _snap(
            devices={
                "gw-1": _dev(
                    "gw-1",
                    "aa:bb:cc:dd:ee:01",
                    "GW-1",
                    dtype="gateway",
                    ip_config={"Corp": {"ip": "10.0.0.1", "netmask": "255.255.255.0"}},
                ),
            },
            ospf_peers={
                "gw-1": [{"peer_ip": "10.0.0.2"}],
            },
        )
        predicted = _snap(
            devices={
                "gw-1": _dev(
                    "gw-1",
                    "aa:bb:cc:dd:ee:01",
                    "GW-1",
                    dtype="gateway",
                    ip_config={"Corp": {"ip": "10.0.0.1", "netmask": "255.255.255.0"}},
                ),
            },
        )
        results = check_routing(baseline, predicted)
        r = _get_result(results, "ROUTE-OSPF")
        assert r.status == "pass"


# ---------------------------------------------------------------------------
# TestRouteBgp
# ---------------------------------------------------------------------------


class TestRouteBgp:
    def test_adjacency_break_critical(self):
        """BGP peer becomes unreachable when the interface subnet changes."""
        baseline = _snap(
            devices={
                "gw-1": _dev(
                    "gw-1",
                    "aa:bb:cc:dd:ee:01",
                    "GW-1",
                    dtype="gateway",
                    ip_config={"WAN": {"ip": "203.0.113.1", "netmask": "255.255.255.252"}},
                ),
            },
            bgp_peers={
                "gw-1": [{"peer_ip": "203.0.113.2"}],
            },
        )
        predicted = _snap(
            devices={
                "gw-1": _dev(
                    "gw-1",
                    "aa:bb:cc:dd:ee:01",
                    "GW-1",
                    dtype="gateway",
                    ip_config={"WAN": {"ip": "198.51.100.1", "netmask": "255.255.255.252"}},
                ),
            },
        )
        results = check_routing(baseline, predicted)
        r = _get_result(results, "ROUTE-BGP")
        assert r is not None
        assert r.status == "critical"
        assert "203.0.113.2" in r.details[0]

    def test_no_bgp_peers_passes(self):
        """No BGP peers in baseline should produce a pass."""
        baseline = _snap()
        predicted = _snap()
        results = check_routing(baseline, predicted)
        r = _get_result(results, "ROUTE-BGP")
        assert r is not None
        assert r.status == "pass"

    def test_peer_still_reachable_passes(self):
        """BGP peer still within a configured subnet should pass."""
        baseline = _snap(
            devices={
                "gw-1": _dev(
                    "gw-1",
                    "aa:bb:cc:dd:ee:01",
                    "GW-1",
                    dtype="gateway",
                    ip_config={"WAN": {"ip": "203.0.113.1", "netmask": "255.255.255.252"}},
                ),
            },
            bgp_peers={
                "gw-1": [{"peer_ip": "203.0.113.2"}],
            },
        )
        predicted = _snap(
            devices={
                "gw-1": _dev(
                    "gw-1",
                    "aa:bb:cc:dd:ee:01",
                    "GW-1",
                    dtype="gateway",
                    ip_config={"WAN": {"ip": "203.0.113.1", "netmask": "255.255.255.252"}},
                ),
            },
        )
        results = check_routing(baseline, predicted)
        r = _get_result(results, "ROUTE-BGP")
        assert r.status == "pass"


# ---------------------------------------------------------------------------
# TestRouteWan
# ---------------------------------------------------------------------------


class TestRouteWan:
    def test_wan_link_removed_warning(self):
        """Removing a single WAN link should produce a warning."""
        baseline = _snap(
            devices={
                "gw-1": _dev(
                    "gw-1",
                    "aa:bb:cc:dd:ee:01",
                    "GW-1",
                    dtype="gateway",
                    port_config={
                        "ge-0/0/0": {"usage": "wan", "wan_type": "broadband"},
                        "ge-0/0/1": {"usage": "wan", "wan_type": "lte"},
                    },
                ),
            },
        )
        predicted = _snap(
            devices={
                "gw-1": _dev(
                    "gw-1",
                    "aa:bb:cc:dd:ee:01",
                    "GW-1",
                    dtype="gateway",
                    port_config={
                        "ge-0/0/0": {"usage": "wan", "wan_type": "broadband"},
                        # ge-0/0/1 WAN link removed
                    },
                ),
            },
        )
        results = check_routing(baseline, predicted)
        r = _get_result(results, "ROUTE-WAN")
        assert r is not None
        assert r.status == "warning"
        assert len(r.details) == 1
        assert "ge-0/0/1" in r.details[0]
        assert "lte" in r.details[0]

    def test_multiple_wan_removed_error(self):
        """Removing multiple WAN links should produce an error."""
        baseline = _snap(
            devices={
                "gw-1": _dev(
                    "gw-1",
                    "aa:bb:cc:dd:ee:01",
                    "GW-1",
                    dtype="gateway",
                    port_config={
                        "ge-0/0/0": {"usage": "wan", "wan_type": "broadband"},
                        "ge-0/0/1": {"usage": "wan", "wan_type": "lte"},
                    },
                ),
            },
        )
        predicted = _snap(
            devices={
                "gw-1": _dev(
                    "gw-1",
                    "aa:bb:cc:dd:ee:01",
                    "GW-1",
                    dtype="gateway",
                    port_config={},  # Both WAN links removed
                ),
            },
        )
        results = check_routing(baseline, predicted)
        r = _get_result(results, "ROUTE-WAN")
        assert r.status == "error"
        assert len(r.details) == 2

    def test_no_change_passes(self):
        """No WAN link changes should pass."""
        devices = {
            "gw-1": _dev(
                "gw-1",
                "aa:bb:cc:dd:ee:01",
                "GW-1",
                dtype="gateway",
                port_config={
                    "ge-0/0/0": {"usage": "wan", "wan_type": "broadband"},
                    "ge-0/0/1": {"usage": "wan", "wan_type": "lte"},
                },
            ),
        }
        baseline = _snap(devices=devices)
        predicted = _snap(devices=devices)
        results = check_routing(baseline, predicted)
        r = _get_result(results, "ROUTE-WAN")
        assert r is not None
        assert r.status == "pass"

    def test_non_gateway_ignored(self):
        """WAN ports on non-gateway devices should not be checked."""
        baseline = _snap(
            devices={
                "sw-1": _dev(
                    "sw-1",
                    "aa:bb:cc:dd:ee:01",
                    "SW-1",
                    dtype="switch",
                    port_config={"ge-0/0/0": {"usage": "wan", "wan_type": "broadband"}},
                ),
            },
        )
        predicted = _snap(
            devices={
                "sw-1": _dev(
                    "sw-1",
                    "aa:bb:cc:dd:ee:01",
                    "SW-1",
                    dtype="switch",
                    port_config={},
                ),
            },
        )
        results = check_routing(baseline, predicted)
        r = _get_result(results, "ROUTE-WAN")
        assert r.status == "pass"


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestCheckRoutingIntegration:
    def test_returns_four_results(self):
        """check_routing always returns exactly 4 CheckResult items."""
        baseline = _snap()
        predicted = _snap()
        results = check_routing(baseline, predicted)
        assert len(results) == 4
        ids = {r.check_id for r in results}
        assert ids == {"ROUTE-GW", "ROUTE-OSPF", "ROUTE-BGP", "ROUTE-WAN"}

    def test_all_pass_on_empty_snapshot(self):
        """An empty snapshot pair should produce all-pass results."""
        baseline = _snap()
        predicted = _snap()
        results = check_routing(baseline, predicted)
        for r in results:
            assert r.status == "pass", f"{r.check_id} should pass on empty snapshot but got {r.status}"
