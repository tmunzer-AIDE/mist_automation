"""
Unit tests for config conflict checks (CFG-SUBNET, CFG-VLAN, CFG-SSID, CFG-DHCP-RNG, CFG-DHCP-CFG).

These checks operate on a SiteSnapshot directly (no baseline needed).
"""

from __future__ import annotations

from app.modules.digital_twin.checks.config_conflicts import check_config_conflicts
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
        model="EX4100",
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
# TestCfgSubnet
# ---------------------------------------------------------------------------


class TestCfgSubnet:
    def test_overlap_detected_critical(self):
        """Two overlapping subnets should produce a critical result."""
        snap = _snap(
            networks={
                "net-1": {"name": "Corp", "subnet": "10.0.0.0/24", "vlan_id": 10},
                "net-2": {"name": "Guest", "subnet": "10.0.0.128/25", "vlan_id": 20},
            }
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-SUBNET")
        assert r is not None
        assert r.status == "critical"
        assert len(r.details) == 1
        assert "Corp" in r.details[0]
        assert "Guest" in r.details[0]
        assert r.affected_sites == ["site-1"]

    def test_no_overlap_passes(self):
        """Non-overlapping subnets should pass."""
        snap = _snap(
            networks={
                "net-1": {"name": "Corp", "subnet": "10.0.0.0/24", "vlan_id": 10},
                "net-2": {"name": "Guest", "subnet": "10.0.1.0/24", "vlan_id": 20},
            }
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-SUBNET")
        assert r is not None
        assert r.status == "pass"

    def test_networks_without_subnet_skipped(self):
        """Networks missing the subnet field are silently skipped."""
        snap = _snap(
            networks={
                "net-1": {"name": "Corp", "vlan_id": 10},
                "net-2": {"name": "Guest", "subnet": "10.0.1.0/24", "vlan_id": 20},
            }
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-SUBNET")
        assert r is not None
        assert r.status == "pass"

    def test_supernet_overlap(self):
        """A /16 overlapping with a /24 inside it should be detected."""
        snap = _snap(
            networks={
                "net-1": {"name": "Wide", "subnet": "192.168.0.0/16"},
                "net-2": {"name": "Narrow", "subnet": "192.168.1.0/24"},
            }
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-SUBNET")
        assert r.status == "critical"


# ---------------------------------------------------------------------------
# TestCfgVlan
# ---------------------------------------------------------------------------


class TestCfgVlan:
    def test_collision_detected_error(self):
        """Two networks sharing a VLAN ID should produce an error."""
        snap = _snap(
            networks={
                "net-1": {"name": "Corp", "subnet": "10.0.0.0/24", "vlan_id": 100},
                "net-2": {"name": "Guest", "subnet": "10.0.1.0/24", "vlan_id": 100},
            }
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-VLAN")
        assert r is not None
        assert r.status == "error"
        assert "VLAN 100" in r.details[0]
        assert "Corp" in r.details[0]
        assert "Guest" in r.details[0]
        assert r.affected_sites == ["site-1"]

    def test_no_collision_passes(self):
        """Different VLAN IDs should pass."""
        snap = _snap(
            networks={
                "net-1": {"name": "Corp", "subnet": "10.0.0.0/24", "vlan_id": 100},
                "net-2": {"name": "Guest", "subnet": "10.0.1.0/24", "vlan_id": 200},
            }
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-VLAN")
        assert r is not None
        assert r.status == "pass"

    def test_no_vlan_id_skipped(self):
        """Networks without vlan_id are ignored."""
        snap = _snap(
            networks={
                "net-1": {"name": "Corp", "subnet": "10.0.0.0/24"},
                "net-2": {"name": "Guest", "subnet": "10.0.1.0/24"},
            }
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-VLAN")
        assert r is not None
        assert r.status == "pass"


# ---------------------------------------------------------------------------
# TestCfgSsid
# ---------------------------------------------------------------------------


class TestCfgSsid:
    def test_duplicate_detected_error(self):
        """Two enabled WLANs with the same SSID should produce an error."""
        snap = _snap(
            wlans={
                "wlan-1": {"ssid": "Corporate", "enabled": True},
                "wlan-2": {"ssid": "Corporate", "enabled": True},
            }
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-SSID")
        assert r is not None
        assert r.status == "error"
        assert "Corporate" in r.details[0]
        assert r.affected_sites == ["site-1"]

    def test_disabled_wlan_ignored(self):
        """A disabled WLAN should not count toward duplicates."""
        snap = _snap(
            wlans={
                "wlan-1": {"ssid": "Corporate", "enabled": True},
                "wlan-2": {"ssid": "Corporate", "enabled": False},
            }
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-SSID")
        assert r is not None
        assert r.status == "pass"

    def test_enabled_defaults_to_true(self):
        """WLANs without an explicit 'enabled' field default to enabled."""
        snap = _snap(
            wlans={
                "wlan-1": {"ssid": "Corporate"},
                "wlan-2": {"ssid": "Corporate"},
            }
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-SSID")
        assert r is not None
        assert r.status == "error"

    def test_unique_ssids_pass(self):
        """Different SSIDs should pass."""
        snap = _snap(
            wlans={
                "wlan-1": {"ssid": "Corporate", "enabled": True},
                "wlan-2": {"ssid": "Guest", "enabled": True},
            }
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-SSID")
        assert r is not None
        assert r.status == "pass"


# ---------------------------------------------------------------------------
# TestCfgDhcp
# ---------------------------------------------------------------------------


class TestCfgDhcp:
    def test_range_overlap_detected(self):
        """Overlapping DHCP ranges across two devices should produce an error."""
        snap = _snap(
            devices={
                "dev-1": _dev(
                    "dev-1",
                    "aa:bb:cc:dd:ee:01",
                    "SW-1",
                    dhcpd_config={
                        "enabled": True,
                        "Corp": {
                            "type": "local",
                            "ip_start": "10.0.0.10",
                            "ip_end": "10.0.0.100",
                        },
                    },
                ),
                "dev-2": _dev(
                    "dev-2",
                    "aa:bb:cc:dd:ee:02",
                    "SW-2",
                    dhcpd_config={
                        "enabled": True,
                        "Corp": {
                            "type": "local",
                            "ip_start": "10.0.0.50",
                            "ip_end": "10.0.0.150",
                        },
                    },
                ),
            }
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-DHCP-RNG")
        assert r is not None
        assert r.status == "error"
        assert len(r.details) == 1
        assert "SW-1" in r.details[0]
        assert "SW-2" in r.details[0]
        assert r.affected_sites == ["site-1"]

    def test_duplicate_shadow_scope_ignored(self):
        """Ignore duplicate DHCP scopes when one shadow copy lacks a device name."""
        snap = _snap(
            devices={
                "dev-gw": _dev(
                    "dev-gw",
                    "aa:bb:cc:dd:ee:01",
                    "DNT-E2E-GW",
                    dtype="gateway",
                    dhcpd_config={
                        "enabled": True,
                        "DNT-E2E-LAN": {
                            "type": "local",
                            "ip_start": "10.42.10.100",
                            "ip_end": "10.42.10.199",
                        },
                    },
                ),
                "dev-shadow": _dev(
                    "dev-shadow",
                    "aa:bb:cc:dd:ee:02",
                    "",
                    dtype="gateway",
                    dhcpd_config={
                        "enabled": True,
                        "DNT-E2E-LAN": {
                            "type": "local",
                            "ip_start": "10.42.10.100",
                            "ip_end": "10.42.10.199",
                        },
                    },
                ),
            }
        )

        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-DHCP-RNG")
        assert r is not None
        assert r.status == "pass"

    def test_same_device_gateway_and_alias_keys_are_deduplicated(self):
        """Do not self-overlap when the same gateway DHCP scope appears under alias keys.

        Example seen in real payloads:
        - "GW-NAME/LAN"
        - "/LAN"
        """
        snap = _snap(
            devices={
                "dev-gw": _dev(
                    "dev-gw",
                    "aa:bb:cc:dd:ee:03",
                    "DNT-E2E-GW",
                    dtype="gateway",
                    dhcpd_config={
                        "enabled": True,
                        "DNT-E2E-GW/DNT-E2E-LAN": {
                            "type": "local",
                            "ip_start": "10.42.10.100",
                            "ip_end": "10.42.10.199",
                        },
                        "/DNT-E2E-LAN": {
                            "type": "local",
                            "ip_start": "10.42.10.100",
                            "ip_end": "10.42.10.199",
                        },
                    },
                ),
            }
        )

        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-DHCP-RNG")
        assert r is not None
        assert r.status == "pass"

    def test_non_overlapping_ranges_pass(self):
        """Non-overlapping DHCP ranges should pass."""
        snap = _snap(
            devices={
                "dev-1": _dev(
                    "dev-1",
                    "aa:bb:cc:dd:ee:01",
                    "SW-1",
                    dhcpd_config={
                        "enabled": True,
                        "Corp": {
                            "type": "local",
                            "ip_start": "10.0.0.10",
                            "ip_end": "10.0.0.50",
                        },
                    },
                ),
                "dev-2": _dev(
                    "dev-2",
                    "aa:bb:cc:dd:ee:02",
                    "SW-2",
                    dhcpd_config={
                        "enabled": True,
                        "Guest": {
                            "type": "local",
                            "ip_start": "10.0.1.10",
                            "ip_end": "10.0.1.50",
                        },
                    },
                ),
            }
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-DHCP-RNG")
        assert r is not None
        assert r.status == "pass"

    def test_disabled_dhcp_skipped(self):
        """DHCP configs with enabled=False should be skipped."""
        snap = _snap(
            devices={
                "dev-1": _dev(
                    "dev-1",
                    "aa:bb:cc:dd:ee:01",
                    "SW-1",
                    dhcpd_config={
                        "enabled": False,
                        "Corp": {
                            "type": "local",
                            "ip_start": "10.0.0.10",
                            "ip_end": "10.0.0.100",
                        },
                    },
                ),
                "dev-2": _dev(
                    "dev-2",
                    "aa:bb:cc:dd:ee:02",
                    "SW-2",
                    dhcpd_config={
                        "enabled": False,
                        "Corp": {
                            "type": "local",
                            "ip_start": "10.0.0.50",
                            "ip_end": "10.0.0.150",
                        },
                    },
                ),
            }
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-DHCP-RNG")
        assert r is not None
        assert r.status == "pass"

    def test_relay_type_skipped(self):
        """DHCP configs with type='relay' should be skipped."""
        snap = _snap(
            devices={
                "dev-1": _dev(
                    "dev-1",
                    "aa:bb:cc:dd:ee:01",
                    "SW-1",
                    dhcpd_config={
                        "enabled": True,
                        "Corp": {
                            "type": "relay",
                            "ip_start": "10.0.0.10",
                            "ip_end": "10.0.0.100",
                        },
                    },
                ),
            }
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-DHCP-RNG")
        assert r is not None
        assert r.status == "pass"

    def test_dhcp_misconfiguration_gateway_outside_subnet(self):
        """Gateway outside subnet should be flagged."""
        snap = _snap(
            networks={
                "net-1": {"name": "Corp", "subnet": "10.0.0.0/24", "vlan_id": 10},
            },
            devices={
                "dev-1": _dev(
                    "dev-1",
                    "aa:bb:cc:dd:ee:01",
                    "SW-1",
                    dhcpd_config={
                        "enabled": True,
                        "Corp": {
                            "type": "local",
                            "ip_start": "10.0.0.10",
                            "ip_end": "10.0.0.100",
                            "gateway": "192.168.1.1",
                        },
                    },
                ),
            },
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-DHCP-CFG")
        assert r is not None
        assert r.status == "error"
        assert "gateway" in r.details[0]
        assert "outside" in r.details[0]
        assert r.affected_sites == ["site-1"]

    def test_dhcp_misconfiguration_range_outside_subnet(self):
        """ip_start or ip_end outside the network subnet should be flagged."""
        snap = _snap(
            networks={
                "net-1": {"name": "Corp", "subnet": "10.0.0.0/24", "vlan_id": 10},
            },
            devices={
                "dev-1": _dev(
                    "dev-1",
                    "aa:bb:cc:dd:ee:01",
                    "SW-1",
                    dhcpd_config={
                        "enabled": True,
                        "Corp": {
                            "type": "local",
                            "ip_start": "10.0.0.10",
                            "ip_end": "10.0.1.100",
                            "gateway": "10.0.0.1",
                        },
                    },
                ),
            },
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-DHCP-CFG")
        assert r is not None
        assert r.status == "error"
        assert "ip_end" in r.details[0]
        assert "outside" in r.details[0]

    def test_dhcp_config_all_within_subnet_passes(self):
        """All DHCP addresses within subnet should pass."""
        snap = _snap(
            networks={
                "net-1": {"name": "Corp", "subnet": "10.0.0.0/24", "vlan_id": 10},
            },
            devices={
                "dev-1": _dev(
                    "dev-1",
                    "aa:bb:cc:dd:ee:01",
                    "SW-1",
                    dhcpd_config={
                        "enabled": True,
                        "Corp": {
                            "type": "local",
                            "ip_start": "10.0.0.10",
                            "ip_end": "10.0.0.100",
                            "gateway": "10.0.0.1",
                        },
                    },
                ),
            },
        )
        results = check_config_conflicts(snap)
        r = _get_result(results, "CFG-DHCP-CFG")
        assert r is not None
        assert r.status == "pass"


# ---------------------------------------------------------------------------
# TestCheckConfigConflictsIntegration
# ---------------------------------------------------------------------------


class TestCheckConfigConflictsIntegration:
    def test_returns_five_results(self):
        """check_config_conflicts always returns exactly 5 CheckResult items."""
        snap = _snap()
        results = check_config_conflicts(snap)
        assert len(results) == 5
        ids = {r.check_id for r in results}
        assert ids == {"CFG-SUBNET", "CFG-VLAN", "CFG-SSID", "CFG-DHCP-RNG", "CFG-DHCP-CFG"}

    def test_all_pass_on_empty_snapshot(self):
        """An empty snapshot should produce all-pass results."""
        snap = _snap()
        results = check_config_conflicts(snap)
        for r in results:
            assert r.status == "pass", f"{r.check_id} should pass on empty snapshot but got {r.status}"


# ---------------------------------------------------------------------------
# TestCheckDescriptions
# ---------------------------------------------------------------------------


class TestCheckDescriptions:
    """Every config conflict check must return a non-empty description."""

    def _empty_snap(self) -> SiteSnapshot:
        return _snap()

    def test_cfg_subnet_description_populated(self):
        results = check_config_conflicts(self._empty_snap())
        by_id = {r.check_id: r for r in results}
        assert by_id["CFG-SUBNET"].description != ""

    def test_cfg_vlan_description_populated(self):
        results = check_config_conflicts(self._empty_snap())
        by_id = {r.check_id: r for r in results}
        assert by_id["CFG-VLAN"].description != ""

    def test_cfg_ssid_description_populated(self):
        results = check_config_conflicts(self._empty_snap())
        by_id = {r.check_id: r for r in results}
        assert by_id["CFG-SSID"].description != ""

    def test_cfg_dhcp_rng_description_populated(self):
        results = check_config_conflicts(self._empty_snap())
        by_id = {r.check_id: r for r in results}
        assert by_id["CFG-DHCP-RNG"].description != ""

    def test_cfg_dhcp_cfg_description_populated(self):
        results = check_config_conflicts(self._empty_snap())
        by_id = {r.check_id: r for r in results}
        assert by_id["CFG-DHCP-CFG"].description != ""
