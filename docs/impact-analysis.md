# Config Change Impact Analysis

Automated monitoring and validation of Juniper Mist network devices after configuration changes. Detects issues caused by config changes through SLE metrics, device health checks, topology analysis, and AI-powered root cause analysis.

## Features

- **Automatic detection** -- Webhook-driven: a config change in the Mist portal triggers monitoring within seconds, no user action required
- **Baseline comparison** -- Captures SLE metrics, topology, LLDP neighbors, template configs, and OSPF/BGP peers before the change, then compares after
- **13 validation checks** -- Connectivity, stability, loop detection, black holes, client impact, port flapping, DHCP health, VC integrity, LAG/MCLAG integrity, routing adjacency (OSPF/BGP), config drift, PoE budget, WAN failover
- **Conditional checks** -- Checks are skipped when the feature isn't configured on the device (e.g., no PoE check on non-PoE switches, no VC check on standalone switches)
- **Proactive routing monitoring** -- Fetches actual OSPF/BGP peer state via Mist API at baseline and compares after the change (lost peers, state degradation)
- **SLE monitoring** -- 60-minute post-change SLE trend monitoring with configurable degradation thresholds
- **AI-powered analysis** -- LLM + MCP tools analyze findings in context, produce severity assessment, root cause hypothesis, and actionable recommendations
- **Chat-style UI** -- Split-view session detail with AI narration timeline (left) and structured data panel (right). Users can ask follow-up questions about the analysis
- **Real-time updates** -- WebSocket-driven progress, timeline events, SLE snapshots, and AI results stream to the UI live
- **Event correlation** -- Webhook events during monitoring (disconnects, reverts, OSPF/BGP neighbor loss) are correlated with the config change and fed into the AI analysis
- **Session merging** -- Rapid-fire config changes to the same device merge into a single session (5s batching + CONFIGURED event dedup)

## Architecture

```
                        Mist Cloud
                            |
                     Webhook Gateway
                      /           \
               Automation       Impact Analysis
               Module           Event Handler
                                     |
                              Session Manager
                             /       |        \
                   Monitoring    Event       Cleanup
                   Worker       Handler     Worker
                  /    |    \
          Baseline  Validation  SLE
          Capture    Branch    Monitoring
              |         |         |
        +-----------+   |    +--------+
        | SLE       |   |    | SLE    |
        | Topology  |   |    | Delta  |
        | LLDP      |   |    | Drill  |
        | Templates |   |    +--------+
        | OSPF/BGP  |   |
        +-----------+   |
                   Validation
                   Service (13 checks)
                        |
                   AI Analysis
                   Service
                        |
                   Timeline + WS
                        |
                   Frontend UI
                   (Chat + Data Panel)
```

### Backend Structure

```
app/modules/impact_analysis/
  models.py                    -- MonitoringSession, TimelineEntry, ConfigChangeEvent, DeviceIncident
  schemas.py                   -- REST API request/response schemas
  router.py                    -- All endpoints under /impact-analysis/*
  services/
    session_manager.py         -- Lifecycle: create, transition, cancel, escalate, broadcast
    validation_service.py      -- 13 validation checks with conditional skip logic
    analysis_service.py        -- LLM agent + rule-based fallback analysis
    sle_service.py             -- SLE baseline, snapshot, delta, drill-down
    topology_service.py        -- Topology snapshot, BFS helpers, caching
    template_service.py        -- Template config snapshot + deep_diff drift detection
    site_data_coordinator.py   -- Shared site-level API data across concurrent sessions
    session_logger.py          -- Per-session structured diagnostic logs
  workers/
    monitoring_worker.py       -- Main pipeline coroutine, AI trigger, narration, finalization
    event_handler.py           -- Webhook event routing (6 categories)
    cleanup_worker.py          -- Nightly old session purge (APScheduler, 3:30 UTC)
  topology/
    builder.py                 -- Builds SiteTopology from raw Mist API data
    models.py                  -- Device, Connection, LogicalGroup dataclasses
    render.py                  -- Mermaid diagram rendering
```

### Frontend Structure

```
features/impact-analysis/
  session-list/
    session-list.component.*        -- Paginated table with status/device-type filters
  session-detail/
    session-detail.component.*      -- Orchestrator: WS subscription, chat message mapping, time-based progress
    impact-chat-panel.component.ts  -- Chat UI: AI narration, system events, user Q&A with streaming
    impact-data-panel.component.ts  -- Data panel: progress, config changes, validation, SLE, incidents
  models/
    impact-analysis.model.ts        -- TypeScript interfaces, VALIDATION_CHECK_LABELS
```

