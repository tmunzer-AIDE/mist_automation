# Telemetry UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `/telemetry` frontend section with org/site scope charts, per-device detail charts, and a live WebSocket event log — plus the backend changes that power it (switch DHCP extraction, WS broadcasting, and two new REST endpoints).

**Architecture:** Backend adds switch DHCP extraction, WS broadcast from `IngestionService` after each device update, and two new REST scope endpoints (`/telemetry/scope/summary`, `/telemetry/scope/devices`). The existing `query_aggregate` endpoint is extended to accept `org_id` as an alternative scope filter. Frontend uses `TelemetryService` for all API/WS access. `TelemetryScopeComponent` renders at both `/telemetry` and `/telemetry/site/:id`. `TelemetryDeviceComponent` renders at `/telemetry/device/:mac` with a live WebSocket log.

**Tech Stack:** Python/FastAPI, pytest-asyncio, Angular 21 (standalone + signals + zoneless), Chart.js, Angular Material, rxjs `takeUntilDestroyed`

---

## File Map

**Backend — modified:**
- `backend/app/modules/telemetry/extractors/switch_extractor.py` — add `_extract_switch_dhcp()`
- `backend/app/modules/telemetry/schemas.py` — add `switch_dhcp` to `ALLOWED_MEASUREMENTS`; add `ScopeSummaryResponse`, `ScopeDevicesResponse` schemas; make `site_id` optional in `AggregateQueryResponse`, add `org_id` field
- `backend/app/modules/telemetry/services/influxdb_service.py` — add `org_id` param to `query_aggregate()`
- `backend/app/modules/telemetry/services/ingestion_service.py` — add `switch_dhcp` to `COV_THRESHOLDS`; add `_build_device_ws_event()` helper; broadcast after write
- `backend/app/modules/telemetry/router.py` — add `org_id` param to aggregate endpoint; add `scope/summary` and `scope/devices` endpoints

**Backend — new:**
- `backend/tests/unit/test_switch_extractor.py`
- `backend/tests/unit/test_scope_endpoints.py`

**Frontend — modified:**
- `frontend/src/app/layout/sidebar/nav-items.config.ts` — add Telemetry nav item
- `frontend/src/app/app.routes.ts` — register `/telemetry` lazy route

**Frontend — new:**
- `frontend/src/app/features/telemetry/telemetry.routes.ts`
- `frontend/src/app/features/telemetry/models.ts` — all TypeScript interfaces
- `frontend/src/app/features/telemetry/telemetry.service.ts`
- `frontend/src/app/features/telemetry/scope/telemetry-scope.component.ts/.html/.scss`
- `frontend/src/app/features/telemetry/scope/components/scope-device-table/scope-device-table.component.ts/.html`
- `frontend/src/app/features/telemetry/device/telemetry-device.component.ts/.html/.scss`
- `frontend/src/app/features/telemetry/device/components/device-live-log/device-live-log.component.ts/.html`

---

## Task 1: Add `_extract_switch_dhcp()` to switch extractor

**Files:**
- Modify: `backend/app/modules/telemetry/extractors/switch_extractor.py`
- Create: `backend/tests/unit/test_switch_extractor.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_switch_extractor.py
"""Unit tests for Switch metric extractor."""

from app.modules.telemetry.extractors.switch_extractor import extract_points


def _switch_payload_with_dhcp() -> dict:
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


def _switch_payload_without_dhcp() -> dict:
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


def test_switch_dhcp_produces_one_point_per_scope():
    points = extract_points(_switch_payload_with_dhcp(), "org1", "site1")
    dhcp_points = [p for p in points if p["measurement"] == "switch_dhcp"]
    assert len(dhcp_points) == 2


def test_switch_dhcp_fields_correct():
    points = extract_points(_switch_payload_with_dhcp(), "org1", "site1")
    corp = next(p for p in points if p.get("tags", {}).get("network_name") == "Corp-LAN")
    assert corp["fields"]["num_ips"] == 200
    assert corp["fields"]["num_leased"] == 130
    assert corp["fields"]["utilization_pct"] == pytest.approx(65.0, abs=0.1)


def test_switch_dhcp_absent_produces_no_points():
    points = extract_points(_switch_payload_without_dhcp(), "org1", "site1")
    dhcp_points = [p for p in points if p["measurement"] == "switch_dhcp"]
    assert dhcp_points == []


import pytest  # noqa: E402 — needed for approx
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd backend && .venv/bin/pytest tests/unit/test_switch_extractor.py -v
```
Expected: `FAILED — ImportError` or missing measurement.

- [ ] **Step 3: Add `_extract_switch_dhcp()` to `switch_extractor.py`**

Add this function before `extract_points()`:

```python
def _extract_switch_dhcp(payload: dict, org_id: str, site_id: str, timestamp: int) -> list[dict]:
    """Build switch_dhcp data points per DHCP scope from dhcpd_stat.

    Silently produces no points when dhcpd_stat is absent (switches without DHCP server).
    """
    dhcpd_stat = payload.get("dhcpd_stat")
    if not dhcpd_stat:
        return []

    points: list[dict] = []
    for network_name, scope in dhcpd_stat.items():
        num_ips = scope.get("num_ips", 0)
        num_leased = scope.get("num_leased", 0)
        utilization_pct = round((num_leased / num_ips * 100) if num_ips > 0 else 0.0, 1)

        points.append(
            {
                "measurement": "switch_dhcp",
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
            }
        )

    return points
```

Add `points.extend(_extract_switch_dhcp(payload, org_id, site_id, timestamp))` to the `extract_points()` function body (after the existing `_extract_module_stats` call).

- [ ] **Step 4: Run tests and confirm they pass**

```bash
cd backend && .venv/bin/pytest tests/unit/test_switch_extractor.py -v
```
Expected: 3 PASSED.

- [ ] **Step 5: Add `switch_dhcp` to `ALLOWED_MEASUREMENTS` and `COV_THRESHOLDS`**

In `schemas.py`, add `"switch_dhcp"` to the `ALLOWED_MEASUREMENTS` frozenset.

In `ingestion_service.py`, add to `COV_THRESHOLDS`:
```python
"switch_dhcp": {
    "num_ips": "exact",
    "num_leased": "exact",
    "utilization_pct": 3.0,
},
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/telemetry/extractors/switch_extractor.py \
        backend/app/modules/telemetry/schemas.py \
        backend/app/modules/telemetry/services/ingestion_service.py \
        backend/tests/unit/test_switch_extractor.py
git commit -m "feat(telemetry): add switch DHCP extraction (switch_dhcp measurement)"
```

---

## Task 2: Extend `query_aggregate` to support org-level scope

**Files:**
- Modify: `backend/app/modules/telemetry/schemas.py`
- Modify: `backend/app/modules/telemetry/services/influxdb_service.py`
- Modify: `backend/app/modules/telemetry/router.py`

Org-level charts need to aggregate across all sites by filtering on `org_id` tag instead of `site_id`.

- [ ] **Step 1: Update `AggregateQueryResponse` schema**

In `schemas.py`, change:
```python
class AggregateQueryResponse(BaseModel):
    site_id: str
    ...
```
to:
```python
class AggregateQueryResponse(BaseModel):
    site_id: str | None = None
    org_id: str | None = None
    measurement: str
    field: str
    agg: str
    window: str
    points: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
```

- [ ] **Step 2: Update `InfluxDBService.query_aggregate()` to accept org_id**

Change signature from:
```python
async def query_aggregate(
    self,
    site_id: str,
    measurement: str,
    ...
```
to:
```python
async def query_aggregate(
    self,
    measurement: str,
    field: str,
    agg: str = "mean",
    window: str = "5m",
    start: str = "-1h",
    end: str = "now()",
    site_id: str | None = None,
    org_id: str | None = None,
) -> list[dict[str, Any]]:
```

Replace the scope filter line in the Flux query:
```python
# old:
f' |> filter(fn: (r) => r.site_id == "{site_id}")'

# new:
scope_filter = (
    f' |> filter(fn: (r) => r.site_id == "{site_id}")'
    if site_id
    else f' |> filter(fn: (r) => r.org_id == "{org_id}")'
)
```

And build the query using `scope_filter`:
```python
query = (
    f'from(bucket: "{self.bucket}")'
    f" |> range(start: {start}, stop: {end})"
    f' |> filter(fn: (r) => r._measurement == "{measurement}")'
    + scope_filter
    + f' |> filter(fn: (r) => r._field == "{field}")'
    f" |> aggregateWindow(every: {window}, fn: {agg}, createEmpty: false)"
)
```

Also update the `logger.warning` call to pass `site_id=site_id, org_id=org_id` instead of just `site_id=site_id`.

- [ ] **Step 3: Update the router endpoint**

In `router.py`, update `query_aggregate`:
```python
@router.get("/query/aggregate", response_model=AggregateQueryResponse)
async def query_aggregate(
    site_id: str | None = Query(None, description="Site UUID (mutually exclusive with org_id)"),
    org_id: str | None = Query(None, description="Org UUID for org-wide aggregation"),
    measurement: str = Query("device_summary", description="InfluxDB measurement name"),
    field: str = Query(..., description="Field to aggregate (e.g., cpu_util)"),
    agg: str = Query("mean", description="Aggregation function"),
    window: str = Query("5m", description="Aggregation window (e.g., 5m, 1h)"),
    start: str = Query("-1h", description="Range start"),
    end: str = Query("now()", description="Range end"),
    _current_user: User = Depends(require_impact_role),
) -> AggregateQueryResponse:
```

Add validation at the top of the handler:
```python
if not site_id and not org_id:
    raise HTTPException(status_code=400, detail="Provide either site_id or org_id")
if site_id and org_id:
    raise HTTPException(status_code=400, detail="Provide either site_id or org_id, not both")
if site_id and not _UUID_RE.match(site_id):
    raise HTTPException(status_code=400, detail="Invalid site_id format")
if org_id and not _UUID_RE.match(org_id):
    raise HTTPException(status_code=400, detail="Invalid org_id format")
```

Update the service call:
```python
points = await telemetry_mod._influxdb_service.query_aggregate(
    measurement=measurement,
    field=field,
    agg=agg,
    window=window,
    start=start,
    end=end,
    site_id=site_id,
    org_id=org_id,
)
return AggregateQueryResponse(
    site_id=site_id,
    org_id=org_id,
    measurement=measurement,
    field=field,
    agg=agg,
    window=window,
    points=points,
    count=len(points),
)
```

- [ ] **Step 4: Run existing telemetry router tests**

