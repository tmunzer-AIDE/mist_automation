# Telemetry UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign telemetry frontend into three pages (Org/Site/Device) with InfluxDB-backed site/device lists, charts, and raw JSON live log viewer.

**Architecture:** Backend adds two new InfluxDB query methods and a `scope/sites` endpoint; modifies `scope/summary` to source `reporting_total` from InfluxDB and adds missing KPIs (memory, ports, SPU); modifies `scope/devices` with `device_type` filter; adds raw payload to WS broadcast. Frontend splits the current scope component into org-only, creates a new site component, adds Chart.js charts to all three pages, and adds a raw JSON toggle to the live log.

**Tech Stack:** Python/FastAPI, InfluxDB Flux queries, Angular 21 standalone components, Chart.js via ng2-charts, Angular Material

**Spec:** `docs/superpowers/specs/2026-03-29-telemetry-ui-redesign.md`

---

### Task 1: Backend — Add InfluxDB query methods for distinct sites and device counts

**Files:**
- Modify: `backend/app/modules/telemetry/services/influxdb_service.py`

- [ ] **Step 1: Add `query_distinct_sites` method**

Add after the existing `query_aggregate` method (after line 285):

```python
async def query_distinct_sites(self, hours: int = 24) -> list[dict[str, Any]]:
    """Query distinct site_id values with per-device-type MAC counts.

    Returns list of dicts: [{site_id, device_counts: {ap: N, switch: N, gateway: N}}]
    """
    if not self._connected:
        return []

    flux = f"""
from(bucket: "{self._bucket}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "device_summary")
  |> filter(fn: (r) => r._field == "cpu_util")
  |> group(columns: ["site_id", "device_type"])
  |> distinct(column: "mac")
  |> count()
  |> group()
"""
    try:
        tables = await self._query_api.query(flux, org=self._org)
        # Build {site_id: {device_type: count}}
        site_map: dict[str, dict[str, int]] = {}
        for table in tables:
            for record in table.records:
                sid = record.values.get("site_id", "")
                dtype = record.values.get("device_type", "")
                count = record.values.get("_value", 0)
                if sid:
                    if sid not in site_map:
                        site_map[sid] = {}
                    site_map[sid][dtype] = int(count)

        return [
            {"site_id": sid, "device_counts": counts}
            for sid, counts in site_map.items()
        ]
    except Exception as e:
        logger.error("influxdb_query_distinct_sites_error", error=str(e))
        return []
```

- [ ] **Step 2: Add `query_distinct_device_count` method**

Add immediately after `query_distinct_sites`:

```python
async def query_distinct_device_count(
    self,
    site_id: str | None = None,
    device_type: str | None = None,
    hours: int = 24,
) -> int:
    """Count distinct MACs in device_summary over the given time window."""
    if not self._connected:
        return 0

    scope_filter = ""
    if site_id:
        scope_filter += f'\n  |> filter(fn: (r) => r.site_id == "{site_id}")'
    if device_type:
        scope_filter += f'\n  |> filter(fn: (r) => r.device_type == "{device_type}")'

    flux = f"""
from(bucket: "{self._bucket}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "device_summary")
  |> filter(fn: (r) => r._field == "cpu_util"){scope_filter}
  |> group()
  |> distinct(column: "mac")
  |> count()
"""
    try:
        tables = await self._query_api.query(flux, org=self._org)
        for table in tables:
            for record in table.records:
                return int(record.values.get("_value", 0))
        return 0
    except Exception as e:
        logger.error("influxdb_query_distinct_count_error", error=str(e))
        return 0
```

- [ ] **Step 3: Verify no syntax errors**

Run: `cd backend && .venv/bin/python -c "from app.modules.telemetry.services.influxdb_service import InfluxDBService; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/modules/telemetry/services/influxdb_service.py
git commit -m "feat(telemetry): add InfluxDB query methods for distinct sites and device counts"
```

---

### Task 2: Backend — Add schemas and scope/sites endpoint

**Files:**
- Modify: `backend/app/modules/telemetry/schemas.py`
- Modify: `backend/app/modules/telemetry/router.py`

- [ ] **Step 1: Add new schemas**

Add at end of `schemas.py` (after `ScopeDevicesResponse`):

```python
class SiteSummaryRecord(BaseModel):
    site_id: str
    site_name: str = ""
    device_counts: dict[str, int] = {}
    total_devices: int = 0


class ScopeSitesResponse(BaseModel):
    sites: list[SiteSummaryRecord]
    total: int = 0
```

- [ ] **Step 2: Add scope/sites endpoint in router.py**

Add the import of the new schema to the existing import block at top of `router.py`:

```python
from app.modules.telemetry.schemas import (
    ...existing imports...,
    ScopeSitesResponse,
    SiteSummaryRecord,
)
```

Add the endpoint before the existing `get_scope_summary` function (around line 130):

```python
@router.get("/scope/sites", response_model=ScopeSitesResponse)
async def get_scope_sites(
    _current_user: User = Depends(require_impact_role),
) -> ScopeSitesResponse:
    """Return list of sites that have reported telemetry data in the last 24h.

    Site names resolved from LatestValueCache; device counts from InfluxDB.
    """
    import app.modules.telemetry as telemetry_mod

    if telemetry_mod._influxdb is None:
        raise HTTPException(status_code=503, detail="InfluxDB not available")

    # Get distinct sites with device counts from InfluxDB
    raw_sites = await telemetry_mod._influxdb.query_distinct_sites(hours=24)

    # Resolve site_name from cache (any device at that site has site_name)
    site_names: dict[str, str] = {}
    if telemetry_mod._latest_cache is not None:
        for _mac, entry in telemetry_mod._latest_cache.get_all_entries().items():
            payload = entry.get("stats", {})
            sid = payload.get("site_id", "")
            sname = payload.get("site_name", "")
            if sid and sname and sid not in site_names:
                site_names[sid] = sname

    sites: list[SiteSummaryRecord] = []
    for raw in raw_sites:
        sid = raw["site_id"]
        counts = raw.get("device_counts", {})
        total = sum(counts.values())
        sites.append(
            SiteSummaryRecord(
                site_id=sid,
                site_name=site_names.get(sid, ""),
                device_counts=counts,
                total_devices=total,
            )
        )

    # Sort by site_name
    sites.sort(key=lambda s: s.site_name.lower())

    return ScopeSitesResponse(sites=sites, total=len(sites))
```

