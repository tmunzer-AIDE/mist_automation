# WebSocket Telemetry Pipeline — Real-Time Device Stats Ingestion

## Context

The app currently fetches device stats via HTTP polling (Mist REST API) with 30-second cache TTL. This is adequate for point-in-time checks but insufficient for:
- Real-time incident detection during impact analysis (seconds vs minutes)
- Historical trend dashboards (CPU, memory, port utilization, PoE, radio metrics)
- Anomaly detection and proactive alerting
- AI chat context enrichment with current device state
- Real-time workflow triggers based on stat thresholds

Mist Cloud provides a WebSocket API (`wss://api-ws.{region}.mist.com/api-ws/v1/stream`) that streams device stats every 20-30 seconds per device. This spec describes a telemetry pipeline that consumes this stream, extracts key metrics, and stores them in InfluxDB for historical queries while maintaining an in-memory cache for real-time access.

## Design Decisions

| Question | Decision |
|----------|----------|
| TSDB choice | InfluxDB 2.7 — purpose-built for time-series, native Grafana support, built-in downsampling/retention, scales to 10K+ devices |
| Why not MongoDB TS | At 10K+ devices, dashboard queries over weeks of data favor purpose-built TSDBs. InfluxDB's retention policies and continuous queries are first-class features. |
| Ingestion strategy | Hybrid CoV — always-write device summaries every cycle, Change-of-Value filter for per-port/radio metrics |
| CoV rationale | Established industrial pattern (OPC UA deadband). Reduces write volume 60-80% while maintaining data fidelity. Max staleness timeout (5 min) guarantees freshness. |
| WebSocket library | `mistapi.websockets.sites.DeviceStatsEvents` — built-in auth, reconnect, channel management |
| Thread bridging | mistapi uses `websocket-client` (thread-based). Bridge to asyncio via `on_message` callback + `loop.call_soon_threadsafe()` into `asyncio.Queue` |
| Connection scaling | Max 1000 channels per WebSocket connection. Auto-scale: `ceil(num_sites / 1000)` connections |
| Connection lifecycle | Always-on — connects at app startup, ingests continuously |
| Backpressure | Bounded in-memory queue (10K items), latest-value-wins eviction per device MAC |
| InfluxDB unavailable | Buffer in memory, drop on overflow. Telemetry is ephemeral — Mist Cloud retains everything. |
| Deployment | InfluxDB as Docker container / K8s StatefulSet alongside existing MongoDB and Redis |

## Architecture

```
Mist Cloud WebSocket(s)
        |
        | wss://api-ws.{region}.mist.com/api-ws/v1/stream
        | (auto-scaled: 1 connection per 1000 sites)
        |
  MistWsManager  (lifecycle, reconnect, health monitoring)
        |
        | raw JSON payloads via asyncio.Queue (bounded 10K, latest-value-wins)
        |
  IngestionService  (dispatches to device-type extractors, applies CoV)
        |
        +---> LatestValueCache (in-memory dict, keyed by device MAC)
        |         |
        |         +---> Impact analysis: real-time device stats (replaces HTTP polling)
        |         +---> AI chat: current device state queries
        |         +---> Frontend: live dashboard via ws_manager broadcast
        |
        +---> InfluxDB write buffer (asyncio.Queue, bounded)
                  |
              InfluxDBService  (batch flush: 500 points or 10s interval)
                  |
              InfluxDB 2.7
                  |
                  +---> Dashboard API endpoints (range, aggregate queries)
                  +---> Impact analysis: historical comparison during validation
                  +---> Future: anomaly detection, workflow triggers
```

### Key Properties

- **Decoupled stages**: WebSocket ingestion, metric extraction, and InfluxDB writes are connected via async queues. If InfluxDB is slow, ingestion continues and the cache stays current.
- **LatestValueCache** always holds the most recent full stats per device — zero-latency reads for impact analysis and AI chat.
- **CoV filtering** happens between extraction and the InfluxDB write buffer, reducing write volume without affecting the cache.

## Mist WebSocket Manager

### Connection Lifecycle

1. On startup: reads configured orgs/sites from SystemConfig
2. Groups sites into chunks of 1000
3. Creates one `DeviceStatsEvents` instance per chunk using `mistapi.websockets.sites.DeviceStatsEvents(session, site_ids)`
4. Each connection runs in a background thread (mistapi uses `websocket-client`)
5. Messages are bridged to asyncio via `on_message` callback + `loop.call_soon_threadsafe(queue.put_nowait)`

