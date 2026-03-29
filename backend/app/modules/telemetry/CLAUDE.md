# Telemetry Module

Part of mist_automation — see root `CLAUDE.md` for global architecture and conventions, `backend/CLAUDE.md` for backend patterns.

## Backend (`app/modules/telemetry/`)

- **Always-on WebSocket ingestion**: Connects to Mist Cloud WebSocket (`wss://api-ws.{region}.mist.com`) at startup, subscribes to `/sites/{site_id}/stats/devices` for all configured sites. Auto-scales connections (max 1000 channels per WebSocket). Uses `mistapi.websockets.sites.DeviceStatsEvents` with thread-to-asyncio bridge.
- **InfluxDB storage**: `InfluxDBService` with async batched writes (500 points or 10s flush interval), bounded buffer (10K items, drop on overflow). Query methods: `query_range`, `query_latest`, `query_aggregate` (Flux-based). InfluxDB 2.7 added to `docker-compose.yml`.
- **Hybrid CoV filtering**: `CoVFilter` with three threshold types: `"exact"` (state changes), `"always"` (counters), `float` (absolute deadband). Max staleness timeout (300s) forces periodic writes. Device summaries always written, per-port/radio metrics CoV-filtered.
- **LatestValueCache**: In-memory dict keyed by device MAC, updated on every WebSocket message. Zero-latency reads for impact analysis (`get_all_for_site()`) and AI chat. Replaces HTTP API polling in `SiteDataCoordinator` when cache has fresh data (< 60s).
- **Device-type extractors** (`extractors/`): Pure functions parsing raw WebSocket payloads into InfluxDB data points. `ap_extractor` (device_summary + radio_stats), `switch_extractor` (device_summary + port_stats + module_stats + switch_dhcp), `gateway_extractor` (SRX standalone/cluster + SSR — gateway_health, gateway_wan, gateway_spu, gateway_resources, gateway_cluster, gateway_dhcp). `switch_dhcp` follows the same pattern as `gateway_dhcp` (from `dhcpd_stat`; silently produces no points when absent).
- **Ingestion pipeline** (`services/ingestion_service.py`): Consumes from asyncio.Queue, dispatches to extractors, applies CoV filtering, writes to InfluxDB + cache. Tracks message rate and error stats.
- **MistWsManager** (`services/mist_ws_manager.py`): Manages WebSocket connections with auto-scaling (`ceil(sites / 1000)`), health monitoring (90s no-message threshold), dynamic site add/remove.
- **REST endpoints**: `GET /telemetry/status` (admin), `GET /telemetry/latest/{mac}`, `GET /telemetry/query/range`, `GET /telemetry/query/aggregate` (require_impact_role; accepts `site_id` OR `org_id` for scope filtering), `GET /telemetry/scope/summary` (aggregated KPI values from LatestValueCache per device type; optional `site_id`; KPI fields include `avg_mem_usage` for all types, `ports_up`/`ports_total` for switch, `avg_spu_cpu`/`total_spu_sessions` for gateway; `reporting_total` comes from InfluxDB distinct MAC count over 24h), `GET /telemetry/scope/sites` (require_impact_role; InfluxDB-backed site list with device counts per type), `GET /telemetry/scope/devices` (flat device list from cache; optional `site_id`, optional `device_type` query parameter), `PUT /telemetry/settings`, `POST /telemetry/reconnect` (admin).
- **WebSocket broadcast**: After each device stat is processed, `IngestionService` broadcasts to `telemetry:device:{mac}` via `ws_manager`. Payload includes `device_type`, `timestamp`, `summary`, `raw` (full payload for live log raw JSON view), and type-specific arrays (bands, ports, modules, dhcp, wan, spu, cluster, resources). No-op if no subscribers.
- **Config**: `SystemConfig` fields: `telemetry_enabled`, `influxdb_url`, `influxdb_token` (encrypted), `influxdb_org`, `influxdb_bucket`, `telemetry_retention_days`. InfluxDB token encrypted via `encrypt_sensitive_data()`.

## Frontend (`features/admin/settings/telemetry/`)

- **Settings page**: Enable toggle, InfluxDB connection form (url, org, bucket, token, retention), test connection button, pipeline status display.

## Frontend (`features/telemetry/`)

- **Routes**: `/telemetry` → `TelemetryScopeComponent` (org-only); `/telemetry/site/:id` → `TelemetrySiteComponent`; `/telemetry/device/:mac` → `TelemetryDeviceComponent`
- **TelemetryService**: `getScopeSites()`, `getScopeDevices(siteId?, deviceType?)`, `getLatestStats(mac)`, `queryAggregate(params)`, `queryRange(mac, measurement, start, end)`, `subscribeToDevice(mac)` via `WebSocketService.subscribe('telemetry:device:{mac}')`.
- **TelemetryScopeComponent**: Org-level aggregated KPIs per device type, site autocomplete dropdown (from `scope/sites`), Chart.js line charts (3 per device type: CPU+Memory, type-specific metric 1, type-specific metric 2). Time range picker (1h/6h/24h).
- **TelemetrySiteComponent**: Site-level KPIs, device type filter chips (All/AP/Switch/Gateway), device search autocomplete, Chart.js charts scoped to site, device table with clickable rows.
- **TelemetryDeviceComponent**: KPI cards, Chart.js time-series charts from `query/range`, type-specific tables (ports, modules, DHCP for switch; WAN, SPU, cluster, resources for gateway). Live event log with formatted/raw JSON toggle.
- **DeviceLiveLogComponent**: Subscribes to `telemetry:device:{mac}`, prepends events to a signal array capped at 100 rows. Supports formatted and raw JSON toggle views.