```bash
cd backend && .venv/bin/pytest tests/unit/test_telemetry_router.py -v
```
Expected: all existing tests still pass (they pass `site_id` which still works).

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/telemetry/schemas.py \
        backend/app/modules/telemetry/services/influxdb_service.py \
        backend/app/modules/telemetry/router.py
git commit -m "feat(telemetry): extend query_aggregate to support org_id scope"
```

---

## Task 3: Broadcast WebSocket events from IngestionService

After each device update is processed, broadcast to `telemetry:device:{mac}` if any frontend client is subscribed to that channel.

**Files:**
- Modify: `backend/app/modules/telemetry/services/ingestion_service.py`

- [ ] **Step 1: Write the failing test** (add to `test_ingestion_service.py`)

```python
# Append these to the existing test file
from unittest.mock import AsyncMock, patch


async def test_broadcast_called_for_ap_after_processing():
    """After processing an AP message, ws_manager.broadcast is awaited with correct channel."""
    from app.modules.telemetry.services.ingestion_service import IngestionService
    from app.modules.telemetry.services.influxdb_service import InfluxDBService
    from app.modules.telemetry.services.latest_value_cache import LatestValueCache
    from app.modules.telemetry.services.cov_filter import CoVFilter

    influxdb = AsyncMock(spec=InfluxDBService)
    cache = LatestValueCache()
    cov = CoVFilter()
    svc = IngestionService(influxdb, cache, cov, org_id="org1")

    ap_msg = {
        "event": "data",
        "channel": "/sites/site-uuid-1111/stats/devices",
        "data": {
            "mac": "aabbccddeeff",
            "type": "ap",
            "model": "AP43",
            "last_seen": 1774576960,
            "cpu_stat": {"idle": 70},
            "memory_stat": {"mem_used_kb": 100000, "mem_total_kb": 400000},
            "num_clients": 5,
            "uptime": 3600,
        },
    }

    mock_broadcast = AsyncMock()
    with patch("app.modules.telemetry.services.ingestion_service.ws_manager") as mock_ws:
        mock_ws.broadcast = mock_broadcast
        await svc._process_message(ap_msg)

    mock_broadcast.assert_awaited_once()
    call_args = mock_broadcast.call_args
    assert call_args[0][0] == "telemetry:device:aabbccddeeff"
    payload = call_args[0][1]
    assert payload["device_type"] == "ap"
    assert "summary" in payload
    assert "bands" in payload


async def test_no_broadcast_when_mac_missing():
    """Messages without a MAC address do not trigger a broadcast."""
    from app.modules.telemetry.services.ingestion_service import IngestionService
    from app.modules.telemetry.services.influxdb_service import InfluxDBService
    from app.modules.telemetry.services.latest_value_cache import LatestValueCache
    from app.modules.telemetry.services.cov_filter import CoVFilter

    influxdb = AsyncMock(spec=InfluxDBService)
    cache = LatestValueCache()
    cov = CoVFilter()
    svc = IngestionService(influxdb, cache, cov, org_id="org1")

    msg = {
        "event": "data",
        "channel": "/sites/site-uuid-1111/stats/devices",
        "data": {"type": "ap", "model": "AP43"},  # no mac
    }

    mock_broadcast = AsyncMock()
    with patch("app.modules.telemetry.services.ingestion_service.ws_manager") as mock_ws:
        mock_ws.broadcast = mock_broadcast
        await svc._process_message(msg)

    mock_broadcast.assert_not_awaited()
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd backend && .venv/bin/pytest tests/unit/test_ingestion_service.py::test_broadcast_called_for_ap_after_processing -v
```
Expected: FAILED — `ws_manager` import not found or broadcast not called.

- [ ] **Step 3: Add `_build_device_ws_event()` helper and broadcast call to `ingestion_service.py`**

At the top of `ingestion_service.py`, add the import:
```python
from app.core.websocket import ws_manager
```

Add the helper function after `_build_cov_key()`:
```python
def _build_device_ws_event(payload: dict[str, Any], device_type: str) -> dict[str, Any]:
    """Build the WebSocket broadcast payload from a raw device stats message.

    This is the live-log payload consumed by TelemetryDeviceComponent.
    """
    import time as _time

    cpu_stat = payload.get("cpu_stat", {})
    memory_stat = payload.get("memory_stat", {})

    if device_type == "gateway":
        cpu_util = 100 - int(cpu_stat.get("idle", 100))
    else:
        cpu_util = 100 - int(cpu_stat.get("idle", 100))

    mem_total = memory_stat.get("mem_total_kb", 0)
    mem_used = memory_stat.get("mem_used_kb", 0)
    if mem_total:
        mem_usage = round(mem_used / mem_total * 100, 1)
    else:
        mem_usage = int(memory_stat.get("usage", 0))

    event: dict[str, Any] = {
        "device_type": device_type,
        "timestamp": int(_time.time()),
        "summary": {},
    }

    if device_type == "ap":
        event["summary"] = {
            "cpu_util": cpu_util,
            "mem_usage": mem_usage,
            "num_clients": payload.get("num_clients", 0),
            "uptime": int(payload.get("uptime", 0)),
        }
        bands = []
        for radio in payload.get("radio_stat", []):
            band = radio.get("band")
            if band and not radio.get("disabled"):
                bands.append(
                    {
                        "band": band,
                        "util_all": radio.get("util_all", 0),
                        "num_clients": radio.get("num_clients", 0),
                        "noise_floor": radio.get("noise_floor", 0),
                        "channel": radio.get("channel", 0),
                        "power": radio.get("power", 0),
                        "bandwidth": radio.get("bandwidth", 0),
                    }
                )
        event["bands"] = bands

    elif device_type == "switch":
        # PoE totals from module_stat
        modules = payload.get("module_stat", [])
        poe_draw = sum(m.get("poe", {}).get("power_draw", 0.0) for m in modules if m.get("poe"))
        poe_max = sum(m.get("poe", {}).get("max_power", 0.0) for m in modules if m.get("poe"))
        # Client count
        clients_stats = payload.get("clients_stats")
        if clients_stats:
            num_clients = clients_stats.get("total", {}).get("num_wired_clients", 0)
        else:
            num_clients = len(payload.get("clients", []))
        event["summary"] = {
            "cpu_util": cpu_util,
            "mem_usage": mem_usage,
            "num_clients": num_clients,
            "uptime": int(payload.get("uptime", 0)),
            "poe_draw_total": poe_draw,
            "poe_max_total": poe_max,
        }
        # Ports (UP only)
        event["ports"] = [
            {
                "port_id": pd.get("port_id", k),
                "speed": pd.get("speed", 0),
                "tx_pkts": pd.get("tx_pkts", 0),
                "rx_pkts": pd.get("rx_pkts", 0),
            }
            for k, pd in (payload.get("if_stat") or {}).items()
            if pd.get("up")
        ]
        # VC modules
        event["modules"] = [
            {
                "fpc_idx": m.get("_idx", 0),
                "vc_role": m.get("vc_role", ""),
                "temp_max": max((t.get("celsius", 0) for t in m.get("temperatures", [])), default=0),
                "poe_draw": m.get("poe", {}).get("power_draw", 0.0) if m.get("poe") else 0.0,
                "vc_links_count": len(m.get("vc_links", [])),
                "mem_usage": m.get("memory_stat", {}).get("usage", 0),
            }
            for m in modules
        ]
        # DHCP
        event["dhcp"] = [
            {
                "network_name": name,
                "num_ips": s.get("num_ips", 0),
                "num_leased": s.get("num_leased", 0),
                "utilization_pct": round(s["num_leased"] / s["num_ips"] * 100, 1) if s.get("num_ips") else 0.0,
            }
            for name, s in (payload.get("dhcpd_stat") or {}).items()
        ]

    elif device_type == "gateway":
        event["summary"] = {
            "cpu_util": cpu_util,
            "mem_usage": mem_usage,
            "uptime": int(payload.get("uptime", 0)),
            "ha_state": payload.get("ha_state", ""),
            "config_status": payload.get("config_status", ""),
        }
        # WAN interfaces
        event["wan"] = [
            {
                "port_id": pd.get("port_id", k),
                "wan_name": pd.get("wan_name", ""),
                "up": bool(pd.get("up")),
                "tx_bytes": pd.get("tx_bytes", 0),
                "rx_bytes": pd.get("rx_bytes", 0),
                "tx_pkts": pd.get("tx_pkts", 0),
                "rx_pkts": pd.get("rx_pkts", 0),
            }
            for k, pd in (payload.get("if_stat") or {}).items()
            if pd.get("port_usage") == "wan"
        ]
        # DHCP
        event["dhcp"] = [
            {
                "network_name": name,
                "num_ips": s.get("num_ips", 0),
                "num_leased": s.get("num_leased", 0),
                "utilization_pct": round(s["num_leased"] / s["num_ips"] * 100, 1) if s.get("num_ips") else 0.0,
            }
            for name, s in (payload.get("dhcpd_stat") or {}).items()
        ]
        # SPU (SRX)
        spu_list = payload.get("spu_stat", [])
        if spu_list:
            spu = spu_list[0]
            event["spu"] = {
                "spu_cpu": spu.get("spu_cpu", 0),
                "spu_sessions": spu.get("spu_current_session", 0),
                "spu_max_sessions": spu.get("spu_max_session", 0),
                "spu_memory": spu.get("spu_memory", 0),
            }
        # Cluster
        cluster = payload.get("cluster_stat")
        if cluster:
            event["cluster"] = {
                "status": cluster.get("status", ""),
                "operational": cluster.get("operational", False),
                "primary_health": cluster.get("primary", {}).get("health_score", 0),
                "secondary_health": cluster.get("secondary", {}).get("health_score", 0),
                "control_link_up": cluster.get("control_link_up", False),
                "fabric_link_up": cluster.get("fabric_link_up", False),
            }
        # SSR resources
        resources = [
            mod for m in (payload.get("module_stat") or [])
            for mod in ([m] if m.get("network_resources") else [])
        ]
        if resources:
            event["resources"] = [
                {
                    "resource_type": r.get("resource_type", ""),
                    "count": r.get("count", 0),
                    "limit": r.get("limit", 0),
                    "utilization_pct": round(r["count"] / r["limit"] * 100, 1) if r.get("limit") else 0.0,
                }
                for mod in resources
                for r in (mod.get("network_resources") or [])
            ]

    return event
```

Then, at the end of `_process_message()`, after step 7 (write to InfluxDB), add:

```python
        # 8. Broadcast to any live device page subscribers
        if mac and device_type:
            event = _build_device_ws_event(payload, device_type)
            await ws_manager.broadcast(f"telemetry:device:{mac}", event)
