# Telemetry UI Redesign

**Date**: 2026-03-29
**Status**: Approved

## Overview

Redesign the telemetry frontend into three distinct pages (Org, Site, Device) with proper drill-down navigation, InfluxDB-backed data sources for site/device lists, charts on every page, and a raw JSON viewer in the device live event log.

## Routes

| Route | Component | Purpose |
|-------|-----------|---------|
| `/telemetry` | `TelemetryScopeComponent` (org mode) | Org-wide aggregated KPIs + charts, site autocomplete |
| `/telemetry/site/:id` | `TelemetrySiteComponent` | Site-level KPIs + charts, device type filter, device table |
| `/telemetry/device/:mac` | `TelemetryDeviceComponent` | Device KPIs + charts, type-specific tables, live event log |

## Backend Changes

### New Endpoint: `GET /telemetry/scope/sites`

Query InfluxDB `device_summary` measurement for distinct `(site_id, name)` pairs over the last 24h. Returns a list of sites that have actively reported telemetry data.

**Response shape:**
```json
{
  "sites": [
    {
      "site_id": "uuid",
      "site_name": "HQ Campus",
      "device_counts": { "ap": 12, "switch": 4, "gateway": 2 },
      "total_devices": 18
    }
  ],
  "total": 5
}
```

**Implementation**: Flux query using `distinct()` on `site_id` tag from `device_summary` where `_time > -24h`. Group by `site_id` and `device_type` to get per-type counts. Site name extracted from the `name` tag — but since `name` is the device name, we need to store `site_name` as a tag in extractors, OR query the LatestValueCache to resolve `site_id → site_name` from any cached payload's `site_name` field. Prefer the cache approach to avoid adding a new tag to all measurements.

Add a new method `query_distinct_sites(hours=24)` to `InfluxDBService`.

### Modify `GET /telemetry/scope/summary`

Add `reporting_total` field per device type section (AP, Switch, Gateway). Currently `reporting_active` and `reporting_total` both come from cache. Change:

- `reporting_active`: count of cache entries where `updated_at` < 60s ago (unchanged)
- `reporting_total`: count of distinct MACs in InfluxDB `device_summary` for that device type over last 24h

Add a new method `query_distinct_device_count(site_id=None, device_type=None, hours=24)` to `InfluxDBService`.

### Modify `GET /telemetry/scope/devices`

Add query parameter: `device_type` (optional, one of `ap`, `switch`, `gateway`) — filters the device list.

Ensure `model` is included in the response (already present in `DeviceSummaryRecord`).

### New InfluxDB Methods

Add to `InfluxDBService`:

1. `query_distinct_sites(hours: int = 24) -> list[dict]` — Flux: filter `device_summary`, range `-{hours}h`, group by `site_id` + `device_type`, count distinct `mac`.

2. `query_distinct_device_count(site_id: str | None, device_type: str | None, hours: int = 24) -> int` — Flux: filter `device_summary`, optional `site_id` and `device_type` filters, count distinct `mac`.

## Org Overview Page (`/telemetry`)

### Layout (top to bottom)

1. **Header row**: Page title "Telemetry" + site autocomplete dropdown (right-aligned)
2. **Time range picker**: 1h / 6h / 24h toggle buttons
3. **Per device type sections** (AP, Switch, Gateway — each section only shown if devices of that type exist):
   - Section header with device type label (colored badge)
   - KPI card row
   - Chart row (3 charts per type)

### KPI Cards Per Type

**Access Points:**
- Reporting (active/total)
- Avg CPU
- Avg Memory
- Total Clients
- Avg Band Utilization (weighted across bands)
- Avg Noise Floor

**Switches:**
- Reporting (active/total)
- Avg CPU
- Avg Memory
- Wired Clients
- Ports UP (total UP / total ports)
- Total PoE Draw
- DHCP Leases

**Gateways:**
- Reporting (active/total)
- Avg CPU
- Avg Memory
- WAN Links (up/total)
- DHCP Leases
- Avg SPU CPU (SRX only, hidden if no SRX)
- SPU Sessions (SRX only)

### Charts Per Type

All charts are line charts via Chart.js, driven by `queryAggregate` with `org_id` scope.

**AP charts:**
1. Avg CPU & Memory (two lines, memory dashed)
2. Total Clients (single line)
3. Avg Band Utilization (three lines: 2.4G, 5G, 6G)

**Switch charts:**
1. Avg CPU & Memory
2. Total PoE Draw (single line, kW)
3. Wired Clients

**Gateway charts:**
1. Avg CPU & Memory
2. SPU Sessions & SPU CPU (two lines)
3. WAN Traffic TX/RX bytes (two lines)

### Site Autocomplete

- Fetches site list from `GET /telemetry/scope/sites`
- Displays site name + device count
- On selection, navigates to `/telemetry/site/:id`
- Filtered client-side as user types

## Site Detail Page (`/telemetry/site/:id`)

### Layout (top to bottom)

1. **Breadcrumb**: Telemetry > Site Name
2. **Filter row**: Device type chips (All / AP(n) / Switch(n) / Gateway(n)) + device search autocomplete (right-aligned)
3. **Time range picker**: 1h / 6h / 24h
4. **KPI cards**: Same structure as org page, but scoped to site. When a device type chip is selected, only that type's KPIs and charts are shown. "All" shows all sections.
5. **Charts**: Same chart set as org page, scoped to site via `site_id` param. Filtered by active device type chip.
6. **Device table**: Sortable Material table with columns: Name, Type, Model, CPU, Memory, Clients, Uptime, Last Seen. Clickable rows navigate to `/telemetry/device/:mac`. Stale devices (non-fresh) styled with muted text + red last-seen.

