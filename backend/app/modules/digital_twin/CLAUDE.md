# Digital Twin Module

Part of mist_automation — see root `CLAUDE.md` for global architecture and conventions.

## Purpose

Pre-deployment simulation engine. Validates proposed Mist configuration changes against a virtual network state before execution. Detects config conflicts, topology issues, routing problems, security policy violations, and L2 loop risks.

## Architecture

### Entry Points

- **LLM Chat**: `digital_twin` MCP tool (`mcp_server/tools/digital_twin.py`) — LLM calls simulate/approve/reject
- **Workflow Executor**: `twin_session_var` ContextVar in `MistService._api_call()` intercepts writes when `workflow.twin_validation=True`. Set in `executor_service.py` before `_execute_graph()`, reset in `finally`.
- **Backup Restore** (Phase 3): Twin intercepts restore writes

### Core Flow

1. **Stage writes**: Parse proposed API calls into `StagedWrite` objects via `endpoint_parser`
2. **Resolve state**: Load backup base + apply writes = virtual state (`state_resolver`)
3. **Build snapshots**: For each affected site, build baseline + predicted `SiteSnapshot` (`site_snapshot`)
4. **Run checks**: 7 check categories across 20 checks (`checks/` package, orchestrated by `snapshot_analyzer`)
5. **Report**: Build `PredictionReport` with severity, details, remediation hints
6. **Remediate**: LLM proposes fixes, re-simulates (bounded by agent max_iterations)
7. **Approve**: User confirms via elicitation, staged writes execute against Mist API

### State Key Conventions

- `endpoint_parser.py` emits canonical singleton object types used by backup snapshots:
	- `/api/v1/sites/{site_id}/setting` and `/api/v1/orgs/{org_id}/setting` -> `settings`
	- `/api/v1/sites/{site_id}` -> `info`
	- `/api/v1/orgs/{org_id}` -> `data`
- `state_resolver.py` still canonicalizes legacy aliases (`setting`, `site_setting`, `site`) for backward compatibility.
- Singleton writes use `object_id=None`; base-state loading handles singleton lookups by `(object_type, site_id/org scope)` without requiring an explicit object ID.
- `site_snapshot.py` loads inherited org networks with an org-level-only filter (`site_id == null`) to avoid leaking other sites' network backups into a single-site snapshot.

### Key Services

| Service | Responsibility |
|---------|---------------|
| `twin_service.py` | Orchestration: simulate(), approve_and_execute(), reject_session() |
| `state_resolver.py` | Build virtual state from backup snapshots + staged writes |
| `site_snapshot.py` | `SiteSnapshot` / `DeviceSnapshot` / `LiveSiteData` dataclasses + `build_site_snapshot()` + `fetch_live_data()` |
| `site_graph.py` | Build networkx graph from `SiteSnapshot` for topology checks |
| `snapshot_analyzer.py` | Orchestrate all 7 check categories, `build_prediction_report()` |
| `checks/` | 7 check modules: connectivity, config_conflicts, port_impact, template_checks, routing, security, stp |
| `template_resolver.py` | Resolve Mist template inheritance chain |
| `config_compiler.py` | Derive effective per-device config from Mist template inheritance chain |
| `twin_ia_bridge.py` | Create IA monitoring sessions after Twin deployment (prediction vs reality) |
| `prediction_comparison.py` | Compare Twin predictions with IA actual findings (accuracy tracking) |
| `endpoint_parser.py` | Extract (object_type, site_id, object_id) from Mist API URLs |

### Data Model

| Model | Purpose |
|-------|---------|
| `TwinSession` | MongoDB document tracking a simulation session (24h TTL) |
| `StagedWrite` | Single intercepted write operation (embedded) |
| `CheckResult` | Result of one validation check (embedded) |
| `PredictionReport` | Aggregated check results with severity (embedded) |
| `RemediationAttempt` | Record of an LLM fix iteration (embedded) |
| `BaseSnapshotRef` | Reference to backup version used as base state (embedded) |

### Check Categories (20 checks across 7 modules)

All checks live in `app/modules/digital_twin/checks/` and operate on `SiteSnapshot` pairs (baseline vs predicted).

| Category | Module | Checks | Description |
|----------|--------|--------|-------------|
| **Connectivity** | `connectivity.py` | CONN-PHYS, CONN-VLAN | Physical reachability (BFS to gateways), VLAN black holes |
| **Config Conflicts** | `config_conflicts.py` | CFG-SUBNET, CFG-VLAN, CFG-SSID, CFG-DHCP-RNG, CFG-DHCP-CFG | IP/subnet overlap, VLAN collision, duplicate SSID, DHCP scope issues |
| **Template** | `template_checks.py` | TMPL-VAR | Unresolved Jinja2 template variables |
| **Port Impact** | `port_impact.py` | PORT-DISC, PORT-CLIENT | Port disconnection risk, client impact from port config changes |
| **Routing** | `routing.py` | ROUTE-GW, ROUTE-OSPF, ROUTE-BGP, ROUTE-WAN | Default gateway gaps, OSPF/BGP adjacency loss, WAN failover |
| **Security** | `security.py` | SEC-GUEST, SEC-POLICY, SEC-NAC | Guest SSID isolation, security policy gaps, NAC rule conflicts |
| **STP** | `stp.py` | STP-ROOT, STP-BPDU, STP-LOOP | STP root bridge shift, BPDU filter risk, loop detection |

### Workflow Integration

When `workflow.twin_validation = True`:
1. `executor_service.execute_workflow()` creates a `TwinSession` before graph execution
2. Sets `twin_session_var` ContextVar so `MistService._api_call()` intercepts POST/PUT/DELETE
3. Intercepted writes are staged in the `TwinSession` via `intercept_write()`
4. After graph execution, the session contains all staged writes for validation
5. ContextVar is reset in `finally` block to prevent leaking to other requests

**Key file**: `app/services/mist_service.py` — `twin_session_var` ContextVar + interception at top of `_api_call()`

### Config Compilation

When a template is modified, the config compiler:
1. Detects template changes in staged writes (`detect_template_changes`)
2. Finds all sites referencing changed templates via backup data (`find_impacted_sites`)
3. For each site, fetches derived site setting and compiles per-device configs
4. Switch: `derived_setting + device.port_config` (shallow merge, vars resolved)
5. Gateway: `gw_template + device_profile + device.port_config` (deep merge for port_config)
6. Updated virtual state feeds into snapshot-based check engine (20 checks across 7 categories)

Uses `fetch_live_data()` for live LLDP/port data in snapshot building.

### Twin-to-IA Bridge (Phase 4)

After successful deployment (`approve_and_execute()`):
1. `twin_ia_bridge.create_ia_sessions_for_deployment()` finds devices at each affected site (telemetry cache -> backup fallback)
2. Creates `MonitoringSession` per device via `session_manager.create_or_merge_session()` with `twin_session_id` and frozen `twin_prediction`
3. Spawns `run_monitoring_pipeline()` background task for each new session
4. Populates `TwinSession.ia_session_ids` with created IA session IDs

After IA completes, `prediction_comparison.compare_prediction_vs_reality()` classifies accuracy:
- `correct`: predicted and actual severity match
- `over_predicted`: Twin flagged issues that didn't materialize (false positive)
- `under_predicted`: IA found issues Twin didn't catch (gap in checks)
- `unknown`: no prediction available

### Dependencies

- `netaddr` — IP/subnet math for overlap detection (CFG-SUBNET, CFG-DHCP-RNG)
- `networkx` — Graph algorithms for connectivity and VLAN reachability (CONN-PHYS, CONN-VLAN)
