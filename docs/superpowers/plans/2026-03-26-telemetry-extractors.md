# Telemetry Metric Extractors Implementation Plan (Plan 2 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build pure-function extractors that parse raw Mist WebSocket payloads into InfluxDB data points for AP, Switch, and Gateway device types.

**Architecture:** Three extractor modules in `app/modules/telemetry/extractors/`, each with a single `extract_points(payload, org_id, site_id) -> list[dict]` entry point. Gateway extractor handles SRX standalone, SRX cluster, and SSR sub-types with detection logic.

**Tech Stack:** Python 3.10+, pytest

**Spec:** `docs/superpowers/specs/2026-03-26-websocket-telemetry-pipeline-design.md`

**Depends on:** Plan 1 (foundation) -- already implemented.

---

# Plan: Telemetry Metric Extractors (Plan 2)

```
# 2026-03-26-telemetry-extractors.md
#
# Spec: docs/superpowers/specs/2026-03-26-websocket-telemetry-pipeline-design.md
# Scope: Pure-function extractors that parse raw Mist WebSocket payloads into
#         InfluxDB data points. AP, Switch, and Gateway (SRX standalone,
#         SRX cluster, SSR). Tests are all sync (no async needed).
#
# NOTE FOR AGENTIC WORKER:
# Each step below is fully self-contained. Execute them IN ORDER.
# Every step includes exact file paths, complete code, and the shell commands to run.
# Do NOT skip steps. Do NOT combine steps. Commit after each green test.
# Working directory for all commands: cd /Users/tmunzer/4_dev/mist_automation/backend
```

---

## Step 1 -- AP extractor: write failing tests

- [ ] Create test file

**Create file:** `backend/tests/unit/test_ap_extractor.py`

```python
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
```

### Run the failing tests

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_ap_extractor.py -x --no-header -q 2>&1 | tail -5
```

Expected: `ModuleNotFoundError` or `ImportError` since the module does not exist yet.

---

## Step 2 -- AP extractor: implement

- [ ] Create the extractor module

**Create file:** `backend/app/modules/telemetry/extractors/ap_extractor.py`

```python
"""AP metric extractor — parses Mist AP WebSocket payloads into InfluxDB data points.

Produces:
- device_summary: cpu_util, mem_usage, num_clients, uptime (always written)
- radio_stats: per-band channel, power, bandwidth, util_all, noise_floor, num_clients (CoV filtered)
"""

from __future__ import annotations

_BANDS = ("band_24", "band_5", "band_6")


def _get_timestamp(payload: dict) -> int:
    """Extract epoch timestamp, preferring _time over last_seen."""
    raw = payload.get("_time") or payload.get("last_seen") or 0
    return int(raw)


def _extract_device_summary(payload: dict, org_id: str, site_id: str, timestamp: int) -> dict:
    """Build device_summary data point from AP payload."""
    mem_total = payload.get("mem_total_kb", 0)
    mem_used = payload.get("mem_used_kb", 0)
    mem_usage = (mem_used / mem_total * 100) if mem_total > 0 else 0

    return {
        "measurement": "device_summary",
        "tags": {
            "org_id": org_id,
            "site_id": site_id,
            "mac": payload.get("mac", ""),
            "device_type": "ap",
            "name": payload.get("name", ""),
        },
        "fields": {
            "cpu_util": payload.get("cpu_util", 0),
            "mem_usage": round(mem_usage, 1),
            "num_clients": payload.get("num_clients", 0),
            "uptime": payload.get("uptime", 0),
        },
        "time": timestamp,
    }


def _extract_radio_stats(payload: dict, org_id: str, site_id: str, timestamp: int) -> list[dict]:
    """Build radio_stats data points for each active band."""
    radio_stat = payload.get("radio_stat")
    if not radio_stat:
        return []

    points: list[dict] = []
    for band in _BANDS:
        band_data = radio_stat.get(band)
        if not band_data:
            continue
        if band_data.get("disabled", False):
            continue

        points.append({
            "measurement": "radio_stats",
            "tags": {
                "org_id": org_id,
                "site_id": site_id,
                "mac": payload.get("mac", ""),
                "band": band,
            },
            "fields": {
                "channel": band_data.get("channel", 0),
                "power": band_data.get("power", 0),
                "bandwidth": band_data.get("bandwidth", 0),
                "util_all": band_data.get("util_all", 0),
                "noise_floor": band_data.get("noise_floor", 0),
                "num_clients": band_data.get("num_clients", 0),
            },
            "time": timestamp,
        })

    return points


def extract_points(payload: dict, org_id: str, site_id: str) -> list[dict]:
    """Extract InfluxDB data points from a raw AP WebSocket payload.

    Skips "basic" messages (no ``model`` field) and returns an empty list.
    For full-stats messages, returns one device_summary point plus one
    radio_stats point per active (non-disabled) band.
    """
    # Skip basic messages — they lack the model field
    if not payload.get("model"):
        return []

    timestamp = _get_timestamp(payload)
    points: list[dict] = []

    points.append(_extract_device_summary(payload, org_id, site_id, timestamp))
    points.extend(_extract_radio_stats(payload, org_id, site_id, timestamp))

    return points
```

### Run the tests (should pass)

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_ap_extractor.py -x --no-header -q
```