```

- [ ] **Step 4: Run tests**

```bash
cd backend && .venv/bin/pytest tests/unit/test_ingestion_service.py -v
```
Expected: all tests pass including the two new ones.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/telemetry/services/ingestion_service.py \
        backend/tests/unit/test_ingestion_service.py
git commit -m "feat(telemetry): broadcast device stats to WS channel after ingestion"
```

---

## Task 4: Add `scope/summary` and `scope/devices` REST endpoints

Both endpoints read from `LatestValueCache` (zero-latency; no InfluxDB required for KPI cards).

**Files:**
- Modify: `backend/app/modules/telemetry/schemas.py`
- Modify: `backend/app/modules/telemetry/router.py`
- Create: `backend/tests/unit/test_scope_endpoints.py`

- [ ] **Step 1: Add schemas to `schemas.py`**

```python
# --- Scope summary -------------------------------------------------------

class BandSummary(BaseModel):
    avg_util_all: float = 0.0
    avg_noise_floor: float = 0.0

class APScopeSummary(BaseModel):
    reporting_active: int = 0
    reporting_total: int = 0
    avg_cpu_util: float = 0.0
    max_cpu_util: float = 0.0
    total_clients: int = 0
    bands: dict[str, BandSummary] = Field(default_factory=dict)

class SwitchScopeSummary(BaseModel):
    reporting_active: int = 0
    reporting_total: int = 0
    avg_cpu_util: float = 0.0
    total_clients: int = 0
    poe_draw_total: float = 0.0
    poe_max_total: float = 0.0
    total_dhcp_leases: int = 0

class GatewayScopeSummary(BaseModel):
    reporting_active: int = 0
    reporting_total: int = 0
    avg_cpu_util: float = 0.0
    wan_links_up: int = 0
    wan_links_total: int = 0
    total_dhcp_leases: int = 0

class ScopeSummaryResponse(BaseModel):
    ap: APScopeSummary | None = None
    switch: SwitchScopeSummary | None = None
    gateway: GatewayScopeSummary | None = None

# --- Scope devices -------------------------------------------------------

class DeviceSummaryRecord(BaseModel):
    mac: str
    site_id: str
    device_type: str
    name: str
    model: str
    cpu_util: float | None = None
    num_clients: int | None = None
    last_seen: float | None = None
    fresh: bool

class ScopeDevicesResponse(BaseModel):
    total: int
    devices: list[DeviceSummaryRecord]
```

- [ ] **Step 2: Write failing tests**

```python
# backend/tests/unit/test_scope_endpoints.py
"""Tests for GET /telemetry/scope/summary and GET /telemetry/scope/devices."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.modules.telemetry.services.latest_value_cache import LatestValueCache


def _make_cache_with_ap_and_switch() -> LatestValueCache:
    cache = LatestValueCache()
    cache.update("aabbccddeeff", {
        "mac": "aabbccddeeff",
        "type": "ap",
        "model": "AP43",
        "name": "AP-01",
        "site_id": "site-0000-0000-0000-000000000001",
        "cpu_stat": {"idle": 60},
        "memory_stat": {"mem_used_kb": 100000, "mem_total_kb": 400000},
        "num_clients": 10,
        "uptime": 3600,
        "radio_stat": [{"band": "band_5", "util_all": 30, "noise_floor": -90}],
    })
    cache.update("112233445566", {
        "mac": "112233445566",
        "type": "switch",
        "model": "EX2300",
        "name": "SW-01",
        "site_id": "site-0000-0000-0000-000000000001",
        "cpu_stat": {"idle": 80},
        "memory_stat": {"usage": 40},
        "num_clients": 5,
        "uptime": 7200,
        "module_stat": [],
    })
    return cache


async def test_scope_summary_ap_fields(client):
    cache = _make_cache_with_ap_and_switch()
    with patch("app.modules.telemetry._latest_cache", cache):
        resp = await client.get(
            "/api/v1/telemetry/scope/summary",
            params={"site_id": "site-0000-0000-0000-000000000001"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ap"] is not None
    assert data["ap"]["total_clients"] == 10
    assert data["ap"]["reporting_active"] == 1
    assert data["ap"]["reporting_total"] == 1


async def test_scope_summary_switch_fields(client):
    cache = _make_cache_with_ap_and_switch()
    with patch("app.modules.telemetry._latest_cache", cache):
        resp = await client.get(
            "/api/v1/telemetry/scope/summary",
            params={"site_id": "site-0000-0000-0000-000000000001"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["switch"] is not None
    assert data["switch"]["total_clients"] == 5


async def test_scope_devices_returns_flat_list(client):
    cache = _make_cache_with_ap_and_switch()
    with patch("app.modules.telemetry._latest_cache", cache):
        resp = await client.get(
            "/api/v1/telemetry/scope/devices",
            params={"site_id": "site-0000-0000-0000-000000000001"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    macs = {d["mac"] for d in data["devices"]}
    assert "aabbccddeeff" in macs
    assert "112233445566" in macs


async def test_scope_summary_no_cache_returns_503(client):
    with patch("app.modules.telemetry._latest_cache", None):
        resp = await client.get(
            "/api/v1/telemetry/scope/summary",
            params={"site_id": "site-0000-0000-0000-000000000001"},
        )
    assert resp.status_code == 503
```

- [ ] **Step 3: Run to confirm they fail**

```bash
cd backend && .venv/bin/pytest tests/unit/test_scope_endpoints.py -v
```
Expected: 404 Not Found for the new endpoints.

- [ ] **Step 4: Implement the endpoints in `router.py`**

Add these imports at the top of `router.py` (with existing imports):
```python
import time as _time
from app.modules.telemetry.schemas import (
    ...existing...,
    ScopeSummaryResponse,
    APScopeSummary,
    SwitchScopeSummary,
    GatewayScopeSummary,
    BandSummary,
    ScopeDevicesResponse,
    DeviceSummaryRecord,
)
```

Add the `_compute_cpu_util` helper (needed by both endpoints):
```python
def _cpu_util_from_payload(stats: dict) -> float:
    cpu_stat = stats.get("cpu_stat", {})
    return float(100 - int(cpu_stat.get("idle", 100)))
```

Add the two endpoint handlers after the existing `query_aggregate` endpoint:

```python
# ── Scope summary (from LatestValueCache) ─────────────────────────────


@router.get("/scope/summary", response_model=ScopeSummaryResponse)
async def get_scope_summary(
    site_id: str | None = Query(None, description="Filter by site UUID; omit for org-wide"),
    _current_user: User = Depends(require_impact_role),
) -> ScopeSummaryResponse:
    """Return aggregated KPI values for all devices in scope from LatestValueCache."""
    import app.modules.telemetry as telemetry_mod

    if not telemetry_mod._latest_cache:
        raise HTTPException(status_code=503, detail="Telemetry service not available")

    if site_id and not _UUID_RE.match(site_id):
        raise HTTPException(status_code=400, detail="Invalid site_id format")

    now = _time.time()
    # Get all cached entries
    all_entries = telemetry_mod._latest_cache._entries  # read-only access

    ap_cpu: list[float] = []
    ap_clients_total = 0
    ap_active = 0
    ap_bands: dict[str, list[float]] = {}  # band -> list of util_all values
    ap_noise: dict[str, list[float]] = {}

    sw_cpu: list[float] = []
    sw_clients_total = 0
    sw_poe_draw = 0.0
    sw_poe_max = 0.0
    sw_dhcp_leases = 0
    sw_active = 0

    gw_cpu: list[float] = []
    gw_wan_up = 0
    gw_wan_total = 0
    gw_dhcp_leases = 0
    gw_active = 0

    for mac, entry in all_entries.items():
        stats = entry.get("stats", {})
        if site_id and stats.get("site_id") != site_id:
            continue
        fresh = (now - entry.get("updated_at", 0)) < 60
        dtype = stats.get("type") or (
            "ap" if isinstance(stats.get("model"), str) and stats["model"].startswith("AP") else None
        )
        cpu = _cpu_util_from_payload(stats)

        if dtype == "ap":
            ap_cpu.append(cpu)
            ap_clients_total += stats.get("num_clients", 0)
            if fresh:
                ap_active += 1
            for radio in stats.get("radio_stat", []):
                band = radio.get("band")
                if band and not radio.get("disabled"):
                    ap_bands.setdefault(band, []).append(radio.get("util_all", 0))
                    ap_noise.setdefault(band, []).append(radio.get("noise_floor", 0))

        elif dtype == "switch":
            sw_cpu.append(cpu)
            clients_stats = stats.get("clients_stats")
            if clients_stats:
                sw_clients_total += clients_stats.get("total", {}).get("num_wired_clients", 0)
            for mod in stats.get("module_stat", []):
                poe = mod.get("poe")
                if poe:
                    sw_poe_draw += poe.get("power_draw", 0.0)
                    sw_poe_max += poe.get("max_power", 0.0)
            for scope in (stats.get("dhcpd_stat") or {}).values():
                sw_dhcp_leases += scope.get("num_leased", 0)
            if fresh:
                sw_active += 1

        elif dtype == "gateway":
            gw_cpu.append(cpu)
            for pd in (stats.get("if_stat") or {}).values():
                if pd.get("port_usage") == "wan":
                    gw_wan_total += 1
                    if pd.get("up"):
                        gw_wan_up += 1
            for scope in (stats.get("dhcpd_stat") or {}).values():
                gw_dhcp_leases += scope.get("num_leased", 0)
            if fresh:
                gw_active += 1

    def _avg(lst: list[float]) -> float:
        return round(sum(lst) / len(lst), 1) if lst else 0.0

    ap_summary = None
    if ap_cpu:
        bands_out = {
            band: BandSummary(avg_util_all=_avg(vals), avg_noise_floor=_avg(ap_noise.get(band, [])))
            for band, vals in ap_bands.items()
        }
        ap_summary = APScopeSummary(
            reporting_active=ap_active,
            reporting_total=len(ap_cpu),
            avg_cpu_util=_avg(ap_cpu),
            max_cpu_util=round(max(ap_cpu), 1),
            total_clients=ap_clients_total,
            bands=bands_out,
        )

    sw_summary = None
    if sw_cpu:
        sw_summary = SwitchScopeSummary(
            reporting_active=sw_active,
            reporting_total=len(sw_cpu),
            avg_cpu_util=_avg(sw_cpu),
            total_clients=sw_clients_total,
            poe_draw_total=round(sw_poe_draw, 1),
            poe_max_total=round(sw_poe_max, 1),
            total_dhcp_leases=sw_dhcp_leases,
        )

    gw_summary = None
    if gw_cpu:
        gw_summary = GatewayScopeSummary(
            reporting_active=gw_active,
            reporting_total=len(gw_cpu),
            avg_cpu_util=_avg(gw_cpu),
            wan_links_up=gw_wan_up,
            wan_links_total=gw_wan_total,
            total_dhcp_leases=gw_dhcp_leases,
        )

    return ScopeSummaryResponse(ap=ap_summary, switch=sw_summary, gateway=gw_summary)


# ── Scope devices (from LatestValueCache) ─────────────────────────────


@router.get("/scope/devices", response_model=ScopeDevicesResponse)
async def get_scope_devices(
    site_id: str | None = Query(None, description="Filter by site UUID; omit for all devices"),
    _current_user: User = Depends(require_impact_role),
) -> ScopeDevicesResponse:
    """Return a flat list of devices with latest stats from LatestValueCache."""
    import app.modules.telemetry as telemetry_mod

    if not telemetry_mod._latest_cache:
        raise HTTPException(status_code=503, detail="Telemetry service not available")

    if site_id and not _UUID_RE.match(site_id):
        raise HTTPException(status_code=400, detail="Invalid site_id format")

    now = _time.time()
    all_entries = telemetry_mod._latest_cache._entries
    records: list[DeviceSummaryRecord] = []

    for mac, entry in all_entries.items():
        stats = entry.get("stats", {})
        if site_id and stats.get("site_id") != site_id:
            continue

        fresh = (now - entry.get("updated_at", 0)) < 60
        dtype = stats.get("type") or (
            "ap" if isinstance(stats.get("model"), str) and stats["model"].startswith("AP") else "unknown"
        )

        cpu = _cpu_util_from_payload(stats)
        clients_stats = stats.get("clients_stats")
        if clients_stats:
            num_clients = clients_stats.get("total", {}).get("num_wired_clients", 0)
        else:
            num_clients = stats.get("num_clients")

        records.append(
            DeviceSummaryRecord(
                mac=mac,
                site_id=stats.get("site_id", ""),
                device_type=dtype,
                name=stats.get("name") or stats.get("hostname") or mac,
                model=stats.get("model", ""),
                cpu_util=cpu,
                num_clients=num_clients,
                last_seen=entry.get("updated_at"),
                fresh=fresh,
            )
        )

    records.sort(key=lambda r: r.last_seen or 0, reverse=True)
    return ScopeDevicesResponse(total=len(records), devices=records)
```

