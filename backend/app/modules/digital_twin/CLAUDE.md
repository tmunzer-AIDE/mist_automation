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

### Site info resolution

`site_snapshot._load_site_info_config()` resolves the per-site config from whichever backup shape carries it — Mist has stored site identity in three forms over time:

- `object_type="info"` at site scope (newer site-level singleton)
- `object_type="site"` at site scope (legacy alias, canonicalized to `info`)
- `object_type="sites"` at the org level, keyed by `object_id=<site_id>` (an entry of the org-wide sites list)

The first two are routed through `_load_site_objects` so mocks in tests keep working; the third is a direct `BackupObject` query because it lives outside the `(object_type, site_id)` shape. Missing all three gracefully degrades to an empty site info dict with a log, and network filtering falls back to including all org networks.

### Site-scoped network filtering

Only networks referenced by the **templates actually assigned to the site** are included in `SiteSnapshot.networks`. `build_site_snapshot()`:

1. Reads `site_info.networktemplate_id` and `site_info.gatewaytemplate_id`.
2. Loads those specific templates from the backup and collects the set of network names they reference (via the inline `networks` dict keyed by name).
3. Also collects network names defined inline in `site_setting.networks`.
4. Filters the standalone `org_networks` pool down to just those referenced names, applies the template overrides on top, then layers site-scoped standalone network backups by id.
5. Finally sorts the resulting `networks` dict by key for deterministic iteration order.

Why this matters: without the filter, `org_networks` contains every network from every network template in the org, which triggers false CFG-SUBNET overlaps between networks that never co-exist on any real site (two different templates each defining a `10.10.10.0/24` network with different names). With the filter, the snapshot only contains networks the site actually consumes.

If no template assignment is discoverable (incomplete backup, or a legitimate site with no template), the filter is skipped and all org networks are included — preserving the old behaviour for partial backups instead of returning an empty snapshot. A `site_snapshot_no_template_refs` info log records when this fallback is used.

MongoDB's `$group` aggregation does not guarantee output order, so repeated calls to `load_all_objects_of_type` can return the same networks in different orders. Sorting the final `networks` dict by key keeps CFG-SUBNET detail strings stable across the baseline and predicted analysis passes, which the `pre_existing` classification relies on.

### Simulation Preflight Validation

- `endpoint_parser.py` rejects unresolved placeholders in path segments (e.g. `{site_id}`, `<device_id>`, `:site_id`) and marks them as parse errors.
- `twin_service.simulate()` runs target validation before snapshot analysis:
	- site-scoped writes must reference a real site present in backup snapshots (supports `info`, legacy `site`, org-level `sites`, or any site-scoped backup record)
	- `PUT`/`DELETE` writes for non-singleton resources must reference an existing backup object
- If preflight validation fails, simulation returns an error report (`SYS-00`/`SYS-01`/`SYS-02`/`SYS-03`) and does not run topology/config checks on invalid targets.
- Sessions with blocking preflight errors (`layer=0`, `check_id` prefixed `SYS-`, status `error|critical`) are marked `failed` instead of `awaiting_approval`.
- `approve_and_execute()` enforces server-side safety: approval is rejected when `prediction_report.execution_safe` is false or blocking preflight errors are present.
- Snapshot analysis fan-out is concurrency-limited (semaphore) to avoid unbounded per-site parallelism on large affected-site sets.

### Diff-based `execution_safe` / pre-existing classification

- `snapshot_analyzer.analyze_site()` runs every check twice: once against `(baseline, baseline)` to capture the current baseline state, once against `(baseline, predicted)` for the proposed change.
- Any failing predicted check whose `details` are a subset of the matching baseline result is marked `CheckResult.pre_existing=True`. New/worsened details disqualify the mark, so a change that introduces *new* issues in an already-failing check is still treated as introduced.
- `build_prediction_report()` then computes `execution_safe` using only non-pre-existing `error`/`critical` results. Pre-existing config debt (e.g. an unrelated subnet overlap in baseline) is surfaced in the report but does not block approval.
- `overall_severity` continues to reflect the true worst severity (including pre-existing issues) so the UI can show the real site state; only approval gating is diff-based.

### Live data sources — `fetch_live_data()`

Runs **two** Mist API calls in parallel to build `LiveSiteData`:

| Endpoint | Purpose | Best for |
|----------|---------|----------|
| `listOrgDevicesStats(org_id, site_id=..., fields="*")` | Device stats incl. `clients[]` (with `source="lldp"`), `if_stat`, `clients_stats.total` | AP client counts, AP-side LLDP (fallback) |
| `searchSiteSwOrGwPorts(site_id, limit=1000)` | Per-port records with `mac`, `port_id`, `neighbor_mac`, `neighbor_system_name`, `up` | **Authoritative switch/gateway LLDP and port state** |

Switch and gateway LLDP neighbours almost never appear in `listOrgDevicesStats.clients[]` — they live in the port stats endpoint. This mirrors how `impact_analysis` and `reports` fetch topology data. Both responses are merged into the same `lldp_neighbors` / `port_status` / `port_devices` dicts; per-source failures are logged (`live_data_org_stats_failed`, `live_data_port_stats_failed`, `live_data_port_stats_error`) without aborting the whole fetch.

All MACs are normalized via `_normalize_mac()` (strip `:`/`-`, lowercase) on both the live-data side and inside `_build_device_snapshot()`, so device lookups in `check_port_impact()` match regardless of the case/format each API returns.

### Port impact checks — missing live data

- When `baseline` contains any switch or gateway but `baseline.lldp_neighbors` is empty, `check_port_impact()` returns `PORT-DISC` and `PORT-CLIENT` with status `skipped` (not `pass`). This avoids a silent false-clear when live telemetry was unavailable.
- `fetch_live_data()` logs a `live_data_no_lldp` warning when neither `listOrgDevicesStats` nor `searchSiteSwOrGwPorts` returns LLDP neighbours for a site with switches/gateways, so operators can diagnose why port-impact checks were skipped.

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