### Device Type Chips

- Chip buttons: All, AP (count), Switch (count), Gateway (count)
- Counts from `scope/devices` response grouped by type
- Selecting a type:
  - Filters KPI cards to that type only
  - Filters charts to that type only
  - Filters device table via `device_type` query param
- "All" resets to showing all types

### Device Search Autocomplete

- Client-side filter over the loaded device list
- Shows device name + type + MAC
- On selection, navigates to `/telemetry/device/:mac`

## Device Detail Page (`/telemetry/device/:mac`)

### Layout (top to bottom)

1. **Breadcrumb**: Telemetry > Site Name > Device Name. Site name and device name resolved from the `latest/{mac}` response payload.
2. **Time range picker**: 1h / 6h / 24h
3. **KPI cards**: Device-specific metrics from `latest/{mac}`
4. **Charts**: Device-specific time series from `query/range`
5. **Type-specific tables**: Ports, VC modules, DHCP, WAN, SPU, cluster, resources
6. **Live event log**: WebSocket subscription with formatted/raw toggle

### KPI Cards

**Common (all types):** CPU, Memory, Uptime

**AP:** + Total Clients
**Switch:** + Wired Clients, PoE Draw / Max
**Gateway:** + HA State, Config Status

### Charts

All charts use `query/range` with the device's MAC. Chart.js line charts.

**Common:** CPU & Memory over time (two lines)

**AP:**
- Client count over time
- Per-band utilization over time (2.4G/5G/6G lines)
- Per-band client count over time
- Noise floor over time

**Switch:**
- Client count over time
- PoE draw over time

**Gateway:**
- WAN TX/RX bytes over time (per WAN interface or summed)
- SPU CPU & sessions over time (SRX only)
- DHCP utilization over time

### Type-Specific Tables

Render conditionally based on device type and data availability.

**Switch:**
- **Ports (UP)**: port_id, speed, TX pkts, RX pkts — from `if_stat` in latest stats
- **VC Members**: FPC index, role, max temp, PoE draw, VC links, memory — from `module_stat`
- **DHCP**: network name, pool size, leased, utilization % — from `dhcpd_stat`

**Gateway:**
- **WAN Interfaces**: port_id, wan_name, up/down status, TX/RX bytes, TX/RX pkts — from `if_stat` (wan ports)
- **DHCP**: same as switch
- **SPU** (SRX): SPU CPU, sessions, max sessions, memory — from `spu_stat`
- **Cluster** (SRX cluster): status, operational, primary/secondary health, control/fabric link — from `cluster_config`
- **Resources** (SSR): resource type, count, limit, utilization % — from `module_stat.network_resources`

**AP:** No tables (radio data shown in charts and KPIs).

### Live Event Log

Subscribes to `telemetry:device:{mac}` WebSocket channel. Displays events newest-first, capped at 100.

**Toggle**: Formatted / Raw JSON (segmented button)

**Formatted view**: One line per event, monospace font.
- Timestamp (HH:mm:ss)
- Device type badge (colored)
- Key metrics inline: CPU, Memory, Clients, type-specific (PoE for switch, WAN status for gateway, band util for AP)

**Raw JSON view**: Full WebSocket payload per event. Each row is collapsible — shows timestamp + "click to expand" by default. Expanded shows the complete JSON payload in a syntax-highlighted, scrollable `<pre>` block. Uses the raw `DeviceLiveEvent` data from the WebSocket, which includes the full Mist stats payload.

## Data Flow

### Site List (InfluxDB-backed)
```
scope/sites endpoint
  → InfluxDBService.query_distinct_sites(hours=24)
  → Flux: device_summary | range(-24h) | group(site_id, device_type) | distinct(mac) | count
  → Returns [{site_id, device_counts}]
  → Resolve site_name from LatestValueCache (any device at that site has site_name in payload)
```

### Reporting Count (InfluxDB-backed)
```
scope/summary endpoint (per device type)
  → reporting_active: cache entries with updated_at < 60s
  → reporting_total: InfluxDBService.query_distinct_device_count(site_id, device_type, hours=24)
```

### Charts
```
Org/Site charts: queryAggregate(org_id|site_id, measurement, field, agg, window, start, end)
Device charts: query/range(mac, measurement, start, end)
```

### Live Events
```
WebSocketService.subscribe('telemetry:device:{mac}')
  → DeviceLiveEvent with full payload
  → Formatted view: extract key fields for one-line display
  → Raw JSON view: show entire event payload
```

## Frontend Components

### New Components
- `TelemetrySiteComponent` — site detail page (new)
- `DeviceChartsComponent` — reusable chart container for device detail
- `ScopeChartsComponent` — reusable chart container for org/site scope

### Modified Components
- `TelemetryScopeComponent` — becomes org-only, add site autocomplete + charts
- `TelemetryDeviceComponent` — add charts, breadcrumb with site name, raw JSON toggle in live log
- `ScopeDeviceTableComponent` — add model column, device type filter support, stale styling
- `DeviceLiveLogComponent` — add formatted/raw toggle, collapsible JSON viewer
- `TelemetryService` — add `getScopeSites()`, update `getScopeDevices()` with `device_type` param
- `models.ts` — add `ScopeSite`, update `ScopeDevices` types

### Shared Dependencies
- Chart.js (already available)
- Angular Material autocomplete, chips, toggle buttons, tables
- WebSocketService for live events

## Time Range Mapping

| Selection | `start` param | `window` param (aggregate) |
|-----------|--------------|---------------------------|
| 1h | `-1h` | `2m` |
| 6h | `-6h` | `10m` |
| 24h | `-24h` | `30m` |

The time range picker signal is shared across all charts and KPI refresh on a page.