- [ ] **Step 5: Run tests**

```bash
cd backend && .venv/bin/pytest tests/unit/test_scope_endpoints.py -v
```
Expected: all 4 tests pass.

- [ ] **Step 6: Run full telemetry suite**

```bash
cd backend && .venv/bin/pytest tests/unit/test_telemetry_router.py tests/unit/test_scope_endpoints.py tests/unit/test_switch_extractor.py tests/unit/test_ingestion_service.py -v
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/telemetry/schemas.py \
        backend/app/modules/telemetry/router.py \
        backend/tests/unit/test_scope_endpoints.py
git commit -m "feat(telemetry): add scope/summary and scope/devices endpoints"
```

---

## Task 5: Frontend wiring — nav item + routes

**Files:**
- Modify: `frontend/src/app/layout/sidebar/nav-items.config.ts`
- Modify: `frontend/src/app/app.routes.ts`
- Create: `frontend/src/app/features/telemetry/telemetry.routes.ts`

- [ ] **Step 1: Add Telemetry to `nav-items.config.ts`**

Add after the `Impact Analysis` item:
```typescript
{
  label: 'Telemetry',
  icon: 'sensors',
  route: '/telemetry',
  roles: ['impact_analysis', 'admin'],
},
```

- [ ] **Step 2: Add the lazy route to `app.routes.ts`**

Add after the `impact-analysis` route child:
```typescript
{
  path: 'telemetry',
  loadChildren: () => import('./features/telemetry/telemetry.routes'),
},
```

- [ ] **Step 3: Create `telemetry.routes.ts`**

```typescript
// frontend/src/app/features/telemetry/telemetry.routes.ts
import { Routes } from '@angular/router';

const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./scope/telemetry-scope.component').then((m) => m.TelemetryScopeComponent),
  },
  {
    path: 'site/:id',
    loadComponent: () =>
      import('./scope/telemetry-scope.component').then((m) => m.TelemetryScopeComponent),
  },
  {
    path: 'device/:mac',
    loadComponent: () =>
      import('./device/telemetry-device.component').then((m) => m.TelemetryDeviceComponent),
  },
];

export default routes;
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/layout/sidebar/nav-items.config.ts \
        frontend/src/app/app.routes.ts \
        frontend/src/app/features/telemetry/telemetry.routes.ts
git commit -m "feat(telemetry): add nav item and lazy-loaded routes"
```

---

## Task 6: Create `models.ts` and `TelemetryService`

**Files:**
- Create: `frontend/src/app/features/telemetry/models.ts`
- Create: `frontend/src/app/features/telemetry/telemetry.service.ts`

- [ ] **Step 1: Create `models.ts`**

```typescript
// frontend/src/app/features/telemetry/models.ts

export type TimeRange = '1h' | '6h' | '24h';

// Scope summary -------------------------------------------------------

export interface BandSummary {
  avg_util_all: number;
  avg_noise_floor: number;
}

export interface APScopeSummary {
  reporting_active: number;
  reporting_total: number;
  avg_cpu_util: number;
  max_cpu_util: number;
  total_clients: number;
  bands: Record<string, BandSummary>;
}

export interface SwitchScopeSummary {
  reporting_active: number;
  reporting_total: number;
  avg_cpu_util: number;
  total_clients: number;
  poe_draw_total: number;
  poe_max_total: number;
  total_dhcp_leases: number;
}

export interface GatewayScopeSummary {
  reporting_active: number;
  reporting_total: number;
  avg_cpu_util: number;
  wan_links_up: number;
  wan_links_total: number;
  total_dhcp_leases: number;
}

export interface ScopeSummary {
  ap: APScopeSummary | null;
  switch: SwitchScopeSummary | null;
  gateway: GatewayScopeSummary | null;
}

// Scope devices -------------------------------------------------------

export interface DeviceSummaryRecord {
  mac: string;
  site_id: string;
  device_type: string;
  name: string;
  model: string;
  cpu_util: number | null;
  num_clients: number | null;
  last_seen: number | null;
  fresh: boolean;
}

export interface ScopeDevices {
  total: number;
  devices: DeviceSummaryRecord[];
}

// Latest device stats -------------------------------------------------

export interface LatestStats {
  mac: string;
  fresh: boolean;
  updated_at: number | null;
  stats: Record<string, unknown> | null;
}

// Aggregate query result ----------------------------------------------

export interface AggregatePoint {
  _time: string;
  _value: number;
  [key: string]: unknown;
}

export interface AggregateResult {
  points: AggregatePoint[];
  count: number;
}

// WebSocket live event -----------------------------------------------

export interface BandStats {
  band: string;
  util_all: number;
  num_clients: number;
  noise_floor: number;
  channel: number;
  power: number;
  bandwidth: number;
}

export interface PortStats {
  port_id: string;
  speed: number;
  tx_pkts: number;
  rx_pkts: number;
}

export interface ModuleStats {
  fpc_idx: number;
  vc_role: string;
  temp_max: number;
  poe_draw: number;
  vc_links_count: number;
  mem_usage: number;
}

export interface DhcpStats {
  network_name: string;
  num_ips: number;
  num_leased: number;
  utilization_pct: number;
}

export interface WanStats {
  port_id: string;
  wan_name: string;
  up: boolean;
  tx_bytes: number;
  rx_bytes: number;
  tx_pkts: number;
  rx_pkts: number;
}

export interface SpuStats {
  spu_cpu: number;
  spu_sessions: number;
  spu_max_sessions: number;
  spu_memory: number;
}

export interface ClusterStats {
  status: string;
  operational: boolean;
  primary_health: number;
  secondary_health: number;
  control_link_up: boolean;
  fabric_link_up: boolean;
}

export interface ResourceStats {
  resource_type: string;
  count: number;
  limit: number;
  utilization_pct: number;
}

export interface DeviceSummaryStats {
  cpu_util: number;
  mem_usage: number;
  num_clients?: number;
  uptime: number;
  poe_draw_total?: number;
  poe_max_total?: number;
  ha_state?: string;
  config_status?: string;
}

export interface DeviceLiveEvent {
  device_type: 'ap' | 'switch' | 'gateway';
  timestamp: number;
  summary: DeviceSummaryStats;
  bands?: BandStats[];
  ports?: PortStats[];
  modules?: ModuleStats[];
  dhcp?: DhcpStats[];
  wan?: WanStats[];
  spu?: SpuStats;
  cluster?: ClusterStats;
  resources?: ResourceStats[];
}
```

- [ ] **Step 2: Create `telemetry.service.ts`**

```typescript
// frontend/src/app/features/telemetry/telemetry.service.ts
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { WebSocketService } from '../../core/services/websocket.service';
import {
  ScopeSummary,
  ScopeDevices,
  LatestStats,
  AggregateResult,
  DeviceLiveEvent,
  TimeRange,
} from './models';

const TIME_RANGE_MAP: Record<TimeRange, string> = {
  '1h': '-1h',
  '6h': '-6h',
  '24h': '-24h',
};

const WINDOW_MAP: Record<TimeRange, string> = {
  '1h': '2m',
  '6h': '10m',
  '24h': '30m',
};

@Injectable({ providedIn: 'root' })
export class TelemetryService {
  private readonly api = inject(ApiService);
  private readonly ws = inject(WebSocketService);

  getScopeSummary(siteId?: string): Observable<ScopeSummary> {
    const params: Record<string, string> = {};
    if (siteId) params['site_id'] = siteId;
    return this.api.get<ScopeSummary>('/telemetry/scope/summary', { params });
  }

  getScopeDevices(siteId?: string): Observable<ScopeDevices> {
    const params: Record<string, string> = {};
    if (siteId) params['site_id'] = siteId;
    return this.api.get<ScopeDevices>('/telemetry/scope/devices', { params });
  }

  getLatestStats(mac: string): Observable<LatestStats> {
    return this.api.get<LatestStats>(`/telemetry/latest/${mac}`);
  }

  /** Query aggregated time-series data for scope charts. */
  queryAggregate(params: {
    siteId?: string;
    orgId?: string;
    measurement: string;
    field: string;
    agg?: string;
    timeRange: TimeRange;
  }): Observable<AggregateResult> {
    const p: Record<string, string> = {
      measurement: params.measurement,
      field: params.field,
      agg: params.agg ?? 'mean',
      window: WINDOW_MAP[params.timeRange],
      start: TIME_RANGE_MAP[params.timeRange],
    };
    if (params.siteId) p['site_id'] = params.siteId;
    if (params.orgId) p['org_id'] = params.orgId;
    return this.api.get<AggregateResult>('/telemetry/query/aggregate', { params: p });
  }

  /** Subscribe to live device stat events via WebSocket. */
  subscribeToDevice(mac: string): Observable<DeviceLiveEvent> {
    return this.ws.subscribe<DeviceLiveEvent>(`telemetry:device:${mac}`);
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/features/telemetry/models.ts \
        frontend/src/app/features/telemetry/telemetry.service.ts
git commit -m "feat(telemetry): add models and TelemetryService"
```

