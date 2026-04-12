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
    _load_site_objects,
    _normalize_mac,
    build_site_snapshot,
    fetch_live_data,
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
    def test_from_clients_stats_total(self):
        assert _extract_client_count({"clients_stats": {"total": 17}}) == 17

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
# TestLoadSiteObjects
# ---------------------------------------------------------------------------


class TestLoadSiteObjects:
    async def test_org_networks_use_org_level_only_filter(self):
        captured: dict[str, object] = {}

        async def fake_loader(org_id, object_type, site_id=None, org_level_only=False):
            captured["org_id"] = org_id
            captured["object_type"] = object_type
            captured["site_id"] = site_id
            captured["org_level_only"] = org_level_only
            return []

        with patch(
            "app.modules.digital_twin.services.site_snapshot.load_all_objects_of_type",
            side_effect=fake_loader,
        ):
            await _load_site_objects("org-1", "networks")

        assert captured["org_id"] == "org-1"
        assert captured["object_type"] == "networks"
        assert captured["site_id"] is None
        assert captured["org_level_only"] is True

    async def test_site_scoped_networks_do_not_use_org_only_filter(self):
        captured: dict[str, object] = {}

        async def fake_loader(org_id, object_type, site_id=None, org_level_only=False):
            captured["org_id"] = org_id
            captured["object_type"] = object_type
            captured["site_id"] = site_id
            captured["org_level_only"] = org_level_only
            return []

        with patch(
            "app.modules.digital_twin.services.site_snapshot.load_all_objects_of_type",
            side_effect=fake_loader,
        ):
            await _load_site_objects("org-1", "networks", site_id="site-1")

        assert captured["org_id"] == "org-1"
        assert captured["object_type"] == "networks"
        assert captured["site_id"] == "site-1"
        assert captured["org_level_only"] is False


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
            # settings
            ("settings", "site-1"): [{"port_usages": {"trunk": {"mode": "trunk", "all_networks": True}}}],
            # site info
            ("info", "site-1"): [{"name": "HQ Office"}],
        }

    async def test_build_from_backup(self, live_data, mock_backup_data):
        async def mock_load(_org_id, object_type, site_id=None):
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

        async def mock_load(_org_id, object_type, site_id=None):
            return mock_backup_data.get((object_type, site_id), [])

        with patch(
            "app.modules.digital_twin.services.site_snapshot._load_site_objects",
            side_effect=mock_load,
        ):
            snap = await build_site_snapshot("site-1", "org-1", live_data, state_overrides=overrides)

        assert snap.devices["dev-1"].name == "sw1-MODIFIED"
        assert snap.devices["dev-1"].port_config["ge-0/0/0"]["vlan_id"] == 999

    async def test_empty_backup(self, live_data):
        async def mock_load(_org_id, _object_type, site_id=None):
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

        async def mock_load(_org_id, object_type, site_id=None):
            if object_type == "networks" and site_id is None:
                return [{"id": "shared-net", "name": "org-version", "vlan_id": 100}]
            if object_type == "networks" and site_id == "site-1":
                return [{"id": "shared-net", "name": "site-version", "vlan_id": 200}]
            if object_type == "info":
                return [{"name": "Test"}]
            return []

        with patch(
            "app.modules.digital_twin.services.site_snapshot._load_site_objects",
            side_effect=mock_load,
        ):
            snap = await build_site_snapshot("site-1", "org-1", live_data)

        assert snap.networks["shared-net"]["name"] == "site-version"
        assert snap.networks["shared-net"]["vlan_id"] == 200

    async def test_post_override_adds_new_wlan(self, live_data, mock_backup_data):
        overrides = {
            ("wlans", "site-1", "twin-new"): {
                "id": "twin-new",
                "ssid": "Guest",
                "enabled": True,
            }
        }

        async def mock_load(_org_id, object_type, site_id=None):
            return mock_backup_data.get((object_type, site_id), [])

        with patch(
            "app.modules.digital_twin.services.site_snapshot._load_site_objects",
            side_effect=mock_load,
        ):
            snap = await build_site_snapshot("site-1", "org-1", live_data, state_overrides=overrides)

        assert "twin-new" in snap.wlans
        assert snap.wlans["twin-new"]["ssid"] == "Guest"

    async def test_delete_override_removes_existing_wlan(self, live_data, mock_backup_data):
        overrides = {
            ("wlans", "site-1", "wlan-1"): {"__twin_deleted__": True},
        }

        async def mock_load(_org_id, object_type, site_id=None):
            return mock_backup_data.get((object_type, site_id), [])

        with patch(
            "app.modules.digital_twin.services.site_snapshot._load_site_objects",
            side_effect=mock_load,
        ):
            snap = await build_site_snapshot("site-1", "org-1", live_data, state_overrides=overrides)

        assert "wlan-1" not in snap.wlans

    async def test_singleton_settings_override_applied(self, live_data, mock_backup_data):
        overrides = {
            ("settings", "site-1", None): {
                "vars": {"office_vlan": "300"},
                "port_usages": {"access": {"mode": "access", "vlan_id": 300}},
            },
        }

        async def mock_load(_org_id, object_type, site_id=None):
            return mock_backup_data.get((object_type, site_id), [])

        with patch(
            "app.modules.digital_twin.services.site_snapshot._load_site_objects",
            side_effect=mock_load,
        ):
            snap = await build_site_snapshot("site-1", "org-1", live_data, state_overrides=overrides)

        assert snap.site_setting["vars"]["office_vlan"] == "300"
        assert "access" in snap.port_usages

    async def test_org_level_network_override_applied(self, live_data, mock_backup_data):
        overrides = {
            ("networks", None, "org-net-1"): {
                "id": "org-net-1",
                "name": "corp-updated",
                "vlan_id": 222,
            },
        }

        async def mock_load(_org_id, object_type, site_id=None):
            return mock_backup_data.get((object_type, site_id), [])

        with patch(
            "app.modules.digital_twin.services.site_snapshot._load_site_objects",
            side_effect=mock_load,
        ):
            snap = await build_site_snapshot("site-1", "org-1", live_data, state_overrides=overrides)

        assert snap.networks["org-net-1"]["name"] == "corp-updated"

    async def test_networks_filtered_by_assigned_templates(self, live_data):
        """Only networks referenced by the site's assigned templates should appear."""
        org_nets = [
            # Referenced by the assigned network template
            {"id": "n-corp", "name": "corp", "subnet": "10.1.0.0/24", "vlan_id": 100},
            # Unrelated to this site's template — belongs to a DIFFERENT network template
            {"id": "n-dplm", "name": "DNT-E2E-DPLM", "subnet": "10.10.10.0/24"},
            {"id": "n-mxe", "name": "PRD-MXE-data-0", "subnet": "10.10.10.0/24"},
        ]
        net_templates = [
            {
                "id": "nt-this-site",
                "name": "SiteNT",
                # The inline `networks` dict is keyed by name with override fragments
                "networks": {"corp": {"vlan_id": 100}, "guest": {"vlan_id": 200}},
            },
            {
                "id": "nt-other",
                "name": "OtherNT",
                "networks": {"DNT-E2E-DPLM": {}, "PRD-MXE-data-0": {}},
            },
        ]

        async def mock_load(_org_id, object_type, site_id=None):
            if object_type == "networks" and site_id is None:
                return org_nets
            if object_type == "networktemplates":
                return net_templates
            return []

        async def mock_site_info(_org_id, _site_id):
            return {"name": "DNT-E2E", "networktemplate_id": "nt-this-site"}

        with (
            patch(
                "app.modules.digital_twin.services.site_snapshot._load_site_objects",
                side_effect=mock_load,
            ),
            patch(
                "app.modules.digital_twin.services.site_snapshot._load_site_info_config",
                side_effect=mock_site_info,
            ),
        ):
            snap = await build_site_snapshot("site-1", "org-1", live_data)

        # Only the assigned template's referenced org network is included.
        names = {n.get("name") for n in snap.networks.values()}
        assert names == {"corp"}
        # The unrelated networks causing the false CFG-SUBNET overlap must NOT appear.
        assert "DNT-E2E-DPLM" not in names
        assert "PRD-MXE-data-0" not in names

    async def test_template_override_merged_into_network(self, live_data):
        """The assigned network template's override fragment is merged over the org network."""
        org_nets = [{"id": "n-corp", "name": "corp", "subnet": "10.1.0.0/24", "vlan_id": 50}]
        net_templates = [
            {
                "id": "nt-1",
                "networks": {"corp": {"vlan_id": 100}},
            }
        ]

        async def mock_load(_org_id, object_type, site_id=None):
            if object_type == "networks" and site_id is None:
                return org_nets
            if object_type == "networktemplates":
                return net_templates
            return []

        async def mock_site_info(_org_id, _site_id):
            return {"name": "Site1", "networktemplate_id": "nt-1"}

        with (
            patch(
                "app.modules.digital_twin.services.site_snapshot._load_site_objects",
                side_effect=mock_load,
            ),
            patch(
                "app.modules.digital_twin.services.site_snapshot._load_site_info_config",
                side_effect=mock_site_info,
            ),
        ):
            snap = await build_site_snapshot("site-1", "org-1", live_data)

        assert snap.networks["n-corp"]["vlan_id"] == 100  # override won over org value 50
        assert snap.networks["n-corp"]["subnet"] == "10.1.0.0/24"  # org-level field preserved


