# Config Change Impact Analysis

Automated monitoring of network devices after configuration changes. Captures baseline metrics, monitors for degradation, runs validation checks, and provides AI-powered assessment.

## Monitoring Pipeline

```
PENDING (5s batching window for rapid-fire events)
  |
BASELINE_CAPTURE
  - SLE baseline (60-min historical trends per metric)
  - Topology snapshot
  - Template configs snapshot (org/site templates + site setting)
  |
MONITORING (poll loop: default 10min interval x 6 polls = 60min)
  - Per-poll SLE snapshots (getSiteSleSummaryTrend per metric)
  - Incident tracking (disconnects, config failures, reverts)
  - Event merging (concurrent config changes extend the session)
  |
ANALYZING
  - Final topology capture
  - SLE delta computation (baseline vs post-change average)
  - Template drift detection (baseline vs current template configs)
  - 14 validation checks (see below)
  - AI assessment (LLM + MCP tools, or rule-based fallback)
  |
COMPLETED (no impact) or ALERT (impact detected)
```

## Validation Checks

14 checks, applied by device type:

| # | Check | AP | SW | GW | What it checks | Pass | Warn | Fail |
|---|-------|:--:|:--:|:--:|---------------|------|------|------|
| 1 | **Upstream/Downstream Connectivity** | x | x | x | BFS paths from changed device to all gateways, comparing baseline vs latest topology | All gateway paths intact | Device not found in topology | Path to a gateway broken |
| 2 | **SLE Performance** | x | x | x | SLE delta from monitoring phase — checks if any metric degraded beyond configured threshold | All metrics stable | Minor degradation on individual metrics | Overall degradation flagged |
| 3 | **Device Stability** | x | x | x | Counts incidents (disconnects, failures) during monitoring window | 0-2 resolved incidents | >2 resolved incidents (elevated activity) | Any unresolved disconnect or incident |
| 4 | **Loop Detection** | x | x | x | Compares VLAN maps and per-connection VLAN summaries between baseline/latest topology | No new VLAN propagation | New VLAN entries or paths detected | — |
| 5 | **Black Hole Detection** | x | x | x | BFS from *every* device to every gateway (not just changed device) — detects traffic black holes | All device-to-gateway paths intact | — | Broken path(s) detected |
| 6 | **Client Impact** | x | x | x | Compares current client count vs baseline | Stable count | >10% drop | >25% drop |
| 7 | **Alarm Correlation** | x | x | x | Filters site alarms for the monitored device MAC | No alarms | Info/warning alarms present | Critical alarms |
| 8 | **Port Flapping** | x | x | x | Counts up/down state transitions per port/interface from incidents | No flapping | — | >2 state changes on same port |
| 9 | **DHCP Health** | — | x | x | Compares DHCP config (scopes, relay targets, enabled state) on changed device and neighbors between baseline/latest topology | Stable | New DHCP config added | Removed, disabled, relay targets changed, or scope type changed |
| 10 | **VC/MCLAG Integrity** | — | x | — | Compares logical groups (VC, MCLAG) between topologies — member changes, group loss, ICL link status | Groups intact | New members gained | Lost members, lost groups, or ICL links degraded |
| 11 | **Routing Adjacency** | — | x | x | Checks incidents for unresolved BGP/OSPF neighbor down events; compares topology connections for lost links | Adjacencies stable | Routing events or lost connections | Unresolved routing adjacency loss |
| 12 | **Configuration Drift** | x | x | x | **Device-level**: pushed vs applied config, `CONFIG_CHANGED_BY_USER` events, failed config status. **Template-level**: baseline vs end-of-monitoring comparison of assigned org/site templates using `deep_diff()`, with correlation to device CONFIGURED events | Config consistent | Template changes detected, or manual device overrides | Device config application failed |
| 13 | **PoE Budget** | — | x | — | Port stats for PoE draw, faults, denied/overload status, and overall budget utilization | Normal range | >75% utilization | PoE fault, denied, or >90% utilization |
| 14 | **WAN Failover** | — | — | x | Gateway WAN port status from device stats and port stats | All WAN paths up | Some paths down (failover active) | All WAN paths down |

## Configuration Scope

Validation checks use data from different sources, each with a different scope:

| Data source | What it reflects | Used by checks |
|-------------|-----------------|----------------|
| `searchSiteDeviceLastConfigs` | Device-level config events (pushed/applied, change type) | Config Drift (device-level) |
| Topology snapshots (baseline/latest) | Effective rendered config — org/site templates already merged by Mist cloud | Connectivity, Loop Detection, Black Holes, DHCP Health, VC/MCLAG, Routing Adjacency |
| Template snapshots (baseline vs current) | Raw org/site template configs fetched from Mist API | Config Drift (template-level) |
| SLE trend data (`getSiteSleSummaryTrend`) | Service Level Experience metrics per device type | SLE Performance |
| Device stats, port stats, alarms | Live operational state | Alarm Correlation, Port Flapping, PoE Budget, WAN Failover |
| Session incidents | Webhook-driven events during monitoring | Stability, Port Flapping, Routing Adjacency |

### Template drift and event correlation

When multiple configuration changes happen concurrently (e.g., someone modifies both the gateway template and the network template), each change may trigger a separate device `CONFIGURED` event. The template drift check:

1. Captures all assigned template configs at monitoring start (baseline)
2. Re-fetches the same templates at analysis time
3. Runs `deep_diff()` on each template's config to identify changed fields
4. Lists all device CONFIGURED events from the monitoring window alongside each changed template

This allows the user to correlate which template change triggered which CONFIGURED event by comparing timestamps and changed field paths.