## Data Flow

### Session Lifecycle

```
PENDING (5s batch) --> BASELINE_CAPTURE --> AWAITING_CONFIG --> MONITORING --> VALIDATING --> COMPLETED
                                             (pre-config       (parallel     (SLE continues
                                              triggers only)    branches)    while validated)

Terminal states: COMPLETED | FAILED | CANCELLED
```

### Pipeline Phases

| Phase | Duration | What Happens |
|-------|----------|-------------|
| **PENDING** | 5s | Batching window for rapid-fire config events on the same device |
| **BASELINE_CAPTURE** | ~5-10s | Captures SLE (1h lookback), topology, LLDP neighbors, template configs, OSPF/BGP peers |
| **AWAITING_CONFIG** | Up to 10 min | Waits for `CONFIGURED` event (pre-config triggers only). Skipped for `CONFIGURED` triggers. |
| **MONITORING** | Device-specific | Two parallel branches: device validation + SLE monitoring |
| **VALIDATING** | Up to 60 min | Validation done, SLE monitoring continues (6 polls x 10 min) |
| **COMPLETED** | -- | Template drift computed, final impact severity determined, AI summary generated |

### Device-Type Timing

| Device Type | Validation Wait | SLE Duration | SLE Interval |
|-------------|----------------|-------------|-------------|
| Access Point | 2 min | 60 min | 10 min |
| Switch | 5 min | 60 min | 10 min |
| Gateway | 10 min | 60 min | 10 min |

### Baseline Data Captured

| Data | Mist API | Purpose |
|------|---------|---------|
| SLE metrics (1h history) | `getSiteSleSummaryTrend` | Pre-change performance baseline |
| Topology snapshot | Multiple: device stats, port stats, LLDP, networks, site settings | Connectivity and link state baseline |
| LLDP neighbors | `listOrgDevicesStats(fields="*")` | AP-switch correlation for disconnect events |
| Template configs | `getSiteInfo` + per-template fetch | Config drift detection at finalization |
| OSPF peers | `searchOrgOspfStats(mac=device_mac)` | Routing adjacency comparison (switches/gateways) |
| BGP peers | `searchOrgBgpStats(mac=device_mac)` | Routing adjacency comparison (switches/gateways) |

## Monitored Information

### Validation Checks

| # | Check | AP | SW | GW | Skip Condition | What It Detects |
|---|-------|:--:|:--:|:--:|----------------|----------------|
| 1 | Connectivity | x | x | x | -- | BFS path loss from device to gateways (baseline vs current topology) |
| 3 | Stability | x | x | x | -- | Unresolved incidents (disconnects, reverts), elevated event activity |
| 4 | Loop Detection | x | x | x | -- | VLAN propagation anomalies, bidirectional connections with same VLAN |
| 5 | Black Holes | x | x | x | -- | Devices unreachable from gateways that were reachable before |
| 6 | Client Impact | x | x | x | -- | Wireless client count drop (>10% warn, >25% fail) |
| 8 | Port Flapping | x | x | x | -- | >2 link state changes on same port/interface |
| 9 | DHCP Health | | x | x | No `dhcpd_config` on device | DHCP disabled, scope removed, relay targets changed |
| 10 | VC Integrity | | x | | Not in Virtual Chassis | VC member loss, ICL link loss or degradation |
| 11 | Routing (OSPF/BGP) | | x | x | No peers at baseline + no incidents | Lost OSPF/BGP peers, state degradation (full->down, established->idle) |
| 12 | Config Drift | x | x | x | -- | Device config push failures, template-level changes correlated with events |
| 13 | PoE Budget | | x | | No PoE-enabled ports | >75% utilization warn, >90% warn, faults/denied fail |
| 14 | WAN Failover | | | x | -- | WAN path down (partial = warn, all down = fail) |
| 15 | LAG/MCLAG | | x | x | No MCLAG domain + no ae interfaces | MCLAG member/ICL loss, LAG (ae) interface down |

### SLE Metrics

| Device Type | Metrics Monitored |
|-------------|-------------------|
| Access Point | time-to-connect, successful-connect, throughput, roaming, capacity, coverage, ap-health |
| Switch | switch-throughput, switch-health, switch-stc, switch-stc-new |
| Gateway | gateway-health, wan-link-health |

### Webhook Events Handled

