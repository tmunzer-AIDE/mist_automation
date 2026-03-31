# Client Telemetry — Design Spec

**Date:** 2026-03-30
**Status:** Approved

## Context

The telemetry module currently streams and stores device stats (APs, Switches, Gateways) via the Mist WebSocket `/sites/{site_id}/stats/devices` channel. Client-level telemetry (wireless clients connected to APs) is not captured — only the aggregate `num_clients` count flows into `device_summary`.

Mist exposes a separate WebSocket channel `/sites/{site_id}/stats/clients` (one message per client, ~60s cadence) covered by `mistapi.websockets.sites.ClientsStatsEvents`. This channel carries all wireless clients regardless of auth method — both PSK and 802.1X/EAP clients appear in the same stream, distinguished by the `key_mgmt` field. This spec adds end-to-end support: ingestion → InfluxDB storage → REST API → dedicated UI page, plus client summary stats surfaced on the existing Scope and Site views.

Wired ethernet clients physically connected to AP LAN ports (`stats_wired_client` in the OAS) are out of scope — they use a different channel with a minimal schema and will be designed separately.

---

## Backend

### 1. WebSocket ingestion — `MistWsManager` + `ClientWsManager`

Add a second WS manager (`ClientWsManager`) using `ClientsStatsEvents` instead of `DeviceStatsEvents`. It shares the same asyncio queue as the device manager so a single `IngestionService` consume loop handles both message types. The manager follows the identical pattern: thread-to-asyncio bridge via `loop.call_soon_threadsafe()`, auto-scaling (1 connection per 1000 sites), auto-reconnect.

`ClientWsManager` lives in a new file `services/client_ws_manager.py`. The module's `__init__.py` instantiates it alongside the existing `MistWsManager`.

### 2. Ingestion dispatch — `IngestionService`

Add channel-based dispatch in the consume loop:

```
channel contains "stats/clients"  → client_extractor.extract(msg)
channel contains "stats/devices"  → existing device extractor dispatch
```

### 3. Client extractor — `extractors/client_extractor.py`

Pure function `extract(msg) → list[dict]` returning InfluxDB data points.

**Measurement:** `client_stats`

**Tags:** `org_id`, `site_id`, `client_mac`, `ap_mac`, `ssid`, `band`, `auth_type`

`auth_type` is derived from `key_mgmt`: `"eap"` when `key_mgmt` contains `"EAP"`, otherwise `"psk"`. Low cardinality, useful for filtering. Both PSK and 802.1X wireless clients arrive on the same `/stats/clients` channel — the `username` field is populated for 802.1X (and per-user PSK) clients.

**Fields (numeric):**
| Field | Type | CoV threshold | Notes |
|-------|------|--------------|-------|
| `rssi` | number | 3.0 dBm | Signal strength |
| `snr` | number | 3.0 | Signal over noise |
| `channel` | integer | `"exact"` | Current channel |
| `tx_rate` | number | `"exact"` | Mbps |
| `rx_rate` | number | `"exact"` | Mbps |
| `tx_bps` | integer | `"always"` | Current TX bitrate |
| `rx_bps` | integer | `"always"` | Current RX bitrate |
| `tx_pkts` | integer | `"always"` | Monotonic counter |
| `rx_pkts` | integer | `"always"` | Monotonic counter |
| `tx_bytes` | integer | `"always"` | Monotonic counter |
| `rx_bytes` | integer | `"always"` | Monotonic counter |
| `tx_retries` | integer | `"always"` | Monotonic counter |
| `rx_retries` | integer | `"always"` | Monotonic counter |
| `idle_time` | number | 5.0 | Seconds since last RX |
| `uptime` | number | `"always"` | Seconds connected |

**Fields (boolean stored as int 0/1):**
| Field | CoV | Notes |
|-------|-----|-------|
| `dual_band` | `"exact"` | Capable of dual-band |
| `is_guest` | `"exact"` | Guest client flag |
| `power_saving` | `"exact"` | Currently in power-save mode |

**Fields (string, CoV `"exact"`):**
| Field | Notes |
|-------|-------|
| `hostname` | From DHCP sniffing |
| `ip` | Client IP |
| `manufacture` | From fingerprinting or OUI |
| `family` | e.g. iPhone, Mac, Windows Mobile |
| `model` | Device model if identifiable |
| `os` | OS from fingerprinting |
| `os_version` | OS version (WS-only field, not in REST OAS) |
| `group` | Client group |
| `vlan_id` | VLAN id (string, may be empty) |
| `proto` | 802.11 protocol (n/g/ac/ax) |
| `key_mgmt` | Full key mgmt string e.g. WPA2-PSK/CCMP |
| `username` | 802.1X identity or per-user PSK username |
| `airespace_ifname` | VLAN interface name (EAP clients) |
| `type` | Client classification: regular/vip/resource/blocked |

**Fields intentionally excluded:**
- Location fields (`map_id`, `x`, `x_m`, `y`, `y_m`, `accuracy`, `rssizones`, `zones`) — different use case, not telemetry metrics
- Complex objects (`airwatch`, `guest`, `vbeacons`, `wxrule_usage`) — not simple time-series values
- Static device metadata (`firmware`, `hardware`, `sdk_version`, `app_version`) — not time-varying
- Association metadata (`psk_id`, `wlan_id`, `ap_id`, `bssid`, `assoc_time`) — not useful as time-series fields

**Wired clients (AP ethernet port clients — `stats_wired_client`):** Out of scope for this iteration. The OAS schema is minimal (`auth_state`, `eth_port`, `device_id`, `tx_bytes`, `rx_bytes`, `tx_pkts`, `rx_pkts`, `uptime`, `vlan_id`) and these clients come on a different channel. Design separately when needed.