### Lint and type-check

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/ruff check app/modules/telemetry/extractors/ap_extractor.py && \
.venv/bin/mypy app/modules/telemetry/extractors/ap_extractor.py --no-error-summary
```

### Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add app/modules/telemetry/extractors/ap_extractor.py tests/unit/test_ap_extractor.py
git commit -m "$(cat <<'EOF'
feat(telemetry): add AP metric extractor with tests

Pure-function extractor that parses Mist AP WebSocket payloads into
InfluxDB data points: device_summary (cpu, mem, clients, uptime) and
radio_stats per active band (channel, power, bandwidth, utilization,
noise floor, clients). Skips basic messages (no model field) and
disabled bands.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 3 -- Switch extractor: write failing tests

- [ ] Create test file

**Create file:** `backend/tests/unit/test_switch_extractor.py`

```python
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
        port0 = next(
            p for p in points
            if p["measurement"] == "port_stats" and p["tags"]["port_id"] == "ge-0/0/0"
        )
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
        mod0 = next(
            p for p in points
            if p["measurement"] == "module_stats" and p["tags"]["fpc_idx"] == "0"
        )
        fields = mod0["fields"]
        # temp_max = max(45.0, 52.0, 38.0) = 52.0
        assert fields["temp_max"] == 52.0
        assert fields["poe_draw"] == 120.5
        assert fields["vc_role"] == "master"
        assert fields["vc_links_count"] == 1
        assert fields["mem_usage"] == 58

    def test_module_stats_fields_member_1(self):
        points = extract_points(_full_switch_payload(), "org-1", "site-1")
        mod1 = next(
            p for p in points
            if p["measurement"] == "module_stats" and p["tags"]["fpc_idx"] == "1"
        )
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
        mod0 = next(
            p for p in points
            if p["measurement"] == "module_stats" and p["tags"]["fpc_idx"] == "0"
        )
        assert mod0["fields"]["temp_max"] == 0
```

### Run the failing tests

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_switch_extractor.py -x --no-header -q 2>&1 | tail -5
```

Expected: `ModuleNotFoundError` or `ImportError`.

---

## Step 4 -- Switch extractor: implement

- [ ] Create the extractor module

**Create file:** `backend/app/modules/telemetry/extractors/switch_extractor.py`

```python
"""Switch metric extractor — parses Mist switch WebSocket payloads into InfluxDB data points.

Produces:
- device_summary: cpu_util, mem_usage, num_clients, uptime, poe_draw_total, poe_max_total
- port_stats: per UP port — port_id, up, tx_pkts, rx_pkts
- module_stats: per VC member — fpc_idx, temp_max, poe_draw, vc_role, vc_links_count, mem_usage
"""

from __future__ import annotations


def _get_timestamp(payload: dict) -> int:
    """Extract epoch timestamp, preferring _time over last_seen."""
    raw = payload.get("_time") or payload.get("last_seen") or 0
    return int(raw)


def _get_name(payload: dict) -> str:
    """Get device name, falling back to hostname."""
    return payload.get("name") or payload.get("hostname") or ""


def _get_num_clients(payload: dict) -> int:
    """Get client count from clients_stats or len(clients)."""
    clients_stats = payload.get("clients_stats")
    if clients_stats:
        total = clients_stats.get("total", {})
        count = total.get("num_wired_clients")
        if count is not None:
            return count
    clients = payload.get("clients")
    if clients is not None:
        return len(clients)
    return 0


def _get_poe_totals(payload: dict) -> tuple[float, float]:
    """Sum PoE draw and max across all module_stat entries."""
    modules = payload.get("module_stat", [])
    draw_total = 0.0
    max_total = 0.0
    for mod in modules:
        poe = mod.get("poe")
        if poe:
            draw_total += poe.get("power_draw", 0.0)
            max_total += poe.get("max_power", 0.0)
    return draw_total, max_total


def _extract_device_summary(payload: dict, org_id: str, site_id: str, timestamp: int) -> dict:
    """Build device_summary data point from switch payload."""
    cpu_stat = payload.get("cpu_stat", {})
    cpu_idle = cpu_stat.get("idle", 100)
    cpu_util = 100 - cpu_idle

    memory_stat = payload.get("memory_stat", {})
    mem_usage = memory_stat.get("usage", 0)

    poe_draw_total, poe_max_total = _get_poe_totals(payload)

    return {
        "measurement": "device_summary",
        "tags": {
            "org_id": org_id,
            "site_id": site_id,
            "mac": payload.get("mac", ""),
            "device_type": "switch",
            "name": _get_name(payload),
        },
        "fields": {
            "cpu_util": cpu_util,
            "mem_usage": mem_usage,
            "num_clients": _get_num_clients(payload),
            "uptime": payload.get("uptime", 0),
            "poe_draw_total": poe_draw_total,
            "poe_max_total": poe_max_total,
        },
        "time": timestamp,
    }


def _extract_port_stats(payload: dict, org_id: str, site_id: str, timestamp: int) -> list[dict]:
    """Build port_stats data points for UP ports from if_stat."""
    if_stat = payload.get("if_stat")
    if not if_stat:
        return []

    points: list[dict] = []
    for _if_key, port_data in if_stat.items():
        if not port_data.get("up", False):
            continue

        points.append({
            "measurement": "port_stats",
            "tags": {
                "org_id": org_id,
                "site_id": site_id,
                "mac": payload.get("mac", ""),
                "port_id": port_data.get("port_id", _if_key),
            },
            "fields": {
                "up": True,
                "tx_pkts": port_data.get("tx_pkts", 0),
                "rx_pkts": port_data.get("rx_pkts", 0),
            },
            "time": timestamp,
        })

    return points


def _extract_module_stats(payload: dict, org_id: str, site_id: str, timestamp: int) -> list[dict]:
    """Build module_stats data points per VC member from module_stat."""
    modules = payload.get("module_stat")
    if not modules:
        return []

    points: list[dict] = []
    for mod in modules:
        temperatures = mod.get("temperatures", [])
        if temperatures:
            temp_max = max(t.get("celsius", 0) for t in temperatures)
        else:
            temp_max = 0

        poe = mod.get("poe", {})
        poe_draw = poe.get("power_draw", 0.0) if poe else 0.0

        points.append({
            "measurement": "module_stats",
            "tags": {
                "org_id": org_id,
                "site_id": site_id,
                "mac": payload.get("mac", ""),
                "fpc_idx": str(mod.get("_idx", 0)),
            },
            "fields": {
                "temp_max": temp_max,
                "poe_draw": poe_draw,
                "vc_role": mod.get("vc_role", ""),
                "vc_links_count": len(mod.get("vc_links", [])),
                "mem_usage": mod.get("memory_stat", {}).get("usage", 0),
            },
            "time": timestamp,
        })

    return points


def extract_points(payload: dict, org_id: str, site_id: str) -> list[dict]:
    """Extract InfluxDB data points from a raw switch WebSocket payload.

    Returns one device_summary point, plus port_stats for each UP port
    and module_stats for each VC member.
    """
    timestamp = _get_timestamp(payload)
    points: list[dict] = []

    points.append(_extract_device_summary(payload, org_id, site_id, timestamp))
    points.extend(_extract_port_stats(payload, org_id, site_id, timestamp))
    points.extend(_extract_module_stats(payload, org_id, site_id, timestamp))

    return points
```