### Authentication

Uses the existing Mist API token from `MistService` config. The `mistapi` library handles auth automatically via `APISession`.

### Region Mapping

| Region | WebSocket URL |
|--------|--------------|
| `global_01` | `wss://api-ws.mist.com/api-ws/v1/stream` |
| `emea_01` | `wss://api-ws.eu.mist.com/api-ws/v1/stream` |
| `apac_01` | `wss://api-ws.ac5.mist.com/api-ws/v1/stream` |

### Auto-Scaling

```
sites = get_all_configured_sites()
connections_needed = ceil(len(sites) / 1000)

for i in range(connections_needed):
    chunk = sites[i*1000 : (i+1)*1000]
    ws = DeviceStatsEvents(api_session, chunk)
    ws.on_message(lambda msg: bridge_to_asyncio(msg))
    ws.connect(run_in_background=True)
```

### Dynamic Subscription

When admin adds/removes sites at runtime, the manager:
- Determines if the site fits in an existing connection (< 1000 channels) or needs a new one
- For removal: disconnects and recreates the affected connection without the removed site
- No full restart required

### Connection Parameters

```python
DeviceStatsEvents(
    mist_session=api_session,
    site_ids=site_chunk,
    ping_interval=30,
    ping_timeout=10,
    auto_reconnect=True,
    max_reconnect_attempts=5,     # then manager takes over with longer backoff
    reconnect_backoff=2.0,
    queue_maxsize=5000,           # per-connection buffer
)
```

### Reconnection

`mistapi` provides built-in auto-reconnect with exponential backoff. If all 5 attempts fail, the manager re-creates the connection after a longer cooldown (60s). The manager monitors `ready()` state and logs reconnection events.

### Health Monitoring

Each connection tracks `last_message_at`. If no message received in 90 seconds (3x the 30s device interval), force reconnect. Health status exposed via `/telemetry/status` endpoint.

## Metric Extraction

### Message Types

The WebSocket sends different message structures per device type:
- **APs**: 2 messages per cycle — "basic" (minimal: mac, uptime, ip) and "full stats" (radio, ports, clients, cpu, mem). Only process full stats (detected by presence of `model` + `radio_stat` fields).
- **Switches**: 1 large message per cycle with `if_stat` (all ports), `module_stat` (VC members), `clients`.
- **Gateways**: 1 message per cycle. Payload structure varies by model:
  - **SRX standalone**: `spu_stat`, `dhcpd_stat`, `ge-*` interfaces
  - **SRX cluster**: `cluster_config`, `module2_stat`/`cpu2_stat`/`memory2_stat` for peer, `reth*` interfaces
  - **SSR (standalone/cluster)**: `network_resources` (FIB/FLOW/ACCESS_POLICY), `ha_state`/`ha_peer_mac` for HA. Each node sends its own message.

### Device-Type Detection

```python
device_type = payload.get("type")  # "ap", "switch", "gateway"

# For gateways, further classify:
if device_type == "gateway":
    if payload.get("model") == "SSR":
        extractor = ssr_extractor
    elif payload.get("cluster_config"):
        extractor = srx_cluster_extractor
    else:
        extractor = srx_standalone_extractor
```

### InfluxDB Measurements

#### `device_summary` — Always written every cycle

| Tag | Description |
|-----|-------------|
| `org_id` | Organization ID |
| `site_id` | Site ID |
| `mac` | Device MAC |
| `device_type` | `ap`, `switch`, `gateway` |
| `name` | Device hostname |

| Field | AP | Switch | Gateway | Source |
|-------|:--:|:------:|:-------:|-------|
| `cpu_util` | x | x | x | `cpu_util` / `100 - cpu_stat.idle` |
| `mem_usage` | x | x | x | `mem_used_kb/mem_total_kb * 100` / `memory_stat.usage` |
| `num_clients` | x | x | | `num_clients` (int for AP, `num_clients.total.num_clients` for switch) |
| `uptime` | x | x | x | `uptime` |
| `poe_draw_total` | | x | | sum of `module_stat[*].poe.power_draw` |
| `poe_max_total` | | x | | sum of `module_stat[*].poe.max_power` |

#### `radio_stats` — CoV filtered (AP only)

| Tag | Description |
|-----|-------------|
| `org_id`, `site_id`, `mac` | Device identity |
| `band` | `band_24`, `band_5`, `band_6` |