# ---------------------------------------------------------------------------
# TestNormalizeMac
# ---------------------------------------------------------------------------


class TestNormalizeMac:
    def test_lowercase_plain(self):
        assert _normalize_mac("485a0dea2e00") == "485a0dea2e00"

    def test_uppercase_with_colons(self):
        assert _normalize_mac("48:5A:0D:EA:2E:00") == "485a0dea2e00"

    def test_with_dashes(self):
        assert _normalize_mac("48-5a-0d-ea-2e-00") == "485a0dea2e00"

    def test_empty(self):
        assert _normalize_mac("") == ""

    def test_none(self):
        assert _normalize_mac(None) == ""


# ---------------------------------------------------------------------------
# TestFetchLiveData
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, data, status_code: int = 200):
        self.data = data
        self.status_code = status_code


class TestFetchLiveData:
    async def test_port_stats_populate_switch_lldp(self):
        """searchSiteSwOrGwPorts drives LLDP neighbours for switches/gateways."""
        org_stats_resp = _FakeResp(
            [
                {
                    "id": "sw-1",
                    "mac": "485a0dea2e00",
                    "type": "switch",
                    # No clients[] LLDP — the switch path must come from port_stats.
                    "clients_stats": {"total": 0},
                }
            ]
        )
        port_stats_resp = _FakeResp(
            [
                {
                    "mac": "48:5A:0D:EA:2E:00",  # upper-cased + separators — must be normalized
                    "port_id": "ge-0/0/9",
                    "neighbor_mac": "5c:5b:35:11:22:33",
                    "up": True,
                },
                {
                    "mac": "485a0dea2e00",
                    "port_id": "ge-0/0/10",
                    "neighbor_mac": "",
                    "up": False,
                },
            ]
        )

        async def fake_arun(fn, *args, **kwargs):
            name = getattr(fn, "__name__", "")
            if name == "listOrgDevicesStats":
                return org_stats_resp
            if name == "searchSiteSwOrGwPorts":
                return port_stats_resp
            raise AssertionError(f"unexpected call: {name}")

        class _FakeMist:
            def get_session(self):
                return object()

        async def fake_factory():
            return _FakeMist()

        with (
            patch("mistapi.arun", side_effect=fake_arun),
            patch(
                "app.services.mist_service_factory.create_mist_service",
                side_effect=fake_factory,
            ),
        ):
            live = await fetch_live_data("site-1", "org-1")

        # LLDP neighbour found via port_stats, keyed by normalized dev mac
        assert live.lldp_neighbors == {"485a0dea2e00": {"ge-0/0/9": "5c5b35112233"}}
        # Port status covers both the up and the down port
        assert live.port_status == {"485a0dea2e00": {"ge-0/0/9": True, "ge-0/0/10": False}}
        # port_devices mirrors LLDP edges (no entry for ge-0/0/10 since no neighbour)
        assert live.port_devices == {"485a0dea2e00": {"ge-0/0/9": "5c5b35112233"}}

    async def test_no_lldp_warning_when_l2_present(self):
        """Emit live_data_no_lldp warning when stats+ports return no LLDP for a switch site."""
        from unittest.mock import MagicMock

        org_stats_resp = _FakeResp([{"id": "sw-1", "mac": "aa11", "type": "switch"}])
        port_stats_resp = _FakeResp([])  # no port records

        async def fake_arun(fn, *args, **kwargs):
            name = getattr(fn, "__name__", "")
            if name == "listOrgDevicesStats":
                return org_stats_resp
            if name == "searchSiteSwOrGwPorts":
                return port_stats_resp
            raise AssertionError(f"unexpected call: {name}")

        class _FakeMist:
            def get_session(self):
                return object()

        async def fake_factory():
            return _FakeMist()

        fake_logger = MagicMock()
        with (
            patch(
                "app.modules.digital_twin.services.site_snapshot.logger",
                fake_logger,
            ),
            patch("mistapi.arun", side_effect=fake_arun),
            patch(
                "app.services.mist_service_factory.create_mist_service",
                side_effect=fake_factory,
            ),
        ):
            live = await fetch_live_data("site-1", "org-1")

        assert live.lldp_neighbors == {}
        warning_events = [call.args[0] for call in fake_logger.warning.call_args_list]
        assert "live_data_no_lldp" in warning_events