---

## Task 7: Build `TelemetryScopeComponent` (org/site view)

This component renders at both `/telemetry` (org-wide) and `/telemetry/site/:id` (site-scoped).

**Files:**
- Create: `frontend/src/app/features/telemetry/scope/telemetry-scope.component.ts`
- Create: `frontend/src/app/features/telemetry/scope/telemetry-scope.component.html`
- Create: `frontend/src/app/features/telemetry/scope/telemetry-scope.component.scss`

- [ ] **Step 1: Create `telemetry-scope.component.ts`**

```typescript
import {
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { forkJoin } from 'rxjs';
import { TelemetryService } from '../telemetry.service';
import { ScopeSummary, ScopeDevices, DeviceSummaryRecord, TimeRange, AggregateResult } from '../models';
import { ScopeDeviceTableComponent } from './components/scope-device-table/scope-device-table.component';

@Component({
  selector: 'app-telemetry-scope',
  standalone: true,
  imports: [
    RouterModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatTableModule,
    MatTooltipModule,
    ScopeDeviceTableComponent,
  ],
  templateUrl: './telemetry-scope.component.html',
  styleUrl: './telemetry-scope.component.scss',
})
export class TelemetryScopeComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly telemetryService = inject(TelemetryService);
  private readonly destroyRef = inject(DestroyRef);

  readonly siteId = signal<string | null>(null);
  readonly timeRange = signal<TimeRange>('1h');
  readonly loading = signal(false);
  readonly summary = signal<ScopeSummary | null>(null);
  readonly devices = signal<ScopeDevices | null>(null);

  /** Aggregated chart data, keyed by "measurement:field" */
  readonly chartData = signal<Record<string, AggregateResult>>({});

  readonly isOrgScope = computed(() => !this.siteId());
  readonly hasAP = computed(() => !!this.summary()?.ap);
  readonly hasSwitch = computed(() => !!this.summary()?.switch);
  readonly hasGateway = computed(() => !!this.summary()?.gateway);

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id');
      this.siteId.set(id);
      this.loadScopeData();
    });
  }

  setTimeRange(tr: TimeRange): void {
    this.timeRange.set(tr);
    this.loadCharts();
  }

  navigateToDevice(mac: string): void {
    this.router.navigate(['/telemetry/device', mac]);
  }

  private loadScopeData(): void {
    this.loading.set(true);
    const siteId = this.siteId() ?? undefined;

    forkJoin({
      summary: this.telemetryService.getScopeSummary(siteId),
      devices: this.telemetryService.getScopeDevices(siteId),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ summary, devices }) => {
          this.summary.set(summary);
          this.devices.set(devices);
          this.loading.set(false);
          this.loadCharts();
        },
        error: () => this.loading.set(false),
      });
  }

  private loadCharts(): void {
    const siteId = this.siteId() ?? undefined;
    const tr = this.timeRange();
    const scopeParam = siteId ? { siteId } : { orgId: 'placeholder' };
    // NOTE: for org scope, the org_id is injected from the backend config.
    // Use a special sentinel or rely on the backend to default to the configured org.
    // For now, use site_id filter when available; org scope uses orgId from settings.

    const queries: Record<string, ReturnType<TelemetryService['queryAggregate']>> = {};

    if (this.hasAP()) {
      queries['device_summary:cpu_util'] = this.telemetryService.queryAggregate({
        ...scopeParam, measurement: 'device_summary', field: 'cpu_util', timeRange: tr,
      });
      queries['device_summary:num_clients'] = this.telemetryService.queryAggregate({
        ...scopeParam, measurement: 'device_summary', field: 'num_clients', agg: 'sum', timeRange: tr,
      });
    }
    if (this.hasSwitch()) {
      queries['sw:cpu_util'] = this.telemetryService.queryAggregate({
        ...scopeParam, measurement: 'device_summary', field: 'cpu_util', timeRange: tr,
      });
    }
    if (this.hasGateway()) {
      queries['gw:cpu_util'] = this.telemetryService.queryAggregate({
        ...scopeParam, measurement: 'gateway_health', field: 'cpu_idle', timeRange: tr,
      });
    }

    if (Object.keys(queries).length === 0) return;

    forkJoin(queries)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((results) => this.chartData.set(results));
  }
}
```

- [ ] **Step 2: Create `telemetry-scope.component.html`**

```html
<div class="telemetry-scope-page">
  @if (loading()) {
    <mat-progress-bar mode="indeterminate" />
  }

  <!-- Header + time range picker -->
  <div class="page-header">
    <div class="page-title">
      <span>Telemetry</span>
      @if (siteId()) {
        <mat-icon class="breadcrumb-sep">chevron_right</mat-icon>
        <span>Site View</span>
      }
    </div>
    <div class="time-range-picker">
      <span class="label">Time range:</span>
      @for (tr of (['1h', '6h', '24h'] as const); track tr) {
        <button
          mat-stroked-button
          [class.active]="timeRange() === tr"
          (click)="setTimeRange(tr)"
        >{{ tr }}</button>
      }
    </div>
  </div>

  <!-- AP section -->
  @if (hasAP()) {
    <section class="device-section">
      <h3 class="section-title">
        Access Points ({{ summary()!.ap!.reporting_active }}/{{ summary()!.ap!.reporting_total }} reporting)
      </h3>
      <div class="kpi-row">
        <div class="kpi-card">
          <div class="kpi-label">Avg CPU</div>
          <div class="kpi-value">{{ summary()!.ap!.avg_cpu_util | number:'1.0-1' }}%</div>
          <div class="kpi-sub">max {{ summary()!.ap!.max_cpu_util | number:'1.0-1' }}%</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Total Clients</div>
          <div class="kpi-value">{{ summary()!.ap!.total_clients | number }}</div>
        </div>
        @for (entry of bandEntries(summary()!.ap!.bands); track entry.band) {
          <div class="kpi-card">
            <div class="kpi-label">Avg Radio Util ({{ entry.band | bandLabel }})</div>
            <div class="kpi-value">{{ entry.avg_util_all | number:'1.0-1' }}%</div>
          </div>
        }
        <div class="kpi-card" [class.reporting-ok]="summary()!.ap!.reporting_active === summary()!.ap!.reporting_total">
          <div class="kpi-label">Reporting</div>
          <div class="kpi-value">{{ summary()!.ap!.reporting_active }}/{{ summary()!.ap!.reporting_total }}</div>
          <div class="kpi-sub">devices active</div>
        </div>
      </div>
    </section>
  }

  <!-- Switch section -->
  @if (hasSwitch()) {
    <section class="device-section">
      <h3 class="section-title">
        Switches ({{ summary()!.switch!.reporting_active }}/{{ summary()!.switch!.reporting_total }} reporting)
      </h3>
      <div class="kpi-row">
        <div class="kpi-card">
          <div class="kpi-label">Avg CPU</div>
          <div class="kpi-value">{{ summary()!.switch!.avg_cpu_util | number:'1.0-1' }}%</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Total Clients</div>
          <div class="kpi-value">{{ summary()!.switch!.total_clients | number }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">PoE Draw</div>
          <div class="kpi-value">{{ summary()!.switch!.poe_draw_total | number:'1.0-0' }} W</div>
          <div class="kpi-sub">of {{ summary()!.switch!.poe_max_total | number:'1.0-0' }} W max</div>
        </div>
        @if (summary()!.switch!.total_dhcp_leases > 0) {
          <div class="kpi-card">
            <div class="kpi-label">DHCP Leases</div>
            <div class="kpi-value">{{ summary()!.switch!.total_dhcp_leases | number }}</div>
          </div>
        }
      </div>
    </section>
  }

  <!-- Gateway section -->
  @if (hasGateway()) {
    <section class="device-section">
      <h3 class="section-title">
        Gateways ({{ summary()!.gateway!.reporting_active }}/{{ summary()!.gateway!.reporting_total }} reporting)
      </h3>
      <div class="kpi-row">
        <div class="kpi-card">
          <div class="kpi-label">Avg CPU</div>
          <div class="kpi-value">{{ summary()!.gateway!.avg_cpu_util | number:'1.0-1' }}%</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">WAN Links Up</div>
          <div class="kpi-value">{{ summary()!.gateway!.wan_links_up }}/{{ summary()!.gateway!.wan_links_total }}</div>
        </div>
        @if (summary()!.gateway!.total_dhcp_leases > 0) {
          <div class="kpi-card">
            <div class="kpi-label">DHCP Leases</div>
            <div class="kpi-value">{{ summary()!.gateway!.total_dhcp_leases | number }}</div>
          </div>
        }
      </div>
    </section>
  }

  <!-- Device table -->
  @if (devices()) {
    <section class="device-section">
      <h3 class="section-title">Devices</h3>
      <app-scope-device-table
        [devices]="devices()!.devices"
        [isOrgScope]="isOrgScope()"
        (deviceSelected)="navigateToDevice($event)"
      />
    </section>
  }
</div>
```

Add this helper method to the component class:

```typescript
bandEntries(bands: Record<string, { avg_util_all: number; avg_noise_floor: number }>): Array<{ band: string; avg_util_all: number }> {
  return Object.entries(bands).map(([band, v]) => ({ band, avg_util_all: v.avg_util_all }));
}
```

Also add `DecimalPipe` to imports in the component decorator, and create a `bandLabel` pipe (or use inline ternary in template: `entry.band === 'band_24' ? '2.4G' : entry.band === 'band_5' ? '5G' : '6G'`). For simplicity use the inline approach and remove the pipe reference.

- [ ] **Step 3: Create `telemetry-scope.component.scss`**