### Run the tests (should pass)

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_switch_extractor.py -x --no-header -q
```

### Lint and type-check

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/ruff check app/modules/telemetry/extractors/switch_extractor.py && \
.venv/bin/mypy app/modules/telemetry/extractors/switch_extractor.py --no-error-summary
```

### Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add app/modules/telemetry/extractors/switch_extractor.py tests/unit/test_switch_extractor.py
git commit -m "$(cat <<'EOF'
feat(telemetry): add switch metric extractor with tests

Pure-function extractor that parses Mist switch WebSocket payloads into
InfluxDB data points: device_summary (cpu, mem, clients, uptime, PoE
totals), port_stats for UP ports (tx/rx packets), and module_stats per
VC member (temp max, PoE draw, VC role, links count, memory).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 5 -- Gateway extractor: write failing tests

- [ ] Create test file

**Create file:** `backend/tests/unit/test_gateway_extractor.py`

```python
"""Unit tests for Gateway metric extractor."""

from app.modules.telemetry.extractors.gateway_extractor import extract_points


# ---------------------------------------------------------------------------
# Fixtures — SRX standalone
# ---------------------------------------------------------------------------

def _srx_standalone_payload() -> dict:
    """Realistic SRX standalone gateway payload."""
    return {
        "mac": "aabb00112233",
        "name": "GW-Branch-01",
        "model": "SRX300",
        "type": "gateway",
        "cpu_stat": {"idle": 78},
        "memory_stat": {"usage": 55},
        "uptime": 604800,
        "config_status": "synced",
        "last_seen": 1774576960,
        "_time": 1774576960.7,
        "spu_stat": [
            {
                "spu_cpu": 22,
                "spu_current_session": 4500,
                "spu_max_session": 64000,
                "spu_memory": 35,
            }
        ],
        "if_stat": {
            "ge-0/0/0.0": {
                "port_id": "ge-0/0/0",
                "port_usage": "wan",
                "wan_name": "ISP-Primary",
                "up": True,
                "tx_bytes": 1000000,
                "rx_bytes": 2000000,
                "tx_pkts": 5000,
                "rx_pkts": 10000,
            },
            "ge-0/0/1.0": {
                "port_id": "ge-0/0/1",
                "port_usage": "lan",
                "up": True,
                "tx_bytes": 500000,
                "rx_bytes": 600000,
                "tx_pkts": 3000,
                "rx_pkts": 4000,
            },
            "ge-0/0/2.0": {
                "port_id": "ge-0/0/2",
                "port_usage": "wan",
                "wan_name": "ISP-Backup",
                "up": False,
                "tx_bytes": 0,
                "rx_bytes": 0,
                "tx_pkts": 0,
                "rx_pkts": 0,
            },
        },
        "dhcpd_stat": {
            "default-vlan": {
                "num_ips": 254,
                "num_leased": 42,
            },
            "guest-vlan": {
                "num_ips": 126,
                "num_leased": 10,
            },
        },
    }


# ---------------------------------------------------------------------------
# Fixtures — SRX cluster
# ---------------------------------------------------------------------------

def _srx_cluster_payload() -> dict:
    """Realistic SRX cluster gateway payload."""
    payload = _srx_standalone_payload()
    payload["cluster_config"] = {
        "status": "Green",
        "operational": "active-passive",
        "primary_node_health": "healthy",
        "secondary_node_health": "healthy",
        "control_link_info": {"status": "Up"},
        "fabric_link_info": {"Status": "Enabled"},
    }
    # Cluster may have reth interfaces for WAN
    payload["if_stat"]["reth0.0"] = {
        "port_id": "reth0",
        "port_usage": "wan",
        "wan_name": "ISP-Primary",
        "up": True,
        "tx_bytes": 3000000,
        "rx_bytes": 4000000,
        "tx_pkts": 15000,
        "rx_pkts": 20000,
    }
    return payload


# ---------------------------------------------------------------------------
# Fixtures — SSR
# ---------------------------------------------------------------------------

def _ssr_standalone_payload() -> dict:
    """Realistic SSR gateway payload."""
    return {
        "mac": "ddeeff001122",
        "name": "SSR-DC-01",
        "model": "SSR",
        "type": "gateway",
        "cpu_stat": {"idle": 90},
        "memory_stat": {"usage": 40},
        "uptime": 2592000,
        "config_status": "synced",
        "ha_state": "running",
        "ha_peer_mac": "",
        "node_name": "node0",
        "router_name": "ssr-dc-cluster",
        "last_seen": 1774576960,
        "_time": 1774576960.9,
        "if_stat": {
            "dpdk1": {
                "port_id": "dpdk1",
                "port_usage": "wan",
                "wan_name": "WAN-MPLS",
                "up": True,
                "tx_bytes": 5000000,
                "rx_bytes": 6000000,
                "tx_pkts": 25000,
                "rx_pkts": 30000,
            },
        },
        "module_stat": [
            {
                "_idx": 0,
                "network_resources": [
                    {"type": "FIB", "count": 2142, "limit": 22608},
                    {"type": "FLOW", "count": 512, "limit": 524288},
                    {"type": "ACCESS_POLICY", "count": 100, "limit": 10000},
                ],
            }
        ],
        "dhcpd_stat": {
            "corp-lan": {
                "num_ips": 500,
                "num_leased": 150,
            },
        },
    }


# ---------------------------------------------------------------------------
# Tests: gateway_health (common to all types)
# ---------------------------------------------------------------------------

class TestGatewayHealth:
    """All gateway types produce a gateway_health point."""

    def test_srx_standalone_health(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        healths = [p for p in points if p["measurement"] == "gateway_health"]
        assert len(healths) == 1
        h = healths[0]
        assert h["tags"]["org_id"] == "org-1"
        assert h["tags"]["site_id"] == "site-1"
        assert h["tags"]["mac"] == "aabb00112233"
        assert h["tags"]["model"] == "SRX300"
        assert h["fields"]["cpu_idle"] == 78
        assert h["fields"]["mem_usage"] == 55
        assert h["fields"]["uptime"] == 604800
        assert h["fields"]["config_status"] == "synced"
        assert h["time"] == 1774576960

    def test_srx_cluster_health(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        healths = [p for p in points if p["measurement"] == "gateway_health"]
        assert len(healths) == 1

    def test_ssr_health_with_ha_fields(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        healths = [p for p in points if p["measurement"] == "gateway_health"]
        assert len(healths) == 1
        h = healths[0]
        assert h["tags"]["model"] == "SSR"
        assert h["tags"]["node_name"] == "node0"
        assert h["tags"]["router_name"] == "ssr-dc-cluster"
        assert h["fields"]["ha_state"] == "running"
        assert h["fields"]["cpu_idle"] == 90

    def test_health_time_falls_back_to_last_seen(self):
        payload = _srx_standalone_payload()
        del payload["_time"]
        points = extract_points(payload, "org-1", "site-1")
        h = next(p for p in points if p["measurement"] == "gateway_health")
        assert h["time"] == 1774576960

    def test_empty_payload_returns_health_with_defaults(self):
        points = extract_points({"mac": "000000000000", "model": "SRX320"}, "org-1", "site-1")
        healths = [p for p in points if p["measurement"] == "gateway_health"]
        assert len(healths) == 1
        assert healths[0]["fields"]["cpu_idle"] == 100


# ---------------------------------------------------------------------------
# Tests: gateway_wan (common to all types)
# ---------------------------------------------------------------------------

class TestGatewayWan:
    """All gateway types produce gateway_wan points for WAN ports."""

    def test_srx_standalone_wan_ports_only(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        wans = [p for p in points if p["measurement"] == "gateway_wan"]
        # ge-0/0/0 is wan+up, ge-0/0/1 is lan (excluded), ge-0/0/2 is wan+down (included)
        assert len(wans) == 2
        port_ids = {p["tags"]["port_id"] for p in wans}
        assert port_ids == {"ge-0/0/0", "ge-0/0/2"}

    def test_wan_point_tags(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        wan = next(
            p for p in points
            if p["measurement"] == "gateway_wan" and p["tags"]["port_id"] == "ge-0/0/0"
        )
        assert wan["tags"]["org_id"] == "org-1"
        assert wan["tags"]["site_id"] == "site-1"
        assert wan["tags"]["mac"] == "aabb00112233"
        assert wan["tags"]["wan_name"] == "ISP-Primary"
        assert wan["tags"]["port_usage"] == "wan"

    def test_wan_point_fields(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        wan = next(
            p for p in points
            if p["measurement"] == "gateway_wan" and p["tags"]["port_id"] == "ge-0/0/0"
        )
        fields = wan["fields"]
        assert fields["up"] is True
        assert fields["tx_bytes"] == 1000000
        assert fields["rx_bytes"] == 2000000
        assert fields["tx_pkts"] == 5000
        assert fields["rx_pkts"] == 10000

    def test_wan_time(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        wans = [p for p in points if p["measurement"] == "gateway_wan"]
        for wan in wans:
            assert wan["time"] == 1774576960

    def test_cluster_reth_wan_included(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        wans = [p for p in points if p["measurement"] == "gateway_wan"]
        port_ids = {p["tags"]["port_id"] for p in wans}
        assert "reth0" in port_ids

    def test_ssr_wan_port(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        wans = [p for p in points if p["measurement"] == "gateway_wan"]
        assert len(wans) == 1
        assert wans[0]["tags"]["port_id"] == "dpdk1"
        assert wans[0]["tags"]["wan_name"] == "WAN-MPLS"

    def test_no_if_stat_produces_no_wan_points(self):
        payload = _srx_standalone_payload()
        del payload["if_stat"]
        points = extract_points(payload, "org-1", "site-1")
        wans = [p for p in points if p["measurement"] == "gateway_wan"]
        assert wans == []


# ---------------------------------------------------------------------------
# Tests: gateway_dhcp (common to SRX and SSR)
# ---------------------------------------------------------------------------

class TestGatewayDhcp:
    """Gateway payloads with dhcpd_stat produce gateway_dhcp points."""

    def test_srx_dhcp_points(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        dhcps = [p for p in points if p["measurement"] == "gateway_dhcp"]
        assert len(dhcps) == 2
        networks = {p["tags"]["network_name"] for p in dhcps}
        assert networks == {"default-vlan", "guest-vlan"}

    def test_dhcp_tags(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        dhcp = next(
            p for p in points
            if p["measurement"] == "gateway_dhcp" and p["tags"]["network_name"] == "default-vlan"
        )
        assert dhcp["tags"]["org_id"] == "org-1"
        assert dhcp["tags"]["site_id"] == "site-1"
        assert dhcp["tags"]["mac"] == "aabb00112233"

    def test_dhcp_fields(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        dhcp = next(
            p for p in points
            if p["measurement"] == "gateway_dhcp" and p["tags"]["network_name"] == "default-vlan"
        )
        fields = dhcp["fields"]
        assert fields["num_ips"] == 254
        assert fields["num_leased"] == 42
        # utilization_pct = 42 / 254 * 100 ~= 16.5
        assert 16.4 < fields["utilization_pct"] < 16.6

    def test_dhcp_utilization_zero_when_no_ips(self):
        payload = _srx_standalone_payload()
        payload["dhcpd_stat"]["empty-scope"] = {"num_ips": 0, "num_leased": 0}
        points = extract_points(payload, "org-1", "site-1")
        dhcp = next(
            p for p in points
            if p["measurement"] == "gateway_dhcp" and p["tags"]["network_name"] == "empty-scope"
        )
        assert dhcp["fields"]["utilization_pct"] == 0

    def test_no_dhcpd_stat_produces_no_dhcp_points(self):
        payload = _srx_standalone_payload()
        del payload["dhcpd_stat"]
        points = extract_points(payload, "org-1", "site-1")
        dhcps = [p for p in points if p["measurement"] == "gateway_dhcp"]
        assert dhcps == []

    def test_ssr_dhcp_points(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        dhcps = [p for p in points if p["measurement"] == "gateway_dhcp"]
        assert len(dhcps) == 1
        assert dhcps[0]["tags"]["network_name"] == "corp-lan"

    def test_dhcp_time(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        dhcps = [p for p in points if p["measurement"] == "gateway_dhcp"]
        for dhcp in dhcps:
            assert dhcp["time"] == 1774576960


# ---------------------------------------------------------------------------
# Tests: gateway_spu (SRX only)
# ---------------------------------------------------------------------------

class TestGatewaySpu:
    """SRX gateways produce gateway_spu point from spu_stat."""

    def test_srx_standalone_spu(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        spus = [p for p in points if p["measurement"] == "gateway_spu"]
        assert len(spus) == 1

    def test_spu_tags(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        spu = next(p for p in points if p["measurement"] == "gateway_spu")
        assert spu["tags"]["org_id"] == "org-1"
        assert spu["tags"]["site_id"] == "site-1"
        assert spu["tags"]["mac"] == "aabb00112233"

    def test_spu_fields(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        spu = next(p for p in points if p["measurement"] == "gateway_spu")
        fields = spu["fields"]
        assert fields["spu_cpu"] == 22
        assert fields["spu_sessions"] == 4500
        assert fields["spu_max_sessions"] == 64000
        assert fields["spu_memory"] == 35

    def test_spu_time(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        spu = next(p for p in points if p["measurement"] == "gateway_spu")
        assert spu["time"] == 1774576960

    def test_srx_cluster_spu(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        spus = [p for p in points if p["measurement"] == "gateway_spu"]
        assert len(spus) == 1

    def test_empty_spu_stat_produces_no_spu(self):
        payload = _srx_standalone_payload()
        payload["spu_stat"] = []
        points = extract_points(payload, "org-1", "site-1")
        spus = [p for p in points if p["measurement"] == "gateway_spu"]
        assert spus == []

    def test_no_spu_stat_key_produces_no_spu(self):
        payload = _srx_standalone_payload()
        del payload["spu_stat"]
        points = extract_points(payload, "org-1", "site-1")
        spus = [p for p in points if p["measurement"] == "gateway_spu"]
        assert spus == []

    def test_ssr_has_no_spu(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        spus = [p for p in points if p["measurement"] == "gateway_spu"]
        assert spus == []


# ---------------------------------------------------------------------------
# Tests: gateway_cluster (SRX cluster only)
# ---------------------------------------------------------------------------

class TestGatewayCluster:
    """SRX cluster gateways produce gateway_cluster point."""

    def test_cluster_point_present(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        clusters = [p for p in points if p["measurement"] == "gateway_cluster"]
        assert len(clusters) == 1

    def test_cluster_tags(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        cluster = next(p for p in points if p["measurement"] == "gateway_cluster")
        assert cluster["tags"]["org_id"] == "org-1"
        assert cluster["tags"]["site_id"] == "site-1"
        assert cluster["tags"]["mac"] == "aabb00112233"

    def test_cluster_fields(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        cluster = next(p for p in points if p["measurement"] == "gateway_cluster")
        fields = cluster["fields"]
        assert fields["status"] == "Green"
        assert fields["operational"] == "active-passive"
        assert fields["primary_health"] == "healthy"
        assert fields["secondary_health"] == "healthy"
        assert fields["control_link_up"] is True
        assert fields["fabric_link_up"] is True

    def test_cluster_control_link_down(self):
        payload = _srx_cluster_payload()
        payload["cluster_config"]["control_link_info"]["status"] = "Down"
        points = extract_points(payload, "org-1", "site-1")
        cluster = next(p for p in points if p["measurement"] == "gateway_cluster")
        assert cluster["fields"]["control_link_up"] is False

    def test_cluster_fabric_link_down(self):
        payload = _srx_cluster_payload()
        payload["cluster_config"]["fabric_link_info"]["Status"] = "Down"
        points = extract_points(payload, "org-1", "site-1")
        cluster = next(p for p in points if p["measurement"] == "gateway_cluster")
        assert cluster["fields"]["fabric_link_up"] is False

    def test_cluster_time(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        cluster = next(p for p in points if p["measurement"] == "gateway_cluster")
        assert cluster["time"] == 1774576960

    def test_standalone_has_no_cluster_point(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        clusters = [p for p in points if p["measurement"] == "gateway_cluster"]
        assert clusters == []

    def test_ssr_has_no_cluster_point(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        clusters = [p for p in points if p["measurement"] == "gateway_cluster"]
        assert clusters == []


# ---------------------------------------------------------------------------
# Tests: gateway_resources (SSR only)
# ---------------------------------------------------------------------------

class TestGatewayResources:
    """SSR gateways produce gateway_resources points from network_resources."""

    def test_ssr_resources_present(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        resources = [p for p in points if p["measurement"] == "gateway_resources"]
        assert len(resources) == 3

    def test_resource_tags(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        fib = next(
            p for p in points
            if p["measurement"] == "gateway_resources" and p["tags"]["resource_type"] == "FIB"
        )
        assert fib["tags"]["org_id"] == "org-1"
        assert fib["tags"]["site_id"] == "site-1"
        assert fib["tags"]["mac"] == "ddeeff001122"
        assert fib["tags"]["node_name"] == "node0"

    def test_resource_fields_fib(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        fib = next(
            p for p in points
            if p["measurement"] == "gateway_resources" and p["tags"]["resource_type"] == "FIB"
        )
        fields = fib["fields"]
        assert fields["count"] == 2142
        assert fields["limit"] == 22608
        # utilization_pct = 2142 / 22608 * 100 ~= 9.47
        assert 9.4 < fields["utilization_pct"] < 9.5

    def test_resource_fields_flow(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        flow = next(
            p for p in points
            if p["measurement"] == "gateway_resources" and p["tags"]["resource_type"] == "FLOW"
        )
        assert flow["fields"]["count"] == 512
        assert flow["fields"]["limit"] == 524288

    def test_resource_fields_access_policy(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        ap = next(
            p for p in points
            if p["measurement"] == "gateway_resources" and p["tags"]["resource_type"] == "ACCESS_POLICY"
        )
        assert ap["fields"]["count"] == 100
        assert ap["fields"]["limit"] == 10000
        # utilization_pct = 100 / 10000 * 100 = 1.0
        assert ap["fields"]["utilization_pct"] == 1.0

    def test_resource_utilization_zero_when_limit_zero(self):
        payload = _ssr_standalone_payload()
        payload["module_stat"][0]["network_resources"][0]["limit"] = 0
        points = extract_points(payload, "org-1", "site-1")
        fib = next(
            p for p in points
            if p["measurement"] == "gateway_resources" and p["tags"]["resource_type"] == "FIB"
        )
        assert fib["fields"]["utilization_pct"] == 0

    def test_resource_time(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        resources = [p for p in points if p["measurement"] == "gateway_resources"]
        for r in resources:
            assert r["time"] == 1774576960

    def test_srx_standalone_has_no_resources(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        resources = [p for p in points if p["measurement"] == "gateway_resources"]
        assert resources == []

    def test_srx_cluster_has_no_resources(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        resources = [p for p in points if p["measurement"] == "gateway_resources"]
        assert resources == []

    def test_ssr_no_module_stat_produces_no_resources(self):
        payload = _ssr_standalone_payload()
        del payload["module_stat"]
        points = extract_points(payload, "org-1", "site-1")
        resources = [p for p in points if p["measurement"] == "gateway_resources"]
        assert resources == []

    def test_ssr_empty_network_resources_produces_no_resources(self):
        payload = _ssr_standalone_payload()
        payload["module_stat"][0]["network_resources"] = []
        points = extract_points(payload, "org-1", "site-1")
        resources = [p for p in points if p["measurement"] == "gateway_resources"]
        assert resources == []


# ---------------------------------------------------------------------------
# Tests: device type detection
# ---------------------------------------------------------------------------

class TestGatewayTypeDetection:
    """Verify correct sub-type detection determines which measurements appear."""

    def test_srx_standalone_measurements(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        measurements = {p["measurement"] for p in points}
        assert "gateway_health" in measurements
        assert "gateway_wan" in measurements
        assert "gateway_dhcp" in measurements
        assert "gateway_spu" in measurements
        assert "gateway_cluster" not in measurements
        assert "gateway_resources" not in measurements

    def test_srx_cluster_measurements(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        measurements = {p["measurement"] for p in points}
        assert "gateway_health" in measurements
        assert "gateway_wan" in measurements
        assert "gateway_dhcp" in measurements
        assert "gateway_spu" in measurements
        assert "gateway_cluster" in measurements
        assert "gateway_resources" not in measurements

    def test_ssr_measurements(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        measurements = {p["measurement"] for p in points}
        assert "gateway_health" in measurements
        assert "gateway_wan" in measurements
        assert "gateway_dhcp" in measurements
        assert "gateway_resources" in measurements
        assert "gateway_spu" not in measurements
        assert "gateway_cluster" not in measurements
```