| Field | CoV Threshold |
|-------|--------------|
| `channel` | exact match |
| `power` | exact match |
| `util_all` | 5% absolute |
| `noise_floor` | 3 dBm absolute |
| `num_clients` | exact match |
| `bandwidth` | exact match |

#### `port_stats` — CoV filtered (switch, UP ports only)

| Tag | Description |
|-----|-------------|
| `org_id`, `site_id`, `mac` | Device identity |
| `port_id` | Port identifier (e.g., `ge-0/0/23`) |

| Field | CoV Threshold |
|-------|--------------|
| `up` | exact match (state change) |
| `tx_pkts` | always write (counter) |
| `rx_pkts` | always write (counter) |
| `speed` | exact match |

#### `module_stats` — CoV filtered (switch VC members)

| Tag | Description |
|-----|-------------|
| `org_id`, `site_id`, `mac` | Device identity |
| `fpc_idx` | VC member index |

| Field | CoV Threshold |
|-------|--------------|
| `temp_max` | 2 degrees |
| `poe_draw` | 5W |
| `vc_role` | exact match |
| `vc_links_count` | exact match |
| `mem_usage` | 5% absolute |

#### `gateway_wan` — CoV filtered (all gateway types)

| Tag | Description |
|-----|-------------|
| `org_id`, `site_id`, `mac` | Device identity |
| `port_id` | Interface (e.g., `ge-0/0/2`, `reth0`) |
| `wan_name` | WAN circuit name |
| `port_usage` | `wan`, `lan`, `control` |

| Field | CoV Threshold |
|-------|--------------|
| `up` | exact match |
| `tx_bytes` | always write (counter) |
| `rx_bytes` | always write (counter) |
| `tx_pkts` | always write (counter) |
| `rx_pkts` | always write (counter) |
| `redundancy_state` | exact match (SSR only) |

#### `gateway_health` — Always written (per node)

| Tag | Description |
|-----|-------------|
| `org_id`, `site_id`, `mac` | Node MAC |
| `model` | `SRX300`, `SRX340`, `SSR`, etc. |
| `node_name` | `node0`, `node1` (HA), or empty |
| `router_name` | Cluster name (SSR) |

| Field | Description |
|-------|-------------|
| `cpu_idle` | `cpu_stat.idle` |
| `mem_usage` | `memory_stat.usage` |
| `uptime` | `uptime` |
| `ha_state` | `ha_state` (SSR) or derived from `cluster_config` (SRX) |
| `config_status` | `config_status` |

#### `gateway_spu` — CoV filtered (SRX only, skip if `spu_stat` empty)

| Tag | Description |
|-----|-------------|
| `org_id`, `site_id`, `mac` | Device identity |

| Field | CoV Threshold |
|-------|--------------|
| `spu_cpu` | 5% absolute |
| `spu_sessions` | 10% relative |
| `spu_max_sessions` | exact match |
| `spu_memory` | 5% absolute |

#### `gateway_resources` — CoV filtered (SSR only)

| Tag | Description |
|-----|-------------|
| `org_id`, `site_id`, `mac` | Node MAC |
| `node_name` | `node0`, `node1` |
| `resource_type` | `FIB`, `FLOW`, `ACCESS_POLICY` |

| Field | CoV Threshold |
|-------|--------------|
| `count` | 5% relative |
| `limit` | exact match |
| `utilization_pct` | 3% absolute |

#### `gateway_cluster` — CoV filtered (SRX cluster only, skip if no `cluster_config`)

| Tag | Description |
|-----|-------------|
| `org_id`, `site_id`, `mac` | Device identity |

| Field | CoV Threshold |
|-------|--------------|
| `status` | exact match (Red/Green/Yellow) |
| `operational` | exact match |
| `primary_health` | exact match |
| `secondary_health` | exact match |
| `control_link_up` | exact match |
| `fabric_link_up` | exact match |

#### `gateway_dhcp` — CoV filtered (SRX and SSR)

| Tag | Description |
|-----|-------------|
| `org_id`, `site_id`, `mac` | Device identity |
| `network_name` | DHCP scope name |

| Field | CoV Threshold |
|-------|--------------|
| `num_ips` | exact match |
| `num_leased` | exact match |
| `utilization_pct` | 3% absolute |

### CoV Filtering Implementation

