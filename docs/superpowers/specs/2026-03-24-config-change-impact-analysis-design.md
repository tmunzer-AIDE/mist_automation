# Config Change Impact Analysis — Design Specification

## Problem

Configuration changes to Juniper Mist network devices can cause service degradation, connectivity loss, or instability. The current application can detect config changes via webhooks and run point-in-time validation reports, but there is no automated, continuous monitoring of the actual impact a configuration change has on network health. Operators must manually correlate config changes with device events, SLE metrics, and topology changes.

## Solution

A dedicated `impact_analysis` module that automatically monitors network health after configuration changes, combining SLE metrics, device events, network topology analysis, and AI-powered assessment to produce actionable recommendations.

## Architecture

### Module: `app/modules/impact_analysis/`

Not workflow-based — requires long-lived stateful sessions (60+ min), multi-turn polling, session dedup/merge, and cross-concern data aggregation.

### Session Lifecycle

```
PENDING (5s batch) → BASELINE_CAPTURE → MONITORING (N polls) → ANALYZING → COMPLETED | ALERT
                                                                                       ↑ FAILED
                                                                          CANCELLED ←──┘
```

- **PENDING**: 5-second batching window for rapid-fire events
- **BASELINE_CAPTURE**: Fetch pre-change SLE + topology
- **MONITORING**: Poll every 10min for 60min (configurable)
- **ANALYZING**: Run 14 validation checks + AI Agent analysis
- **COMPLETED/ALERT**: Final status based on impact detection

### Trigger: Device-Events Webhooks

| Category | Events | Action |
|----------|--------|--------|
| TRIGGER | AP/SW/GW_CONFIGURED | Create or merge monitoring session |
| INCIDENT | AP/SW/GW_DISCONNECTED, *_CONFIG_FAILED, *_PORT_DOWN, *_NEIGHBOR_DOWN, *_TUNNEL_DOWN | Append to session incidents |
| REVERT | SW/GW_CONFIG_REVERTED | Critical incident → skip to ANALYZING |
| RESOLUTION | AP/SW/GW_CONNECTED, *_PORT_UP, *_TUNNEL_UP | Mark incident resolved |

### Session Dedup

Single active session per `device_mac`. New config events for a device already being monitored merge into the existing session (append event, reset poll counter). Baseline is NOT re-captured on merge.

### API Call Optimization: SiteDataCoordinator

Fetches site-level data once per poll interval, shared across all active sessions at that site. When 3+ sites have active sessions, upgrades non-SLE data to org-level endpoints.

### SLE Strategy: Site → Device Drill-Down

- Site-level SLE at every poll (shared via coordinator, zero extra API calls per device)
- Device-level drill-down only when degradation detected (impacted-aps/switches/gateways/clients/interfaces endpoints)
- Baseline: 1h lookback before config change

### 14 Validation Checks

| # | Check | AP | SW | GW |
|---|-------|----|----|-----|
| 1 | Upstream/downstream connectivity (BFS paths to gateways) | x | x | x |
| 2 | SLE performance degradation | x | x | x |
| 3 | Stability (unresolved disconnect events) | x | x | x |
| 4 | Loop detection (VLAN segment analysis) | x | x | x |
| 5 | Black hole detection (broken paths) | x | x | x |
| 6 | Client impact (wireless/wired count drop) | x | x | x |
| 7 | Alarm correlation (new alarms post-change) | x | x | x |
| 8 | Port flapping (>2 state changes on same port) | x | x | x |
| 9 | DHCP health (scope/relay config changes) | | x | x |
| 10 | VC/MCLAG integrity (member/role changes) | | x | |
| 11 | Routing adjacency (BGP/OSPF neighbor loss) | | x | x |
| 12 | Config drift (applied vs intended) | x | x | x |
| 13 | PoE budget (utilization/alarm changes) | | x | |
| 14 | WAN failover (primary down, backup active) | | | x |

### AI Agent Integration

Required. Analyzes all collected data (SLE delta, incidents, topology diff, validation results) and produces:
- Impact assessment with severity (critical/warning/info)
- Specific culprit identification
- Recommendations (rollback, adjust, monitor longer, accept)
- Rule-based fallback when LLM is unavailable

### Network Topology Integration

Copied from `/Users/tmunzer/4_dev/net_topology/src/mist_topology/` into `app/modules/impact_analysis/topology/`. Provides BFS path finding, link classification (VC/MCLAG/LAG/Fabric), VLAN segment analysis, device health.

### Access Control

New `impact_analysis` role. Existing `reports` role renamed to `post_deployment`.

### Background Execution

`create_background_task()` async coroutines (not Celery). Long-lived with periodic interruptible sleeps. Semaphore-limited API calls per site.

## UI

- **Dedicated page**: Session list with filters + detail view (SLE charts, topology, event timeline, AI assessment)
- **Dashboard widget**: Active/alert session counts with live WS updates

## Data Model

`MonitoringSession` Beanie Document: site/device info, status, config_changes[], incidents[], SLE baseline/snapshots/delta, topology baseline/latest, validation_results, ai_assessment, progress, timing fields. Indexes on [site_id], [device_mac, status], [status], [created_at].

## Implementation Phases

0. Role rename (reports → post_deployment)
1. Data models + session manager
2. Webhook integration
3. SLE service
4. Topology integration
5. Site data coordinator + monitoring pipeline
6. Validation service (14 checks)
7. AI analysis service
8. REST API + WebSocket
9. Frontend session list + detail
10. Dashboard widget
11. Cleanup worker + MCP tools
12. Documentation (README.md + CLAUDE.md)