### Run the failing tests

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_gateway_extractor.py -x --no-header -q 2>&1 | tail -5
```

Expected: `ModuleNotFoundError` or `ImportError`.

---

## Step 6 -- Gateway extractor: implement

- [ ] Create the extractor module

**Create file:** `backend/app/modules/telemetry/extractors/gateway_extractor.py`

```python
"""Gateway metric extractor — parses Mist gateway WebSocket payloads into InfluxDB data points.

Handles three sub-types:
- SRX standalone: spu_stat present, no cluster_config, model != "SSR"
- SRX cluster: cluster_config present
- SSR (standalone/HA): model == "SSR", network_resources in module_stat

Produces (depending on sub-type):
- gateway_health: cpu_idle, mem_usage, uptime, ha_state, config_status (all types)
- gateway_wan: per WAN interface — up, tx/rx bytes/pkts, wan_name (all types)
- gateway_dhcp: per DHCP scope — num_ips, num_leased, utilization_pct (all types)
- gateway_spu: SPU stats — spu_cpu, sessions, memory (SRX only)
- gateway_cluster: cluster status and link health (SRX cluster only)
- gateway_resources: network resource utilization — FIB, FLOW, ACCESS_POLICY (SSR only)
"""

from __future__ import annotations


def _get_timestamp(payload: dict) -> int:
    """Extract epoch timestamp, preferring _time over last_seen."""
    raw = payload.get("_time") or payload.get("last_seen") or 0
    return int(raw)


