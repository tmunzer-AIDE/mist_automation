# Telemetry UI Design

**Date:** 2026-03-28
**Status:** Approved

## Overview

A new `/telemetry` section in the frontend that provides insights into the device stats received via the Mist WebSocket pipeline. The goal is not to replicate a full NMS dashboard, but to show what data is being received, what its shape looks like (charts), and what values are flowing in (live log at device level).

## Routing Structure

Three lazy-loaded routes:

| Route | Component | Purpose |
|---|---|---|
| `/telemetry` | `TelemetryScopeComponent` | Org-wide view |
| `/telemetry/site/:id` | `TelemetryScopeComponent` (same) | Site-scoped view |
| `/telemetry/device/:mac` | `TelemetryDeviceComponent` | Device detail + live event log |

The "Telemetry" sidebar nav item (already planned) links to `/telemetry`.

Breadcrumb: **Telemetry › [Site Name] › [Device Name]**

## Org/Site Page (`TelemetryScopeComponent`)

One component renders both the org and site views. Scope is determined by the presence of `:id` in the route params — absent means org-wide.

### Layout (top to bottom)

1. **Time range picker** — 1h / 6h / 24h. Applies to charts only; KPI cards always show latest values.
2. **Device-type sections** — one section per type that has data in scope (AP / Switch / Gateway). Sections not rendered if no data.
3. **Device/site table** — at org level: site cards with device counts; at site level: device table with latest stats, clickable rows → `/telemetry/device/:mac`.

### Per device-type section: KPI cards + charts

#### Access Points

**KPI cards:**
- Avg `cpu_util`
- Total `num_clients`
- Avg `util_all` per active band (band_24, band_5, band_6 — only bands with data)
- Reporting: N/N devices (devices with a `LatestValueCache` entry fresher than 60s)

**Charts (time-series):**
- Avg `cpu_util` over time
- Total `num_clients` over time
- Avg `util_all` per band over time (multi-line: one line per band)
- Avg `noise_floor` per band over time

#### Switches

**KPI cards:**
- Avg `cpu_util`
- Total wired `num_clients`
- Total `poe_draw_total` W / `poe_max_total` W
- Total DHCP leases (`num_leased` sum, when `switch_dhcp` data present)
- Reporting: N/N devices

**Charts:**
- Avg `cpu_util` over time
- Total `poe_draw_total` over time
- Total `num_clients` (wired) over time

#### Gateways

**KPI cards:**
- Avg CPU % (`100 − cpu_idle`)
- WAN links up: N/N (across all WAN ports of all gateways in scope)
- Total WAN TX bytes/s (derived via InfluxDB `derivative()`)
- Total DHCP leases (`num_leased` sum across all scopes)
- Reporting: N/N devices

**Charts:**
- Avg CPU over time
- Total WAN `tx_bytes` + `rx_bytes` per second over time (derivative of counters)

## Device Page (`TelemetryDeviceComponent`)

### Layout (stacked, top to bottom)

1. **KPI cards** — current values from latest received stat
2. **Time range picker** — 1h / 6h / 24h
3. **Charts** — device-type specific (see below)
4. **Live event log** — full width, newest entry at top, capped at 100 rows

### KPI cards + charts by device type

#### AP

**KPI cards:** `cpu_util`, `mem_usage`, `num_clients`, `uptime`

Per active band (sub-cards): `channel`, `power` (dBm), `bandwidth` (MHz), `noise_floor` (dBm)

**Charts:**
- `cpu_util` + `mem_usage` over time (dual-line)
- `num_clients` over time
- `util_all` per band over time (multi-line)
- `num_clients` per band over time
- `noise_floor` per band over time

#### Switch

**KPI cards:** `cpu_util`, `mem_usage`, `num_clients` (wired), `poe_draw_total` / `poe_max_total`, `uptime`

**Charts:**
- `cpu_util` + `mem_usage` over time
- `poe_draw_total` over time

**Tables (latest values, no time range):**
- Port table: `port_id`, `speed`, `tx_pkts`, `rx_pkts` (UP ports only)
- VC member table: `fpc_idx`, `vc_role`, `temp_max` °C, `poe_draw` W, `vc_links_count`, `mem_usage` % (when `module_stats` present)
- DHCP table: `network_name`, `num_ips`, `num_leased`, `utilization_pct` (when `switch_dhcp` data present)

#### Gateway

**KPI cards:** CPU % (`100 − cpu_idle`), `mem_usage`, `ha_state`, `config_status`, `uptime`

**Charts:**
- CPU + `mem_usage` over time
- WAN `tx_bytes` / `rx_bytes` per port over time (bytes/s derivative)
- `spu_sessions` + `spu_cpu` over time *(SRX only)*

**Tables:**
- DHCP table: `network_name`, `num_ips`, `num_leased`, `utilization_pct`
- Cluster health: `status`, `operational`, `primary_health`, `secondary_health`, `control_link_up`, `fabric_link_up` *(SRX cluster only)*
- Resources table: `resource_type` (FIB / FLOW / ACCESS_POLICY), `count`, `limit`, `utilization_pct` *(SSR only)*