- [ ] **Step 3: Verify import and endpoint**

Run: `cd backend && .venv/bin/python -c "from app.modules.telemetry.router import router; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/modules/telemetry/schemas.py backend/app/modules/telemetry/router.py
git commit -m "feat(telemetry): add scope/sites endpoint with InfluxDB-backed site discovery"
```

---

### Task 3: Backend — Modify scope/summary with InfluxDB reporting_total and missing KPIs

**Files:**
- Modify: `backend/app/modules/telemetry/schemas.py`
- Modify: `backend/app/modules/telemetry/router.py`

- [ ] **Step 1: Add missing fields to scope summary schemas**

In `schemas.py`, update `APScopeSummary` to add `avg_mem_usage`:

```python
class APScopeSummary(BaseModel):
    reporting_active: int = 0
    reporting_total: int = 0
    avg_cpu_util: float = 0.0
    max_cpu_util: float = 0.0
    avg_mem_usage: float = 0.0
    total_clients: int = 0
    bands: dict[str, BandSummary] = {}
```

Update `SwitchScopeSummary` to add `avg_mem_usage`, `ports_up`, `ports_total`:

```python
class SwitchScopeSummary(BaseModel):
    reporting_active: int = 0
    reporting_total: int = 0
    avg_cpu_util: float = 0.0
    avg_mem_usage: float = 0.0
    total_clients: int = 0
    ports_up: int = 0
    ports_total: int = 0
    poe_draw_total: float = 0.0
    poe_max_total: float = 0.0
    total_dhcp_leases: int = 0
```

Update `GatewayScopeSummary` to add `avg_mem_usage`, `avg_spu_cpu`, `total_spu_sessions`:

```python
class GatewayScopeSummary(BaseModel):
    reporting_active: int = 0
    reporting_total: int = 0
    avg_cpu_util: float = 0.0
    avg_mem_usage: float = 0.0
    wan_links_up: int = 0
    wan_links_total: int = 0
    total_dhcp_leases: int = 0
    avg_spu_cpu: float = 0.0
    total_spu_sessions: int = 0
```

- [ ] **Step 2: Update the get_scope_summary endpoint in router.py**

Add memory accumulators alongside existing CPU accumulators (around line 152):

```python
    ap_mems: list[float] = []
```

And in the switch section:
```python
    sw_mems: list[float] = []
    sw_ports_up: int = 0
    sw_ports_total: int = 0
```

And in the gateway section:
```python
    gw_mems: list[float] = []
    gw_spu_cpus: list[float] = []
    gw_spu_sessions: int = 0
```

In the AP processing block (around line 188), after `ap_cpus.append(cpu)`, add:
```python
            mem_total = payload.get("mem_total_kb", 0) or 0
            mem_used = payload.get("mem_used_kb", 0) or 0
            if mem_total > 0:
                ap_mems.append(mem_used / mem_total * 100)
```

In the switch processing block (around line 210), after `sw_cpus.append(cpu)`, add:
```python
            memory_stat = payload.get("memory_stat")
            if isinstance(memory_stat, dict):
                mem_usage = memory_stat.get("usage")
                if mem_usage is not None:
                    sw_mems.append(float(mem_usage))
```

In the switch section, after the PoE processing and before DHCP (around line 231), add port counting:
```python
            # Ports from if_stat
            if_stat = payload.get("if_stat")
            if isinstance(if_stat, dict):
                for _if_key, port_data in if_stat.items():
                    if not isinstance(port_data, dict):
                        continue
                    sw_ports_total += 1
                    if port_data.get("up"):
                        sw_ports_up += 1
```

In the gateway processing block (around line 243), after `gw_cpus.append(cpu)`, add:
```python
            memory_stat = payload.get("memory_stat")
            if isinstance(memory_stat, dict):
                mem_usage = memory_stat.get("usage")
                if mem_usage is not None:
                    gw_mems.append(float(mem_usage))
            # SPU stats
            spu_stat = payload.get("spu_stat")
            if isinstance(spu_stat, list) and spu_stat:
                spu = spu_stat[0]
                if isinstance(spu, dict):
                    spu_cpu = spu.get("spu_cpu")
                    if spu_cpu is not None:
                        gw_spu_cpus.append(float(spu_cpu))
                    spu_sessions = spu.get("spu_current_session")
                    if spu_sessions is not None:
                        gw_spu_sessions += int(spu_sessions)
```

- [ ] **Step 3: Replace reporting_total with InfluxDB-backed count**

Before the per-device-type accumulation loop (around line 149), add the InfluxDB queries:

```python
    # Get reporting_total from InfluxDB (distinct MACs in last 24h)
    influxdb_totals: dict[str, int] = {}
    if telemetry_mod._influxdb is not None:
        for dtype in ("ap", "switch", "gateway"):
            influxdb_totals[dtype] = await telemetry_mod._influxdb.query_distinct_device_count(
                site_id=site_id, device_type=dtype, hours=24
            )
```

Update the response builders to use `influxdb_totals`. Replace `reporting_total=ap_total` with `reporting_total=influxdb_totals.get("ap", ap_total)` (and similarly for switch/gateway). Also add the new fields:

AP summary builder:
```python
    ap_summary = APScopeSummary(
        reporting_active=ap_active,
        reporting_total=influxdb_totals.get("ap", ap_total),
        avg_cpu_util=round(sum(ap_cpus) / len(ap_cpus), 2) if ap_cpus else 0.0,
        max_cpu_util=round(max(ap_cpus), 2) if ap_cpus else 0.0,
        avg_mem_usage=round(sum(ap_mems) / len(ap_mems), 2) if ap_mems else 0.0,
        total_clients=ap_clients,
        bands=bands,
    )
```