def _detect_subtype(payload: dict) -> str:
    """Detect gateway sub-type: 'ssr', 'srx_cluster', or 'srx_standalone'."""
    if payload.get("model") == "SSR":
        return "ssr"
    if payload.get("cluster_config"):
        return "srx_cluster"
    return "srx_standalone"


# ---------------------------------------------------------------------------
# Common measurements
# ---------------------------------------------------------------------------

def _extract_gateway_health(payload: dict, org_id: str, site_id: str, timestamp: int) -> dict:
    """Build gateway_health data point (common to all gateway types)."""
    cpu_stat = payload.get("cpu_stat", {})
    cpu_idle = cpu_stat.get("idle", 100)

    memory_stat = payload.get("memory_stat", {})
    mem_usage = memory_stat.get("usage", 0)

    tags: dict = {
        "org_id": org_id,
        "site_id": site_id,
        "mac": payload.get("mac", ""),
        "model": payload.get("model", ""),
        "node_name": payload.get("node_name", ""),
        "router_name": payload.get("router_name", ""),
    }

    return {
        "measurement": "gateway_health",
        "tags": tags,
        "fields": {
            "cpu_idle": cpu_idle,
            "mem_usage": mem_usage,
            "uptime": payload.get("uptime", 0),
            "ha_state": payload.get("ha_state", ""),
            "config_status": payload.get("config_status", ""),
        },
        "time": timestamp,
    }


