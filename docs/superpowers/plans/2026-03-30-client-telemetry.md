# Client Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add wireless client telemetry — subscribe to Mist `/stats/clients` WS channel, store per-client metrics in InfluxDB, expose REST endpoints, and surface client data on a dedicated Clients page plus summary cards on the existing Site and Scope views.

**Architecture:** A new `ClientWsManager` (same pattern as `MistWsManager`) shares the existing asyncio queue; `IngestionService` dispatches by channel suffix (`devices` vs `clients`); a `LatestClientCache` (subclass of `LatestValueCache`) stores the latest payload per client MAC. All frontend state uses signals; the new Clients page is a lazy-loaded standalone component.

**Tech Stack:** Python/FastAPI, Beanie/MongoDB, InfluxDB 2.7 (Flux), mistapi `ClientsStatsEvents`, Angular 21 (standalone, signals, zoneless), Angular Material, Chart.js/ng2-charts.

**Spec:** `docs/superpowers/specs/2026-03-30-client-telemetry-design.md`

---

## File Map

**Create:**
- `backend/app/modules/telemetry/extractors/client_extractor.py`
- `backend/app/modules/telemetry/services/latest_client_cache.py`
- `backend/app/modules/telemetry/services/client_ws_manager.py`
- `backend/tests/unit/test_client_extractor.py`
- `backend/tests/unit/test_latest_client_cache.py`
- `frontend/src/app/features/telemetry/clients/telemetry-clients.component.ts`
- `frontend/src/app/features/telemetry/clients/telemetry-clients.component.html`
- `frontend/src/app/features/telemetry/clients/telemetry-clients.component.scss`

**Modify:**
- `backend/app/modules/telemetry/services/ingestion_service.py` — add client channel dispatch
- `backend/app/modules/telemetry/services/lifecycle.py` — instantiate `ClientWsManager` + `LatestClientCache`
- `backend/app/modules/telemetry/__init__.py` — declare `_client_cache` + `_client_ws_manager` singletons
- `backend/app/modules/telemetry/schemas.py` — add client Pydantic models; add `"client_stats"` to `ALLOWED_MEASUREMENTS`
- `backend/app/modules/telemetry/router.py` — add `/scope/clients`, `/scope/clients/summary`, `/query/clients/range` + update `/status`
- `frontend/src/app/features/telemetry/models.ts` — add `ClientStatRecord`, `ClientSiteSummary`, `ClientListResponse`
- `frontend/src/app/features/telemetry/telemetry.service.ts` — add `getSiteClients`, `getSiteClientsSummary`, `queryClientRange`
- `frontend/src/app/features/telemetry/telemetry.routes.ts` — add `site/:id/clients` route
- `frontend/src/app/features/telemetry/site/telemetry-site.component.ts` — load + show clients summary
- `frontend/src/app/features/telemetry/site/telemetry-site.component.html` — add clients section card
- `frontend/src/app/features/telemetry/scope/telemetry-scope.component.ts` — load org-wide client summary
- `frontend/src/app/features/telemetry/scope/telemetry-scope.component.html` — add Clients section

---

## Task 1: Client Extractor

**Files:**
- Create: `backend/app/modules/telemetry/extractors/client_extractor.py`
- Test: `backend/tests/unit/test_client_extractor.py`

- [ ] **Step 1: Write the failing tests**

```python
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
        "model": "MBP 14\" M1 2021",
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend
.venv/bin/pytest tests/unit/test_client_extractor.py -v
```
Expected: `ImportError` or `ModuleNotFoundError` — `client_extractor` doesn't exist yet.

- [ ] **Step 3: Write the extractor**

```python
# backend/app/modules/telemetry/extractors/client_extractor.py
"""Wireless client metric extractor — parses Mist client WebSocket payloads into InfluxDB data points.

Each message is one client record from the /sites/{id}/stats/clients channel.
Produces one `client_stats` measurement point per message.
"""

from __future__ import annotations

from app.modules.telemetry.extractors._helpers import get_timestamp


def extract_points(payload: dict, org_id: str, site_id: str) -> list[dict]:
    """Extract an InfluxDB data point from a Mist client stats payload.

    Returns a single-element list, or empty list if the payload lacks a MAC.
    """
    mac = payload.get("mac", "")
    if not mac:
        return []

    timestamp = get_timestamp(payload)

    key_mgmt = payload.get("key_mgmt", "") or ""
    auth_type = "eap" if "EAP" in key_mgmt.upper() else "psk"

    tags = {
        "org_id": org_id,
        "site_id": site_id,
        "mac": mac,
        "ap_mac": payload.get("ap_mac", "") or "",
        "ssid": payload.get("ssid", "") or "",
        "band": str(payload.get("band", "") or ""),
        "auth_type": auth_type,
    }

    fields: dict = {
        # Numeric — signal
        "rssi": _to_float(payload.get("rssi")),
        "snr": _to_float(payload.get("snr")),
        "channel": _to_int(payload.get("channel")),
        # Numeric — rates
        "tx_rate": _to_float(payload.get("tx_rate")),
        "rx_rate": _to_float(payload.get("rx_rate")),
        "tx_bps": _to_int(payload.get("tx_bps")),
        "rx_bps": _to_int(payload.get("rx_bps")),
        # Numeric — counters
        "tx_pkts": _to_int(payload.get("tx_pkts")),
        "rx_pkts": _to_int(payload.get("rx_pkts")),
        "tx_bytes": _to_int(payload.get("tx_bytes")),
        "rx_bytes": _to_int(payload.get("rx_bytes")),
        "tx_retries": _to_int(payload.get("tx_retries")),
        "rx_retries": _to_int(payload.get("rx_retries")),
        # Numeric — timing
        "idle_time": _to_float(payload.get("idle_time")),
        "uptime": _to_int(payload.get("uptime")),
        # Boolean stored as 0/1
        "is_guest": 1 if payload.get("is_guest") else 0,
        "dual_band": 1 if payload.get("dual_band") else 0,
        # String identity fields
        "hostname": payload.get("hostname") or "",
        "ip": payload.get("ip") or "",
        "manufacture": payload.get("manufacture") or "",
        "family": payload.get("family") or "",
        "model": payload.get("model") or "",
        "os": payload.get("os") or "",
        "os_version": payload.get("os_version") or "",
        "group": payload.get("group") or "",
        "vlan_id": str(payload.get("vlan_id") or ""),
        "proto": payload.get("proto") or "",
        "key_mgmt": key_mgmt,
        "username": payload.get("username") or "",
        "airespace_ifname": payload.get("airespace_ifname") or "",
        "type": payload.get("type") or "",
    }

    # Drop None values — InfluxDB will omit absent fields gracefully
    fields = {k: v for k, v in fields.items() if v is not None}

    return [
        {
            "measurement": "client_stats",
            "tags": tags,
            "fields": fields,
            "time": timestamp,
        }
    ]


def _to_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend
.venv/bin/pytest tests/unit/test_client_extractor.py -v
```
Expected: all 11 tests pass.

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/modules/telemetry/extractors/client_extractor.py tests/unit/test_client_extractor.py
git commit -m "feat(telemetry): add wireless client extractor for client_stats measurement"
```

---

## Task 2: Latest Client Cache

**Files:**
- Create: `backend/app/modules/telemetry/services/latest_client_cache.py`
- Test: `backend/tests/unit/test_latest_client_cache.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_latest_client_cache.py
"""Unit tests for LatestClientCache."""

import time

from app.modules.telemetry.services.latest_client_cache import LatestClientCache


def _client(mac: str, site_id: str, band: str = "24", rssi: int = -50,
            tx_bps: int = 100, rx_bps: int = 200) -> dict:
    return {
        "mac": mac,
        "site_id": site_id,
        "band": band,
        "rssi": rssi,
        "tx_bps": tx_bps,
        "rx_bps": rx_bps,
    }


