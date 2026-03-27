"""Unit tests for Switch metric extractor."""

from app.modules.telemetry.extractors.switch_extractor import extract_points

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _full_switch_payload() -> dict:
    """Realistic full-stats switch payload."""
    return {
        "mac": "112233445566",
        "name": "SW-Floor2-01",
        "hostname": "SW-Floor2-01",
        "type": "switch",
        "cpu_stat": {"idle": 85},
        "memory_stat": {"usage": 62},
        "clients_stats": {"total": {"num_wired_clients": 24}},
        "uptime": 172800,
        "last_seen": 1774576960,
        "_time": 1774576960.5,
        "if_stat": {
            "ge-0/0/0.0": {
                "port_id": "ge-0/0/0",
                "up": True,
                "tx_pkts": 1234567,
                "rx_pkts": 7654321,
            },
            "ge-0/0/1.0": {
                "port_id": "ge-0/0/1",
                "up": True,
                "tx_pkts": 111,
                "rx_pkts": 222,
            },
            "ge-0/0/2.0": {
                "port_id": "ge-0/0/2",
                "up": False,
                "tx_pkts": 0,
                "rx_pkts": 0,
            },
        },
        "module_stat": [
            {
                "_idx": 0,
                "temperatures": [
                    {"celsius": 45.0, "name": "CPU"},
                    {"celsius": 52.0, "name": "PHY"},
                    {"celsius": 38.0, "name": "Ambient"},
                ],
                "poe": {"power_draw": 120.5, "max_power": 370.0},
                "vc_role": "master",
                "vc_links": [{"neighbor_idx": 1, "status": "Up"}],
                "memory_stat": {"usage": 58},
            },
            {
                "_idx": 1,
                "temperatures": [
                    {"celsius": 43.0, "name": "CPU"},
                    {"celsius": 50.0, "name": "PHY"},
                ],
                "poe": {"power_draw": 95.0, "max_power": 370.0},
                "vc_role": "backup",
                "vc_links": [{"neighbor_idx": 0, "status": "Up"}],
                "memory_stat": {"usage": 55},
            },
        ],
    }


def _switch_payload_no_module_stat() -> dict:
    """Switch payload without module_stat (standalone, no VC)."""
    payload = _full_switch_payload()
    del payload["module_stat"]
    return payload


def _switch_payload_clients_fallback() -> dict:
    """Switch payload using clients list instead of clients_stats."""
    payload = _full_switch_payload()
    del payload["clients_stats"]
    payload["clients"] = [{"mac": "aa:bb:cc:dd:ee:01"}, {"mac": "aa:bb:cc:dd:ee:02"}]
    return payload


def _switch_payload_no_poe() -> dict:
    """Switch payload with module_stat but no PoE data."""
    payload = _full_switch_payload()
    for mod in payload["module_stat"]:
        del mod["poe"]
    return payload


# ---------------------------------------------------------------------------
# Tests: device_summary
# ---------------------------------------------------------------------------


class TestSwitchDeviceSummary:
    """Switch payload produces a device_summary point."""

    def test_device_summary_present(self):
        points = extract_points(_full_switch_payload(), "org-1", "site-1")
        summaries = [p for p in points if p["measurement"] == "device_summary"]
        assert len(summaries) == 1

    def test_device_summary_tags(self):
        points = extract_points(_full_switch_payload(), "org-1", "site-1")
        summary = next(p for p in points if p["measurement"] == "device_summary")
        assert summary["tags"]["org_id"] == "org-1"
        assert summary["tags"]["site_id"] == "site-1"
        assert summary["tags"]["mac"] == "112233445566"
        assert summary["tags"]["device_type"] == "switch"
        assert summary["tags"]["name"] == "SW-Floor2-01"

    def test_device_summary_fields(self):
        points = extract_points(_full_switch_payload(), "org-1", "site-1")
        summary = next(p for p in points if p["measurement"] == "device_summary")
        fields = summary["fields"]
        # cpu_util = 100 - cpu_stat.idle = 100 - 85 = 15
        assert fields["cpu_util"] == 15
        assert fields["mem_usage"] == 62
        assert fields["num_clients"] == 24
        assert fields["uptime"] == 172800
        # poe_draw_total = 120.5 + 95.0 = 215.5
        assert fields["poe_draw_total"] == 215.5
        # poe_max_total = 370.0 + 370.0 = 740.0
        assert fields["poe_max_total"] == 740.0

    def test_device_summary_time(self):
        points = extract_points(_full_switch_payload(), "org-1", "site-1")
        summary = next(p for p in points if p["measurement"] == "device_summary")
        assert summary["time"] == 1774576960

    def test_num_clients_fallback_to_clients_list(self):
        points = extract_points(_switch_payload_clients_fallback(), "org-1", "site-1")
        summary = next(p for p in points if p["measurement"] == "device_summary")
        assert summary["fields"]["num_clients"] == 2

    def test_poe_totals_zero_when_no_module_stat(self):
        points = extract_points(_switch_payload_no_module_stat(), "org-1", "site-1")
        summary = next(p for p in points if p["measurement"] == "device_summary")
        assert summary["fields"]["poe_draw_total"] == 0
        assert summary["fields"]["poe_max_total"] == 0

    def test_poe_totals_zero_when_no_poe_in_modules(self):
        points = extract_points(_switch_payload_no_poe(), "org-1", "site-1")
        summary = next(p for p in points if p["measurement"] == "device_summary")
        assert summary["fields"]["poe_draw_total"] == 0
        assert summary["fields"]["poe_max_total"] == 0

    def test_name_falls_back_to_hostname(self):
        payload = _full_switch_payload()
        del payload["name"]
        points = extract_points(payload, "org-1", "site-1")
        summary = next(p for p in points if p["measurement"] == "device_summary")
        assert summary["tags"]["name"] == "SW-Floor2-01"

    def test_empty_payload_returns_device_summary_with_defaults(self):
        points = extract_points({"mac": "deadbeef0000"}, "org-1", "site-1")
        summaries = [p for p in points if p["measurement"] == "device_summary"]
        assert len(summaries) == 1
        assert summaries[0]["fields"]["cpu_util"] == 0