Switch summary builder:
```python
    sw_summary = SwitchScopeSummary(
        reporting_active=sw_active,
        reporting_total=influxdb_totals.get("switch", sw_total),
        avg_cpu_util=round(sum(sw_cpus) / len(sw_cpus), 2) if sw_cpus else 0.0,
        avg_mem_usage=round(sum(sw_mems) / len(sw_mems), 2) if sw_mems else 0.0,
        total_clients=sw_clients,
        ports_up=sw_ports_up,
        ports_total=sw_ports_total,
        poe_draw_total=round(sw_poe_draw, 2),
        poe_max_total=round(sw_poe_max, 2),
        total_dhcp_leases=sw_dhcp_leases,
    )
```

Gateway summary builder:
```python
    gw_summary = GatewayScopeSummary(
        reporting_active=gw_active,
        reporting_total=influxdb_totals.get("gateway", gw_total),
        avg_cpu_util=round(sum(gw_cpus) / len(gw_cpus), 2) if gw_cpus else 0.0,
        avg_mem_usage=round(sum(gw_mems) / len(gw_mems), 2) if gw_mems else 0.0,
        wan_links_up=gw_wan_up,
        wan_links_total=gw_wan_total,
        total_dhcp_leases=gw_dhcp_leases,
        avg_spu_cpu=round(sum(gw_spu_cpus) / len(gw_spu_cpus), 2) if gw_spu_cpus else 0.0,
        total_spu_sessions=gw_spu_sessions,
    )
```

- [ ] **Step 4: Verify import**

Run: `cd backend && .venv/bin/python -c "from app.modules.telemetry.router import router; print('OK')"`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/telemetry/schemas.py backend/app/modules/telemetry/router.py
git commit -m "feat(telemetry): add memory/ports/SPU KPIs and InfluxDB-backed reporting_total"
```

---

### Task 4: Backend — Add device_type filter to scope/devices and include raw payload in WS broadcast

**Files:**
- Modify: `backend/app/modules/telemetry/router.py`
- Modify: `backend/app/modules/telemetry/services/ingestion_service.py`

- [ ] **Step 1: Add device_type filter to scope/devices**

Update the `get_scope_devices` function signature (around line 308) to accept a `device_type` query param:

```python
@router.get("/scope/devices", response_model=ScopeDevicesResponse)
async def get_scope_devices(
    site_id: str | None = Query(None, description="Site UUID to filter by"),
    device_type: str | None = Query(None, description="Device type: ap, switch, gateway"),
    _current_user: User = Depends(require_impact_role),
) -> ScopeDevicesResponse:
```

Add validation after the site_id check:

```python
    if device_type is not None and device_type not in ("ap", "switch", "gateway"):
        raise HTTPException(status_code=400, detail="Invalid device_type; must be ap, switch, or gateway")
```

Add filter in the loop, after the `site_id` filter (around line 335):

```python
        if device_type and dtype != device_type:
            continue
```

- [ ] **Step 2: Add raw payload to WS broadcast event**

In `ingestion_service.py`, modify `_build_device_ws_event` (line 120) to include the raw payload. Add at line 127, after the `event` dict is created:

```python
    event["raw"] = payload
```

This adds the full Mist stats payload to every WS event so the frontend can show it in raw mode.

- [ ] **Step 3: Verify imports**

Run: `cd backend && .venv/bin/python -c "from app.modules.telemetry.router import router; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/modules/telemetry/router.py backend/app/modules/telemetry/services/ingestion_service.py
git commit -m "feat(telemetry): add device_type filter to scope/devices, include raw payload in WS"
```

---

### Task 5: Frontend — Update models and TelemetryService

**Files:**
- Modify: `frontend/src/app/features/telemetry/models.ts`
- Modify: `frontend/src/app/features/telemetry/telemetry.service.ts`

- [ ] **Step 1: Add new types to models.ts**

Add `ScopeSite` interface after `ScopeDevices`:

```typescript
export interface ScopeSite {
  site_id: string;
  site_name: string;
  device_counts: Record<string, number>;
  total_devices: number;
}

export interface ScopeSites {
  sites: ScopeSite[];
  total: number;
}
```

Add `avg_mem_usage` to `APScopeSummary`:

```typescript
export interface APScopeSummary {
  reporting_active: number;
  reporting_total: number;
  avg_cpu_util: number;
  max_cpu_util: number;
  avg_mem_usage: number;
  total_clients: number;
  bands: Record<string, BandSummary>;
}
```

Add `avg_mem_usage`, `ports_up`, `ports_total` to `SwitchScopeSummary`:

```typescript
export interface SwitchScopeSummary {
  reporting_active: number;
  reporting_total: number;
  avg_cpu_util: number;
  avg_mem_usage: number;
  total_clients: number;
  ports_up: number;
  ports_total: number;
  poe_draw_total: number;
  poe_max_total: number;
  total_dhcp_leases: number;
}
```

Add `avg_mem_usage`, `avg_spu_cpu`, `total_spu_sessions` to `GatewayScopeSummary`:

```typescript
export interface GatewayScopeSummary {
  reporting_active: number;
  reporting_total: number;
  avg_cpu_util: number;
  avg_mem_usage: number;
  wan_links_up: number;
  wan_links_total: number;
  total_dhcp_leases: number;
  avg_spu_cpu: number;
  total_spu_sessions: number;
}
```

Add `raw` field to `DeviceLiveEvent`:

```typescript
export interface DeviceLiveEvent {
  device_type: string;
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
  raw?: Record<string, unknown>;
}
```

Add `RangeResult` interface for device chart queries:

```typescript
export interface RangeResult {
  mac: string;
  measurement: string;
  start: string;
  end: string;
  points: Record<string, unknown>[];
  count: number;
}
```

- [ ] **Step 2: Add new service methods**

In `telemetry.service.ts`, add import for `ScopeSites` and `RangeResult`:

```typescript
import {
  ScopeSummary,
  ScopeDevices,
  ScopeSites,
  LatestStats,
  AggregateResult,
  RangeResult,
  DeviceLiveEvent,
  TimeRange,
} from './models';
```

Add `getScopeSites()` method:

```typescript
  getScopeSites(): Observable<ScopeSites> {
    return this.api.get<ScopeSites>('/telemetry/scope/sites');
  }