def _extract_gateway_wan(payload: dict, org_id: str, site_id: str, timestamp: int) -> list[dict]:
    """Build gateway_wan data points for WAN interfaces from if_stat."""
    if_stat = payload.get("if_stat")
    if not if_stat:
        return []

    points: list[dict] = []
    for _if_key, port_data in if_stat.items():
        if port_data.get("port_usage") != "wan":
            continue

        points.append({
            "measurement": "gateway_wan",
            "tags": {
                "org_id": org_id,
                "site_id": site_id,
                "mac": payload.get("mac", ""),
                "port_id": port_data.get("port_id", _if_key),
                "wan_name": port_data.get("wan_name", ""),
                "port_usage": "wan",
            },
            "fields": {
                "up": port_data.get("up", False),
                "tx_bytes": port_data.get("tx_bytes", 0),
                "rx_bytes": port_data.get("rx_bytes", 0),
                "tx_pkts": port_data.get("tx_pkts", 0),
                "rx_pkts": port_data.get("rx_pkts", 0),
            },
            "time": timestamp,
        })

    return points


def _extract_gateway_dhcp(payload: dict, org_id: str, site_id: str, timestamp: int) -> list[dict]:
    """Build gateway_dhcp data points from dhcpd_stat."""
    dhcpd_stat = payload.get("dhcpd_stat")
    if not dhcpd_stat:
        return []

    points: list[dict] = []
    for network_name, scope_data in dhcpd_stat.items():
        num_ips = scope_data.get("num_ips", 0)
        num_leased = scope_data.get("num_leased", 0)
        utilization_pct = round(num_leased / num_ips * 100, 1) if num_ips > 0 else 0

        points.append({
            "measurement": "gateway_dhcp",
            "tags": {
                "org_id": org_id,
                "site_id": site_id,
                "mac": payload.get("mac", ""),
                "network_name": network_name,
            },
            "fields": {
                "num_ips": num_ips,
                "num_leased": num_leased,
                "utilization_pct": utilization_pct,
            },
            "time": timestamp,
        })

    return points