# ---------------------------------------------------------------------------
# Tests: port_stats
# ---------------------------------------------------------------------------


class TestSwitchPortStats:
    """Switch payload produces port_stats points for UP ports only."""

    def test_only_up_ports_included(self):
        points = extract_points(_full_switch_payload(), "org-1", "site-1")
        ports = [p for p in points if p["measurement"] == "port_stats"]
        # ge-0/0/0 up, ge-0/0/1 up, ge-0/0/2 down => 2 points
        assert len(ports) == 2

    def test_port_stats_tags(self):
        points = extract_points(_full_switch_payload(), "org-1", "site-1")
        ports = [p for p in points if p["measurement"] == "port_stats"]
        port_ids = {p["tags"]["port_id"] for p in ports}
        assert port_ids == {"ge-0/0/0", "ge-0/0/1"}
        for port in ports:
            assert port["tags"]["org_id"] == "org-1"
            assert port["tags"]["site_id"] == "site-1"
            assert port["tags"]["mac"] == "112233445566"

    def test_port_stats_fields(self):
        points = extract_points(_full_switch_payload(), "org-1", "site-1")
        port0 = next(p for p in points if p["measurement"] == "port_stats" and p["tags"]["port_id"] == "ge-0/0/0")
        fields = port0["fields"]
        assert fields["up"] is True
        assert fields["tx_pkts"] == 1234567
        assert fields["rx_pkts"] == 7654321

    def test_port_stats_time(self):
        points = extract_points(_full_switch_payload(), "org-1", "site-1")
        ports = [p for p in points if p["measurement"] == "port_stats"]
        for port in ports:
            assert port["time"] == 1774576960

    def test_no_if_stat_produces_no_port_stats(self):
        payload = _full_switch_payload()
        del payload["if_stat"]
        points = extract_points(payload, "org-1", "site-1")
        ports = [p for p in points if p["measurement"] == "port_stats"]
        assert ports == []


# ---------------------------------------------------------------------------
# Tests: module_stats
# ---------------------------------------------------------------------------


class TestSwitchModuleStats:
    """Switch payload produces module_stats points per VC member."""

    def test_two_module_points(self):
        points = extract_points(_full_switch_payload(), "org-1", "site-1")
        modules = [p for p in points if p["measurement"] == "module_stats"]
        assert len(modules) == 2

    def test_module_stats_tags(self):
        points = extract_points(_full_switch_payload(), "org-1", "site-1")
        modules = [p for p in points if p["measurement"] == "module_stats"]
        fpc_indices = {p["tags"]["fpc_idx"] for p in modules}
        assert fpc_indices == {"0", "1"}
        for mod in modules:
            assert mod["tags"]["org_id"] == "org-1"
            assert mod["tags"]["site_id"] == "site-1"
            assert mod["tags"]["mac"] == "112233445566"

    def test_module_stats_fields_member_0(self):
        points = extract_points(_full_switch_payload(), "org-1", "site-1")
        mod0 = next(p for p in points if p["measurement"] == "module_stats" and p["tags"]["fpc_idx"] == "0")
        fields = mod0["fields"]
        # temp_max = max(45.0, 52.0, 38.0) = 52.0
        assert fields["temp_max"] == 52.0
        assert fields["poe_draw"] == 120.5
        assert fields["vc_role"] == "master"
        assert fields["vc_links_count"] == 1
        assert fields["mem_usage"] == 58

    def test_module_stats_fields_member_1(self):
        points = extract_points(_full_switch_payload(), "org-1", "site-1")
        mod1 = next(p for p in points if p["measurement"] == "module_stats" and p["tags"]["fpc_idx"] == "1")
        fields = mod1["fields"]
        assert fields["temp_max"] == 50.0
        assert fields["poe_draw"] == 95.0
        assert fields["vc_role"] == "backup"
        assert fields["vc_links_count"] == 1
        assert fields["mem_usage"] == 55

    def test_module_stats_time(self):
        points = extract_points(_full_switch_payload(), "org-1", "site-1")
        modules = [p for p in points if p["measurement"] == "module_stats"]
        for mod in modules:
            assert mod["time"] == 1774576960

    def test_no_module_stat_produces_no_module_stats(self):
        points = extract_points(_switch_payload_no_module_stat(), "org-1", "site-1")
        modules = [p for p in points if p["measurement"] == "module_stats"]
        assert modules == []

    def test_empty_temperatures_gives_zero_temp_max(self):
        payload = _full_switch_payload()
        payload["module_stat"][0]["temperatures"] = []
        points = extract_points(payload, "org-1", "site-1")
        mod0 = next(p for p in points if p["measurement"] == "module_stats" and p["tags"]["fpc_idx"] == "0")
        assert mod0["fields"]["temp_max"] == 0