| Category | Events | Effect |
|----------|--------|--------|
| **Pre-Config** (triggers session) | `*_CONFIG_CHANGED_BY_USER`, `*_CONFIG_CHANGED_BY_RRM` | Creates/merges monitoring session |
| **Configured** (confirms push) | `AP/SW/GW_CONFIGURED` | Advances session from AWAITING_CONFIG to MONITORING |
| **Config Failed** | `AP/SW/GW_CONFIG_FAILED` | Fails session immediately, critical impact |
| **Incident** | `*_DISCONNECTED`, `SW_VC_PORT_DOWN`, `GW_VPN_PATH_DOWN`, `GW_TUNNEL_DOWN`, `*_OSPF_NEIGHBOR_DOWN`, `*_BGP_NEIGHBOR_DOWN` | Adds incident, escalates severity, triggers AI |
| **Revert** | `SW/GW_CONFIG_REVERTED` | Critical incident, immediate AI analysis |
| **Resolution** | `*_CONNECTED`, `SW_VC_PORT_UP`, `GW_VPN_PATH_UP`, `GW_TUNNEL_UP` | Resolves matching open incident |

### AI Analysis

Triggered automatically when issues are detected (validation failures, SLE degradation, incidents, config reverts). Uses LLM + MCP tools with full session context:

- Config change details (diffs, before/after JSON, commit user/method)
- All validation check results with details
- SLE baseline vs current delta with per-metric breakdown
- LLDP neighbor data and port stats
- Topology diff (devices, connections, VLANs)
- All incidents with timestamps and resolution status
- Previous AI analyses from the session timeline

**Output**: Severity rating, markdown summary with root cause hypothesis, actionable recommendations.

**Fallback**: Rule-based analysis when LLM is unavailable (deterministic severity from reverts, incidents, validation results, SLE delta).

### Session Chat (Q&A)

When LLM is enabled, users can ask follow-up questions about the analysis directly in the session detail page. The AI has:

- Full session context (config changes, validation results, SLE data, incidents, timeline)
- Access to MCP tools (backups, workflows, device stats, system data)
- Optional external MCP server selection (same as global chat)
- Conversation thread with 20-turn sliding window

Messages are stored in the session timeline and visible to all users viewing the session.

## WebSocket Channels

| Channel | Purpose | Key Events |
|---------|---------|------------|
| `impact:{session_id}` | Per-session real-time updates | `session_update`, `timeline_entry`, `incident_added/resolved`, `sle_snapshot`, `validation_completed`, `ai_analysis_completed`, `impact_severity_changed` |
| `impact:summary` | Dashboard widget | `summary_update` (active, impacted, completed_24h, total) |
| `impact:alerts` | Global notifications | `impact_alert` (critical findings, config failures) |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/impact-analysis/sessions` | List sessions (paginated, filterable by status/site/device_type) |
| POST | `/impact-analysis/sessions` | Create manual session |
| GET | `/impact-analysis/sessions/{id}` | Full session detail |
| POST | `/impact-analysis/sessions/{id}/cancel` | Cancel active session |
| POST | `/impact-analysis/sessions/{id}/reanalyze` | Re-run AI analysis on completed session |
| POST | `/impact-analysis/sessions/{id}/chat` | Send message to AI about this session (streaming via WS) |
| GET | `/impact-analysis/sessions/{id}/sle-data` | SLE chart data |
| GET | `/impact-analysis/sessions/{id}/logs` | Diagnostic logs |
| GET | `/impact-analysis/summary` | Dashboard summary counts |
| GET | `/impact-analysis/settings` | Admin: read settings |
| PUT | `/impact-analysis/settings` | Admin: update settings |

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `impact_analysis_enabled` | `true` | Global kill switch |
| `impact_analysis_default_duration_minutes` | 60 | Total monitoring window |
| `impact_analysis_default_interval_minutes` | 10 | SLE poll interval |
| `impact_analysis_sle_threshold_percent` | 10.0 | SLE degradation threshold (%) |
| `impact_analysis_retention_days` | 90 | Auto-cleanup cutoff for old sessions |

## Access Control

- All endpoints require `impact_analysis` or `admin` role (via `require_impact_role`)
- Settings endpoints require `admin` role
- Chat endpoint: rate-limited per user, conversation thread ownership enforced
- LLM output sanitized via `DOMPurify.sanitize()` in frontend
- User input sanitized via `_sanitize_for_prompt()` before injection into LLM prompts