# ---------------------------------------------------------------------------
# SRX-specific measurements
# ---------------------------------------------------------------------------

def _extract_gateway_spu(payload: dict, org_id: str, site_id: str, timestamp: int) -> list[dict]:
    """Build gateway_spu data point from spu_stat (SRX only). Returns empty list if no SPU data."""
    spu_stat = payload.get("spu_stat")
    if not spu_stat:
        return []

    spu = spu_stat[0]

    return [{
        "measurement": "gateway_spu",
        "tags": {
            "org_id": org_id,
            "site_id": site_id,
            "mac": payload.get("mac", ""),
        },
        "fields": {
            "spu_cpu": spu.get("spu_cpu", 0),
            "spu_sessions": spu.get("spu_current_session", 0),
            "spu_max_sessions": spu.get("spu_max_session", 0),
            "spu_memory": spu.get("spu_memory", 0),
        },
        "time": timestamp,
    }]


def _extract_gateway_cluster(payload: dict, org_id: str, site_id: str, timestamp: int) -> list[dict]:
    """Build gateway_cluster data point from cluster_config (SRX cluster only)."""
    cluster_config = payload.get("cluster_config")
    if not cluster_config:
        return []

    control_link_info = cluster_config.get("control_link_info", {})
    control_link_up = control_link_info.get("status", "").lower() == "up"

    # Note: Mist uses capital-S "Status" for fabric_link_info
    fabric_link_info = cluster_config.get("fabric_link_info", {})
    fabric_status = fabric_link_info.get("Status", fabric_link_info.get("status", ""))
    fabric_link_up = fabric_status.lower() in ("up", "enabled")

    return [{
        "measurement": "gateway_cluster",
        "tags": {
            "org_id": org_id,
            "site_id": site_id,
            "mac": payload.get("mac", ""),
        },
        "fields": {
            "status": cluster_config.get("status", ""),
            "operational": cluster_config.get("operational", ""),
            "primary_health": cluster_config.get("primary_node_health", ""),
            "secondary_health": cluster_config.get("secondary_node_health", ""),
            "control_link_up": control_link_up,
            "fabric_link_up": fabric_link_up,
        },
        "time": timestamp,
    }]


# ---------------------------------------------------------------------------
# SSR-specific measurements
# ---------------------------------------------------------------------------

