# Telemetry Analytics Brainstorming: Network Issue Detection & Prediction

## Context

The app is ingesting Mist WebSocket device stats (AP, switch, gateway) every ~30 seconds into InfluxDB, with an in-memory `LatestValueCache` for real-time access. The question: what analytics can we build on top of this data to detect, analyze, and predict network issues?

The app already has **impact analysis** (reactive, config-change-triggered) and **SLE monitoring** (Mist's own metrics). This is about what the *raw device telemetry* unlocks beyond those.

---

## Tier 1: Real-Time Detection (Highest Value, Lowest Complexity)

These operate on the live stream as it arrives -- no historical data needed beyond a short window.

### 1.1 Threshold-Based Alerts with Hysteresis

**What**: Static + sustained thresholds on key health metrics. Alert only after N consecutive polls exceed threshold (prevents noise). Use hysteresis -- different trigger vs clear thresholds.

**Metrics & thresholds** (industry standard):

| Metric | Warn | Critical | Sustained | Clear |
|--------|------|----------|-----------|-------|
| CPU utilization | 80% | 90% | 3 polls (90s) | <70% |
| Memory utilization | 85% | 95% | 3 polls (90s) | <75% |
| Channel utilization (AP) | 60% | 80% | 5 polls (2.5min) | <50% |
| PoE budget usage | 80% | 90% | immediate | <70% |
| SPU sessions (SRX) | 75% | 90% | 3 polls | <65% |
| Gateway resources (SSR) | 75% | 90% | 3 polls | <65% |
| DHCP pool utilization | 80% | 95% | 3 polls | <70% |

**Why valuable**: Catches things before they become outages. A switch at 93% memory for 90 seconds is about to crash. A DHCP pool at 96% means the next device gets no IP.

**Implementation**: Per-device state machine in Python (normal/warn/critical), runs inline in the ingestion service after each CoV-filtered update. Alerts stored in MongoDB, broadcast via WebSocket.

### 1.2 Link Flap Detection

**What**: Track interface state transitions (up/down) per port per device. If >N state changes within a sliding window, flag as flapping.

**Parameters**: 3+ state changes in 10 minutes = flapping (Nagios standard).

**Applies to**: Switch ports, gateway WAN/LAN ports, VC links, AP eth0.

**Why valuable**: A flapping link causes intermittent connectivity that's maddening to troubleshoot. Catching it automatically saves hours. Also indicates cable/SFP hardware failure.

**Implementation**: Ring buffer of `(timestamp, state)` tuples per port. Count transitions in window. The CoV filter already tracks port `up` state changes with "exact" threshold, so we know every transition.

### 1.3 Deadman / Device Disappearance

**What**: If a device stops sending telemetry (no data for >90s = 3 missed polls), flag as unreachable.

**Why valuable**: Faster than waiting for Mist's device-updowns webhook (which can be delayed). The `LatestValueCache.get_fresh(mac, max_age_seconds=60)` is already the foundation.

**Implementation**: Periodic sweep of the cache (every 30s), flag stale entries. Compare against known inventory to distinguish "device removed" from "device crashed."

### 1.4 Sudden Change Detection (Rate-of-Change)

**What**: Compute delta between consecutive polls. Flag abnormal jumps.

| Signal | Trigger |
|--------|---------|
| Throughput drop | >50% drop in single poll |
| Error rate spike | tx_errors or rx_errors delta >10/min |
| Client count drop | >30% drop on single AP |
| Noise floor spike | >10 dBm jump |
| PoE draw spike/drop | >5W change on single module |

**Why valuable**: Catches acute events within 30 seconds -- faster than any polling-based monitoring.

---

## Tier 2: Baseline-Aware Detection (High Value, Moderate Complexity)

These require 7-14 days of historical data to build per-device baselines.

### 2.1 Per-Device Time-of-Day Baselines

**What**: For each device + metric, compute mean and stddev per hour-of-week (168 buckets). Compare incoming values against the baseline for *this device, right now*.

**Example**: AP-lobby normally serves 45 clients at 10am Tuesday (stddev 8). If it suddenly reports 12 clients, that's 4 standard deviations below normal -- something is wrong, even though 12 clients isn't inherently alarming.

**Key metrics for baselining**:
- Client count per AP (strong daily/weekly pattern)
- Channel utilization per AP (follows occupancy)
- CPU/memory per device (follows traffic patterns)
- Port utilization on uplinks (follows business hours)
- Throughput on WAN links (follows usage patterns)

**Why valuable**: This is the core of what Mist AI / Aruba Central / Cisco DNA Center do. It eliminates false positives (high CPU at peak hour is normal) and catches true anomalies (high CPU at 3am is not).

**Implementation**:
- Background job (nightly) queries InfluxDB for last 14 days, computes baselines, stores in MongoDB as `DeviceBaseline` documents
- On each telemetry update, look up baseline for current device + hour-of-week
- Flag if value deviates >2 stddev (warning) or >3 stddev (critical)
- Baselines recompute weekly (sliding 14-day window), adapting to legitimate changes

### 2.2 Site-Wide Correlation

**What**: When multiple devices at the same site show anomalies simultaneously, it's likely a site-level event (power issue, upstream failure, interference source) rather than individual device problems.

**Patterns**:
- 3+ APs at same site: high noise floor simultaneously = external interference source
- All switches at site: high CPU simultaneously = broadcast storm or loop
- Multiple APs: client count drops simultaneously = RADIUS/DHCP issue, not RF
- Gateway WAN down + all devices degraded = ISP outage

**Why valuable**: Moves from "device X has a problem" to "site Y has a problem caused by Z." Root cause identification vs symptom listing.

**Implementation**: After individual anomaly detection, a correlation engine groups anomalies by site + time window (5 min). Pattern matching against known multi-device signatures.

### 2.3 VC Health Monitoring (Switch-Specific)

**What**: Track Virtual Chassis integrity using module_stats and vc_links data.

**Detect**:
- VC member disappearing (module_stat entry vanishes)
- VC role changes (backup becomes master = failover happened)
- VC link count dropping (remember: `vc_links` only shows UP links, so fewer entries = links went down)
- Temperature anomalies on individual VC members
- Memory divergence between VC members (one leaking, others stable)

**Why valuable**: VC failures are one of the most impactful switch events. Catching a degrading VC before the second member fails prevents a full stack outage.

### 2.4 Gateway HA Monitoring

**What**: Specialized monitoring for SRX cluster and SSR HA pairs.

**Detect**:
- Cluster status changes (Green/Yellow/Red)
- `operational` becoming false
- Control/fabric link failures
- SPU divergence between primary/secondary
- ha_state transitions (SSR)
- Node health asymmetry (one node degrading while peer is fine)

**Why valuable**: Gateway HA is the most critical infrastructure. A degraded cluster that hasn't failed over is a ticking bomb -- one more failure takes down the site.

---

## Tier 3: Predictive Analytics (Medium Value, Higher Complexity)

These require weeks of data and statistical modeling.

### 3.1 Time-to-Threshold Forecasting

**What**: For trending metrics, fit a linear regression to recent data. Extrapolate when the metric will cross a critical threshold.

**Best candidates**:
- Memory utilization (memory leaks show linear growth)
- DHCP pool utilization (as devices are added over time)
- PoE budget consumption (as PoE devices are deployed)
- Disk/storage on switches (log accumulation)
- SPU session count growth (as traffic patterns change)

**Output**: "Switch-core-01 memory will reach 95% in approximately 12 days at current growth rate."

**Implementation**:
- Nightly job queries InfluxDB for last 7-30 days of each metric per device
- Fit `y = mx + b` using numpy/scipy
- If slope > 0 and R-squared > 0.7 (good fit), compute time to threshold
- If within configurable horizon (default 14 days), create prediction alert
- Refresh predictions daily

**Why valuable**: Gives operators days/weeks of lead time instead of reacting when something crashes. Industry reports show 40% reduction in unplanned outages.

### 3.2 Seasonal Forecasting (Capacity Planning)

**What**: Use Holt-Winters or Prophet to forecast metrics that have daily/weekly patterns. Detect when forecasted peak-hour values exceed capacity.

**Best candidates**:
- Peak concurrent clients per AP (am I going to run out of capacity?)
- Peak WAN bandwidth utilization (do I need a bigger pipe?)
- Peak-hour channel utilization (is this AP location becoming congested?)

**Output**: "AP-conf-room-3: peak client count trending upward. Projected to exceed 30 clients during business hours within 3 weeks."

**Why valuable**: Capacity planning based on actual data trends, not guesswork.

### 3.3 Failure Precursor Detection

**What**: Identify metric patterns that historically preceded device issues.

**Correlations to look for**:
- Rising CPU + stable traffic = process issue / memory leak
- Rising error counters + stable throughput = early cable/SFP degradation
- Increasing noise floor trend + decreasing throughput = growing RF interference
- Memory sawtooth pattern (steady rise then sudden drop) = service restarting itself
- PoE oscillation on a port = failing PoE device or cable

**Implementation**: This is where you'd use the existing LLM integration -- feed the AI agent a device's recent metric trends and ask it to identify concerning patterns. The LLM can reason about multi-metric correlations better than hand-coded rules for rare patterns.

---

## Tier 4: Advanced / Future (Lower Priority)

### 4.1 Anomaly-Aware Workflow Triggers

**What**: Fire automation workflows when telemetry anomalies are detected.

**Examples**:
- Channel utilization >80% for 5 min on AP -> trigger workflow to adjust RRM
- PoE budget >90% -> notify facilities team
- WAN link down -> trigger failover verification workflow
- Memory leak detected -> schedule maintenance reboot during off-hours

**Why valuable**: Closes the loop from detection to remediation automatically. This is the "self-driving network" path.

### 4.2 Comparative Device Analysis

**What**: Compare similar devices (same model, same role, same site) to find outliers.

**Example**: 10 APs at a site, 9 report noise floor of -90 dBm, 1 reports -75 dBm. The outlier has a local interference source.

**Implementation**: Group devices by (site, model, role). Compute per-group statistics. Flag devices that are >2 stddev from their peer group.

### 4.3 Network Health Score

**What**: Composite health score per device and per site, aggregated from all monitored metrics.

**Per-device score** (0-100):
- Start at 100
- Deduct for each active threshold alert (-10 warn, -25 critical)
- Deduct for baseline deviations (-5 per anomalous metric)
- Deduct for trending-toward-threshold (-5 per prediction)
- Deduct for flapping ports (-10 per flapping port)

**Per-site score**: Weighted average of device scores, with gateway weighted higher than APs.

**Why valuable**: Single-glance health assessment for dashboards. Enables "sort by worst sites" for NOC operators.

### 4.4 Impact Analysis Integration

**What**: Cross-reference telemetry anomalies with active impact analysis sessions.

**When a config change is being monitored AND a telemetry anomaly fires on the same device/site**:
- Automatically link the anomaly to the impact session
- Add to the session timeline
- Trigger AI analysis with both config diff and anomaly context
- Faster and more accurate impact assessment

**Why valuable**: This is a unique differentiator. No commercial tool combines change-awareness with telemetry anomaly detection this tightly. The existing impact analysis module already has the structure for this.

---

## Recommended Implementation Order

| Phase | Capability | Complexity | Data Needed | Dependencies |
|-------|-----------|------------|-------------|--------------|
| **1** | 1.1 Threshold alerts + 1.3 Deadman + 1.4 Rate-of-change | Low | Live stream only | Telemetry pipeline running |
| **2** | 1.2 Link flap detection + 2.3 VC health + 2.4 Gateway HA | Low-Med | Live stream + short history | Phase 1 |
| **3** | 2.1 Per-device baselines + 2.2 Site correlation | Medium | 7-14 days of data | InfluxDB populated |
| **4** | 3.1 Time-to-threshold forecasting | Medium | 7-30 days of data | Phase 3 baselines |
| **5** | 4.4 Impact analysis integration | Medium | Phase 1-3 running | Impact analysis module |
| **6** | 4.3 Health scores + 4.1 Workflow triggers | Medium | Phase 1-3 running | Phases 1-3 |
| **7** | 3.2 Seasonal forecasting + 3.3 Failure precursors | High | 30+ days of data | Phases 3-4 |
| **8** | 4.2 Comparative device analysis | Medium | Phase 3 baselines | Phase 3 |

---

## Architecture Sketch

```
Telemetry Pipeline (existing)
    |
    v
Analytics Engine (new module: app/modules/telemetry/analytics/)
    |
    +-- detectors/
    |   +-- threshold_detector.py      (Tier 1.1)
    |   +-- rate_detector.py           (Tier 1.4)
    |   +-- flap_detector.py           (Tier 1.2)
    |   +-- deadman_detector.py        (Tier 1.3)
    |   +-- baseline_detector.py       (Tier 2.1)
    |   +-- correlation_detector.py    (Tier 2.2)
    |
    +-- predictors/
    |   +-- trend_forecaster.py        (Tier 3.1)
    |   +-- seasonal_forecaster.py     (Tier 3.2)
    |
    +-- models/
    |   +-- alert.py                   (TelemetryAlert Beanie Document)
    |   +-- baseline.py                (DeviceBaseline Beanie Document)
    |   +-- health_score.py            (DeviceHealthScore)
    |
    +-- services/
        +-- alert_service.py           (dedup, escalation, delivery)
        +-- baseline_service.py        (compute, store, query)
        +-- health_score_service.py    (aggregation)

WebSocket channels:
    telemetry:alerts          (new alert notifications)
    telemetry:health          (health score updates)
    telemetry:{site_id}       (site-level dashboard updates)
```

All analytics run in the application layer (Python), not in InfluxDB. InfluxDB is used purely for storage and time-range queries. This avoids version lock-in (Flux is deprecated in InfluxDB 3) and gives full access to app context (impact analysis sessions, device inventory, config history).

---

## Constraint: 30-Day InfluxDB Retention

All raw telemetry data is retained for 30 days. This affects each tier differently:

| Tier | Data Needed | 30-Day Impact | Mitigation |
|------|-------------|---------------|------------|
| Tier 1 | Live stream only | No impact | N/A |
| Tier 2 | 7-14 days | Fully supported | N/A |
| Tier 3 forecasting | 7-30 days | Supported | N/A |
| Tier 3 seasonal | 2-4 weeks | Supported (tight) | N/A |
| Long-term trending | Months | Not supported in raw form | **Downsampled bucket** |

**Key mitigation: Persist computed artifacts in MongoDB, not raw data.**

Baselines, health scores, prediction results, and alert history live in MongoDB (no retention limit). The 30-day window is sufficient to *compute* all analytics. Once computed, the derived data persists indefinitely:

- `DeviceBaseline` (MongoDB): hourly mean/stddev per metric, recomputed weekly from 14-day window
- `TelemetryAlert` (MongoDB): alert history with full context, kept per retention policy
- `HealthScoreHistory` (MongoDB): daily snapshots of per-device/per-site scores
- `PredictionResult` (MongoDB): forecasting results with confidence intervals

Optional future enhancement: a **downsampled InfluxDB bucket** (`mist_telemetry_downsampled`) with 1-year retention, hourly aggregates computed by InfluxDB tasks. This would support multi-month trending without the raw data cost. But this is not needed for any of the Tier 1-3 capabilities.

---

## Client Stats: Do We Need Them?

**Short answer: not for Tiers 1-3. Useful for Tier 4+ but with significant storage cost.**

### What client stats add

The Mist client stats WebSocket (`/sites/{site_id}/stats/clients`) sends per-client data every ~30s: mac, hostname, ssid, band, channel, rssi, snr, tx/rx rates, idle time, uptime, ip, vlan, ap_mac.

| Capability | Device Stats Alone | With Client Stats |
|------------|-------------------|-------------------|
| AP overload detection | num_clients count | Per-client RSSI/SNR distribution |
| Coverage holes | Noise floor + channel util | Actual client RSSI in the area |
| Roaming issues | Client count fluctuations | Per-client AP transitions, handoff time |
| Sticky clients | Not detectable | Client on distant AP with low RSSI |
| SSID-specific issues | Not detectable | Per-SSID client health |
| Auth/DHCP failures | Not directly | Clients stuck in connecting state |

### Storage cost

Client volume is 10-100x device volume. At a medium site (500 devices, ~2000 clients):
- Device stats: ~33 msg/s, ~250 writes/s (with CoV) -> ~7.5 GB/30d
- Client stats: ~130 msg/s, ~1000+ writes/s -> ~30+ GB/30d (even with aggressive CoV)

### Recommendation

**Phase 1-3: Device stats only.** The Tier 1-3 analytics work entirely on device telemetry. Mist's own SLEs already cover client-level metrics (time-to-connect, roaming, throughput, coverage) and we already consume those in impact analysis.

**Phase 4+: Consider aggregated client stats** -- not per-client raw data, but per-AP aggregates computed on ingestion:
- RSSI distribution (mean, P10, P90) per AP per band
- Client count per SSID per AP
- Roaming event count (client appears on new AP)
- These give 90% of the analytical value at 10% of the storage cost

---

## Full Roadmap

### Phase 1: Detection Foundation (can start now)

Build the analytics engine core and the simplest, highest-value detectors that work on the live stream.

**Components:**
- `TelemetryAlert` model in MongoDB (alert storage, dedup, lifecycle)
- Alert service (create, deduplicate, escalate, resolve, notify)
- WebSocket channel `telemetry:alerts` for real-time alert delivery
- Threshold detector (CPU, memory, channel util, PoE, SPU, DHCP pool)
- Rate-of-change detector (throughput drops, error spikes, client drops, noise jumps)
- Deadman detector (device disappearance via cache staleness sweep)
- Admin UI: alert configuration (global thresholds), alert list/detail views

**Depends on:** Telemetry pipeline running (ingestion + InfluxDB writes)

### Phase 2: Stateful Detection (can start with Phase 1)

Detectors that need short-term state tracking but no historical queries.

**Components:**
- Link flap detector (ring buffer of state transitions per port)
- VC health detector (track VC membership, role changes, link counts)
- Gateway HA detector (cluster status, node health asymmetry)
- Alert correlation engine (group concurrent anomalies by site + time window)

**Depends on:** Phase 1 alert infrastructure

### Phase 3: Baseline Intelligence (needs 14+ days of data)

Per-device behavioral baselines that make alerts context-aware.

**Components:**
- Baseline computation job (nightly, queries InfluxDB 14-day window)
- `DeviceBaseline` MongoDB model (168 hourly buckets per device per metric)
- Baseline detector (compare incoming values to current-hour baseline)
- Site-wide correlation (multi-device anomaly pattern matching)
- Alert enrichment: "this is X stddev from normal for this device at this time"

**Depends on:** 14 days of InfluxDB data accumulated

### Phase 4: Predictive Analytics (needs 14-30 days of data)

Forward-looking analysis and forecasting.

**Components:**
- Time-to-threshold forecaster (linear regression, nightly job)
- `PredictionResult` MongoDB model
- Prediction alerts ("memory will reach 95% in 12 days")
- Health score computation (composite 0-100 per device and per site)
- Health score dashboard (sortable device/site list, trend sparklines)

**Depends on:** 14-30 days of data, Phase 3 baselines

### Phase 5: Closed-Loop Integration

Connect analytics to existing app features for automated response.

**Components:**
- Impact analysis cross-reference (link anomalies to active monitoring sessions)
- Workflow triggers from telemetry anomalies
- LLM-powered multi-metric analysis (feed trends to AI agent for complex correlation)
- Comparative device analysis (peer-group outlier detection)
- Optional: aggregated client stats ingestion for coverage/roaming insights

**Depends on:** Phases 1-4 stable, meaningful alert history

---

## Open Questions

1. Should alerts be configurable per-device/per-site, or global thresholds to start?
2. Should we expose a Grafana datasource for InfluxDB, or build dashboards in the Angular frontend?
3. How should telemetry alerts relate to the existing impact analysis workflow -- separate systems with cross-references, or tighter integration?
4. Should LLM analysis be triggered automatically on complex multi-metric anomalies, or only on user request?
