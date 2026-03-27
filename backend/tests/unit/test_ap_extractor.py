"""Unit tests for AP metric extractor."""

from app.modules.telemetry.extractors.ap_extractor import extract_points

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _full_ap_payload() -> dict:
    """Realistic full-stats AP payload (has model + radio_stat)."""
    return {
        "mac": "aabbccddeeff",
        "name": "AP-Lobby-01",
        "model": "AP45",
        "type": "ap",
        "cpu_util": 42,
        "mem_total_kb": 1048576,
        "mem_used_kb": 681574,
        "num_clients": 7,
        "uptime": 86400,
        "last_seen": 1774576960,
        "_time": 1774576960.123,
        "radio_stat": {
            "band_24": {
                "channel": 6,
                "power": 17,
                "bandwidth": 20,
                "util_all": 45,
                "noise_floor": -90,
                "num_clients": 3,
            },
            "band_5": {
                "channel": 36,
                "power": 20,
                "bandwidth": 80,
                "util_all": 30,
                "noise_floor": -95,
                "num_clients": 4,
            },
        },
    }


def _basic_ap_payload() -> dict:
    """Basic AP payload (no model field) -- should be skipped."""
    return {
        "mac": "aabbccddeeff",
        "name": "AP-Lobby-01",
        "uptime": 86400,
        "ip_stat": {"ip": "10.0.0.1"},
        "last_seen": 1774576960,
    }


def _ap_payload_with_disabled_band() -> dict:
    """AP payload where band_6 is disabled."""
    payload = _full_ap_payload()
    payload["radio_stat"]["band_6"] = {
        "channel": 0,
        "power": 0,
        "bandwidth": 0,
        "util_all": 0,
        "noise_floor": 0,
        "num_clients": 0,
        "disabled": True,
    }
    return payload


# ---------------------------------------------------------------------------
# Tests: basic message filtering
# ---------------------------------------------------------------------------


class TestApBasicMessageFiltering:
    """Basic AP messages (no model field) must be skipped."""

    def test_basic_payload_returns_empty_list(self):
        result = extract_points(_basic_ap_payload(), "org-1", "site-1")
        assert result == []

    def test_empty_payload_returns_empty_list(self):
        result = extract_points({}, "org-1", "site-1")
        assert result == []


# ---------------------------------------------------------------------------
# Tests: device_summary extraction
# ---------------------------------------------------------------------------


class TestApDeviceSummary:
    """Full-stats AP payload produces a device_summary point."""

    def test_device_summary_present(self):
        points = extract_points(_full_ap_payload(), "org-1", "site-1")
        summaries = [p for p in points if p["measurement"] == "device_summary"]
        assert len(summaries) == 1

    def test_device_summary_tags(self):
        points = extract_points(_full_ap_payload(), "org-1", "site-1")
        summary = next(p for p in points if p["measurement"] == "device_summary")
        assert summary["tags"]["org_id"] == "org-1"
        assert summary["tags"]["site_id"] == "site-1"
        assert summary["tags"]["mac"] == "aabbccddeeff"
        assert summary["tags"]["device_type"] == "ap"
        assert summary["tags"]["name"] == "AP-Lobby-01"

    def test_device_summary_fields(self):
        points = extract_points(_full_ap_payload(), "org-1", "site-1")
        summary = next(p for p in points if p["measurement"] == "device_summary")
        fields = summary["fields"]
        assert fields["cpu_util"] == 42
        # mem_usage = mem_used_kb / mem_total_kb * 100 = 681574 / 1048576 * 100 ~= 65.0
        assert 64.9 < fields["mem_usage"] < 65.1
        assert fields["num_clients"] == 7
        assert fields["uptime"] == 86400

    def test_device_summary_time_uses_underscore_time(self):
        points = extract_points(_full_ap_payload(), "org-1", "site-1")
        summary = next(p for p in points if p["measurement"] == "device_summary")
        assert summary["time"] == 1774576960

    def test_device_summary_time_falls_back_to_last_seen(self):
        payload = _full_ap_payload()
        del payload["_time"]
        points = extract_points(payload, "org-1", "site-1")
        summary = next(p for p in points if p["measurement"] == "device_summary")
        assert summary["time"] == 1774576960

    def test_mem_usage_handles_zero_total(self):
        payload = _full_ap_payload()
        payload["mem_total_kb"] = 0
        points = extract_points(payload, "org-1", "site-1")
        summary = next(p for p in points if p["measurement"] == "device_summary")
        assert summary["fields"]["mem_usage"] == 0


# ---------------------------------------------------------------------------
# Tests: radio_stats extraction
# ---------------------------------------------------------------------------


class TestApRadioStats:
    """Full-stats AP payload produces radio_stats points per active band."""

    def test_two_radio_points_for_two_bands(self):
        points = extract_points(_full_ap_payload(), "org-1", "site-1")
        radios = [p for p in points if p["measurement"] == "radio_stats"]
        assert len(radios) == 2

    def test_radio_stats_tags_include_band(self):
        points = extract_points(_full_ap_payload(), "org-1", "site-1")
        radios = [p for p in points if p["measurement"] == "radio_stats"]
        bands = {p["tags"]["band"] for p in radios}
        assert bands == {"band_24", "band_5"}
        for radio in radios:
            assert radio["tags"]["org_id"] == "org-1"
            assert radio["tags"]["site_id"] == "site-1"
            assert radio["tags"]["mac"] == "aabbccddeeff"

    def test_radio_stats_fields_band_5(self):
        points = extract_points(_full_ap_payload(), "org-1", "site-1")
        band5 = next(p for p in points if p["measurement"] == "radio_stats" and p["tags"]["band"] == "band_5")
        fields = band5["fields"]
        assert fields["channel"] == 36
        assert fields["power"] == 20
        assert fields["bandwidth"] == 80
        assert fields["util_all"] == 30
        assert fields["noise_floor"] == -95
        assert fields["num_clients"] == 4

    def test_radio_stats_fields_band_24(self):
        points = extract_points(_full_ap_payload(), "org-1", "site-1")
        band24 = next(p for p in points if p["measurement"] == "radio_stats" and p["tags"]["band"] == "band_24")
        fields = band24["fields"]
        assert fields["channel"] == 6
        assert fields["power"] == 17
        assert fields["bandwidth"] == 20
        assert fields["util_all"] == 45
        assert fields["noise_floor"] == -90
        assert fields["num_clients"] == 3

    def test_disabled_band_is_skipped(self):
        points = extract_points(_ap_payload_with_disabled_band(), "org-1", "site-1")
        radios = [p for p in points if p["measurement"] == "radio_stats"]
        bands = {p["tags"]["band"] for p in radios}
        assert "band_6" not in bands
        assert len(radios) == 2

    def test_radio_stats_time(self):
        points = extract_points(_full_ap_payload(), "org-1", "site-1")
        radios = [p for p in points if p["measurement"] == "radio_stats"]
        for radio in radios:
            assert radio["time"] == 1774576960

    def test_missing_radio_stat_key(self):
        payload = _full_ap_payload()
        del payload["radio_stat"]
        points = extract_points(payload, "org-1", "site-1")
        radios = [p for p in points if p["measurement"] == "radio_stats"]
        assert radios == []