```scss
.telemetry-scope-page {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-title {
  display: flex;
  align-items: center;
  font-size: 20px;
  font-weight: 600;
  color: var(--app-text);
  gap: 4px;

  .breadcrumb-sep {
    font-size: 18px;
    color: var(--app-text-muted);
  }
}

.time-range-picker {
  display: flex;
  align-items: center;
  gap: 8px;

  .label {
    font-size: 12px;
    color: var(--app-text-muted);
  }

  button.active {
    background-color: var(--app-primary);
    color: white;
  }
}

.device-section {
  background: var(--app-canvas);
  border-radius: 8px;
  border: 1px solid var(--app-border);
  padding: 16px;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--app-text-muted);
  margin: 0 0 12px;
}

.kpi-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.kpi-card {
  flex: 1;
  min-width: 120px;
  background: var(--app-surface);
  border-radius: 8px;
  border: 1px solid var(--app-border);
  padding: 12px;

  .kpi-label {
    font-size: 11px;
    color: var(--app-text-muted);
    margin-bottom: 4px;
  }

  .kpi-value {
    font-size: 22px;
    font-weight: 700;
    color: var(--app-text);
  }

  .kpi-sub {
    font-size: 11px;
    color: var(--app-text-muted);
    margin-top: 2px;
  }

  &.reporting-ok .kpi-value {
    color: var(--app-success);
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/features/telemetry/scope/telemetry-scope.component.ts \
        frontend/src/app/features/telemetry/scope/telemetry-scope.component.html \
        frontend/src/app/features/telemetry/scope/telemetry-scope.component.scss
git commit -m "feat(telemetry): add TelemetryScopeComponent (org/site KPI view)"
```

---

## Task 8: Build `ScopeDeviceTableComponent`

**Files:**
- Create: `frontend/src/app/features/telemetry/scope/components/scope-device-table/scope-device-table.component.ts`
- Create: `frontend/src/app/features/telemetry/scope/components/scope-device-table/scope-device-table.component.html`

- [ ] **Step 1: Create `scope-device-table.component.ts`**

```typescript
import { Component, EventEmitter, Input, Output, computed, signal } from '@angular/core';
import { DecimalPipe, DatePipe } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatTableModule } from '@angular/material/table';
import { MatSortModule } from '@angular/material/sort';
import { MatPaginatorModule } from '@angular/material/paginator';
import { DeviceSummaryRecord } from '../../../models';

@Component({
  selector: 'app-scope-device-table',
  standalone: true,
  imports: [DecimalPipe, DatePipe, RouterModule, MatTableModule, MatSortModule, MatPaginatorModule],
  templateUrl: './scope-device-table.component.html',
})
export class ScopeDeviceTableComponent {
  @Input() devices: DeviceSummaryRecord[] = [];
  @Input() isOrgScope = false;
  @Output() deviceSelected = new EventEmitter<string>();

  readonly displayedColumns = computed(() =>
    this.isOrgScope
      ? ['name', 'site_id', 'device_type', 'cpu_util', 'num_clients', 'last_seen']
      : ['name', 'device_type', 'cpu_util', 'num_clients', 'last_seen'],
  );
}
```

- [ ] **Step 2: Create `scope-device-table.component.html`**

```html
<div class="table-card">
  <table mat-table [dataSource]="devices">
    <ng-container matColumnDef="name">
      <th mat-header-cell *matHeaderCellDef>Name</th>
      <td mat-cell *matCellDef="let row">
        <a (click)="deviceSelected.emit(row.mac)" class="device-link">{{ row.name }}</a>
      </td>
    </ng-container>
    <ng-container matColumnDef="site_id">
      <th mat-header-cell *matHeaderCellDef>Site</th>
      <td mat-cell *matCellDef="let row">{{ row.site_id | slice:0:8 }}…</td>
    </ng-container>
    <ng-container matColumnDef="device_type">
      <th mat-header-cell *matHeaderCellDef>Type</th>
      <td mat-cell *matCellDef="let row">{{ row.device_type | titlecase }}</td>
    </ng-container>
    <ng-container matColumnDef="cpu_util">
      <th mat-header-cell *matHeaderCellDef>CPU</th>
      <td mat-cell *matCellDef="let row">
        @if (row.cpu_util !== null) { {{ row.cpu_util | number:'1.0-0' }}% }
      </td>
    </ng-container>
    <ng-container matColumnDef="num_clients">
      <th mat-header-cell *matHeaderCellDef>Clients</th>
      <td mat-cell *matCellDef="let row">{{ row.num_clients ?? '—' }}</td>
    </ng-container>
    <ng-container matColumnDef="last_seen">
      <th mat-header-cell *matHeaderCellDef>Last seen</th>
      <td mat-cell *matCellDef="let row" [class.stale]="!row.fresh">
        @if (row.last_seen) { {{ row.last_seen * 1000 | date:'HH:mm:ss' }} }
      </td>
    </ng-container>

    <tr mat-header-row *matHeaderRowDef="displayedColumns()"></tr>
    <tr
      mat-row
      *matRowDef="let row; columns: displayedColumns();"
      class="clickable-row"
      (click)="deviceSelected.emit(row.mac)"
    ></tr>
  </table>
</div>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/features/telemetry/scope/components/
git commit -m "feat(telemetry): add ScopeDeviceTableComponent"
```

---

## Task 9: Build `TelemetryDeviceComponent` (KPI + charts + tables)

**Files:**
- Create: `frontend/src/app/features/telemetry/device/telemetry-device.component.ts`
- Create: `frontend/src/app/features/telemetry/device/telemetry-device.component.html`
- Create: `frontend/src/app/features/telemetry/device/telemetry-device.component.scss`

- [ ] **Step 1: Create `telemetry-device.component.ts`**

```typescript
import {
  AfterViewInit,
  Component,
  DestroyRef,
  ElementRef,
  OnInit,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { DecimalPipe, DatePipe, TitleCasePipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { Chart } from 'chart.js/auto';
import { forkJoin } from 'rxjs';
import { TelemetryService } from '../telemetry.service';
import {
  LatestStats,
  TimeRange,
  AggregateResult,
  AggregatePoint,
  PortStats,
  ModuleStats,
  DhcpStats,
} from '../models';
import { DeviceLiveLogComponent } from './components/device-live-log/device-live-log.component';
import { getChartGridColor } from '../../../shared/utils/chart-defaults';

@Component({
  selector: 'app-telemetry-device',
  standalone: true,
  imports: [
    RouterModule,
    DecimalPipe,
    DatePipe,
    TitleCasePipe,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatTableModule,
    DeviceLiveLogComponent,
  ],
  templateUrl: './telemetry-device.component.html',
  styleUrl: './telemetry-device.component.scss',
})
export class TelemetryDeviceComponent implements OnInit, AfterViewInit {
  private readonly route = inject(ActivatedRoute);
  private readonly telemetryService = inject(TelemetryService);
  private readonly destroyRef = inject(DestroyRef);

  @ViewChild('cpuChart') cpuChartRef?: ElementRef<HTMLCanvasElement>;
  @ViewChild('clientsChart') clientsChartRef?: ElementRef<HTMLCanvasElement>;
  @ViewChild('cpuChartEl') cpuChartEl?: ElementRef<HTMLCanvasElement>;

  readonly mac = signal('');
  readonly timeRange = signal<TimeRange>('1h');
  readonly loading = signal(false);
  readonly latestStats = signal<LatestStats | null>(null);

  readonly deviceType = computed<'ap' | 'switch' | 'gateway' | null>(() => {
    const stats = this.latestStats()?.stats;
    if (!stats) return null;
    const t = stats['type'] as string | undefined;
    if (t === 'switch' || t === 'gateway') return t;
    const model = stats['model'] as string | undefined;
    if (model?.startsWith('AP')) return 'ap';
    return null;
  });

  readonly isAP = computed(() => this.deviceType() === 'ap');
  readonly isSwitch = computed(() => this.deviceType() === 'switch');
  readonly isGateway = computed(() => this.deviceType() === 'gateway');

  // Derived tables from latestStats
  readonly portRows = computed<PortStats[]>(() => {
    const if_stat = this.latestStats()?.stats?.['if_stat'] as Record<string, PortStats> | undefined;
    if (!if_stat) return [];
    return Object.values(if_stat).filter((p: any) => p.up);
  });

  readonly moduleRows = computed<ModuleStats[]>(() => {
    const mods = this.latestStats()?.stats?.['module_stat'] as any[] | undefined;
    if (!mods?.length) return [];
    return mods.map((m: any) => ({
      fpc_idx: m._idx ?? 0,
      vc_role: m.vc_role ?? '',
      temp_max: Math.max(...(m.temperatures ?? []).map((t: any) => t.celsius ?? 0), 0),
      poe_draw: m.poe?.power_draw ?? 0,
      vc_links_count: (m.vc_links ?? []).length,
      mem_usage: m.memory_stat?.usage ?? 0,
    }));
  });

  readonly dhcpRows = computed<DhcpStats[]>(() => {
    const dhcpd = this.latestStats()?.stats?.['dhcpd_stat'] as Record<string, any> | undefined;
    if (!dhcpd) return [];
    return Object.entries(dhcpd).map(([name, s]) => ({
      network_name: name,
      num_ips: s.num_ips ?? 0,
      num_leased: s.num_leased ?? 0,
      utilization_pct: s.num_ips ? Math.round((s.num_leased / s.num_ips) * 100) : 0,
    }));
  });

  private charts: Chart[] = [];

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const mac = params.get('mac') ?? '';
      this.mac.set(mac);
      this.loadDevice();
    });
  }

  ngAfterViewInit(): void {
    // Charts are built after data loads — see buildCharts()
  }

  setTimeRange(tr: TimeRange): void {
    this.timeRange.set(tr);
    this.loadCharts();
  }

  private loadDevice(): void {
    this.loading.set(true);
    this.telemetryService
      .getLatestStats(this.mac())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (stats) => {
          this.latestStats.set(stats);
          this.loading.set(false);
          this.loadCharts();
        },
        error: () => this.loading.set(false),
      });
  }

  private loadCharts(): void {
    const mac = this.mac();
    const tr = this.timeRange();
    const dtype = this.deviceType();
    if (!mac || !dtype) return;

    const measurement = dtype === 'gateway' ? 'gateway_health' : 'device_summary';
    const cpuField = dtype === 'gateway' ? 'cpu_idle' : 'cpu_util';

    forkJoin({
      cpu: this.telemetryService.queryAggregate({ siteId: 'todo', measurement, field: cpuField, timeRange: tr }),
      clients: dtype !== 'gateway'
        ? this.telemetryService.queryAggregate({ siteId: 'todo', measurement: 'device_summary', field: 'num_clients', agg: 'max', timeRange: tr })
        : this.telemetryService.queryAggregate({ siteId: 'todo', measurement: 'gateway_health', field: 'mem_usage', timeRange: tr }),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((results) => {
        this.buildCharts(results);
      });
  }

  private buildCharts(data: Record<string, AggregateResult>): void {
    this.charts.forEach((c) => c.destroy());
    this.charts = [];

    if (this.cpuChartRef?.nativeElement) {
      const labels = (data['cpu']?.points ?? []).map((p) => new Date(p._time).toLocaleTimeString());
      const cpuValues = (data['cpu']?.points ?? []).map((p) =>
        this.deviceType() === 'gateway' ? 100 - p._value : p._value,
      );
      const chart = new Chart(this.cpuChartRef.nativeElement, {
        type: 'line',
        data: {
          labels,
          datasets: [
            {
              label: 'CPU %',
              data: cpuValues,
              borderColor: '#60a5fa',
              backgroundColor: 'transparent',
              pointRadius: 2,
              tension: 0.3,
              borderWidth: 2,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { display: false }, ticks: { maxTicksLimit: 10, font: { size: 10 } } },
            y: {
              beginAtZero: true,
              max: 100,
              grid: { color: getChartGridColor() },
              ticks: { font: { size: 10 } },
            },
          },
        },
      });
      this.charts.push(chart);
    }
  }
}
```