class TestLatestClientCache:
    def test_update_and_get(self):
        cache = LatestClientCache()
        stats = _client("aabbccddeeff", "site1")
        cache.update("aabbccddeeff", stats)
        assert cache.get("aabbccddeeff") == stats

    def test_get_unknown_returns_none(self):
        cache = LatestClientCache()
        assert cache.get("000000000000") is None

    def test_size(self):
        cache = LatestClientCache()
        cache.update("aa", _client("aa", "site1"))
        cache.update("bb", _client("bb", "site1"))
        assert cache.size() == 2

    def test_get_all_for_site_returns_matching(self):
        cache = LatestClientCache()
        cache.update("aa", _client("aa", "site1"))
        cache.update("bb", _client("bb", "site2"))
        results = cache.get_all_for_site("site1")
        assert len(results) == 1
        assert results[0]["mac"] == "aa"

    def test_get_site_summary_counts(self):
        cache = LatestClientCache()
        cache.update("aa", _client("aa", "site1", band="24", rssi=-40, tx_bps=100, rx_bps=50))
        cache.update("bb", _client("bb", "site1", band="5", rssi=-60, tx_bps=200, rx_bps=150))
        cache.update("cc", _client("cc", "site2", band="24", rssi=-30, tx_bps=0, rx_bps=0))

        summary = cache.get_site_summary("site1")
        assert summary["total_clients"] == 2
        assert summary["avg_rssi"] == -50.0
        assert summary["band_counts"] == {"24": 1, "5": 1}
        assert summary["total_tx_bps"] == 300
        assert summary["total_rx_bps"] == 200

    def test_get_site_summary_empty_site(self):
        cache = LatestClientCache()
        summary = cache.get_site_summary("no_such_site")
        assert summary["total_clients"] == 0
        assert summary["avg_rssi"] == 0.0
        assert summary["band_counts"] == {}

    def test_prune_removes_stale(self):
        cache = LatestClientCache()
        cache.update("aa", _client("aa", "site1"))
        # Force stale by manipulating entry timestamp
        cache._entries["aa"]["updated_at"] = time.time() - 700
        cache.prune(max_age_seconds=600)
        assert cache.size() == 0

    def test_get_site_summary_excludes_stale(self):
        cache = LatestClientCache()
        cache.update("aa", _client("aa", "site1"))
        cache._entries["aa"]["updated_at"] = time.time() - 200
        # max_age=120 → stale
        summary = cache.get_site_summary("site1", max_age_seconds=120)
        assert summary["total_clients"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend
.venv/bin/pytest tests/unit/test_latest_client_cache.py -v
```
Expected: `ImportError` — module doesn't exist yet.

- [ ] **Step 3: Write the cache**

```python
# backend/app/modules/telemetry/services/latest_client_cache.py
"""In-memory cache of latest wireless client stats per MAC address.

Extends LatestValueCache with client-specific aggregate methods (site summary).
"""

from __future__ import annotations

import time

from app.modules.telemetry.services.latest_value_cache import LatestValueCache


class LatestClientCache(LatestValueCache):
    """Stores the most recent client stats payload per client MAC.

    Inherits all LatestValueCache methods (update, get, get_all_for_site, prune, etc.)
    and adds get_site_summary() for aggregate client KPIs.
    """

    def get_site_summary(self, site_id: str, max_age_seconds: float = 120) -> dict:
        """Compute aggregate client stats for a site from the in-memory cache.

        Returns:
            dict with keys: total_clients, avg_rssi, band_counts, total_tx_bps, total_rx_bps
        """
        now = time.time()
        clients = []
        for _mac, entry in self._entries.items():
            if now - entry["updated_at"] > max_age_seconds:
                continue
            stats = entry.get("stats", {})
            if stats.get("site_id") == site_id:
                clients.append(stats)

        if not clients:
            return {
                "total_clients": 0,
                "avg_rssi": 0.0,
                "band_counts": {},
                "total_tx_bps": 0,
                "total_rx_bps": 0,
            }

        rssiz = [float(c["rssi"]) for c in clients if c.get("rssi") is not None]
        band_counts: dict[str, int] = {}
        for c in clients:
            band = str(c.get("band") or "")
            if band:
                band_counts[band] = band_counts.get(band, 0) + 1

        return {
            "total_clients": len(clients),
            "avg_rssi": round(sum(rssiz) / len(rssiz), 1) if rssiz else 0.0,
            "band_counts": band_counts,
            "total_tx_bps": sum(int(c.get("tx_bps") or 0) for c in clients),
            "total_rx_bps": sum(int(c.get("rx_bps") or 0) for c in clients),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend
.venv/bin/pytest tests/unit/test_latest_client_cache.py -v
```
Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/modules/telemetry/services/latest_client_cache.py tests/unit/test_latest_client_cache.py
git commit -m "feat(telemetry): add LatestClientCache for per-client in-memory stats"
```

---

## Task 3: Ingestion Service — Client Channel Dispatch

**Files:**
- Modify: `backend/app/modules/telemetry/services/ingestion_service.py`

The current `_CHANNEL_SITE_RE` only matches `/sites/{id}/stats/devices`. We extend it to also match `/stats/clients` and route to a new `_process_client_message()` method. We also add `client_stats` CoV thresholds and an optional `client_cache` constructor param.

- [ ] **Step 1: Update `_CHANNEL_SITE_RE` → `_CHANNEL_RE`**

In `ingestion_service.py`, replace line 28:
```python
# Old:
_CHANNEL_SITE_RE = re.compile(r"/sites/([^/]+)/stats/devices")

# New:
_CHANNEL_RE = re.compile(r"/sites/([^/]+)/stats/(devices|clients)")
```

- [ ] **Step 2: Add `client_stats` to `COV_THRESHOLDS`**

In `ingestion_service.py`, add to the `COV_THRESHOLDS` dict after `switch_dhcp`:

```python
    "client_stats": {
        "rssi": 3.0,
        "snr": 3.0,
        "channel": "exact",
        "tx_rate": "exact",
        "rx_rate": "exact",
        "tx_bps": "always",
        "rx_bps": "always",
        "tx_pkts": "always",
        "rx_pkts": "always",
        "tx_bytes": "always",
        "rx_bytes": "always",
        "tx_retries": "always",
        "rx_retries": "always",
        "idle_time": 5.0,
        "uptime": "always",
        "hostname": "exact",
        "ip": "exact",
        "group": "exact",
        "vlan_id": "exact",
        "proto": "exact",
        "username": "exact",
        "manufacture": "exact",
        "os": "exact",
        "os_version": "exact",
        "key_mgmt": "exact",
        "type": "exact",
    },
```

- [ ] **Step 3: Add `client_cache` param to `IngestionService.__init__`**

In the `IngestionService.__init__` method, add `client_cache` as an optional parameter. The full updated signature and body:

```python
    def __init__(
        self,
        influxdb: InfluxDBService,
        cache: LatestValueCache,
        cov_filter: CoVFilter,
        org_id: str,
        client_cache: Any | None = None,
        queue_maxsize: int = 10_000,
    ) -> None:
        self._influxdb = influxdb
        self._cache = cache
        self._cov = cov_filter
        self._org_id = org_id
        self._client_cache = client_cache
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_maxsize)
        self._running = False
        self._task: asyncio.Task | None = None

        # Stats
        self._messages_processed = 0
        self._points_extracted = 0
        self._points_written = 0
        self._points_filtered = 0
        self._last_message_at: float = 0
```

Add `from typing import Any` to the import block if not already present (it is — check line 15).

- [ ] **Step 4: Update `_process_message` to dispatch on channel type**

Replace the channel-extraction block (around lines 463–470) with the new multi-channel dispatch. The full updated `_process_message` method (replace the existing one):

```python
    async def _process_message(self, msg: dict[str, Any]) -> None:
        """Process a single WebSocket message through the full pipeline."""
        # 1. Only process "data" events
        if msg.get("event") != "data":
            return

        # 2. Extract site_id and channel type
        channel = msg.get("channel", "")
        match = _CHANNEL_RE.search(channel)
        if not match:
            logger.debug("ingestion_unknown_channel", channel=channel)
            return
        site_id = match.group(1)
        stat_type = match.group(2)  # "devices" or "clients"

        # 3. Parse the data JSON string
        raw_data = msg.get("data")
        if not raw_data:
            return
        try:
            if isinstance(raw_data, str):
                payload = json.loads(raw_data)
            else:
                payload = raw_data
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug("ingestion_json_parse_error", error=str(e))
            return

        if not isinstance(payload, dict):
            return

        # 4. Route by channel type
        if stat_type == "clients":
            await self._process_client_message(site_id, payload)
            return

        # --- Device pipeline (stat_type == "devices") ---

        # 4b. Update LatestValueCache with the full payload.
        mac = payload.get("mac", "")
        has_type_info = bool(payload.get("type") or payload.get("model"))
        if mac and has_type_info:
            if not payload.get("site_id"):
                payload = {**payload, "site_id": site_id}
            self._cache.update(mac, payload)

        # 5. Extract InfluxDB data points
        device_type = payload.get("type") or ("ap" if isinstance(payload.get("model"), str) and payload["model"].startswith("AP") else None)
        has_time = payload.get("_time") is not None
        points = extract_points(payload, self._org_id, site_id)
        self._points_extracted += len(points)

        measurements = {p.get("measurement") for p in points} if points else set()
        logger.debug(
            "ingestion_message_processed",
            mac=mac,
            device_type=device_type,
            has_time=has_time,
            points_extracted=len(points),
            measurements=sorted(measurements),
        )

        if not points:
            self._messages_processed += 1
            self._last_message_at = time.time()
            return

        # 6. Apply CoV filtering
        filtered_points: list[dict[str, Any]] = []
        for point in points:
            measurement = point.get("measurement", "")

            if measurement in _ALWAYS_WRITE_MEASUREMENTS:
                filtered_points.append(point)
                continue

            thresholds = COV_THRESHOLDS.get(measurement)
            if thresholds is None:
                filtered_points.append(point)
                continue

            cov_key = _build_cov_key(point)
            fields = point.get("fields", {})

            if self._cov.should_write(cov_key, fields, thresholds):
                self._cov.record_write(cov_key, fields)
                filtered_points.append(point)
            else:
                self._points_filtered += 1

        # 7. Write filtered points to InfluxDB
        if filtered_points:
            filtered_measurements = {}
            for p in filtered_points:
                m = p.get("measurement", "")
                filtered_measurements[m] = filtered_measurements.get(m, 0) + 1
            logger.debug(
                "ingestion_writing_points",
                mac=mac,
                device_type=device_type,
                total=len(filtered_points),
                measurements=filtered_measurements,
            )
            await self._influxdb.write_points(filtered_points)
            self._points_written += len(filtered_points)

        # 8. Broadcast to any live device page subscribers
        if mac and device_type:
            event = _build_device_ws_event(payload, device_type)
            await ws_manager.broadcast(f"telemetry:device:{mac}", event)

        # Broadcast lightweight refresh signals to site and org channels
        if site_id and mac and device_type:
            tick = {"mac": mac, "device_type": device_type}
            await ws_manager.broadcast(f"telemetry:site:{site_id}", tick)
            await ws_manager.broadcast("telemetry:org", tick)

        self._messages_processed += 1
        self._last_message_at = time.time()

        if self._messages_processed % 1000 == 0:
            self._cache.prune(max_age_seconds=3600)
```

- [ ] **Step 5: Add `_process_client_message` method**

Add this method to the `IngestionService` class (after `_process_message`):

```python
    async def _process_client_message(self, site_id: str, payload: dict[str, Any]) -> None:
        """Process a single client stats message: cache → CoV filter → InfluxDB → WS broadcast."""
        from app.modules.telemetry.extractors.client_extractor import extract_points as extract_client_points

        client_mac = payload.get("mac", "")
        if not client_mac:
            return

        # Inject site_id if missing (should already be present in client payloads)
        if not payload.get("site_id"):
            payload = {**payload, "site_id": site_id}

        # Update client cache
        if self._client_cache is not None:
            self._client_cache.update(client_mac, payload)

        # Extract InfluxDB points (one point per client message)
        points = extract_client_points(payload, self._org_id, site_id)
        self._points_extracted += len(points)

        if not points:
            self._messages_processed += 1
            self._last_message_at = time.time()
            return

        # Apply CoV filtering
        filtered_points: list[dict[str, Any]] = []
        thresholds = COV_THRESHOLDS.get("client_stats", {})
        for point in points:
            cov_key = _build_cov_key(point)
            fields = point.get("fields", {})
            if self._cov.should_write(cov_key, fields, thresholds):
                self._cov.record_write(cov_key, fields)
                filtered_points.append(point)
            else:
                self._points_filtered += 1

        # Write to InfluxDB
        if filtered_points:
            await self._influxdb.write_points(filtered_points)
            self._points_written += len(filtered_points)

        # Broadcast lightweight tick to site channel (frontend debounces at 5s)
        tick = {"mac": client_mac, "type": "client"}
        await ws_manager.broadcast(f"telemetry:site:{site_id}", tick)

        self._messages_processed += 1
        self._last_message_at = time.time()

        # Periodic client cache pruning (every 1000 messages; 600s > _ttl=300)
        if self._messages_processed % 1000 == 0 and self._client_cache is not None:
            self._client_cache.prune(max_age_seconds=600)
```

- [ ] **Step 6: Run existing tests to verify nothing broke**

```bash
cd backend
.venv/bin/pytest tests/unit/ -v -k "not scope"
```
Expected: all previously-passing tests still pass.

- [ ] **Step 7: Commit**

```bash
cd backend
git add app/modules/telemetry/services/ingestion_service.py
git commit -m "feat(telemetry): dispatch /stats/clients channel to client pipeline in IngestionService"
```

---

## Task 4: Client WS Manager + Module Wiring

**Files:**
- Create: `backend/app/modules/telemetry/services/client_ws_manager.py`
- Modify: `backend/app/modules/telemetry/__init__.py`
- Modify: `backend/app/modules/telemetry/services/lifecycle.py`

- [ ] **Step 1: Create `client_ws_manager.py`**

```python
# backend/app/modules/telemetry/services/client_ws_manager.py
"""Client WebSocket Manager — subscribes to /sites/{id}/stats/clients for client stats.

Identical pattern to MistWsManager but uses ClientsStatsEvents instead of DeviceStatsEvents.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from mistapi.websockets.sites import ClientsStatsEvents

logger = structlog.get_logger(__name__)

_MAX_SITES_PER_CONNECTION = 1000


class ClientWsManager:
    """Manages Mist WebSocket connections for wireless client stats streaming."""

    def __init__(
        self,
        api_session: Any,
        message_queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        self._api_session = api_session
        self._message_queue = message_queue
        self._connections: list[ClientsStatsEvents] = []
        self._subscribed_sites: list[str] = []
        self._loop: asyncio.AbstractEventLoop | None = None

        self._messages_received = 0
        self._messages_bridge_dropped = 0
        self._last_message_at: float = 0
        self._started_at: float = 0

    def _chunk_sites(self, site_ids: list[str]) -> list[list[str]]:
        n = _MAX_SITES_PER_CONNECTION
        return [site_ids[i : i + n] for i in range(0, len(site_ids), n)]

    def _on_ws_message(self, msg: dict[str, Any]) -> None:
        self._messages_received += 1
        self._last_message_at = time.time()
        if self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._safe_enqueue, msg)
        except RuntimeError:
            pass

    def _safe_enqueue(self, msg: dict[str, Any]) -> None:
        try:
            self._message_queue.put_nowait(msg)
        except asyncio.QueueFull:
            self._messages_bridge_dropped += 1

    async def start(self, site_ids: list[str]) -> None:
        self._loop = asyncio.get_running_loop()
        self._subscribed_sites = list(site_ids)
        chunks = self._chunk_sites(site_ids)

        if not chunks:
            logger.info("client_ws_manager_no_sites")
            return

        for chunk in chunks:
            ws = ClientsStatsEvents(
                mist_session=self._api_session,
                site_ids=chunk,
                auto_reconnect=True,
                max_reconnect_attempts=5,
                reconnect_backoff=2.0,
            )
            ws.on_message(self._on_ws_message)
            ws.connect(run_in_background=True)
            self._connections.append(ws)

        self._started_at = time.time()
        logger.info(
            "client_ws_manager_started",
            connections=len(self._connections),
            sites=len(self._subscribed_sites),
        )

    async def stop(self) -> None:
        for ws in self._connections:
            try:
                ws.disconnect()
            except Exception as e:
                logger.warning("client_ws_disconnect_error", error=str(e))

        count = len(self._connections)
        self._connections = []
        self._subscribed_sites = []
        self._loop = None
        logger.info("client_ws_manager_stopped", connections_closed=count)

    async def add_sites(self, site_ids: list[str]) -> None:
        combined = list(set(self._subscribed_sites + site_ids))
        await self.stop()
        await self.start(combined)

    async def remove_sites(self, site_ids: list[str]) -> None:
        remaining = [s for s in self._subscribed_sites if s not in set(site_ids)]
        await self.stop()
        if remaining:
            await self.start(remaining)

    def get_status(self) -> dict[str, Any]:
        ready_list = []
        for ws in self._connections:
            try:
                ready_list.append(ws.ready())
            except Exception:
                ready_list.append(False)
        return {
            "connections": len(self._connections),
            "sites_subscribed": len(self._subscribed_sites),
            "all_ready": all(ready_list) if ready_list else True,
            "connections_ready": sum(1 for r in ready_list if r),
            "messages_received": self._messages_received,
            "messages_bridge_dropped": self._messages_bridge_dropped,
            "last_message_at": self._last_message_at,
            "started_at": self._started_at,
        }
```

- [ ] **Step 2: Add client singletons to `__init__.py`**

Replace the full content of `backend/app/modules/telemetry/__init__.py`:

```python
"""Telemetry module — WebSocket device stats ingestion pipeline.

Module-level singletons are initialized during app startup when
telemetry_enabled is True in SystemConfig.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.telemetry.services.client_ws_manager import ClientWsManager
    from app.modules.telemetry.services.cov_filter import CoVFilter
    from app.modules.telemetry.services.influxdb_service import InfluxDBService
    from app.modules.telemetry.services.ingestion_service import IngestionService
    from app.modules.telemetry.services.latest_client_cache import LatestClientCache
    from app.modules.telemetry.services.latest_value_cache import LatestValueCache
    from app.modules.telemetry.services.mist_ws_manager import MistWsManager

_influxdb_service: InfluxDBService | None = None
_latest_cache: LatestValueCache | None = None
_client_cache: LatestClientCache | None = None
_cov_filter: CoVFilter | None = None
_ingestion_service: IngestionService | None = None
_ws_manager: MistWsManager | None = None
_client_ws_manager: ClientWsManager | None = None
```

- [ ] **Step 3: Wire `ClientWsManager` and `LatestClientCache` into `lifecycle.py`**

Replace the full content of `backend/app/modules/telemetry/services/lifecycle.py`:

```python
"""Telemetry pipeline lifecycle management."""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


async def start_telemetry_pipeline() -> dict:
    """Start the full telemetry pipeline from SystemConfig."""
    import mistapi

    import app.modules.telemetry as telemetry_mod
    from app.core.security import decrypt_sensitive_data
    from app.models.system import SystemConfig
    from app.modules.telemetry.services.client_ws_manager import ClientWsManager
    from app.modules.telemetry.services.cov_filter import CoVFilter
    from app.modules.telemetry.services.influxdb_service import InfluxDBService
    from app.modules.telemetry.services.ingestion_service import IngestionService
    from app.modules.telemetry.services.latest_client_cache import LatestClientCache
    from app.modules.telemetry.services.latest_value_cache import LatestValueCache
    from app.modules.telemetry.services.mist_ws_manager import MistWsManager
    from app.services.mist_service_factory import create_mist_service

    config = await SystemConfig.get_config()

    if not config.telemetry_enabled:
        raise ValueError("Telemetry is not enabled in settings")
    if not config.influxdb_url:
        raise ValueError("InfluxDB URL is not configured")
    if not config.influxdb_token:
        raise ValueError("InfluxDB token is not configured")

    # 1. Core services
    telemetry_mod._latest_cache = LatestValueCache()
    telemetry_mod._client_cache = LatestClientCache()
    telemetry_mod._cov_filter = CoVFilter()
    telemetry_mod._influxdb_service = InfluxDBService(
        url=config.influxdb_url,
        token=decrypt_sensitive_data(config.influxdb_token),
        org=config.influxdb_org or "mist_automation",
        bucket=config.influxdb_bucket or "mist_telemetry",
    )
    await telemetry_mod._influxdb_service.start()

    # 2. Ingestion service (shared queue for both device + client WS managers)
    org_id = config.mist_org_id or ""
    telemetry_mod._ingestion_service = IngestionService(
        influxdb=telemetry_mod._influxdb_service,
        cache=telemetry_mod._latest_cache,
        cov_filter=telemetry_mod._cov_filter,
        org_id=org_id,
        client_cache=telemetry_mod._client_cache,
    )
    await telemetry_mod._ingestion_service.start()

    # 3. WebSocket managers — both share the same queue
    site_ids: list[str] = []
    if org_id:
        mist = await create_mist_service()
        api_session = mist.get_session()
        resp = await mistapi.arun(
            mistapi.api.v1.orgs.sites.listOrgSites, api_session, org_id, limit=1000
        )
        site_ids = [s["id"] for s in (resp.data or [])]
        if site_ids:
            shared_queue = telemetry_mod._ingestion_service.get_queue()

            telemetry_mod._ws_manager = MistWsManager(
                api_session=api_session,
                message_queue=shared_queue,
            )
            await telemetry_mod._ws_manager.start(site_ids)

            telemetry_mod._client_ws_manager = ClientWsManager(
                api_session=api_session,
                message_queue=shared_queue,
            )
            await telemetry_mod._client_ws_manager.start(site_ids)

    logger.info(
        "telemetry_started",
        sites=len(site_ids),
        ws_connections=telemetry_mod._ws_manager.get_status()["connections"] if telemetry_mod._ws_manager else 0,
        client_ws_connections=telemetry_mod._client_ws_manager.get_status()["connections"] if telemetry_mod._client_ws_manager else 0,
    )

    return {
        "sites": len(site_ids),
        "connections": telemetry_mod._ws_manager.get_status()["connections"] if telemetry_mod._ws_manager else 0,
    }


async def stop_telemetry_pipeline() -> None:
    """Stop the full telemetry pipeline and clear all singletons."""
    import app.modules.telemetry as telemetry_mod

    if telemetry_mod._client_ws_manager:
        await telemetry_mod._client_ws_manager.stop()
        telemetry_mod._client_ws_manager = None
    if telemetry_mod._ws_manager:
        await telemetry_mod._ws_manager.stop()
        telemetry_mod._ws_manager = None
    if telemetry_mod._ingestion_service:
        await telemetry_mod._ingestion_service.stop()
        telemetry_mod._ingestion_service = None
    if telemetry_mod._influxdb_service:
        await telemetry_mod._influxdb_service.stop()
        telemetry_mod._influxdb_service = None
    telemetry_mod._latest_cache = None
    telemetry_mod._client_cache = None
    telemetry_mod._cov_filter = None
    logger.info("telemetry_stopped")
```

- [ ] **Step 4: Run existing tests**

```bash
cd backend
.venv/bin/pytest tests/unit/ -v
```
Expected: all unit tests pass.

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/modules/telemetry/services/client_ws_manager.py \
        app/modules/telemetry/__init__.py \
        app/modules/telemetry/services/lifecycle.py
git commit -m "feat(telemetry): add ClientWsManager and wire client_cache into pipeline lifecycle"
```

---

## Task 5: Schemas + REST Endpoints

**Files:**
- Modify: `backend/app/modules/telemetry/schemas.py`
- Modify: `backend/app/modules/telemetry/router.py`

- [ ] **Step 1: Add `"client_stats"` to `ALLOWED_MEASUREMENTS` in `schemas.py`**

In `schemas.py`, find the `ALLOWED_MEASUREMENTS` frozenset and add `"client_stats"`:

```python
ALLOWED_MEASUREMENTS = frozenset(
    {
        "device_summary",
        "radio_stats",
        "port_stats",
        "module_stats",
        "gateway_wan",
        "gateway_health",
        "gateway_spu",
        "gateway_resources",
        "gateway_cluster",
        "gateway_dhcp",
        "switch_dhcp",
        "client_stats",   # ← add this line
    }
)
```

- [ ] **Step 2: Add client Pydantic models to `schemas.py`**

Append to the end of `schemas.py`:

```python
# ── Client telemetry models ──────────────────────────────────────────────

class ClientStatRecord(BaseModel):
    """A single wireless client's latest stats from LatestClientCache."""
    mac: str
    site_id: str
    ap_mac: str
    ssid: str
    band: str
    auth_type: str
    hostname: str = ""
    ip: str = ""
    manufacture: str = ""
    family: str = ""
    model: str = ""
    os: str = ""
    group: str = ""
    vlan_id: str = ""
    proto: str = ""
    username: str = ""
    rssi: float | None = None
    snr: float | None = None
    channel: int | None = None
    tx_rate: float | None = None
    rx_rate: float | None = None
    tx_bps: int = 0
    rx_bps: int = 0
    tx_bytes: int = 0
    rx_bytes: int = 0
    uptime: int = 0
    idle_time: float = 0.0
    is_guest: bool = False
    dual_band: bool = False
    last_seen: float | None = None
    fresh: bool = False


class ClientSiteSummary(BaseModel):
    """Aggregate client stats for a site (from LatestClientCache)."""
    total_clients: int = 0
    avg_rssi: float = 0.0
    band_counts: dict[str, int] = Field(default_factory=dict)
    total_tx_bps: int = 0
    total_rx_bps: int = 0


class ClientListResponse(BaseModel):
    """Response for GET /telemetry/scope/clients."""
    clients: list[ClientStatRecord] = Field(default_factory=list)
    total: int = 0
```

- [ ] **Step 3: Add client endpoints to `router.py`**

Add the following imports to the existing import block at the top of `router.py`:

```python
from app.modules.telemetry.schemas import (
    ...existing imports...,
    ClientListResponse,
    ClientSiteSummary,
    ClientStatRecord,
)
```

Then add these three endpoints anywhere after the existing `/scope/devices` endpoint:

```python
# ── Client scope endpoints ──────────────────────────────────────────────

@router.get("/scope/clients/summary", response_model=ClientSiteSummary)
async def get_scope_clients_summary(
    site_id: str | None = Query(None, description="Site UUID to filter by"),
    _current_user: User = Depends(require_impact_role),
) -> ClientSiteSummary:
    """Return aggregate wireless client stats from the in-memory client cache.
    Zero-latency. Returns org-wide stats when site_id is omitted.
    """
    import app.modules.telemetry as telemetry_mod

    if site_id is not None and not _UUID_RE.match(site_id):
        raise HTTPException(status_code=400, detail="Invalid site_id format")
    if telemetry_mod._client_cache is None:
        return ClientSiteSummary()

    if site_id:
        raw = telemetry_mod._client_cache.get_site_summary(site_id)
    else:
        # Org-wide: aggregate across all sites by passing a sentinel that matches everything
        # We iterate entries directly for org-wide aggregation
        all_entries = telemetry_mod._client_cache.get_all_entries()
        import time as _time_mod
        now = _time_mod.time()
        clients = [
            e["stats"] for e in all_entries.values()
            if now - e["updated_at"] < 120
        ]
        if not clients:
            return ClientSiteSummary()
        rssiz = [float(c["rssi"]) for c in clients if c.get("rssi") is not None]
        band_counts: dict[str, int] = {}
        for c in clients:
            band = str(c.get("band") or "")
            if band:
                band_counts[band] = band_counts.get(band, 0) + 1
        raw = {
            "total_clients": len(clients),
            "avg_rssi": round(sum(rssiz) / len(rssiz), 1) if rssiz else 0.0,
            "band_counts": band_counts,
            "total_tx_bps": sum(int(c.get("tx_bps") or 0) for c in clients),
            "total_rx_bps": sum(int(c.get("rx_bps") or 0) for c in clients),
        }

    return ClientSiteSummary(**raw)


@router.get("/scope/clients", response_model=ClientListResponse)
async def get_scope_clients(
    site_id: str = Query(..., description="Site UUID"),
    _current_user: User = Depends(require_impact_role),
) -> ClientListResponse:
    """Return all cached wireless clients for a site. Zero-latency."""
    import app.modules.telemetry as telemetry_mod

    if not _UUID_RE.match(site_id):
        raise HTTPException(status_code=400, detail="Invalid site_id format")
    if telemetry_mod._client_cache is None:
        return ClientListResponse()

    now = _time.time()
    raw_entries = telemetry_mod._client_cache.get_all_entries()
    clients: list[ClientStatRecord] = []

    for mac, entry in raw_entries.items():
        stats = entry.get("stats", {})
        if stats.get("site_id") != site_id:
            continue
        fresh = (now - entry.get("updated_at", 0)) < 120
        clients.append(
            ClientStatRecord(
                mac=mac,
                site_id=site_id,
                ap_mac=stats.get("ap_mac") or "",
                ssid=stats.get("ssid") or "",
                band=str(stats.get("band") or ""),
                auth_type="eap" if "EAP" in (stats.get("key_mgmt") or "").upper() else "psk",
                hostname=stats.get("hostname") or "",
                ip=stats.get("ip") or "",
                manufacture=stats.get("manufacture") or "",
                family=stats.get("family") or "",
                model=stats.get("model") or "",
                os=stats.get("os") or "",
                group=stats.get("group") or "",
                vlan_id=str(stats.get("vlan_id") or ""),
                proto=stats.get("proto") or "",
                username=stats.get("username") or "",
                rssi=stats.get("rssi"),
                snr=stats.get("snr"),
                channel=stats.get("channel"),
                tx_rate=stats.get("tx_rate"),
                rx_rate=stats.get("rx_rate"),
                tx_bps=int(stats.get("tx_bps") or 0),
                rx_bps=int(stats.get("rx_bps") or 0),
                tx_bytes=int(stats.get("tx_bytes") or 0),
                rx_bytes=int(stats.get("rx_bytes") or 0),
                uptime=int(stats.get("uptime") or 0),
                idle_time=float(stats.get("idle_time") or 0.0),
                is_guest=bool(stats.get("is_guest")),
                dual_band=bool(stats.get("dual_band")),
                last_seen=stats.get("last_seen"),
                fresh=fresh,
            )
        )

    clients.sort(key=lambda c: c.rssi or 0, reverse=True)  # best signal first
    return ClientListResponse(clients=clients, total=len(clients))


@router.get("/query/clients/range", response_model=RangeQueryResponse)
async def query_clients_range(
    mac: str = Query(..., description="Client MAC address"),
    site_id: str = Query(..., description="Site UUID"),
    start: str = Query("-1h", description="Range start (e.g., -1h, -30m)"),
    end: str = Query("now()", description="Range end"),
    _current_user: User = Depends(require_impact_role),
) -> RangeQueryResponse:
    """Query historical time-range data for a single wireless client from InfluxDB."""
    import app.modules.telemetry as telemetry_mod

    if not _MAC_RE.match(mac):
        raise HTTPException(status_code=400, detail="Invalid MAC address format")
    mac_clean = mac.lower().replace(":", "")
    if not _UUID_RE.match(site_id):
        raise HTTPException(status_code=400, detail="Invalid site_id format")
    if end != "now()" and not _DURATION_RE.match(end):
        raise HTTPException(status_code=400, detail="Invalid end parameter")
    if not _DURATION_RE.match(start):
        raise HTTPException(status_code=400, detail="Invalid start parameter")
    if not telemetry_mod._influxdb_service:
        raise HTTPException(status_code=503, detail="Telemetry service not available")

    # query_range filters on r.mac == mac_clean, which matches client_stats.mac tag
    points = await telemetry_mod._influxdb_service.query_range(
        mac_clean, "client_stats", start, end
    )
    return RangeQueryResponse(
        mac=mac_clean,
        measurement="client_stats",
        start=start,
        end=end,
        points=points,
        count=len(points),
    )
```

- [ ] **Step 4: Update `/status` endpoint to include client pipeline stats**

In `router.py`, find the `get_telemetry_status` function and replace its return dict with:

```python
    return {
        "enabled": telemetry_mod._influxdb_service is not None,
        "influxdb": telemetry_mod._influxdb_service.get_stats() if telemetry_mod._influxdb_service else None,
        "cache_size": telemetry_mod._latest_cache.size() if telemetry_mod._latest_cache else 0,
        "client_cache_size": telemetry_mod._client_cache.size() if telemetry_mod._client_cache else 0,
        "websocket": telemetry_mod._ws_manager.get_status() if telemetry_mod._ws_manager else None,
        "client_websocket": telemetry_mod._client_ws_manager.get_status() if telemetry_mod._client_ws_manager else None,
        "ingestion": telemetry_mod._ingestion_service.get_stats() if telemetry_mod._ingestion_service else None,
    }
```

- [ ] **Step 5: Run lint + type check**

```bash
cd backend
.venv/bin/ruff check app/modules/telemetry/
.venv/bin/mypy app/modules/telemetry/
```
Fix any issues reported before continuing.

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/modules/telemetry/schemas.py app/modules/telemetry/router.py
git commit -m "feat(telemetry): add client scope/query REST endpoints and client Pydantic schemas"
```

---

## Task 6: Frontend — Models + Service

**Files:**
- Modify: `frontend/src/app/features/telemetry/models.ts`
- Modify: `frontend/src/app/features/telemetry/telemetry.service.ts`

- [ ] **Step 1: Add client models to `models.ts`**

Append to `frontend/src/app/features/telemetry/models.ts`:

```typescript
// ── Client telemetry ────────────────────────────────────────────────────

export interface ClientSiteSummary {
  total_clients: number;
  avg_rssi: number;
  band_counts: Record<string, number>;
  total_tx_bps: number;
  total_rx_bps: number;
}

export interface ClientStatRecord {
  mac: string;
  site_id: string;
  ap_mac: string;
  ssid: string;
  band: string;
  auth_type: 'psk' | 'eap' | string;
  hostname: string;
  ip: string;
  manufacture: string;
  family: string;
  model: string;
  os: string;
  group: string;
  vlan_id: string;
  proto: string;
  username: string;
  rssi: number | null;
  snr: number | null;
  channel: number | null;
  tx_rate: number | null;
  rx_rate: number | null;
  tx_bps: number;
  rx_bps: number;
  tx_bytes: number;
  rx_bytes: number;
  uptime: number;
  idle_time: number;
  is_guest: boolean;
  dual_band: boolean;
  last_seen: number | null;
  fresh: boolean;
}

export interface ClientListResponse {
  clients: ClientStatRecord[];
  total: number;
}
```

- [ ] **Step 2: Add service methods to `telemetry.service.ts`**

In `TelemetryService`, add these three methods after the existing `getScopeDevices` method:

```typescript
  getSiteClients(siteId: string): Observable<ClientListResponse> {
    return this.api.get<ClientListResponse>('/telemetry/scope/clients', { site_id: siteId });
  }

  getSiteClientsSummary(siteId?: string): Observable<ClientSiteSummary> {
    const params: Record<string, string> = {};
    if (siteId) params['site_id'] = siteId;
    return this.api.get<ClientSiteSummary>('/telemetry/scope/clients/summary', params);
  }

  queryClientRange(clientMac: string, siteId: string, start: string, end: string): Observable<RangeResult> {
    return this.api.get<RangeResult>('/telemetry/query/clients/range', {
      mac: clientMac,
      site_id: siteId,
      start,
      end,
    });
  }
```

Also add the new model imports to the import block at the top of `telemetry.service.ts`:

```typescript
import {
  ScopeSummary,
  ScopeDevices,
  ScopeSites,
  LatestStats,
  AggregateResult,
  RangeResult,
  DeviceLiveEvent,
  SiteUpdateEvent,
  OrgUpdateEvent,
  TimeRange,
  ClientListResponse,   // ← add
  ClientSiteSummary,    // ← add
} from './models';
```

- [ ] **Step 3: Commit**

```bash
cd frontend
git add src/app/features/telemetry/models.ts src/app/features/telemetry/telemetry.service.ts
git commit -m "feat(telemetry): add client TypeScript models and TelemetryService methods"
```

---

## Task 7: TelemetryClientsComponent

**Files:**
- Create: `frontend/src/app/features/telemetry/clients/telemetry-clients.component.ts`
- Create: `frontend/src/app/features/telemetry/clients/telemetry-clients.component.html`
- Create: `frontend/src/app/features/telemetry/clients/telemetry-clients.component.scss`

- [ ] **Step 1: Create the component TS**

```typescript
// frontend/src/app/features/telemetry/clients/telemetry-clients.component.ts
import {
  Component,
  DestroyRef,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { DecimalPipe, DatePipe } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription, debounceTime, forkJoin } from 'rxjs';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { BaseChartDirective } from 'ng2-charts';
import { Chart, registerables } from 'chart.js';
import type { ChartConfiguration } from 'chart.js';
import 'chartjs-adapter-date-fns';
import { TelemetryService, TIME_RANGE_MAP, WINDOW_MAP } from '../telemetry.service';
import {
  TimeRange,
  ClientListResponse,
  ClientSiteSummary,
  ClientStatRecord,
  AggregateResult,
  ScopeSite,
} from '../models';

Chart.register(...registerables);

@Component({
  selector: 'app-telemetry-clients',
  standalone: true,
  imports: [
    DecimalPipe,
    DatePipe,
    ReactiveFormsModule,
    RouterModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatTableModule,
    BaseChartDirective,
  ],
  templateUrl: './telemetry-clients.component.html',
  styleUrl: './telemetry-clients.component.scss',
})
export class TelemetryClientsComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly telemetryService = inject(TelemetryService);

  readonly siteId = signal('');
  readonly siteName = signal('');
  readonly timeRange = signal<TimeRange>('1h');
  readonly loading = signal(false);
  readonly summary = signal<ClientSiteSummary | null>(null);
  readonly clientsResponse = signal<ClientListResponse | null>(null);

  readonly searchCtrl = new FormControl('');
  private readonly searchTerm = signal('');

  readonly timeRanges: TimeRange[] = ['1h', '6h', '24h'];
  readonly clientColumns = ['hostname', 'mac', 'ap_mac', 'band', 'channel', 'rssi', 'snr',
                            'tx_bps', 'rx_bps', 'tx_rate', 'manufacture', 'auth_type', 'last_seen'];

  // Filter chips: '' | 'psk' | 'eap'
  readonly activeAuthType = signal('');

  readonly filteredClients = computed(() => {
    const all = this.clientsResponse()?.clients ?? [];
    const term = this.searchTerm().toLowerCase();
    const auth = this.activeAuthType();
    return all.filter((c) => {
      if (auth && c.auth_type !== auth) return false;
      if (!term) return true;
      return (
        (c.hostname || '').toLowerCase().includes(term) ||
        c.mac.includes(term) ||
        (c.ap_mac || '').includes(term) ||
        (c.manufacture || '').toLowerCase().includes(term)
      );
    });
  });

  readonly bandEntries = computed(() => {
    const counts = this.summary()?.band_counts ?? {};
    return Object.entries(counts).map(([band, count]) => ({
      label: band === '24' ? '2.4G' : band === '5' ? '5G' : band === '6' ? '6G' : band,
      count,
    }));
  });

  readonly countsByAuth = computed(() => {
    const all = this.clientsResponse()?.clients ?? [];
    return {
      psk: all.filter((c) => c.auth_type === 'psk').length,
      eap: all.filter((c) => c.auth_type === 'eap').length,
    };
  });

  // Charts
  readonly countChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly rssiChart = signal<ChartConfiguration<'line'> | null>(null);

  private wsSub?: Subscription;

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id') ?? '';
      this.siteId.set(id);
      this._loadAll();
      this._subscribeWs(id);
    });

    this.searchCtrl.valueChanges
      .pipe(debounceTime(200), takeUntilDestroyed(this.destroyRef))
      .subscribe((v) => this.searchTerm.set(v ?? ''));
  }

  ngOnDestroy(): void {
    this.wsSub?.unsubscribe();
  }

  setTimeRange(tr: TimeRange): void {
    this.timeRange.set(tr);
    this._loadCharts();
  }

  toggleAuthType(auth: string): void {
    this.activeAuthType.set(this.activeAuthType() === auth ? '' : auth);
  }

  private _loadAll(): void {
    const siteId = this.siteId();
    if (!siteId) return;
    this.loading.set(true);

    forkJoin({
      summary: this.telemetryService.getSiteClientsSummary(siteId),
      clients: this.telemetryService.getSiteClients(siteId),
      sites: this.telemetryService.getScopeSites(),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ summary, clients, sites }) => {
          this.summary.set(summary);
          this.clientsResponse.set(clients);
          const site = sites.sites.find((s: ScopeSite) => s.site_id === siteId);
          if (site) this.siteName.set(site.site_name);
          this.loading.set(false);
          this._loadCharts();
        },
        error: () => this.loading.set(false),
      });
  }

  private _loadCharts(): void {
    const siteId = this.siteId();
    if (!siteId) return;
    const tr = this.timeRange();

    forkJoin({
      count: this.telemetryService.queryAggregate({
        siteId,
        measurement: 'client_stats',
        field: 'rssi',
        agg: 'count',
        timeRange: tr,
      }),
      rssi: this.telemetryService.queryAggregate({
        siteId,
        measurement: 'client_stats',
        field: 'rssi',
        agg: 'mean',
        timeRange: tr,
      }),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(({ count, rssi }) => {
        this.countChart.set(this._buildLineChart(count, 'Clients', '#4caf50'));
        this.rssiChart.set(this._buildLineChart(rssi, 'Avg RSSI (dBm)', '#2196f3'));
      });
  }

  private _buildLineChart(
    result: AggregateResult,
    label: string,
    color: string,
  ): ChartConfiguration<'line'> {
    const labels = result.points.map((p) => new Date(p['_time'] as string));
    const data = result.points.map((p) => p['_value'] as number);
    return {
      data: {
        labels,
        datasets: [{ label, data, borderColor: color, backgroundColor: color + '22',
                     tension: 0.3, pointRadius: 0, fill: true }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { type: 'time', time: { unit: 'minute' } },
          y: { beginAtZero: false },
        },
      },
    };
  }

  private _subscribeWs(siteId: string): void {
    this.wsSub?.unsubscribe();
    this.wsSub = this.telemetryService
      .subscribeToSite(siteId)
      .pipe(debounceTime(5000))
      .subscribe(() => {
        this.telemetryService.getSiteClientsSummary(siteId).subscribe((s) => this.summary.set(s));
        this.telemetryService.getSiteClients(siteId).subscribe((c) => this.clientsResponse.set(c));
      });
  }
}
```

- [ ] **Step 2: Create the HTML template**

```html
<!-- frontend/src/app/features/telemetry/clients/telemetry-clients.component.html -->
<div class="clients-page">
  @if (loading()) {
    <mat-progress-bar mode="indeterminate" />
  }

  <!-- Breadcrumb -->
  <div class="page-header">
    <div class="breadcrumb">
      <a routerLink="/telemetry">Telemetry</a>
      <mat-icon class="sep">chevron_right</mat-icon>
      <a [routerLink]="['/telemetry/site', siteId()]">{{ siteName() }}</a>
      <mat-icon class="sep">chevron_right</mat-icon>
      <span>Clients</span>
    </div>
    <!-- Time range picker -->
    <div class="time-range-picker">
      @for (tr of timeRanges; track tr) {
        <button mat-stroked-button [class.active]="timeRange() === tr" (click)="setTimeRange(tr)">
          {{ tr }}
        </button>
      }
    </div>
  </div>

  <!-- KPI cards -->
  @if (summary()) {
    <div class="kpi-row">
      <div class="kpi-card">
        <div class="kpi-label">Total Clients</div>
        <div class="kpi-value">{{ summary()!.total_clients | number }}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Avg RSSI</div>
        <div class="kpi-value">{{ summary()!.avg_rssi | number: '1.0-0' }} dBm</div>
      </div>
      @for (b of bandEntries(); track b.label) {
        <div class="kpi-card">
          <div class="kpi-label">{{ b.label }}</div>
          <div class="kpi-value">{{ b.count }}</div>
        </div>
      }
      <div class="kpi-card">
        <div class="kpi-label">TX</div>
        <div class="kpi-value">{{ summary()!.total_tx_bps | number }} bps</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">RX</div>
        <div class="kpi-value">{{ summary()!.total_rx_bps | number }} bps</div>
      </div>
    </div>
  }

  <!-- Charts -->
  <div class="chart-row">
    @if (countChart()) {
      <div class="chart-container">
        <div class="chart-title">Client Count</div>
        <canvas baseChart [data]="countChart()!.data" [options]="countChart()!.options" type="line"></canvas>
      </div>
    }
    @if (rssiChart()) {
      <div class="chart-container">
        <div class="chart-title">Avg RSSI (dBm)</div>
        <canvas baseChart [data]="rssiChart()!.data" [options]="rssiChart()!.options" type="line"></canvas>
      </div>
    }
  </div>

  <!-- Filter row -->
  <div class="filter-row">
    <div class="chip-row">
      <button mat-stroked-button [class.active]="activeAuthType() === ''" (click)="toggleAuthType('')">
        All ({{ clientsResponse()?.total ?? 0 }})
      </button>
      <button mat-stroked-button [class.active]="activeAuthType() === 'psk'" (click)="toggleAuthType('psk')">
        PSK ({{ countsByAuth().psk }})
      </button>
      <button mat-stroked-button [class.active]="activeAuthType() === 'eap'" (click)="toggleAuthType('eap')">
        802.1X ({{ countsByAuth().eap }})
      </button>
    </div>
    <mat-form-field appearance="outline" class="search-field">
      <mat-label>Search hostname / MAC / AP / manufacturer</mat-label>
      <input matInput [formControl]="searchCtrl" />
      <mat-icon matSuffix>search</mat-icon>
    </mat-form-field>
  </div>

  <!-- Client table -->
  <div class="table-card">
    <table mat-table [dataSource]="filteredClients()">
      <ng-container matColumnDef="hostname">
        <th mat-header-cell *matHeaderCellDef>Hostname</th>
        <td mat-cell *matCellDef="let c">{{ c.hostname || c.mac }}</td>
      </ng-container>

      <ng-container matColumnDef="mac">
        <th mat-header-cell *matHeaderCellDef>MAC</th>
        <td mat-cell *matCellDef="let c" class="monospace">{{ c.mac }}</td>
      </ng-container>

      <ng-container matColumnDef="ap_mac">
        <th mat-header-cell *matHeaderCellDef>AP</th>
        <td mat-cell *matCellDef="let c" class="monospace">{{ c.ap_mac }}</td>
      </ng-container>

      <ng-container matColumnDef="band">
        <th mat-header-cell *matHeaderCellDef>Band</th>
        <td mat-cell *matCellDef="let c">
          {{ c.band === '24' ? '2.4G' : c.band === '5' ? '5G' : c.band === '6' ? '6G' : c.band }}
        </td>
      </ng-container>

      <ng-container matColumnDef="channel">
        <th mat-header-cell *matHeaderCellDef>Ch</th>
        <td mat-cell *matCellDef="let c">{{ c.channel }}</td>
      </ng-container>

      <ng-container matColumnDef="rssi">
        <th mat-header-cell *matHeaderCellDef>RSSI</th>
        <td mat-cell *matCellDef="let c">{{ c.rssi }} dBm</td>
      </ng-container>

      <ng-container matColumnDef="snr">
        <th mat-header-cell *matHeaderCellDef>SNR</th>
        <td mat-cell *matCellDef="let c">{{ c.snr }}</td>
      </ng-container>

      <ng-container matColumnDef="tx_bps">
        <th mat-header-cell *matHeaderCellDef>TX bps</th>
        <td mat-cell *matCellDef="let c">{{ c.tx_bps | number }}</td>
      </ng-container>

      <ng-container matColumnDef="rx_bps">
        <th mat-header-cell *matHeaderCellDef>RX bps</th>
        <td mat-cell *matCellDef="let c">{{ c.rx_bps | number }}</td>
      </ng-container>

      <ng-container matColumnDef="tx_rate">
        <th mat-header-cell *matHeaderCellDef>TX Rate</th>
        <td mat-cell *matCellDef="let c">{{ c.tx_rate }} Mbps</td>
      </ng-container>

      <ng-container matColumnDef="manufacture">
        <th mat-header-cell *matHeaderCellDef>Manufacturer</th>
        <td mat-cell *matCellDef="let c">{{ c.manufacture }}</td>
      </ng-container>

      <ng-container matColumnDef="auth_type">
        <th mat-header-cell *matHeaderCellDef>Auth</th>
        <td mat-cell *matCellDef="let c">{{ c.auth_type === 'eap' ? '802.1X' : 'PSK' }}</td>
      </ng-container>

      <ng-container matColumnDef="last_seen">
        <th mat-header-cell *matHeaderCellDef>Last Seen</th>
        <td mat-cell *matCellDef="let c">
          @if (c.last_seen) {
            {{ c.last_seen * 1000 | date: 'HH:mm:ss' }}
          }
        </td>
      </ng-container>

      <tr mat-header-row *matHeaderRowDef="clientColumns"></tr>
      <tr mat-row *matRowDef="let row; columns: clientColumns;"></tr>
    </table>
  </div>
</div>
```

- [ ] **Step 3: Create the SCSS**

```scss
// frontend/src/app/features/telemetry/clients/telemetry-clients.component.scss
.clients-page {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 14px;

  a { color: var(--app-primary); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .sep { font-size: 16px; color: var(--app-neutral-text); }
}

.time-range-picker {
  display: flex;
  gap: 4px;

  button.active {
    background-color: var(--app-primary);
    color: white;
  }
}

.kpi-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.kpi-card {
  background: var(--app-canvas-card);
  border: 1px solid var(--app-neutral-border);
  border-radius: 8px;
  padding: 12px 16px;
  min-width: 100px;

  .kpi-label { font-size: 11px; color: var(--app-neutral-text); text-transform: uppercase; }
  .kpi-value { font-size: 22px; font-weight: 600; margin-top: 4px; }
}

.chart-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
}

.chart-container {
  background: var(--app-canvas-card);
  border: 1px solid var(--app-neutral-border);
  border-radius: 8px;
  padding: 12px;
  max-height: 220px;

  .chart-title { font-size: 12px; font-weight: 500; margin-bottom: 8px; }
  canvas { max-height: 180px; }
}

.filter-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.chip-row {
  display: flex;
  gap: 6px;

  button.active {
    background-color: var(--app-primary);
    color: white;
  }
}

.search-field { min-width: 320px; }

.monospace { font-family: monospace; font-size: 12px; }
```

- [ ] **Step 4: Commit**

```bash
cd frontend
git add src/app/features/telemetry/clients/
git commit -m "feat(telemetry): add TelemetryClientsComponent with KPI cards, charts, and searchable client table"
```

---

## Task 8: Route Registration

**Files:**
- Modify: `frontend/src/app/features/telemetry/telemetry.routes.ts`

- [ ] **Step 1: Add the clients route**

In `telemetry.routes.ts`, add the new route after the `site/:id` entry:

```typescript
const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./scope/telemetry-scope.component').then((m) => m.TelemetryScopeComponent),
  },
  {
    path: 'site/:id',
    loadComponent: () =>
      import('./site/telemetry-site.component').then((m) => m.TelemetrySiteComponent),
  },
  {
    path: 'site/:id/clients',
    loadComponent: () =>
      import('./clients/telemetry-clients.component').then((m) => m.TelemetryClientsComponent),
  },
  {
    path: 'device/:mac',
    loadComponent: () =>
      import('./device/telemetry-device.component').then((m) => m.TelemetryDeviceComponent),
  },
];

export default routes;
```

- [ ] **Step 2: Commit**

```bash
cd frontend
git add src/app/features/telemetry/telemetry.routes.ts
git commit -m "feat(telemetry): register /telemetry/site/:id/clients lazy route"
```

---

## Task 9: Site View — Clients Summary Card

**Files:**
- Modify: `frontend/src/app/features/telemetry/site/telemetry-site.component.ts`
- Modify: `frontend/src/app/features/telemetry/site/telemetry-site.component.html`

- [ ] **Step 1: Add `clientSummary` signal and loading to the TS component**

In `telemetry-site.component.ts`:

1. Add the `ClientSiteSummary` import to the models import block:
```typescript
import {
  TimeRange,
  ScopeSummary,
  ScopeDevices,
  DeviceSummaryRecord,
  APScopeSummary,
  SwitchScopeSummary,
  GatewayScopeSummary,
  BandSummary,
  AggregateResult,
  ClientSiteSummary,   // ← add
} from '../models';
```

2. Add a new signal after the existing ones (e.g. after `readonly devices = signal<ScopeDevices | null>(null);`):
```typescript
  readonly clientSummary = signal<ClientSiteSummary | null>(null);
```

3. In the existing data-loading method (the one that calls `getScopeSummary` and `getScopeDevices`), add `getSiteClientsSummary` to the `forkJoin`. Find the existing `forkJoin` call that loads data (look for the method that calls `this.telemetryService.getScopeSummary`) and add the client summary call alongside:

```typescript
// Find the existing forkJoin block and add clientSummary:
forkJoin({
  summary: this.telemetryService.getScopeSummary(siteId),
  devices: this.telemetryService.getScopeDevices(siteId),
  sites: this.telemetryService.getScopeSites(),
  clientSummary: this.telemetryService.getSiteClientsSummary(siteId),  // ← add
})
  .pipe(takeUntilDestroyed(this.destroyRef))
  .subscribe({
    next: ({ summary, devices, sites, clientSummary }) => {
      this.summary.set(summary);
      this.devices.set(devices);
      // existing site name resolution code ...
      this.clientSummary.set(clientSummary);   // ← add
      // rest of existing code ...
    },
    error: () => this.loading.set(false),
  });
```

Also add `RouterModule` to the `imports` array of the `@Component` decorator if not already present (it is — it appears in the existing imports array).

- [ ] **Step 2: Add the clients section to the HTML**

At the end of `telemetry-site.component.html`, before the `</div>` that closes the page wrapper, add:

```html
  <!-- Clients summary section -->
  @if (clientSummary()) {
    <section class="device-section clients-section">
      <h3 class="section-title">
        Wireless Clients
        <a mat-stroked-button [routerLink]="['/telemetry/site', siteId(), 'clients']" class="view-clients-btn">
          <mat-icon>people</mat-icon>
          View Clients
        </a>
      </h3>
      <div class="kpi-row">
        <div class="kpi-card">
          <div class="kpi-label">Total</div>
          <div class="kpi-value">{{ clientSummary()!.total_clients | number }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Avg RSSI</div>
          <div class="kpi-value">{{ clientSummary()!.avg_rssi | number: '1.0-0' }} dBm</div>
        </div>
        @for (entry of clientBandEntries(); track entry.label) {
          <div class="kpi-card">
            <div class="kpi-label">{{ entry.label }}</div>
            <div class="kpi-value">{{ entry.count }}</div>
          </div>
        }
        <div class="kpi-card">
          <div class="kpi-label">Total TX</div>
          <div class="kpi-value">{{ clientSummary()!.total_tx_bps | number }} bps</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Total RX</div>
          <div class="kpi-value">{{ clientSummary()!.total_rx_bps | number }} bps</div>
        </div>
      </div>
    </section>
  }
```

- [ ] **Step 3: Add `clientBandEntries` computed in the TS component**

Add after the existing computed properties:

```typescript
  readonly clientBandEntries = computed(() => {
    const counts = this.clientSummary()?.band_counts ?? {};
    return Object.entries(counts).map(([band, count]) => ({
      label: band === '24' ? '2.4G' : band === '5' ? '5G' : band === '6' ? '6G' : band,
      count,
    }));
  });
```

Also add `RouterModule` to imports if not already there, and add `MatIconModule` if needed for the icon in the button. Check the existing imports array — both are already present from the existing component.

- [ ] **Step 4: Commit**

```bash
cd frontend
git add src/app/features/telemetry/site/
git commit -m "feat(telemetry): add clients summary card with View Clients link to site view"
```

---

## Task 10: Scope View — Clients Section

**Files:**
- Modify: `frontend/src/app/features/telemetry/scope/telemetry-scope.component.ts`
- Modify: `frontend/src/app/features/telemetry/scope/telemetry-scope.component.html`

- [ ] **Step 1: Add `clientSummary` signal to the scope component TS**

In `telemetry-scope.component.ts`:

1. Add model import:
```typescript
import {
  TimeRange,
  ScopeSummary,
  ScopeSite,
  APScopeSummary,
  SwitchScopeSummary,
  GatewayScopeSummary,
  BandSummary,
  AggregateResult,
  ClientSiteSummary,   // ← add
} from '../models';
```

2. Add signal:
```typescript
  readonly clientSummary = signal<ClientSiteSummary | null>(null);
```

3. In the `ngOnInit` or existing data-loading method (where `getScopeSummary()` and `getScopeSites()` are called), add `getSiteClientsSummary()` to the existing `forkJoin`:

```typescript
// Find the forkJoin that loads summary + sites and add clientSummary:
forkJoin({
  summary: this.telemetryService.getScopeSummary(),
  sites: this.telemetryService.getScopeSites(),
  clientSummary: this.telemetryService.getSiteClientsSummary(),   // ← no siteId = org-wide
})
  .pipe(takeUntilDestroyed(this.destroyRef))
  .subscribe({
    next: ({ summary, sites, clientSummary }) => {
      this.summary.set(summary);
      this.sites.set(sites.sites);
      this.clientSummary.set(clientSummary);   // ← add
      this.loading.set(false);
      this._loadCharts();
    },
    error: () => this.loading.set(false),
  });
```

4. Add a `clientBandEntries` computed:
```typescript
  readonly clientBandEntries = computed(() => {
    const counts = this.clientSummary()?.band_counts ?? {};
    return Object.entries(counts).map(([band, count]) => ({
      label: band === '24' ? '2.4G' : band === '5' ? '5G' : band === '6' ? '6G' : band,
      count,
    }));
  });
```

Also ensure `RouterModule` is in the component `imports` array. The existing scope component does not use `RouterModule` — add it:
- Add `RouterModule` to the `imports` array in `@Component`
- Add `import { RouterModule } from '@angular/router';` to the imports at the top

- [ ] **Step 2: Add the Clients section to the scope HTML**

At the end of the scope HTML (before the final `</div>`), add a Clients section that mirrors the device sections:

```html
  <!-- Clients section -->
  @if (clientSummary() && clientSummary()!.total_clients > 0) {
    <section class="device-section">
      <h3 class="section-title">Wireless Clients ({{ clientSummary()!.total_clients }} active)</h3>
      <div class="kpi-row">
        <div class="kpi-card">
          <div class="kpi-label">Avg RSSI</div>
          <div class="kpi-value">{{ clientSummary()!.avg_rssi | number: '1.0-0' }} dBm</div>
        </div>
        @for (entry of clientBandEntries(); track entry.label) {
          <div class="kpi-card">
            <div class="kpi-label">{{ entry.label }}</div>
            <div class="kpi-value">{{ entry.count }}</div>
          </div>
        }
        <div class="kpi-card">
          <div class="kpi-label">Total TX</div>
          <div class="kpi-value">{{ clientSummary()!.total_tx_bps | number }} bps</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Total RX</div>
          <div class="kpi-value">{{ clientSummary()!.total_rx_bps | number }} bps</div>
        </div>
      </div>
      <p class="clients-nav-hint">
        Select a site above to view per-site client details.
      </p>
    </section>
  }
```

- [ ] **Step 3: Commit**

```bash
cd frontend
git add src/app/features/telemetry/scope/
git commit -m "feat(telemetry): add org-wide Clients section to scope view"
```

---

## Verification

After all tasks are complete, verify end-to-end:

**Backend:**
```bash
cd backend
.venv/bin/pytest tests/unit/ -v          # all unit tests pass
.venv/bin/ruff check app/modules/telemetry/
.venv/bin/mypy app/modules/telemetry/
```

**Manual backend test (with running app + Mist configured):**
1. Enable telemetry in Admin > Settings > Telemetry, configure InfluxDB
2. Call `POST /api/v1/telemetry/reconnect` (admin)
3. `GET /api/v1/telemetry/status` → verify `client_websocket.connections > 0`
4. Wait ~60s for first client messages
5. `GET /api/v1/telemetry/scope/clients/summary?site_id={id}` → verify `total_clients > 0`
6. `GET /api/v1/telemetry/scope/clients?site_id={id}` → verify client list
7. Query InfluxDB: `from(bucket:"mist_telemetry") |> range(start:-5m) |> filter(fn:(r) => r._measurement == "client_stats")` → verify data

**Frontend:**
```bash
cd frontend
npm start   # then open http://localhost:4200
```
1. Navigate to Telemetry > Site → verify Clients summary card appears at bottom
2. Click "View Clients" → verify `/telemetry/site/:id/clients` loads
3. Verify KPI cards, table with client rows, auth filter chips
4. Navigate to Telemetry (org scope) → verify Clients section at bottom
