"""Unit tests for Switch DHCP metric extraction."""

import pytest

from app.modules.telemetry.extractors.switch_extractor import extract_points

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _switch_payload_with_dhcp():
    return {
        "mac": "aabbccddeeff",
        "name": "SW-HQ-01",
        "model": "EX2300-48P",
        "type": "switch",
        "last_seen": 1774576960,
        "_time": 1774576960.0,
        "cpu_stat": {"idle": 85},
        "memory_stat": {"usage": 42},
        "uptime": 86400,
        "dhcpd_stat": {
            "Corp-LAN": {"num_ips": 200, "num_leased": 130},
            "Guest-WiFi": {"num_ips": 50, "num_leased": 20},
        },
    }


def _switch_payload_without_dhcp():
    return {
        "mac": "aabbccddeeff",
        "name": "SW-HQ-01",
        "model": "EX2300-48P",
        "type": "switch",
        "last_seen": 1774576960,
        "_time": 1774576960.0,
        "cpu_stat": {"idle": 85},
        "memory_stat": {"usage": 42},
        "uptime": 86400,
    }


# ---------------------------------------------------------------------------
# Tests: switch_dhcp
# ---------------------------------------------------------------------------


class TestSwitchDhcp:
    """Switch DHCP extraction from dhcpd_stat."""

    def test_switch_dhcp_produces_one_point_per_scope(self):
        points = extract_points(_switch_payload_with_dhcp(), "org1", "site1")
        dhcp_points = [p for p in points if p["measurement"] == "switch_dhcp"]
        assert len(dhcp_points) == 2

    def test_switch_dhcp_fields_correct(self):
        points = extract_points(_switch_payload_with_dhcp(), "org1", "site1")
        corp = next(p for p in points if p.get("tags", {}).get("network_name") == "Corp-LAN")
        assert corp["fields"]["num_ips"] == 200
        assert corp["fields"]["num_leased"] == 130
        assert corp["fields"]["utilization_pct"] == pytest.approx(65.0, abs=0.1)

    def test_switch_dhcp_guest_fields(self):
        points = extract_points(_switch_payload_with_dhcp(), "org1", "site1")
        guest = next(p for p in points if p.get("tags", {}).get("network_name") == "Guest-WiFi")
        assert guest["fields"]["num_ips"] == 50
        assert guest["fields"]["num_leased"] == 20
        assert guest["fields"]["utilization_pct"] == pytest.approx(40.0, abs=0.1)

    def test_switch_dhcp_tags(self):
        points = extract_points(_switch_payload_with_dhcp(), "org1", "site1")
        corp = next(p for p in points if p.get("tags", {}).get("network_name") == "Corp-LAN")
        assert corp["tags"]["org_id"] == "org1"
        assert corp["tags"]["site_id"] == "site1"
        assert corp["tags"]["mac"] == "aabbccddeeff"
        assert corp["tags"]["network_name"] == "Corp-LAN"

    def test_switch_dhcp_time(self):
        points = extract_points(_switch_payload_with_dhcp(), "org1", "site1")
        dhcp_points = [p for p in points if p["measurement"] == "switch_dhcp"]
        for p in dhcp_points:
            assert p["time"] == 1774576960

    def test_switch_dhcp_absent_produces_no_points(self):
        points = extract_points(_switch_payload_without_dhcp(), "org1", "site1")
        dhcp_points = [p for p in points if p["measurement"] == "switch_dhcp"]
        assert dhcp_points == []

    def test_switch_dhcp_zero_ips_gives_zero_utilization(self):
        payload = _switch_payload_with_dhcp()
        payload["dhcpd_stat"] = {"Empty-Net": {"num_ips": 0, "num_leased": 0}}
        points = extract_points(payload, "org1", "site1")
        dhcp = next(p for p in points if p["measurement"] == "switch_dhcp")
        assert dhcp["fields"]["utilization_pct"] == 0.0

    def test_switch_dhcp_measurement_name(self):
        points = extract_points(_switch_payload_with_dhcp(), "org1", "site1")
        dhcp_points = [p for p in points if p["measurement"] == "switch_dhcp"]
        assert all(p["measurement"] == "switch_dhcp" for p in dhcp_points)