Note: The `siteId: 'todo'` placeholder must be replaced — the device's `site_id` is available in `latestStats().stats['site_id']`. In `loadCharts()`, extract it:
```typescript
const siteId = (this.latestStats()?.stats?.['site_id'] as string) ?? '';
```
Then pass `siteId` instead of `'todo'` in all `queryAggregate` calls.

- [ ] **Step 2: Create `telemetry-device.component.html`**

```html
<div class="telemetry-device-page">
  @if (loading()) {
    <mat-progress-bar mode="indeterminate" />
  }

  <div class="page-header">
    <div class="breadcrumb">
      <a routerLink="/telemetry">Telemetry</a>
      <mat-icon class="sep">chevron_right</mat-icon>
      <span>{{ latestStats()?.stats?.['name'] ?? mac() }}</span>
    </div>
  </div>

  @if (latestStats()?.stats; as stats) {
    <!-- KPI cards -->
    <section class="kpi-row">
      <div class="kpi-card">
        <div class="kpi-label">CPU</div>
        <div class="kpi-value">
          @if (isGateway()) {
            {{ 100 - (stats['cpu_stat'] as any)?.idle ?? 0 | number:'1.0-0' }}%
          } @else {
            {{ (100 - ((stats['cpu_stat'] as any)?.idle ?? 100)) | number:'1.0-0' }}%
          }
        </div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Memory</div>
        <div class="kpi-value">{{ (stats['memory_stat'] as any)?.usage ?? 0 | number:'1.0-0' }}%</div>
      </div>
      @if (!isGateway()) {
        <div class="kpi-card">
          <div class="kpi-label">Clients</div>
          <div class="kpi-value">{{ stats['num_clients'] ?? 0 }}</div>
        </div>
      }
      <div class="kpi-card">
        <div class="kpi-label">Uptime</div>
        <div class="kpi-value">{{ stats['uptime'] | number:'1.0-0' }}s</div>
      </div>
      @if (isGateway()) {
        <div class="kpi-card">
          <div class="kpi-label">HA State</div>
          <div class="kpi-value">{{ stats['ha_state'] ?? '—' }}</div>
        </div>
      }
    </section>

    <!-- Time range picker -->
    <div class="time-range-picker">
      <span class="label">Time range:</span>
      @for (tr of (['1h', '6h', '24h'] as const); track tr) {
        <button mat-stroked-button [class.active]="timeRange() === tr" (click)="setTimeRange(tr)">
          {{ tr }}
        </button>
      }
    </div>

    <!-- CPU chart -->
    <section class="chart-section">
      <h3 class="section-title">CPU over time</h3>
      <div class="chart-wrapper">
        <canvas #cpuChart></canvas>
      </div>
    </section>

    <!-- Switch tables -->
    @if (isSwitch()) {
      @if (portRows().length > 0) {
        <section class="table-section">
          <h3 class="section-title">UP Ports</h3>
          <div class="table-card">
            <table mat-table [dataSource]="portRows()">
              <ng-container matColumnDef="port_id">
                <th mat-header-cell *matHeaderCellDef>Port</th>
                <td mat-cell *matCellDef="let r">{{ r.port_id }}</td>
              </ng-container>
              <ng-container matColumnDef="speed">
                <th mat-header-cell *matHeaderCellDef>Speed</th>
                <td mat-cell *matCellDef="let r">{{ r.speed | number }} Mbps</td>
              </ng-container>
              <ng-container matColumnDef="tx_pkts">
                <th mat-header-cell *matHeaderCellDef>TX Pkts</th>
                <td mat-cell *matCellDef="let r">{{ r.tx_pkts | number }}</td>
              </ng-container>
              <ng-container matColumnDef="rx_pkts">
                <th mat-header-cell *matHeaderCellDef>RX Pkts</th>
                <td mat-cell *matCellDef="let r">{{ r.rx_pkts | number }}</td>
              </ng-container>
              <tr mat-header-row *matHeaderRowDef="['port_id','speed','tx_pkts','rx_pkts']"></tr>
              <tr mat-row *matRowDef="let r; columns: ['port_id','speed','tx_pkts','rx_pkts']"></tr>
            </table>
          </div>
        </section>
      }
      @if (dhcpRows().length > 0) {
        <section class="table-section">
          <h3 class="section-title">DHCP Pools</h3>
          <div class="table-card">
            <table mat-table [dataSource]="dhcpRows()">
              <ng-container matColumnDef="network_name">
                <th mat-header-cell *matHeaderCellDef>Network</th>
                <td mat-cell *matCellDef="let r">{{ r.network_name }}</td>
              </ng-container>
              <ng-container matColumnDef="num_leased">
                <th mat-header-cell *matHeaderCellDef>Leased</th>
                <td mat-cell *matCellDef="let r">{{ r.num_leased }}/{{ r.num_ips }}</td>
              </ng-container>
              <ng-container matColumnDef="utilization_pct">
                <th mat-header-cell *matHeaderCellDef>Utilization</th>
                <td mat-cell *matCellDef="let r">{{ r.utilization_pct | number:'1.0-1' }}%</td>
              </ng-container>
              <tr mat-header-row *matHeaderRowDef="['network_name','num_leased','utilization_pct']"></tr>
              <tr mat-row *matRowDef="let r; columns: ['network_name','num_leased','utilization_pct']"></tr>
            </table>
          </div>
        </section>
      }
    }

    <!-- Gateway DHCP table -->
    @if (isGateway() && dhcpRows().length > 0) {
      <section class="table-section">
        <h3 class="section-title">DHCP Pools</h3>
        <div class="table-card">
          <table mat-table [dataSource]="dhcpRows()">
            <ng-container matColumnDef="network_name">
              <th mat-header-cell *matHeaderCellDef>Network</th>
              <td mat-cell *matCellDef="let r">{{ r.network_name }}</td>
            </ng-container>
            <ng-container matColumnDef="num_leased">
              <th mat-header-cell *matHeaderCellDef>Leased</th>
              <td mat-cell *matCellDef="let r">{{ r.num_leased }}/{{ r.num_ips }}</td>
            </ng-container>
            <ng-container matColumnDef="utilization_pct">
              <th mat-header-cell *matHeaderCellDef>Utilization</th>
              <td mat-cell *matCellDef="let r">{{ r.utilization_pct | number:'1.0-1' }}%</td>
            </ng-container>
            <tr mat-header-row *matHeaderRowDef="['network_name','num_leased','utilization_pct']"></tr>
            <tr mat-row *matRowDef="let r; columns: ['network_name','num_leased','utilization_pct']"></tr>
          </table>
        </div>
      </section>
    }
  }

  <!-- Live event log -->
  @if (mac()) {
    <section class="device-section">
      <h3 class="section-title">Live Event Log</h3>
      <app-device-live-log [mac]="mac()" />
    </section>
  }
</div>
```

- [ ] **Step 3: Create `telemetry-device.component.scss`**

```scss
.telemetry-device-page {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header .breadcrumb {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 14px;

  a { color: var(--app-primary); text-decoration: none; }
  .sep { font-size: 16px; color: var(--app-text-muted); }
}

.kpi-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.kpi-card {
  flex: 1;
  min-width: 110px;
  background: var(--app-canvas);
  border: 1px solid var(--app-border);
  border-radius: 8px;
  padding: 12px;

  .kpi-label { font-size: 11px; color: var(--app-text-muted); margin-bottom: 4px; }
  .kpi-value { font-size: 22px; font-weight: 700; color: var(--app-text); }
}

.time-range-picker {
  display: flex;
  align-items: center;
  gap: 8px;

  .label { font-size: 12px; color: var(--app-text-muted); }
  button.active { background-color: var(--app-primary); color: white; }
}

.chart-section, .table-section, .device-section {
  background: var(--app-canvas);
  border: 1px solid var(--app-border);
  border-radius: 8px;
  padding: 16px;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--app-text-muted);
  margin: 0 0 12px;
}

.chart-wrapper {
  height: 160px;
  position: relative;
}
```

- [ ] **Step 4: Fix `loadCharts()` to use real siteId**

In `telemetry-device.component.ts`, update `loadCharts()`:
```typescript
private loadCharts(): void {
  const mac = this.mac();
  const tr = this.timeRange();
  const dtype = this.deviceType();
  const siteId = (this.latestStats()?.stats?.['site_id'] as string) ?? '';
  if (!mac || !dtype || !siteId) return;

  const measurement = dtype === 'gateway' ? 'gateway_health' : 'device_summary';
  const cpuField = dtype === 'gateway' ? 'cpu_idle' : 'cpu_util';

  forkJoin({
    cpu: this.telemetryService.queryAggregate({ siteId, measurement, field: cpuField, timeRange: tr }),
  })
    .pipe(takeUntilDestroyed(this.destroyRef))
    .subscribe((results) => this.buildCharts(results));
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/features/telemetry/device/telemetry-device.component.ts \
        frontend/src/app/features/telemetry/device/telemetry-device.component.html \
        frontend/src/app/features/telemetry/device/telemetry-device.component.scss
git commit -m "feat(telemetry): add TelemetryDeviceComponent with KPI cards and tables"
```