```

Update `getScopeDevices` to accept `deviceType`:

```typescript
  getScopeDevices(siteId?: string, deviceType?: string): Observable<ScopeDevices> {
    const params: Record<string, string> = {};
    if (siteId) params['site_id'] = siteId;
    if (deviceType) params['device_type'] = deviceType;
    return this.api.get<ScopeDevices>('/telemetry/scope/devices', params);
  }
```

Add `queryRange` method:

```typescript
  queryRange(mac: string, measurement: string, start: string, end: string): Observable<RangeResult> {
    return this.api.get<RangeResult>('/telemetry/query/range', { mac, measurement, start, end });
  }
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && npx ng build --configuration development 2>&1 | tail -5`

Expected: Build succeeds (warnings OK)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/features/telemetry/models.ts frontend/src/app/features/telemetry/telemetry.service.ts
git commit -m "feat(telemetry): update models with new KPI fields, add service methods for sites and range queries"
```

---

### Task 6: Frontend — Refactor TelemetryScopeComponent as org-only with site autocomplete and charts

**Files:**
- Modify: `frontend/src/app/features/telemetry/scope/telemetry-scope.component.ts`
- Modify: `frontend/src/app/features/telemetry/scope/telemetry-scope.component.html`
- Modify: `frontend/src/app/features/telemetry/scope/telemetry-scope.component.scss`
- Modify: `frontend/src/app/features/telemetry/telemetry.routes.ts`

This is the largest single task. The component becomes org-only (no more site/:id route pointing here), gains a site autocomplete, and adds Chart.js charts.

- [ ] **Step 1: Update routes**

Replace `telemetry.routes.ts` content:

```typescript
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
      import('./site/telemetry-site.component').then((m) => m.TelemetrySiteComponent),
  },
  {
    path: 'device/:mac',
    loadComponent: () =>
      import('./device/telemetry-device.component').then((m) => m.TelemetryDeviceComponent),
  },
];

export default routes;
```

- [ ] **Step 2: Rewrite TelemetryScopeComponent TypeScript**

Replace the full component. Key changes: remove siteId/route param handling, add site autocomplete signal, add chart data loading via `queryAggregate`.

