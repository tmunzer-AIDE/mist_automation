"""
Unit tests for site_snapshot: dataclasses, extraction helpers, and snapshot builder.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.modules.digital_twin.services.site_snapshot import (
    DeviceSnapshot,
    LiveSiteData,
    SiteSnapshot,
    _build_device_snapshot,
    _extract_client_count,
    _extract_lldp_from_stats,
    _extract_port_devices,
    _extract_port_status,
    build_site_snapshot,
)

# ---------------------------------------------------------------------------
# TestDeviceSnapshot
# ---------------------------------------------------------------------------


class TestDeviceSnapshot:
    def test_switch_construction(self):
        ds = DeviceSnapshot(
            device_id="dev-1",
            mac="aabbccddeeff",
            name="switch-1",
            type="switch",
            model="EX4100-48T",
            port_config={"ge-0/0/0": {"usage": "trunk", "vlan_id": 100}},
            ip_config={"mgmt": {"ip": "10.0.0.1", "netmask": "255.255.255.0"}},
            dhcpd_config={"enabled": True},
        )
        assert ds.device_id == "dev-1"
        assert ds.type == "switch"
        assert ds.port_config["ge-0/0/0"]["usage"] == "trunk"
        assert ds.oob_ip_config is None
        assert ds.ospf_config is None
        assert ds.bgp_config is None
        assert ds.extra_routes is None
        assert ds.stp_config is None
        assert ds.port_usages is None

    def test_gateway_construction(self):
        ds = DeviceSnapshot(
            device_id="gw-1",
            mac="112233445566",
            name="gateway-1",
            type="gateway",
            model="SRX300",
            port_config={"ge-0/0/0": {"usage": "wan", "wan_type": "broadband"}},
            ip_config={"wan": {"ip": "192.168.1.1", "netmask": "255.255.255.0", "type": "static"}},
            dhcpd_config={"enabled": False},
            oob_ip_config={"ip": "10.10.10.1", "netmask": "255.255.255.0"},
            ospf_config={"enabled": True, "areas": {"0": {"networks": {"10.0.0.0/24": {}}}}},
            bgp_config={"local_as": 65000},
            extra_routes={"0.0.0.0/0": {"via": "192.168.1.254"}},
        )
        assert ds.type == "gateway"
        assert ds.oob_ip_config is not None
        assert ds.ospf_config["enabled"] is True
        assert ds.bgp_config["local_as"] == 65000


# ---------------------------------------------------------------------------
# TestLiveSiteData
# ---------------------------------------------------------------------------


class TestLiveSiteData:
    def test_construction_with_defaults(self):
        ld = LiveSiteData(
            lldp_neighbors={"mac1": {"ge-0/0/0": "mac2"}},
            port_status={"mac1": {"ge-0/0/0": True}},
            ap_clients={"ap-1": 5},
            port_devices={"mac1": {"ge-0/0/0": "mac2"}},
        )
        assert ld.lldp_neighbors["mac1"]["ge-0/0/0"] == "mac2"
        assert ld.ospf_peers == {}
        assert ld.bgp_peers == {}

    def test_construction_with_all_fields(self):
        ld = LiveSiteData(
            lldp_neighbors={},
            port_status={},
            ap_clients={},
            port_devices={},
            ospf_peers={"gw-1": [{"neighbor": "10.0.0.2", "state": "full"}]},
            bgp_peers={"gw-1": [{"neighbor": "10.0.0.3", "state": "established"}]},
        )
        assert len(ld.ospf_peers["gw-1"]) == 1
        assert len(ld.bgp_peers["gw-1"]) == 1


# ---------------------------------------------------------------------------
# TestSiteSnapshot
# ---------------------------------------------------------------------------


class TestSiteSnapshot:
    def test_construction(self):
        dev = DeviceSnapshot(
            device_id="dev-1",
            mac="aabb",
            name="sw1",
            type="switch",
            model="EX4100",
            port_config={},
            ip_config={},
            dhcpd_config={},
        )
        snap = SiteSnapshot(
            site_id="site-1",
            site_name="HQ",
            site_setting={"vars": {"gw_ip": "10.0.0.1"}},
            networks={"net-1": {"name": "mgmt", "vlan_id": 100}},
            wlans={"wlan-1": {"ssid": "Corp"}},
            devices={"dev-1": dev},
            port_usages={"trunk": {"mode": "trunk"}},
            lldp_neighbors={},
            port_status={},
            ap_clients={},
            port_devices={},
        )
        assert snap.site_id == "site-1"
        assert snap.site_name == "HQ"
        assert "dev-1" in snap.devices
        assert snap.devices["dev-1"].name == "sw1"
        assert snap.ospf_peers == {}
        assert snap.bgp_peers == {}


# ---------------------------------------------------------------------------
# TestExtractLldpFromStats
# ---------------------------------------------------------------------------


class TestExtractLldpFromStats:
    def test_happy_path_multiple_ports(self):
        stats = {
            "clients": [
                {"source": "lldp", "mac": "aabb", "port_ids": ["ge-0/0/0", "ge-0/0/1"]},
                {"source": "lldp", "mac": "ccdd", "port_ids": ["ge-0/0/2"]},
            ]
        }
        result = _extract_lldp_from_stats(stats)
        assert result == {"ge-0/0/0": "aabb", "ge-0/0/1": "aabb", "ge-0/0/2": "ccdd"}

    def test_empty_clients(self):
        assert _extract_lldp_from_stats({"clients": []}) == {}
        assert _extract_lldp_from_stats({}) == {}

    def test_empty_mac_skip(self):
        stats = {"clients": [{"source": "lldp", "mac": "", "port_ids": ["ge-0/0/0"]}]}
        assert _extract_lldp_from_stats(stats) == {}

    def test_non_lldp_clients_ignored(self):
        stats = {"clients": [{"source": "arp", "mac": "aabb", "port_ids": ["ge-0/0/0"]}]}
        assert _extract_lldp_from_stats(stats) == {}

    def test_empty_port_ids(self):
        stats = {"clients": [{"source": "lldp", "mac": "aabb", "port_ids": []}]}
        assert _extract_lldp_from_stats(stats) == {}


# ---------------------------------------------------------------------------
# TestExtractPortStatus
# ---------------------------------------------------------------------------


class TestExtractPortStatus:
    def test_happy_path(self):
        stats = {
            "if_stat": {
                "ge-0/0/0": {"up": True, "speed": 1000},
                "ge-0/0/1": {"up": False, "speed": 0},
            }
        }
        result = _extract_port_status(stats)
        assert result == {"ge-0/0/0": True, "ge-0/0/1": False}

    def test_empty_if_stat(self):
        assert _extract_port_status({"if_stat": {}}) == {}
        assert _extract_port_status({"if_stat": None}) == {}
        assert _extract_port_status({}) == {}

    def test_non_dict_entries_skipped(self):
        stats = {"if_stat": {"ge-0/0/0": {"up": True}, "bad": "string"}}
        result = _extract_port_status(stats)
        assert result == {"ge-0/0/0": True}

    def test_missing_up_defaults_false(self):
        stats = {"if_stat": {"ge-0/0/0": {"speed": 1000}}}
        result = _extract_port_status(stats)
        assert result == {"ge-0/0/0": False}


# ---------------------------------------------------------------------------
# TestExtractClientCount
# ---------------------------------------------------------------------------


class TestExtractClientCount:
    def test_from_num_clients(self):
        assert _extract_client_count({"num_clients": 42}) == 42

    def test_zero_when_missing(self):
        assert _extract_client_count({}) == 0

    def test_zero_when_none(self):
        assert _extract_client_count({"num_clients": None}) == 0

    def test_zero_when_zero(self):
        assert _extract_client_count({"num_clients": 0}) == 0


# ---------------------------------------------------------------------------
# TestExtractPortDevices
# ---------------------------------------------------------------------------


class TestExtractPortDevices:
    def test_happy_path(self):
        stats = {
            "clients": [
                {"mac": "aabb", "port_ids": ["ge-0/0/0"]},
                {"mac": "ccdd", "port_ids": ["ge-0/0/1"]},
            ]
        }
        result = _extract_port_devices(stats)
        assert result == {"ge-0/0/0": "aabb", "ge-0/0/1": "ccdd"}

    def test_empty_mac_skip(self):
        stats = {"clients": [{"mac": "", "port_ids": ["ge-0/0/0"]}]}
        assert _extract_port_devices(stats) == {}


# ---------------------------------------------------------------------------
# TestBuildDeviceSnapshot
# ---------------------------------------------------------------------------


class TestBuildDeviceSnapshot:
    def test_from_switch_config(self):
        config = {
            "id": "dev-1",
            "mac": "aabb",
            "name": "sw1",
            "type": "switch",
            "model": "EX4100",
            "port_config": {"ge-0/0/0": {"usage": "trunk"}},
            "ip_config": {"mgmt": {"ip": "10.0.0.1"}},
            "dhcpd_config": {"enabled": True},
        }
        ds = _build_device_snapshot(config)
        assert ds.device_id == "dev-1"
        assert ds.ip_config == {"mgmt": {"ip": "10.0.0.1"}}

    def test_ip_configs_plural(self):
        """Gateways use ip_configs (plural)."""
        config = {
            "id": "gw-1",
            "mac": "ccdd",
            "name": "gw1",
            "type": "gateway",
            "model": "SRX300",
            "port_config": {},
            "ip_configs": {"wan": {"ip": "1.2.3.4", "type": "static"}},
            "dhcpd_config": {},
        }
        ds = _build_device_snapshot(config)
        assert ds.ip_config == {"wan": {"ip": "1.2.3.4", "type": "static"}}

    def test_ip_config_preferred_over_ip_configs(self):
        """ip_config (singular) takes precedence when both exist."""
        config = {
            "id": "dev-1",
            "mac": "aabb",
            "name": "x",
            "type": "switch",
            "model": "X",
            "port_config": {},
            "ip_config": {"a": {"ip": "1.1.1.1"}},
            "ip_configs": {"b": {"ip": "2.2.2.2"}},
            "dhcpd_config": {},
        }
        ds = _build_device_snapshot(config)
        assert "a" in ds.ip_config

    def test_missing_optional_fields(self):
        config = {"id": "dev-1", "mac": "aa", "name": "x", "type": "switch", "model": "X"}
        ds = _build_device_snapshot(config)
        assert ds.port_config == {}
        assert ds.ip_config == {}
        assert ds.dhcpd_config == {}
        assert ds.oob_ip_config is None
        assert ds.ospf_config is None


# ---------------------------------------------------------------------------
# TestBuildSiteSnapshot
# ---------------------------------------------------------------------------


class TestBuildSiteSnapshot:
    @pytest.fixture
    def live_data(self):
        return LiveSiteData(
            lldp_neighbors={"mac1": {"ge-0/0/0": "mac2"}},
            port_status={"mac1": {"ge-0/0/0": True}},
            ap_clients={"ap-1": 5},
            port_devices={"mac1": {"ge-0/0/0": "mac2"}},
        )

    @pytest.fixture
    def mock_backup_data(self):
        """Return value for each _load_site_objects call in the gather."""
        return {
            # devices
            ("devices", "site-1"): [
                {
                    "id": "dev-1",
                    "mac": "aabb",
                    "name": "sw1",
                    "type": "switch",
                    "model": "EX4100",
                    "port_config": {"ge-0/0/0": {"usage": "trunk"}},
                    "ip_config": {"mgmt": {"ip": "10.0.0.1"}},
                    "dhcpd_config": {},
                }
            ],
            # site networks
            ("networks", "site-1"): [{"id": "net-1", "name": "mgmt", "vlan_id": 100}],
            # org networks
            ("networks", None): [{"id": "org-net-1", "name": "corp", "vlan_id": 200}],
            # wlans
            ("wlans", "site-1"): [{"id": "wlan-1", "ssid": "Corp"}],
            # site_setting
            ("site_setting", "site-1"): [
                {"port_usages": {"trunk": {"mode": "trunk", "all_networks": True}}}
            ],
            # site info
            ("site", "site-1"): [{"name": "HQ Office"}],
        }

    async def test_build_from_backup(self, live_data, mock_backup_data):
        async def mock_load(org_id, object_type, site_id=None):
            return mock_backup_data.get((object_type, site_id), [])

        with patch(
            "app.modules.digital_twin.services.site_snapshot._load_site_objects",
            side_effect=mock_load,
        ):
            snap = await build_site_snapshot("site-1", "org-1", live_data)

        assert snap.site_id == "site-1"
        assert snap.site_name == "HQ Office"
        assert "dev-1" in snap.devices
        assert snap.devices["dev-1"].type == "switch"
        assert "net-1" in snap.networks
        assert "org-net-1" in snap.networks  # org-level inherited
        assert "wlan-1" in snap.wlans
        assert snap.port_usages["trunk"]["mode"] == "trunk"
        assert snap.lldp_neighbors == live_data.lldp_neighbors
        assert snap.ap_clients == live_data.ap_clients

    async def test_state_overrides_replace_backup(self, live_data, mock_backup_data):
        overrides = {
            ("devices", "site-1", "dev-1"): {
                "id": "dev-1",
                "mac": "aabb",
                "name": "sw1-MODIFIED",
                "type": "switch",
                "model": "EX4100",
                "port_config": {"ge-0/0/0": {"usage": "access", "vlan_id": 999}},
                "ip_config": {},
                "dhcpd_config": {},
            }
        }

        async def mock_load(org_id, object_type, site_id=None):
            return mock_backup_data.get((object_type, site_id), [])

        with patch(
            "app.modules.digital_twin.services.site_snapshot._load_site_objects",
            side_effect=mock_load,
        ):
            snap = await build_site_snapshot("site-1", "org-1", live_data, state_overrides=overrides)

        assert snap.devices["dev-1"].name == "sw1-MODIFIED"
        assert snap.devices["dev-1"].port_config["ge-0/0/0"]["vlan_id"] == 999

    async def test_empty_backup(self, live_data):
        async def mock_load(org_id, object_type, site_id=None):
            return []

        with patch(
            "app.modules.digital_twin.services.site_snapshot._load_site_objects",
            side_effect=mock_load,
        ):
            snap = await build_site_snapshot("site-1", "org-1", live_data)

        assert snap.site_name == ""
        assert snap.devices == {}
        assert snap.networks == {}
        assert snap.wlans == {}
        assert snap.port_usages == {}

    async def test_site_networks_override_org_networks(self, live_data):
        """Site-level networks should override org-level with the same ID."""

        async def mock_load(org_id, object_type, site_id=None):
            if object_type == "networks" and site_id is None:
                return [{"id": "shared-net", "name": "org-version", "vlan_id": 100}]
            if object_type == "networks" and site_id == "site-1":
                return [{"id": "shared-net", "name": "site-version", "vlan_id": 200}]
            if object_type == "site":
                return [{"name": "Test"}]
            return []

        with patch(
            "app.modules.digital_twin.services.site_snapshot._load_site_objects",
            side_effect=mock_load,
        ):
            snap = await build_site_snapshot("site-1", "org-1", live_data)

        assert snap.networks["shared-net"]["name"] == "site-version"
        assert snap.networks["shared-net"]["vlan_id"] == 200