---

## Task 10: Build `DeviceLiveLogComponent`

The live log subscribes to `telemetry:device:{mac}` on init and renders each incoming event as a new row at the top. Capped at 100 rows.

**Files:**
- Create: `frontend/src/app/features/telemetry/device/components/device-live-log/device-live-log.component.ts`
- Create: `frontend/src/app/features/telemetry/device/components/device-live-log/device-live-log.component.html`

- [ ] **Step 1: Create `device-live-log.component.ts`**

```typescript
import {
  Component,
  DestroyRef,
  Input,
  OnChanges,
  SimpleChanges,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DatePipe, DecimalPipe } from '@angular/common';
import { Subscription } from 'rxjs';
import { TelemetryService } from '../../../telemetry.service';
import { DeviceLiveEvent } from '../../../models';

const MAX_LOG_ROWS = 100;

@Component({
  selector: 'app-device-live-log',
  standalone: true,
  imports: [DatePipe, DecimalPipe],
  templateUrl: './device-live-log.component.html',
})
export class DeviceLiveLogComponent implements OnChanges {
  @Input() mac = '';

  private readonly telemetryService = inject(TelemetryService);
  private readonly destroyRef = inject(DestroyRef);
  private wsSub?: Subscription;

  readonly entries = signal<DeviceLiveEvent[]>([]);
  readonly newEntryMac = signal<number | null>(null);  // timestamp of newest entry for highlight

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['mac'] && this.mac) {
      this.subscribeToDevice(this.mac);
    }
  }

  private subscribeToDevice(mac: string): void {
    this.wsSub?.unsubscribe();
    this.entries.set([]);

    this.wsSub = this.telemetryService
      .subscribeToDevice(mac)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((event) => {
        this.entries.update((prev) => {
          const next = [event, ...prev];
          return next.length > MAX_LOG_ROWS ? next.slice(0, MAX_LOG_ROWS) : next;
        });
        this.newEntryMac.set(event.timestamp);
      });
  }
}
```

- [ ] **Step 2: Create `device-live-log.component.html`**

```html
<div class="live-log">
  @if (entries().length === 0) {
    <div class="empty">Waiting for live events… (subscribe by viewing this page)</div>
  }

  @for (entry of entries(); track entry.timestamp) {
    <div class="log-row" [class.new-entry]="newEntryMac() === entry.timestamp">
      <span class="ts">{{ entry.timestamp * 1000 | date:'HH:mm:ss' }}</span>
      <span class="dtype badge-{{ entry.device_type }}">{{ entry.device_type | uppercase }}</span>
      <span class="field">CPU: {{ entry.summary.cpu_util | number:'1.0-0' }}%</span>
      <span class="field">Mem: {{ entry.summary.mem_usage | number:'1.0-0' }}%</span>
      @if (entry.summary.num_clients !== undefined) {
        <span class="field">Clients: {{ entry.summary.num_clients }}</span>
      }
      @if (entry.device_type === 'ap' && entry.bands?.length) {
        @for (band of entry.bands; track band.band) {
          <span class="field band">{{ band.band }}: util={{ band.util_all | number:'1.0-0' }}% cl={{ band.num_clients }}</span>
        }
      }
      @if (entry.device_type === 'switch') {
        <span class="field">PoE: {{ entry.summary.poe_draw_total | number:'1.0-0' }}W</span>
        <span class="field">Ports UP: {{ entry.ports?.length ?? 0 }}</span>
      }
      @if (entry.device_type === 'gateway') {
        <span class="field">{{ entry.summary.ha_state }}</span>
        @for (wan of (entry.wan ?? []); track wan.port_id) {
          <span class="field wan" [class.wan-up]="wan.up" [class.wan-down]="!wan.up">
            {{ wan.wan_name || wan.port_id }}: {{ wan.up ? 'UP' : 'DOWN' }}
          </span>
        }
      }
    </div>
  }
</div>

<style>
.live-log {
  font-family: monospace;
  font-size: 12px;
  max-height: 400px;
  overflow-y: auto;
  background: var(--app-surface);
  border-radius: 6px;
  padding: 8px;
}
.empty { color: var(--app-text-muted); padding: 12px; text-align: center; }
.log-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 4px 6px;
  border-bottom: 1px solid var(--app-border);
  align-items: center;
  transition: background 0.4s;
}
.log-row.new-entry { background: var(--app-primary-subtle, rgba(96,165,250,0.1)); }
.ts { color: var(--app-text-muted); min-width: 70px; }
.dtype { padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; }
.badge-ap { background: var(--app-info-bg, #dbeafe); color: var(--app-info, #2563eb); }
.badge-switch { background: var(--app-success-bg, #dcfce7); color: var(--app-success, #16a34a); }
.badge-gateway { background: var(--app-warning-bg, #fef9c3); color: var(--app-warning, #ca8a04); }
.field { color: var(--app-text); }
.band { color: var(--app-text-muted); }
.wan-up { color: var(--app-success); }
.wan-down { color: var(--app-error); }
</style>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/features/telemetry/device/components/
git commit -m "feat(telemetry): add DeviceLiveLogComponent with WebSocket subscription"
```

---

## Task 11: Update CLAUDE.md files

**Files:**
- Modify: `backend/app/modules/telemetry/CLAUDE.md`
- Modify: `frontend/CLAUDE.md` (add telemetry feature note if needed)

- [ ] **Step 1: Update `backend/app/modules/telemetry/CLAUDE.md`**

In the **Backend** section, update the **REST endpoints** bullet to add:
```
- `GET /telemetry/scope/summary` — aggregated KPI values from LatestValueCache per device type; optional `site_id` filter (omit for org-wide). Requires `require_impact_role`.
- `GET /telemetry/scope/devices` — flat list of devices with latest stats from cache; optional `site_id` filter. Requires `require_impact_role`.
- `GET /telemetry/query/aggregate` — now accepts either `site_id` OR `org_id` (mutually exclusive) for scope filtering. `org_id` filters by org_id tag for org-wide chart queries.
```

In the **Backend** section, update the **Device-type extractors** bullet to add:
```
`switch_extractor` also produces `switch_dhcp` (same logic as `gateway_dhcp`, from `dhcpd_stat`; silently produces no points when absent).
```

In the **Backend** section, update or add a **WebSocket broadcast** bullet:
```
- **WebSocket broadcast**: After each device stat is written to InfluxDB, `IngestionService` broadcasts to `telemetry:device:{mac}` via `ws_manager` (from `app.core.websocket`). Payload includes `device_type`, `timestamp`, `summary` dict, and type-specific arrays (`bands`, `ports`, `modules`, `dhcp`, `wan`, `spu`, `cluster`, `resources`). The broadcast is a no-op if no frontend client is subscribed.
```

Add a **Frontend** section at the end:
```
## Frontend (`features/telemetry/`)

- **Routes**: `/telemetry` and `/telemetry/site/:id` → `TelemetryScopeComponent`; `/telemetry/device/:mac` → `TelemetryDeviceComponent`
- **TelemetryService**: All API calls (`getScopeSummary`, `getScopeDevices`, `getLatestStats`, `queryAggregate`) plus `subscribeToDevice(mac)` which returns an Observable from `WebSocketService.subscribe('telemetry:device:{mac}')`.
- **TelemetryScopeComponent**: Time range picker (1h/6h/24h, triggers chart reload only), per-device-type KPI cards from scope/summary, device table from scope/devices. Scope determined by `ActivatedRoute` param `:id`.
- **TelemetryDeviceComponent**: KPI cards from `GET /telemetry/latest/{mac}`, charts from `query_aggregate` (per-device filtered by site_id from latest stats), type-specific tables (ports, modules, DHCP). Charts use Chart.js `canvas` elements via `ViewChild`.
- **DeviceLiveLogComponent**: Subscribes to `telemetry:device:{mac}` via `TelemetryService.subscribeToDevice()`. Prepends each event to a signal array capped at 100 rows.
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/modules/telemetry/CLAUDE.md
git commit -m "docs: update telemetry CLAUDE.md with new endpoints, WS broadcast, and frontend"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| Switch DHCP extraction (`switch_dhcp` measurement) | Task 1 |
| `switch_dhcp` in ALLOWED_MEASUREMENTS + COV_THRESHOLDS | Task 1 |
| WS broadcast `telemetry:device:{mac}` from IngestionService | Task 3 |
| `GET /telemetry/scope/summary` | Task 4 |
| `GET /telemetry/scope/devices` | Task 4 |
| Org-level chart queries (via `org_id` filter in `query_aggregate`) | Task 2 |
| Sidebar Telemetry nav item + lazy route | Task 5 |
| `TelemetryScopeComponent` (org + site, time range picker, KPI cards per type) | Task 7 |
| Scope device table (clickable, links to device page) | Task 8 |
| `TelemetryDeviceComponent` (KPI cards, charts, switch tables, DHCP tables) | Task 9 |
| `DeviceLiveLogComponent` (WebSocket, prepend rows, cap 100, highlight) | Task 10 |
| Breadcrumb navigation | Task 9 (in template) |
| Per-band KPI cards (AP) | Task 7 |
| PoE KPI (switch) | Task 7 |
| WAN links KPI (gateway) | Task 7 |

**Gaps found and fixed:**
- The `loadCharts()` in Task 9 initially used `'todo'` as siteId — fixed in Step 4 to read it from `latestStats().stats['site_id']`.
- The scope component's org-level `queryAggregate` call passes `orgId` but needs the real org UUID. The backend has `settings.mist_org_id` from the config. The frontend doesn't know the org UUID. **Resolution**: the `/telemetry/scope/summary` endpoint already reads all-org data from cache without needing an org_id param. For scope charts at org level, the frontend should call `queryAggregate` with `orgId` — but the frontend needs to know the org ID. Since the frontend doesn't have direct access to it, the simplest fix: the scope charts are only loaded when `siteId` is known (site scope). At org level, only KPI cards (from `scope/summary`) are shown; charts are omitted. Update `loadCharts()` in `TelemetryScopeComponent` to guard: `if (!siteId) return;`.

**Placeholder scan:** No TBD or TODO in code blocks. All imports match defined types.

**Type consistency check:**
- `TelemetryService.queryAggregate()` accepts `{ siteId?, orgId?, measurement, field, agg?, timeRange }` — matches all call sites in Tasks 7 and 9.
- `DeviceLiveEvent` interface matches `_build_device_ws_event()` output in Task 3.
- `ScopeSummary`, `ScopeDevices`, `DeviceSummaryRecord` all match backend Pydantic schemas.