```typescript
import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { Router } from '@angular/router';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin } from 'rxjs';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { BaseChartDirective } from 'ng2-charts';
import { ChartConfiguration } from 'chart.js';
import { TelemetryService, TIME_RANGE_MAP, WINDOW_MAP } from '../telemetry.service';
import {
  TimeRange,
  ScopeSummary,
  ScopeSite,
  APScopeSummary,
  SwitchScopeSummary,
  GatewayScopeSummary,
  BandSummary,
  AggregateResult,
} from '../models';

@Component({
  selector: 'app-telemetry-scope',
  standalone: true,
  imports: [
    DecimalPipe,
    ReactiveFormsModule,
    MatAutocompleteModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    BaseChartDirective,
  ],
  templateUrl: './telemetry-scope.component.html',
  styleUrl: './telemetry-scope.component.scss',
})
export class TelemetryScopeComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly telemetryService = inject(TelemetryService);

  // State
  readonly timeRange = signal<TimeRange>('6h');
  readonly loading = signal(false);
  readonly summary = signal<ScopeSummary | null>(null);
  readonly sites = signal<ScopeSite[]>([]);
  readonly timeRanges: TimeRange[] = ['1h', '6h', '24h'];

  // Site autocomplete
  readonly siteSearchCtrl = new FormControl('');
  readonly filteredSites = computed(() => {
    const q = (this.siteSearchCtrl.value || '').toLowerCase();
    const all = this.sites();
    return q ? all.filter((s) => s.site_name.toLowerCase().includes(q)) : all;
  });

  // Chart data
  readonly apCpuChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly apClientsChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly apBandChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly swCpuChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly swPoeChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly swClientsChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly gwCpuChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly gwSpuChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly gwWanChart = signal<ChartConfiguration<'line'> | null>(null);

  // Computed
  readonly hasAP = computed(() => !!this.summary()?.ap);
  readonly hasSwitch = computed(() => !!this.summary()?.switch);
  readonly hasGateway = computed(() => !!this.summary()?.gateway);

  get ap(): APScopeSummary | undefined {
    return this.summary()?.ap ?? undefined;
  }
  get sw(): SwitchScopeSummary | undefined {
    return this.summary()?.switch ?? undefined;
  }
  get gw(): GatewayScopeSummary | undefined {
    return this.summary()?.gateway ?? undefined;
  }

  ngOnInit(): void {
    this.loadData();
    this.siteSearchCtrl.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
  }

  loadData(): void {
    this.loading.set(true);
    forkJoin({
      summary: this.telemetryService.getScopeSummary(),
      sites: this.telemetryService.getScopeSites(),
    }).subscribe({
      next: ({ summary, sites }) => {
        this.summary.set(summary);
        this.sites.set(sites.sites);
        this.loading.set(false);
        this.loadCharts();
      },
      error: () => this.loading.set(false),
    });
  }

  setTimeRange(tr: TimeRange): void {
    this.timeRange.set(tr);
    this.loadCharts();
  }

  selectSite(site: ScopeSite): void {
    this.router.navigate(['/telemetry/site', site.site_id]);
  }

  displaySiteName(site: ScopeSite): string {
    return site?.site_name || '';
  }

  bandEntries(bands: Record<string, BandSummary> | undefined): { band: string; label: string; data: BandSummary }[] {
    if (!bands) return [];
    const labels: Record<string, string> = { band_24: '2.4 GHz', band_5: '5 GHz', band_6: '6 GHz' };
    return Object.entries(bands).map(([band, data]) => ({ band, label: labels[band] || band, data }));
  }

  reportingOk(active: number, total: number): boolean {
    return total > 0 && active === total;
  }

  private loadCharts(): void {
    const tr = this.timeRange();
    const start = TIME_RANGE_MAP[tr];
    const window = WINDOW_MAP[tr];
    const base = { agg: 'mean' as const, start, window };

    if (this.hasAP()) {
      this.loadLineChart(
        { ...base, measurement: 'device_summary', field: 'cpu_util' },
        { ...base, measurement: 'device_summary', field: 'mem_usage' },
        'Avg CPU', 'Avg Memory', this.apCpuChart,
      );
      this.loadSingleChart({ ...base, measurement: 'device_summary', field: 'num_clients', agg: 'sum' }, 'Clients', this.apClientsChart);
      // Band utilization: 3 separate queries for each band is complex; use a single radio_stats query
      this.loadSingleChart({ ...base, measurement: 'radio_stats', field: 'util_all' }, 'Avg Utilization', this.apBandChart);
    }

    if (this.hasSwitch()) {
      this.loadLineChart(
        { ...base, measurement: 'device_summary', field: 'cpu_util' },
        { ...base, measurement: 'device_summary', field: 'mem_usage' },
        'Avg CPU', 'Avg Memory', this.swCpuChart,
      );
      this.loadSingleChart({ ...base, measurement: 'device_summary', field: 'poe_draw_total', agg: 'sum' }, 'PoE Draw (W)', this.swPoeChart);
      this.loadSingleChart({ ...base, measurement: 'device_summary', field: 'num_clients', agg: 'sum' }, 'Wired Clients', this.swClientsChart);
    }

    if (this.hasGateway()) {
      this.loadLineChart(
        { ...base, measurement: 'gateway_health', field: 'cpu_idle' },
        { ...base, measurement: 'gateway_health', field: 'mem_usage' },
        'Avg CPU (idle)', 'Avg Memory', this.gwCpuChart,
      );
      this.loadLineChart(
        { ...base, measurement: 'gateway_spu', field: 'spu_cpu' },
        { ...base, measurement: 'gateway_spu', field: 'spu_sessions', agg: 'sum' },
        'SPU CPU', 'SPU Sessions', this.gwSpuChart,
      );
      this.loadLineChart(
        { ...base, measurement: 'gateway_wan', field: 'tx_bytes', agg: 'sum' },
        { ...base, measurement: 'gateway_wan', field: 'rx_bytes', agg: 'sum' },
        'TX Bytes', 'RX Bytes', this.gwWanChart,
      );
    }
  }

  private loadLineChart(
    params1: { measurement: string; field: string; agg?: string; start: string; window: string },
    params2: { measurement: string; field: string; agg?: string; start: string; window: string },
    label1: string,
    label2: string,
    target: ReturnType<typeof signal<ChartConfiguration<'line'> | null>>,
  ): void {
    forkJoin({
      d1: this.telemetryService.queryAggregate({ ...params1, agg: params1.agg || 'mean' }),
      d2: this.telemetryService.queryAggregate({ ...params2, agg: params2.agg || 'mean' }),
    }).subscribe({
      next: ({ d1, d2 }) => {
        target.set(this.buildDualLineConfig(d1, d2, label1, label2));
      },
    });
  }

  private loadSingleChart(
    params: { measurement: string; field: string; agg?: string; start: string; window: string },
    label: string,
    target: ReturnType<typeof signal<ChartConfiguration<'line'> | null>>,
  ): void {
    this.telemetryService.queryAggregate({ ...params, agg: params.agg || 'mean' }).subscribe({
      next: (result) => {
        target.set(this.buildSingleLineConfig(result, label));
      },
    });
  }

  private buildDualLineConfig(
    d1: AggregateResult, d2: AggregateResult, l1: string, l2: string,
  ): ChartConfiguration<'line'> {
    return {
      type: 'line',
      data: {
        labels: d1.points.map((p) => new Date(p['_time'] as string)),
        datasets: [
          { label: l1, data: d1.points.map((p) => p['_value'] as number), borderWidth: 2, pointRadius: 0, tension: 0.3 },
          { label: l2, data: d2.points.map((p) => p['_value'] as number), borderWidth: 2, pointRadius: 0, tension: 0.3, borderDash: [5, 3] },
        ],
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { x: { type: 'time', display: true }, y: { beginAtZero: true } }, plugins: { legend: { position: 'bottom' } } },
    };
  }

  private buildSingleLineConfig(result: AggregateResult, label: string): ChartConfiguration<'line'> {
    return {
      type: 'line',
      data: {
        labels: result.points.map((p) => new Date(p['_time'] as string)),
        datasets: [
          { label, data: result.points.map((p) => p['_value'] as number), borderWidth: 2, pointRadius: 0, tension: 0.3, fill: true },
        ],
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { x: { type: 'time', display: true }, y: { beginAtZero: true } }, plugins: { legend: { position: 'bottom' } } },
    };
  }
}
```

- [ ] **Step 3: Rewrite the template**

Replace `telemetry-scope.component.html` with the org overview layout: page title, site autocomplete, time range picker, per-device-type KPI sections with chart rows below each section. Each device-type section shows KPI cards followed by 3 charts using `<canvas baseChart>`.

The template should follow the wireframe structure from the spec: header row with title + site autocomplete, time range picker, then AP/Switch/Gateway sections each with KPI row + chart row.

- [ ] **Step 4: Update SCSS**

Add styles for `.chart-row` (flex wrap, 3 equal-width chart containers), `.chart-container` (min-height 200px, border, border-radius), `.site-autocomplete` styling.

- [ ] **Step 5: Export `TIME_RANGE_MAP` and `WINDOW_MAP` from service**

In `telemetry.service.ts`, change the const declarations to `export const`:

```typescript
export const TIME_RANGE_MAP: Record<TimeRange, string> = { '1h': '-1h', '6h': '-6h', '24h': '-24h' };
export const WINDOW_MAP: Record<TimeRange, string> = { '1h': '2m', '6h': '10m', '24h': '30m' };
```

- [ ] **Step 6: Verify build**

Run: `cd frontend && npx ng build --configuration development 2>&1 | tail -5`

