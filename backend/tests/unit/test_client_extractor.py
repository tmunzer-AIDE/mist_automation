# backend/tests/unit/test_client_extractor.py
"""Unit tests for wireless client metric extractor."""

from app.modules.telemetry.extractors.client_extractor import extract_points


def _psk_payload() -> dict:
    """PSK wireless client payload."""
    return {
        "mac": "10521c42ce5f",
        "site_id": "d6fb4f96-3ba4-4cf5-8af2-a8d7b85087ac",
        "ap_mac": "04a92439fb75",
        "ssid": "MlN",
        "band": "24",
        "channel": 11,
        "key_mgmt": "WPA2-PSK/CCMP",
        "psk_id": "505d68f7-5e4e-4c95-bcab-a64dabe82437",
        "username": "",
        "hostname": "iot-light-off",
        "ip": "10.3.8.26",
        "manufacture": "Espressif Inc.",
        "family": "",
        "model": "",
        "os": "",
        "os_version": "",
        "group": "iot",
        "vlan_id": "8",
        "proto": "n",
        "rssi": -30,
        "snr": 69,
        "idle_time": 2.0,
        "tx_rate": 65.0,
        "rx_rate": 54.0,
        "tx_pkts": 51839,
        "rx_pkts": 6081,
        "tx_bytes": 7059192,
        "rx_bytes": 601929,
        "tx_retries": 145236,
        "rx_retries": 215,
        "tx_bps": 375,
        "rx_bps": 0,
        "dual_band": False,
        "is_guest": False,
        "uptime": 47887,
        "last_seen": 1774924326,
        "_ttl": 300,
    }


def _eap_payload() -> dict:
    """802.1X (EAP) wireless client payload."""
    return {
        "mac": "c889f3bb55dc",
        "site_id": "ac9c6dda-52a5-4804-b40c-bef61dbdb609",
        "ap_mac": "c8786708bb5d",
        "ssid": "easy_nac",
        "band": "5",
        "channel": 44,
        "key_mgmt": "WPA3-EAP-SHA256/CCMP",
        "psk_id": "",
        "username": "ndusch@juniper.net",
        "hostname": "ndusch-mbp",
        "ip": "192.168.230.40",
        "manufacture": "Apple",
        "family": "Mac",
        "model": 'MBP 14" M1 2021',
        "os": "macOS",
        "os_version": "26.4 (Build 25E246)",
        "group": "sales",
        "vlan_id": "230",
        "airespace_ifname": "vlansales",
        "proto": "ax",
        "rssi": -51,
        "snr": 47,
        "idle_time": 24.0,
        "tx_rate": 243.7,
        "rx_rate": 24.0,
        "tx_pkts": 2054654,
        "rx_pkts": 547675,
        "tx_bytes": 5234706013,
        "rx_bytes": 271501853,
        "tx_retries": 171087,
        "rx_retries": 5316,
        "tx_bps": 0,
        "rx_bps": 0,
        "dual_band": False,
        "is_guest": False,
        "uptime": 39422,
        "last_seen": 1774925612,
        "_ttl": 300,
    }


class TestExtractPoints:
    def test_returns_one_point_per_client(self):
        points = extract_points(_psk_payload(), "org123", "site456")
        assert len(points) == 1

    def test_measurement_name(self):
        points = extract_points(_psk_payload(), "org123", "site456")
        assert points[0]["measurement"] == "client_stats"

    def test_tags_psk_client(self):
        points = extract_points(_psk_payload(), "org123", "site456")
        tags = points[0]["tags"]
        assert tags["org_id"] == "org123"
        assert tags["site_id"] == "site456"
        assert tags["mac"] == "10521c42ce5f"
        assert tags["ap_mac"] == "04a92439fb75"
        assert tags["ssid"] == "MlN"
        assert tags["band"] == "24"
        assert tags["auth_type"] == "psk"

    def test_tags_eap_client(self):
        points = extract_points(_eap_payload(), "org123", "site456")
        tags = points[0]["tags"]
        assert tags["auth_type"] == "eap"
        assert tags["band"] == "5"

    def test_numeric_fields(self):
        points = extract_points(_psk_payload(), "org123", "site456")
        fields = points[0]["fields"]
        assert fields["rssi"] == -30
        assert fields["snr"] == 69
        assert fields["channel"] == 11
        assert fields["tx_bps"] == 375
        assert fields["rx_bps"] == 0
        assert fields["tx_bytes"] == 7059192
        assert fields["uptime"] == 47887

    def test_string_fields(self):
        points = extract_points(_psk_payload(), "org123", "site456")
        fields = points[0]["fields"]
        assert fields["hostname"] == "iot-light-off"
        assert fields["manufacture"] == "Espressif Inc."
        assert fields["group"] == "iot"

    def test_eap_username_field(self):
        points = extract_points(_eap_payload(), "org123", "site456")
        fields = points[0]["fields"]
        assert fields["username"] == "ndusch@juniper.net"
        assert fields["airespace_ifname"] == "vlansales"

    def test_boolean_fields_stored_as_int(self):
        points = extract_points(_psk_payload(), "org123", "site456")
        fields = points[0]["fields"]
        assert fields["is_guest"] == 0
        assert fields["dual_band"] == 0

    def test_timestamp_from_last_seen(self):
        points = extract_points(_psk_payload(), "org123", "site456")
        assert points[0]["time"] == 1774924326

    def test_empty_mac_returns_empty(self):
        payload = {**_psk_payload(), "mac": ""}
        assert extract_points(payload, "org123", "site456") == []

    def test_missing_mac_returns_empty(self):
        payload = {k: v for k, v in _psk_payload().items() if k != "mac"}
        assert extract_points(payload, "org123", "site456") == []