```python
class CoVFilter:
    """Change-of-Value filter with max staleness timeout."""

    def __init__(self, max_staleness_seconds: int = 300):
        # Key: (mac, measurement, tag_hash) → (last_value_dict, last_write_time)
        self._last_written: dict[str, tuple[dict, float]] = {}

    def should_write(self, key: str, fields: dict, thresholds: dict) -> bool:
        """Returns True if any field changed beyond its threshold or max staleness exceeded."""
        prev = self._last_written.get(key)
        if prev is None:
            return True  # First write

        prev_fields, prev_time = prev
        if time.time() - prev_time > self.max_staleness_seconds:
            return True  # Force write on staleness

        for field_name, value in fields.items():
            threshold = thresholds.get(field_name)
            prev_value = prev_fields.get(field_name)
            if prev_value is None or threshold is None:
                return True  # New field or no threshold = always write
            if threshold == "exact":
                if value != prev_value:
                    return True
            elif threshold == "always":
                return True  # Counters
            else:
                if abs(value - prev_value) > threshold:
                    return True
        return False
```

### AP "Basic" Message Filtering

APs send two WebSocket messages per cycle:
1. **Basic** (`_offset_apbasic`): minimal — `mac`, `uptime`, `ip_stat`, `ble_stat`
2. **Full stats** (`_offset_apstats`): complete — `model`, `radio_stat`, `port_stat`, `cpu_util`, `num_clients`

Detection: full stats message has `model` field. Basic does not. Skip basic messages.

## InfluxDB Configuration

### SystemConfig Fields

| Setting | Default | Description |
|---------|---------|-------------|
| `telemetry_enabled` | `false` | Global kill switch |
| `influxdb_url` | `http://localhost:8086` | InfluxDB connection URL |
| `influxdb_token` | (encrypted) | InfluxDB admin token |
| `influxdb_org` | `mist_automation` | InfluxDB organization |
| `influxdb_bucket` | `mist_telemetry` | InfluxDB bucket name |
| `telemetry_retention_days` | `30` | Data retention period |

### Write Batching

- Batch size: 500 data points
- Flush interval: 10 seconds (whichever comes first)
- `write_api.write()` with `write_precision=WritePrecision.S` (second precision sufficient for 30s intervals)
- `influxdb_client.client.write_api` with batching mode enabled

## Module Structure

```
backend/app/modules/telemetry/
+-- __init__.py
+-- router.py                    # REST endpoints: status, query, settings
+-- services/
|   +-- __init__.py
|   +-- mist_ws_manager.py       # Mist WS lifecycle, auto-scaling, reconnect
|   +-- ingestion_service.py     # Payload dispatch, CoV filtering, queue management
|   +-- influxdb_service.py      # InfluxDB client, batched writes, buffer
|   +-- latest_value_cache.py    # In-memory dict of latest stats per device MAC
+-- extractors/
    +-- __init__.py
    +-- ap_extractor.py          # AP payload -> device_summary + radio_stats
    +-- switch_extractor.py      # Switch payload -> device_summary + port_stats + module_stats
    +-- gateway_extractor.py     # Gateway payload -> gateway_* (SRX/SSR/cluster-aware)
```

### Module Registration

```python
# In app/modules/__init__.py
AppModule(
    name="telemetry",
    router_path="app.modules.telemetry.router",
    models=[],  # No Beanie models — config in SystemConfig, data in InfluxDB
)
```

### Startup / Shutdown

```python
# In app/main.py lifespan
# Startup (after DB init):
config = await SystemConfig.get_config()
if config.telemetry_enabled:
    await telemetry_manager.start()

# Shutdown:
await telemetry_manager.stop()
```

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/telemetry/status` | `require_admin` | Connection health: WS count, channels, msg rate, buffer depth |
| GET | `/telemetry/latest/{mac}` | `require_impact_role` | Latest cached stats for a device (from memory, not InfluxDB) |
| GET | `/telemetry/query/range` | `require_impact_role` | Time-range query: `?mac=X&metric=cpu_util&start=-1h` |
| GET | `/telemetry/query/aggregate` | `require_impact_role` | Aggregated: `?site_id=X&metric=cpu_util&agg=mean&window=5m` |
| PUT | `/telemetry/settings` | `require_admin` | Enable/disable, InfluxDB connection, retention |
| POST | `/telemetry/reconnect` | `require_admin` | Force reconnect all WebSocket connections |

## Integration with Impact Analysis

`SiteDataCoordinator` gains an optional telemetry integration:

1. **LatestValueCache read**: When telemetry is enabled and cache has fresh data (< 60s), read device stats from cache instead of HTTP API call
2. **InfluxDB historical query**: During validation, query InfluxDB for "was this port up 5 minutes ago?" instead of relying on single point-in-time HTTP snapshot
3. **Faster incident detection**: Port flaps and disconnects visible in cache within seconds, not dependent on webhook delivery latency

Fallback: When telemetry is disabled or cache is stale, `SiteDataCoordinator` continues using HTTP API calls (current behavior).

## Docker / Kubernetes Deployment

### Docker Compose

```yaml
influxdb:
  image: influxdb:2.7
  ports:
    - "8086:8086"
  volumes:
    - influxdb_data:/var/lib/influxdb2
  environment:
    - DOCKER_INFLUXDB_INIT_MODE=setup
    - DOCKER_INFLUXDB_INIT_USERNAME=admin
    - DOCKER_INFLUXDB_INIT_PASSWORD=${INFLUXDB_PASSWORD}
    - DOCKER_INFLUXDB_INIT_ORG=mist_automation
    - DOCKER_INFLUXDB_INIT_BUCKET=mist_telemetry
    - DOCKER_INFLUXDB_INIT_RETENTION=30d
    - DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=${INFLUXDB_TOKEN}