Expected: Build succeeds

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/features/telemetry/
git commit -m "feat(telemetry): refactor scope component as org-only with site autocomplete and charts"
```

---

### Task 7: Frontend — Create TelemetrySiteComponent

**Files:**
- Create: `frontend/src/app/features/telemetry/site/telemetry-site.component.ts`
- Create: `frontend/src/app/features/telemetry/site/telemetry-site.component.html`
- Create: `frontend/src/app/features/telemetry/site/telemetry-site.component.scss`

This is the new site detail page with breadcrumb, device type chips, KPIs, charts, and device table.

- [ ] **Step 1: Create the component TypeScript**

```typescript
import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin } from 'rxjs';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { BaseChartDirective } from 'ng2-charts';
import { ChartConfiguration } from 'chart.js';
import { TelemetryService, TIME_RANGE_MAP, WINDOW_MAP } from '../telemetry.service';
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
} from '../models';

@Component({
  selector: 'app-telemetry-site',
  standalone: true,
  imports: [
    DecimalPipe,
    ReactiveFormsModule,
    RouterModule,
    MatAutocompleteModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatTableModule,
    BaseChartDirective,
  ],
  templateUrl: './telemetry-site.component.html',
  styleUrl: './telemetry-site.component.scss',
})
export class TelemetrySiteComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly telemetryService = inject(TelemetryService);

  // State
  readonly siteId = signal<string>('');
  readonly siteName = signal<string>('');
  readonly timeRange = signal<TimeRange>('6h');
  readonly loading = signal(false);
  readonly summary = signal<ScopeSummary | null>(null);
  readonly devices = signal<ScopeDevices | null>(null);
  readonly activeDeviceType = signal<string>('');
  readonly timeRanges: TimeRange[] = ['1h', '6h', '24h'];
  readonly deviceTypes = ['ap', 'switch', 'gateway'];

  // Device search
  readonly deviceSearchCtrl = new FormControl('');
  readonly filteredDevices = computed(() => {
    const q = (this.deviceSearchCtrl.value || '').toLowerCase();
    const all = this.devices()?.devices || [];
    return q ? all.filter((d) => d.name.toLowerCase().includes(q) || d.mac.toLowerCase().includes(q)) : all;
  });

  // Chart data
  readonly cpuChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly chart2 = signal<ChartConfiguration<'line'> | null>(null);
  readonly chart3 = signal<ChartConfiguration<'line'> | null>(null);

  // Computed
  readonly hasAP = computed(() => !!this.summary()?.ap);
  readonly hasSwitch = computed(() => !!this.summary()?.switch);
  readonly hasGateway = computed(() => !!this.summary()?.gateway);

  readonly deviceCounts = computed(() => {
    const devs = this.devices()?.devices || [];
    return {
      ap: devs.filter((d) => d.device_type === 'ap').length,
      switch: devs.filter((d) => d.device_type === 'switch').length,
      gateway: devs.filter((d) => d.device_type === 'gateway').length,
    };
  });

  readonly displayedDevices = computed(() => {
    const type = this.activeDeviceType();
    const devs = this.filteredDevices();
    return type ? devs.filter((d) => d.device_type === type) : devs;
  });

  get ap(): APScopeSummary | undefined { return this.summary()?.ap ?? undefined; }
  get sw(): SwitchScopeSummary | undefined { return this.summary()?.switch ?? undefined; }
  get gw(): GatewayScopeSummary | undefined { return this.summary()?.gateway ?? undefined; }

  readonly deviceColumns = ['name', 'device_type', 'model', 'cpu_util', 'mem_usage', 'num_clients', 'uptime', 'last_seen'];

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id');
      if (id) {
        this.siteId.set(id);
        this.loadData();
      }
    });
    this.deviceSearchCtrl.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
  }

  loadData(): void {
    this.loading.set(true);
    const sid = this.siteId();
    forkJoin({
      summary: this.telemetryService.getScopeSummary(sid),
      devices: this.telemetryService.getScopeDevices(sid),
    }).subscribe({
      next: ({ summary, devices }) => {
        this.summary.set(summary);
        this.devices.set(devices);
        // Resolve site name from first device
        const firstDev = devices.devices[0];
        if (firstDev) {
          this.siteName.set(firstDev.name ? '' : ''); // Will be resolved from scope/sites or cache
        }
        this.loading.set(false);
        this.loadCharts();
      },
      error: () => this.loading.set(false),
    });
    // Also fetch site name
    this.telemetryService.getScopeSites().subscribe({
      next: (res) => {
        const site = res.sites.find((s) => s.site_id === sid);
        if (site) this.siteName.set(site.site_name);
      },
    });
  }

  toggleDeviceType(type: string): void {
    this.activeDeviceType.set(this.activeDeviceType() === type ? '' : type);
  }

  setTimeRange(tr: TimeRange): void {
    this.timeRange.set(tr);
    this.loadCharts();
  }

  navigateToDevice(mac: string): void {
    this.router.navigate(['/telemetry/device', mac]);
  }

  selectDevice(device: DeviceSummaryRecord): void {
    this.router.navigate(['/telemetry/device', device.mac]);
  }

  displayDeviceName(device: DeviceSummaryRecord): string {
    return device?.name || device?.mac || '';
  }

  bandEntries(bands: Record<string, BandSummary> | undefined): { band: string; label: string; data: BandSummary }[] {
    if (!bands) return [];
    const labels: Record<string, string> = { band_24: '2.4 GHz', band_5: '5 GHz', band_6: '6 GHz' };
    return Object.entries(bands).map(([band, data]) => ({ band, label: labels[band] || band, data }));
  }

  reportingOk(active: number, total: number): boolean {
    return total > 0 && active === total;
  }

  formatUptime(seconds: number | null | undefined): string {
    if (!seconds) return '—';
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    return d > 0 ? `${d}d ${h}h` : `${h}h`;
  }

  private loadCharts(): void {
    // Charts scoped to site — same pattern as org but with site_id filter
    // Implementation follows the same pattern as TelemetryScopeComponent.loadCharts()
    // but passes site_id to queryAggregate
    const tr = this.timeRange();
    const start = TIME_RANGE_MAP[tr];
    const window = WINDOW_MAP[tr];
    const sid = this.siteId();
    const type = this.activeDeviceType();

    // Show charts for active device type, or default to first available
    const showType = type || (this.hasAP() ? 'ap' : this.hasSwitch() ? 'switch' : 'gateway');

    if (showType === 'ap') {
      this.loadDualChart(sid, 'device_summary', 'cpu_util', 'mem_usage', 'CPU', 'Memory', start, window, this.cpuChart);
      this.loadAggChart(sid, 'device_summary', 'num_clients', 'sum', 'Clients', start, window, this.chart2);
      this.loadAggChart(sid, 'radio_stats', 'util_all', 'mean', 'Band Utilization', start, window, this.chart3);
    } else if (showType === 'switch') {
      this.loadDualChart(sid, 'device_summary', 'cpu_util', 'mem_usage', 'CPU', 'Memory', start, window, this.cpuChart);
      this.loadAggChart(sid, 'device_summary', 'poe_draw_total', 'sum', 'PoE Draw', start, window, this.chart2);
      this.loadAggChart(sid, 'device_summary', 'num_clients', 'sum', 'Wired Clients', start, window, this.chart3);
    } else {
      this.loadDualChart(sid, 'gateway_health', 'cpu_idle', 'mem_usage', 'CPU (idle)', 'Memory', start, window, this.cpuChart);
      this.loadDualChart(sid, 'gateway_spu', 'spu_cpu', 'spu_sessions', 'SPU CPU', 'Sessions', start, window, this.chart2);
      this.loadDualChart(sid, 'gateway_wan', 'tx_bytes', 'rx_bytes', 'TX', 'RX', start, window, this.chart3);
    }
  }

  private loadDualChart(
    siteId: string, measurement: string, f1: string, f2: string,
    l1: string, l2: string, start: string, window: string,
    target: ReturnType<typeof signal<ChartConfiguration<'line'> | null>>,
  ): void {
    forkJoin({
      d1: this.telemetryService.queryAggregate({ site_id: siteId, measurement, field: f1, agg: 'mean', start, window }),
      d2: this.telemetryService.queryAggregate({ site_id: siteId, measurement, field: f2, agg: 'mean', start, window }),
    }).subscribe({
      next: ({ d1, d2 }) => target.set(this.buildDualLine(d1, d2, l1, l2)),
    });
  }

  private loadAggChart(
    siteId: string, measurement: string, field: string, agg: string,
    label: string, start: string, window: string,
    target: ReturnType<typeof signal<ChartConfiguration<'line'> | null>>,
  ): void {
    this.telemetryService.queryAggregate({ site_id: siteId, measurement, field, agg, start, window }).subscribe({
      next: (r) => target.set(this.buildSingleLine(r, label)),
    });
  }

  private buildDualLine(d1: AggregateResult, d2: AggregateResult, l1: string, l2: string): ChartConfiguration<'line'> {
    return {
      type: 'line',
      data: {
        labels: d1.points.map((p) => new Date(p['_time'] as string)),
        datasets: [
          { label: l1, data: d1.points.map((p) => p['_value'] as number), borderWidth: 2, pointRadius: 0, tension: 0.3 },
          { label: l2, data: d2.points.map((p) => p['_value'] as number), borderWidth: 2, pointRadius: 0, tension: 0.3, borderDash: [5, 3] },
        ],
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { x: { type: 'time', display: true }, y: { beginAtZero: true } }, plugins: { legend: { position: 'bottom' } } },
    };
  }

  private buildSingleLine(result: AggregateResult, label: string): ChartConfiguration<'line'> {
    return {
      type: 'line',
      data: {
        labels: result.points.map((p) => new Date(p['_time'] as string)),
        datasets: [
          { label, data: result.points.map((p) => p['_value'] as number), borderWidth: 2, pointRadius: 0, tension: 0.3, fill: true },
        ],
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { x: { type: 'time', display: true }, y: { beginAtZero: true } }, plugins: { legend: { position: 'bottom' } } },
    };
  }
}
```

- [ ] **Step 2: Create the template**

Create `telemetry-site.component.html` with: breadcrumb, device type chips row + device search autocomplete, time range picker, KPI cards (conditional per active device type), chart row (3 charts), device table.

The template follows the site detail wireframe from the spec: breadcrumb, filter row with chips and search, KPI section that shows the selected device type's KPIs, chart row, then device table with clickable rows.

- [ ] **Step 3: Create the SCSS**

Create `telemetry-site.component.scss` with the same pattern as `telemetry-scope.component.scss`: page layout, breadcrumb, chip buttons, KPI row, chart row, table section. Use `--app-*` custom properties.

- [ ] **Step 4: Verify build**

Run: `cd frontend && npx ng build --configuration development 2>&1 | tail -5`

Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/features/telemetry/site/
git commit -m "feat(telemetry): add TelemetrySiteComponent with device type chips, charts, and device table"
```