def _extract_gateway_resources(payload: dict, org_id: str, site_id: str, timestamp: int) -> list[dict]:
    """Build gateway_resources data points from module_stat network_resources (SSR only)."""
    module_stat = payload.get("module_stat")
    if not module_stat:
        return []

    first_module = module_stat[0]
    network_resources = first_module.get("network_resources")
    if not network_resources:
        return []

    points: list[dict] = []
    for resource in network_resources:
        count = resource.get("count", 0)
        limit = resource.get("limit", 0)
        utilization_pct = round(count / limit * 100, 1) if limit > 0 else 0

        points.append({
            "measurement": "gateway_resources",
            "tags": {
                "org_id": org_id,
                "site_id": site_id,
                "mac": payload.get("mac", ""),
                "node_name": payload.get("node_name", ""),
                "resource_type": resource.get("type", ""),
            },
            "fields": {
                "count": count,
                "limit": limit,
                "utilization_pct": utilization_pct,
            },
            "time": timestamp,
        })

    return points


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_points(payload: dict, org_id: str, site_id: str) -> list[dict]:
    """Extract InfluxDB data points from a raw gateway WebSocket payload.

    Detects gateway sub-type (SSR, SRX cluster, SRX standalone) and produces
    the appropriate set of measurements. All types emit gateway_health,
    gateway_wan, and gateway_dhcp. SRX types additionally emit gateway_spu.
    SRX clusters emit gateway_cluster. SSR emits gateway_resources.
    """
    timestamp = _get_timestamp(payload)
    subtype = _detect_subtype(payload)
    points: list[dict] = []

    # Common measurements (all gateway types)
    points.append(_extract_gateway_health(payload, org_id, site_id, timestamp))
    points.extend(_extract_gateway_wan(payload, org_id, site_id, timestamp))
    points.extend(_extract_gateway_dhcp(payload, org_id, site_id, timestamp))

    # Sub-type-specific measurements
    if subtype == "ssr":
        points.extend(_extract_gateway_resources(payload, org_id, site_id, timestamp))
    elif subtype == "srx_cluster":
        points.extend(_extract_gateway_spu(payload, org_id, site_id, timestamp))
        points.extend(_extract_gateway_cluster(payload, org_id, site_id, timestamp))
    else:
        # srx_standalone
        points.extend(_extract_gateway_spu(payload, org_id, site_id, timestamp))

    return points
```

### Run the tests (should pass)

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_gateway_extractor.py -x --no-header -q
```

### Lint and type-check

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/ruff check app/modules/telemetry/extractors/gateway_extractor.py && \
.venv/bin/mypy app/modules/telemetry/extractors/gateway_extractor.py --no-error-summary
```

### Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add app/modules/telemetry/extractors/gateway_extractor.py tests/unit/test_gateway_extractor.py
git commit -m "$(cat <<'EOF'
feat(telemetry): add gateway metric extractor with tests

Pure-function extractor that parses Mist gateway WebSocket payloads
into InfluxDB data points. Handles three sub-types: SRX standalone
(spu_stat), SRX cluster (cluster_config + spu_stat), and SSR
(network_resources). Common measurements: gateway_health, gateway_wan,
gateway_dhcp. SRX adds gateway_spu. SRX cluster adds gateway_cluster.
SSR adds gateway_resources.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 7 -- Update extractors __init__.py and run full suite

- [ ] Update the extractors package init

**Edit file:** `backend/app/modules/telemetry/extractors/__init__.py`

Replace the empty file contents with:

```python
"""Telemetry metric extractors — parse raw Mist WebSocket payloads into InfluxDB data points.

Each extractor module exposes a single ``extract_points(payload, org_id, site_id)``
function that returns a list of InfluxDB point dicts.
"""

from app.modules.telemetry.extractors.ap_extractor import extract_points as extract_ap_points
from app.modules.telemetry.extractors.gateway_extractor import extract_points as extract_gateway_points
from app.modules.telemetry.extractors.switch_extractor import extract_points as extract_switch_points

__all__ = [
    "extract_ap_points",
    "extract_switch_points",
    "extract_gateway_points",
]
```

### Run the full test suite to verify no regressions

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_ap_extractor.py tests/unit/test_switch_extractor.py tests/unit/test_gateway_extractor.py -v --no-header -q
```

### Lint and type-check all extractors

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/ruff check app/modules/telemetry/extractors/ && \
.venv/bin/mypy app/modules/telemetry/extractors/ --no-error-summary
```

### Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add app/modules/telemetry/extractors/__init__.py
git commit -m "$(cat <<'EOF'
feat(telemetry): export all extractors from extractors package __init__

Provides extract_ap_points, extract_switch_points, extract_gateway_points
as convenient top-level imports for the ingestion service.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 8 -- Run full backend test suite to verify no regressions

- [ ] Validate nothing else broke

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest --no-header -q 2>&1 | tail -10
```

If any tests fail that are unrelated to this plan, investigate and fix. If all pass, this plan is complete.

---

## Summary

| Step | Action | Files | Commit |
|------|--------|-------|--------|
| 1 | AP extractor tests (TDD: red) | `tests/unit/test_ap_extractor.py` | -- |
| 2 | AP extractor implementation (TDD: green) | `app/modules/telemetry/extractors/ap_extractor.py` | `feat(telemetry): add AP metric extractor with tests` |
| 3 | Switch extractor tests (TDD: red) | `tests/unit/test_switch_extractor.py` | -- |
| 4 | Switch extractor implementation (TDD: green) | `app/modules/telemetry/extractors/switch_extractor.py` | `feat(telemetry): add switch metric extractor with tests` |
| 5 | Gateway extractor tests (TDD: red) | `tests/unit/test_gateway_extractor.py` | -- |
| 6 | Gateway extractor implementation (TDD: green) | `app/modules/telemetry/extractors/gateway_extractor.py` | `feat(telemetry): add gateway metric extractor with tests` |
| 7 | Export from `__init__.py`, full extractor suite | `app/modules/telemetry/extractors/__init__.py` | `feat(telemetry): export all extractors from extractors package __init__` |
| 8 | Full backend regression check | -- | -- |

---

### Critical Files for Implementation
- `/Users/tmunzer/4_dev/mist_automation/backend/app/modules/telemetry/extractors/ap_extractor.py`
- `/Users/tmunzer/4_dev/mist_automation/backend/app/modules/telemetry/extractors/switch_extractor.py`
- `/Users/tmunzer/4_dev/mist_automation/backend/app/modules/telemetry/extractors/gateway_extractor.py`
- `/Users/tmunzer/4_dev/mist_automation/backend/app/modules/telemetry/extractors/__init__.py`
- `/Users/tmunzer/4_dev/mist_automation/docs/superpowers/specs/2026-03-26-websocket-telemetry-pipeline-design.md`