```

### Kubernetes

- InfluxDB: StatefulSet with PersistentVolumeClaim
- Telemetry WebSocket connections are per-pod. Multi-replica strategy:
  - Option A: Each replica handles a disjoint subset of sites (configured via env var or ConfigMap)
  - Option B: Leader election — one pod owns all WebSocket connections, others are standby
  - Option C: Shared nothing — all replicas connect to all sites, InfluxDB deduplicates by timestamp+tags (wastes bandwidth but simplest)
- LatestValueCache is pod-local; cross-pod queries go through InfluxDB

## Scaling Reference

| Scale | Devices | Sites | WS Connections | Messages/s | InfluxDB writes/s (with CoV) | Cache Memory |
|-------|---------|-------|---------------|-----------|-------------------------------|-------------|
| Small | 100 | 5 | 1 | ~7 | ~50 | ~5MB |
| Medium | 500 | 25 | 1 | ~33 | ~250 | ~25MB |
| Large | 2,000 | 100 | 1 | ~133 | ~1,000 | ~100MB |
| XL | 10,000 | 500 | 1 | ~667 | ~5,000 | ~500MB |
| XXL | 10,000 | 1,500 | 2 | ~667 | ~5,000 | ~500MB |

### Bottleneck Analysis

- **WebSocket**: Not a concern until 1,000+ sites (auto-scales connections at that point)
- **InfluxDB writes**: 5K points/s is comfortable for a single instance (handles 100K+)
- **Memory**: 500MB for 10K device cache is acceptable for any production deployment
- **CPU**: JSON parsing at 667 msg/s is trivial for Python async
- **Network**: ~1.3MB/s raw at 2K devices, ~6.5MB/s at 10K — not a bandwidth concern

### InfluxDB Storage Estimates (30-day retention)

| Scale | device_summary | CoV measurements | Total |
|-------|---------------|-----------------|-------|
| Small (100 devices) | ~1GB | ~0.5GB | ~1.5GB |
| Medium (500) | ~5GB | ~2.5GB | ~7.5GB |
| Large (2K) | ~20GB | ~10GB | ~30GB |
| XL (10K) | ~100GB | ~50GB | ~150GB |

## Future Enhancements (Out of Scope)

- **Downsampled bucket**: `mist_telemetry_downsampled` with 1-year retention, hourly aggregates via InfluxDB tasks
- **Real-time workflow triggers**: Fire workflows when stat thresholds crossed (e.g., PoE > 90% for 5 min)
- **Anomaly detection**: Trend analysis on stored metrics for gradual degradation (memory creep, throughput decay)
- **Live network map**: Real-time device health + port utilization overlay on topology view
- **Grafana integration**: Direct InfluxDB datasource for custom dashboards
- **Client stats channel**: Subscribe to `/sites/{site_id}/stats/clients` for wireless client telemetry

## Verification

1. Enable telemetry in admin settings, verify WebSocket connects and messages flow
2. Check `/telemetry/status` shows active connections, message rate, write rate
3. Query `/telemetry/latest/{mac}` and verify fresh device stats
4. Query `/telemetry/query/range` for historical data in InfluxDB
5. Trigger impact analysis session and verify it reads from cache (no HTTP API calls in logs)
6. Disable telemetry, verify graceful disconnect and fallback to HTTP polling
7. Scale test: subscribe to 1000+ sites, verify auto-scaling to 2 WebSocket connections
8. Kill InfluxDB, verify buffer fills and cache continues updating (no crash)