---

### Task 8: Frontend — Update TelemetryDeviceComponent with breadcrumb, charts, WAN/SPU/cluster/resources tables

**Files:**
- Modify: `frontend/src/app/features/telemetry/device/telemetry-device.component.ts`
- Modify: `frontend/src/app/features/telemetry/device/telemetry-device.component.html`
- Modify: `frontend/src/app/features/telemetry/device/telemetry-device.component.scss`

- [ ] **Step 1: Update component TypeScript**

Add imports for `BaseChartDirective`, `ChartConfiguration`, `TelemetryService` chart methods, `RouterModule`. Add signals for chart data. Add computed properties for:
- `siteName`: extracted from `latestStats` payload's `site_name` field
- `siteId`: extracted from `latestStats` payload's `site_id` field
- `wanRows`: transform `if_stat` WAN ports from gateway stats
- `spuRow`: extract from `spu_stat`
- `clusterRow`: extract from `cluster_config`
- `resourceRows`: extract from `module_stat[0].network_resources`

Add `loadCharts()` method that queries `query/range` for the device's MAC with the selected time range. Charts:
- Common: CPU & Memory (from `device_summary`)
- AP: Clients (from `device_summary`), band utilization (from `radio_stats`)
- Switch: Clients, PoE draw (both from `device_summary`)
- Gateway: WAN TX/RX (from `gateway_wan`), SPU (from `gateway_spu`)

Add new table column arrays: `wanColumns`, `spuColumns`, `clusterColumns`, `resourceColumns`.

- [ ] **Step 2: Update template**