### Live Event Log

Full-width scrolling log below the charts. Each incoming WebSocket event appends as a new row at the top. Capped at 100 rows (oldest dropped). A brief highlight animation marks each new row.

Row format per device type:

| Type | Fields shown per row |
|---|---|
| AP | timestamp, `cpu_util`, `mem_usage`, `num_clients` + per active band: `util_all`, `num_clients`, `noise_floor`, `channel`, `bandwidth` |
| Switch | timestamp, `cpu_util`, `mem_usage`, `num_clients`, `poe_draw_total` + UP port count in this message |
| Gateway | timestamp, CPU %, `mem_usage`, `ha_state`, `config_status` + per WAN port: `up`, `tx_bytes`, `rx_bytes` |

## Data Sources

| Data | Source |
|---|---|
| KPI cards (org/site) | `GET /telemetry/scope/summary?site_id=&device_type=` (new) |
| Device list / site list | `GET /telemetry/scope/devices?site_id=` (new) |
| KPI cards (device) | `GET /telemetry/latest/{mac}` (existing) |
| Charts | `GET /telemetry/query/aggregate` (existing) with time range + scope filters |
| Live event log | WebSocket channel `telemetry:device:{mac}` (new) |

## Backend Changes

### 1. Switch DHCP extraction

Add `_extract_switch_dhcp()` to `switch_extractor.py`:
- Same logic as `_extract_gateway_dhcp()` — reads `dhcpd_stat`, produces one point per scope
- Measurement name: `switch_dhcp`
- Fields: `num_ips`, `num_leased`, `utilization_pct`; tag: `network_name`
- Silently produces no points when `dhcpd_stat` is absent
- Called from `extract_points()`

### 2. WebSocket broadcast in `IngestionService`

After processing a device update, broadcast to `telemetry:device:{mac}` only if the channel has subscribers:

```python
await ws_manager.broadcast(f"telemetry:device:{mac}", {
    "device_type": "ap" | "switch" | "gateway",
    "timestamp": <unix_ts>,
    "summary": {
        # AP: cpu_util, mem_usage, num_clients, uptime
        # Switch: cpu_util, mem_usage, num_clients, uptime, poe_draw_total, poe_max_total
        # Gateway: cpu_util (100-cpu_idle), mem_usage, uptime, ha_state, config_status
    },
    # AP only:
    "bands": [{ "band", "util_all", "num_clients", "noise_floor", "channel", "power", "bandwidth" }],
    # Switch only:
    "ports": [{ "port_id", "speed", "tx_pkts", "rx_pkts" }],
    "modules": [{ "fpc_idx", "vc_role", "temp_max", "poe_draw", "vc_links_count", "mem_usage" }],
    "dhcp": [{ "network_name", "num_ips", "num_leased", "utilization_pct" }],
    # Gateway only:
    "wan": [{ "port_id", "wan_name", "up", "tx_bytes", "rx_bytes", "tx_pkts", "rx_pkts" }],
    "dhcp": [{ "network_name", "num_ips", "num_leased", "utilization_pct" }],
    "spu": { "spu_cpu", "spu_sessions", "spu_max_sessions", "spu_memory" },  # SRX
    "cluster": { "status", "operational", "primary_health", "secondary_health",
                 "control_link_up", "fabric_link_up" },  # SRX cluster
    "resources": [{ "resource_type", "count", "limit", "utilization_pct" }],  # SSR
})
```

`WebSocketManager.broadcast()` is `async def` — await it directly inside `IngestionService`'s async consumer loop. It already skips channels with no subscribers, so no guard needed before calling it.

### 3. New REST endpoints

**`GET /telemetry/scope/summary`**

Query params: `site_id` (optional), `device_type` (optional: `ap` | `switch` | `gateway`)

Returns aggregated KPI values for the scope: avg/max of key metrics, computed via `query_aggregate` at the latest time window. Used for KPI cards on the org/site page.

**`GET /telemetry/scope/devices`**

Query params: `site_id` (optional)

Returns a flat paginated list of devices with their latest stats from `LatestValueCache`, each record including `site_id`, `device_type`, `mac`, `name`, `model`, and summary fields. At org level (no `site_id`), returns all devices across all sites. Used for the device table and to derive the site cards (frontend groups by `site_id`).

## Frontend Components

```
features/telemetry/
  telemetry.routes.ts
  scope/
    telemetry-scope.component.ts/.html/.scss
    components/
      scope-kpi-cards/          # per device type
      scope-charts/             # per device type
      scope-device-table/       # device list + site cards
  device/
    telemetry-device.component.ts/.html/.scss
    components/
      device-kpi-cards/         # per device type
      device-charts/            # per device type
      device-live-log/          # WebSocket event log
      device-port-table/        # switch ports
      device-module-table/      # switch VC members
      device-dhcp-table/        # switch + gateway DHCP
      device-cluster-panel/     # SRX cluster health
      device-resources-table/   # SSR resources
```

Charts use the existing `chart-defaults` utility from `shared/utils/chart-defaults`. All components are standalone, use `signal()`/`computed()` for state, `inject()` for DI.
