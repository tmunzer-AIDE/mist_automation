"""Unit tests for predicted topology builder."""

import pytest

from app.modules.digital_twin.services.predicted_topology import build_synthetic_raw_data
from app.modules.impact_analysis.topology.client import RawSiteData


@pytest.mark.unit
class TestBuildSyntheticRawData:
    def test_extracts_devices_from_virtual_state(self):
        virtual_state = {
            ("devices", "s1", "dev-1"): {
                "id": "dev-1", "name": "SW1", "mac": "aabbcc001122",
                "type": "switch", "port_config": {"ge-0/0/0": {"usage": "lan"}},
            },
            ("devices", "s1", "dev-2"): {
                "id": "dev-2", "name": "GW1", "mac": "aabbcc003344", "type": "gateway",
            },
        }
        raw = build_synthetic_raw_data("s1", virtual_state)
        assert isinstance(raw, RawSiteData)
        assert len(raw.devices) == 2

    def test_extracts_site_setting(self):
        virtual_state = {
            ("setting", "s1", None): {"vars": {"vlan": "100"}, "networks": {"LAN": {"vlan_id": 100}}},
        }
        raw = build_synthetic_raw_data("s1", virtual_state)
        assert raw.site_setting.get("vars", {}).get("vlan") == "100"

    def test_extracts_networks_as_org_networks(self):
        virtual_state = {
            ("networks", "s1", "net-1"): {"name": "Staff", "subnet": "10.0.0.0/24", "vlan_id": 100},
            ("networks", None, "net-2"): {"name": "Guest", "subnet": "10.0.1.0/24", "vlan_id": 200},
        }
        raw = build_synthetic_raw_data("s1", virtual_state)
        assert len(raw.org_networks) >= 1

    def test_filters_by_site_id(self):
        virtual_state = {
            ("devices", "s1", "dev-1"): {"id": "dev-1", "name": "SW1", "mac": "aa"},
            ("devices", "s2", "dev-2"): {"id": "dev-2", "name": "SW2", "mac": "bb"},
        }
        raw = build_synthetic_raw_data("s1", virtual_state)
        assert len(raw.devices) == 1

    def test_empty_state_returns_empty_raw_data(self):
        raw = build_synthetic_raw_data("s1", {})
        assert raw.devices == []
        assert raw.port_stats == []