CoV key: `client_mac` (each client tracked independently). `client_stats` is CoV-filtered (unlike `device_summary` which is always written). Max staleness: 300s (matches Mist `_ttl`).

### 4. Latest client cache — `services/latest_client_cache.py`

In-memory dict keyed by `(site_id, client_mac)`. Mirrors `LatestValueCache` pattern.

```python
update(site_id: str, client_mac: str, stats: dict) -> None
get_all_for_site(site_id: str, max_age: int = 120) -> list[dict]
get_site_summary(site_id: str) -> ClientSiteSummary
prune(max_age: int = 600) -> None   # called every N messages; 600s > _ttl=300
```

`ClientSiteSummary`: `total_clients`, `avg_rssi`, `band_counts` (`{"24": n, "5": n, "6": n}`), `total_tx_bps`, `total_rx_bps`.

### 5. WebSocket broadcast

After each client stat is processed, broadcast to the existing `telemetry:site:{site_id}` channel — no new WS channel. The site component already debounces this at 5s to trigger a refresh.

### 6. REST endpoints (added to `router.py`)

All endpoints require `require_impact_role`.

```
GET /telemetry/scope/clients?site_id={id}
    → list of clients from LatestClientCache for a site
    → response: { clients: ClientStatRecord[], total: int }

GET /telemetry/scope/clients/summary?site_id={id}
    → ClientSiteSummary from cache (used by scope + site views)

GET /telemetry/query/clients/range
    ?client_mac={mac}&site_id={id}&start={s}&end={e}
    → time-range data from InfluxDB for a single client
    → the existing `influxdb_service.query_range(mac, measurement, start, end)` filters on
      a `mac` tag; `client_stats` uses `client_mac` as the tag name instead. Either pass
      `client_mac` as the filter param to a new `query_range_by_tag(tag, value, ...)` helper,
      or add an optional `tag_name` parameter to `query_range`.
```

### 7. Schemas (`schemas.py`)

New Pydantic models:
- `ClientStatRecord` — per-client fields returned by `/scope/clients`
- `ClientSiteSummary` — aggregate summary
- `ClientListResponse` — wraps list + total

### 8. Status endpoint

Extend `GET /telemetry/status` to include `ClientWsManager` stats (connections, sites, messages) alongside the existing device WS manager stats.

---

## Frontend

### 1. New models (`models.ts`)

```typescript
ClientStatRecord      // per-client latest stats
ClientSiteSummary     // { total_clients, avg_rssi, band_counts, total_tx_bps, total_rx_bps }
ClientListResponse    // { clients, total }
```

### 2. Service additions (`telemetry.service.ts`)

```typescript
getSiteClients(siteId: string): Observable<ClientListResponse>
getSiteClientsSummary(siteId: string): Observable<ClientSiteSummary>
getClientRange(clientMac: string, siteId: string, start: string, end: string): Observable<RangeResult>
```

### 3. New route

`/telemetry/site/:id/clients` → `TelemetryClientsComponent` (lazy-loaded, added to `telemetry.routes.ts`)

### 4. `TelemetryClientsComponent`

**Layout:**
- Breadcrumb: Telemetry › [Site Name] › Clients
- Time range picker (1h / 6h / 24h)
- KPI cards: Total Clients, Avg RSSI, Band split (2.4G / 5G / 6G counts), Total TX bps + RX bps
- Charts:
  - Client count over time (aggregate query on `client_stats`, `count` of distinct `client_mac`)
  - Avg RSSI over time (aggregate query on `client_stats`, `mean` of `rssi`)
- Client table (searchable by hostname/MAC/manufacture/AP):
  - Columns: Hostname, MAC, AP, Band, Channel, RSSI, SNR, TX bps, RX bps, TX rate, Manufacture, Last seen
- Real-time: debounced re-fetch on `telemetry:site:{id}` WS events (5s debounce, same as site view pattern)

### 5. Site view updates (`telemetry-site.component`)

Add a "Clients" summary card below the existing device KPI rows:
- Shows: total clients, avg RSSI, band counts (2.4G / 5G / 6G)
- "View Clients →" button linking to `/telemetry/site/:id/clients`
- Data: `GET /telemetry/scope/clients/summary?site_id={id}`

### 6. Scope view updates (`telemetry-scope.component`)

In the AP section, extend the existing KPI cards to include:
- Total clients (currently only shown as a count on the KPI card; enrich with avg RSSI)
- No new chart — the AP charts already cover `num_clients` from `device_summary`; a dedicated clients chart belongs on the clients page
- "Clients →" link per site row in the sites table navigating to `/telemetry/site/:id/clients`

---

## Data flow summary

```
Mist Cloud WS /stats/clients
       │  (one msg per client, ~60s)
       ▼
ClientWsManager (thread → asyncio.Queue)
       │
       ▼ channel="stats/clients"
IngestionService.consume_loop()
       │
       ├─► client_extractor.extract()  →  InfluxDB "client_stats" measurement
       ├─► LatestClientCache.update()
       └─► broadcast telemetry:site:{site_id}
                          │
                          ▼ (5s debounce)
              Frontend re-fetches
              /scope/clients/summary   → site + scope KPI cards
              /scope/clients           → TelemetryClientsComponent table
              /query/clients/range     → TelemetryClientsComponent charts
```

---

## Out of scope (future)

- Wired AP ethernet clients (`stats_wired_client`) — different channel, minimal schema, design separately
- Per-client detail page
- Client roaming history (AP transitions over time)