Update `telemetry-device.component.html`:
- Replace hardcoded breadcrumb with dynamic: `Telemetry > {{ siteName() }} > {{ deviceName() }}` with router links
- Add chart section below KPI cards (2-3 chart containers using `<canvas baseChart>`)
- Add WAN interface table (gateway only): port_id, wan_name, status (up/down badge), TX/RX bytes, TX/RX pkts
- Add SPU table (gateway SRX only): spu_cpu, sessions, max_sessions, memory
- Add Cluster table (gateway SRX cluster only): status, operational, primary/secondary health, control/fabric link
- Add Resources table (gateway SSR only): resource_type, count, limit, utilization %

- [ ] **Step 3: Update SCSS**

Add chart container styles, WAN status badge styles (`.wan-up`, `.wan-down`), cluster health styling.

- [ ] **Step 4: Verify build**

Run: `cd frontend && npx ng build --configuration development 2>&1 | tail -5`

Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/features/telemetry/device/
git commit -m "feat(telemetry): add charts, breadcrumb, and gateway tables to device detail page"
```

---

### Task 9: Frontend — Update DeviceLiveLogComponent with raw JSON toggle

**Files:**
- Modify: `frontend/src/app/features/telemetry/device/components/device-live-log/device-live-log.component.ts`
- Modify: `frontend/src/app/features/telemetry/device/components/device-live-log/device-live-log.component.html`
- Modify: `frontend/src/app/features/telemetry/device/components/device-live-log/device-live-log.component.scss`

- [ ] **Step 1: Add raw mode signal and expanded tracking**

In `device-live-log.component.ts`, add:

```typescript
import { JsonPipe } from '@angular/common';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
```

Add to imports array: `JsonPipe`, `MatButtonToggleModule`.

Add signals:
```typescript
  readonly viewMode = signal<'formatted' | 'raw'>('formatted');
  readonly expandedRows = signal<Set<number>>(new Set());
```

Add methods:
```typescript
  setViewMode(mode: 'formatted' | 'raw'): void {
    this.viewMode.set(mode);
  }

  toggleExpand(index: number): void {
    const expanded = new Set(this.expandedRows());
    if (expanded.has(index)) {
      expanded.delete(index);
    } else {
      expanded.add(index);
    }
    this.expandedRows.set(expanded);
  }

  isExpanded(index: number): boolean {
    return this.expandedRows().has(index);
  }

  formatJson(obj: Record<string, unknown> | undefined): string {
    return obj ? JSON.stringify(obj, null, 2) : '{}';
  }
```

- [ ] **Step 2: Update template**

Replace the live log template. Add a header row with "Live Events" title and a `mat-button-toggle-group` for Formatted/Raw. Below:

When `viewMode() === 'formatted'`: show existing formatted log rows (unchanged).

When `viewMode() === 'raw'`: show each event as a collapsible row. Each row shows timestamp + device type badge + "click to expand". When expanded, show the full `entry.raw` payload in a `<pre>` block with `formatJson()`.

```html
<div class="live-log-header">
  <span class="section-title">Live Events</span>
  <mat-button-toggle-group [value]="viewMode()" (change)="setViewMode($event.value)" hideSingleSelectionIndicator>
    <mat-button-toggle value="formatted">Formatted</mat-button-toggle>
    <mat-button-toggle value="raw">Raw JSON</mat-button-toggle>
  </mat-button-toggle-group>
</div>

<div class="live-log">
  @if (entries().length === 0) {
    <div class="empty">Waiting for live events...</div>
  }

  @if (viewMode() === 'formatted') {
    @for (entry of entries(); track entry.timestamp; let i = $index) {
      <!-- existing formatted row markup -->
    }
  } @else {
    @for (entry of entries(); track entry.timestamp; let i = $index) {
      <div class="log-row raw-row" (click)="toggleExpand(i)">
        <span class="ts">{{ entry.timestamp * 1000 | date: 'HH:mm:ss' }}</span>
        <span class="dtype" [class]="'badge-' + entry.device_type">{{ entry.device_type | uppercase }}</span>
        <span class="expand-hint">{{ isExpanded(i) ? 'collapse' : 'expand' }}</span>
      </div>
      @if (isExpanded(i)) {
        <pre class="raw-json">{{ formatJson(entry.raw) }}</pre>
      }
    }
  }
</div>
```

- [ ] **Step 3: Update SCSS**

Add styles:

```scss
.live-log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.raw-row {
  cursor: pointer;
}

.expand-hint {
  font-size: var(--app-text-xs);
  color: var(--mat-sys-primary);
  margin-left: auto;
}

.raw-json {
  font-family: monospace;
  font-size: 11px;
  background: var(--mat-sys-surface-container);
  border: 1px solid var(--mat-sys-outline-variant);
  border-radius: var(--app-radius-sm);
  padding: 12px;
  margin: 0 0 4px 0;
  overflow-x: auto;
  max-height: 400px;
  white-space: pre-wrap;
  word-break: break-all;
}
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && npx ng build --configuration development 2>&1 | tail -5`

Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/features/telemetry/device/components/device-live-log/
git commit -m "feat(telemetry): add raw JSON toggle to device live event log"
```

---

### Task 10: Backend/Frontend — Update CLAUDE.md and final verification

**Files:**
- Modify: `backend/app/modules/telemetry/CLAUDE.md`
- Modify: `frontend/CLAUDE.md`

- [ ] **Step 1: Update telemetry CLAUDE.md**

Update the Frontend section to reflect the new three-page structure, chart integration, and raw JSON log. Add the new `scope/sites` endpoint to the REST endpoints list. Update the schema descriptions.

- [ ] **Step 2: Update frontend CLAUDE.md**

Add `telemetry` to the lazy-loaded feature areas list if not already there.

- [ ] **Step 3: Run full frontend build**

Run: `cd frontend && npx ng build 2>&1 | tail -10`

Expected: Production build succeeds

- [ ] **Step 4: Run backend lint**

Run: `cd backend && .venv/bin/ruff check app/modules/telemetry/ 2>&1 | tail -10`

Expected: No errors (warnings acceptable)

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/telemetry/CLAUDE.md frontend/CLAUDE.md
git commit -m "docs: update telemetry CLAUDE.md with new pages, endpoints, and charts"
```
