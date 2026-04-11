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
3. **Run checks**: Validation checks across 5 layers (`prediction_service` + check modules)
4. **Report**: Build `PredictionReport` with severity, details, remediation hints
5. **Remediate**: LLM proposes fixes, re-simulates (bounded by agent max_iterations)
6. **Approve**: User confirms via elicitation, staged writes execute against Mist API

### Key Services

| Service | Responsibility |
|---------|---------------|
| `twin_service.py` | Orchestration: simulate(), approve_and_execute(), reject_session() |
| `state_resolver.py` | Build virtual state from backup snapshots + staged writes |
| `prediction_service.py` | Run checks, build PredictionReport |
| `config_checks.py` | 14 Layer 1 config conflict checks (pure functions) |
| `topology_checks.py` | 9 Layer 2 topology prediction checks (pure functions, uses networkx) |
| `predicted_topology.py` | Build synthetic `RawSiteData` from virtual state for topology builder |
| `template_resolver.py` | Resolve Mist template inheritance chain for L1-06/L1-07 |
| `config_compiler.py` | Derive effective per-device config from Mist template inheritance chain |
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

### Check Layers

| Layer | Count | Description | Status |
|-------|-------|-------------|--------|
| L1 | 14 | Config conflicts: IP overlap, VLAN collision, SSID dupes, template vars, DHCP, etc. | Done |
| L2 | 9 | Topology: connectivity, VLAN black holes, LAG/VC, PoE | Done |
| L3 | 5 | Routing: OSPF/BGP adjacency, default gateway gap | Phase 3 |
| L4 | 6 | Security: firewall rules, NAC conflicts, guest SSID | Phase 3 |
| L5 | 3 | L2 loops: STP root shift, BPDU filter, loop detection | Phase 3 |

### L1 Check Catalog (Phase 1)

| ID | Check | Severity | Function |
|----|-------|----------|----------|
| L1-01 | IP/subnet overlap (cross-site) | Critical | `check_ip_subnet_overlap()` |
| L1-02 | Subnet collision within site | Critical | `check_subnet_collision_within_site()` |
| L1-03 | VLAN ID collision | Error | `check_vlan_id_collision()` |
| L1-04 | Duplicate SSID | Error | `check_duplicate_ssid()` |
| L1-05 | Port profile conflict | Error | `check_port_profile_conflict()` |
| L1-06 | Template override crush | Warning | `check_template_override_crush()` |
| L1-07 | Unresolved template variables | Error | `check_unresolved_template_variables()` |
| L1-08 | DHCP scope overlap | Error | `check_dhcp_scope_overlap()` |
| L1-09 | DHCP server misconfiguration | Error | `check_dhcp_server_misconfiguration()` |
| L1-10 | DNS/NTP consistency | Warning | `check_dns_ntp_consistency()` |
| L1-11 | SSID airtime overhead | Warning/Error | `check_ssid_airtime_overhead()` |
| L1-12 | PSK rotation client impact | Warning | `check_psk_rotation_impact()` |
| L1-13 | RF template impact | Warning | `check_rf_template_impact()` |
| L1-14 | Client capacity impact | Warning/Error | `check_client_capacity_impact()` |

### L2 Check Catalog (Phase 2)

| ID | Check | Severity | Function |
|----|-------|----------|----------|
| L2-01 | Connectivity loss (BFS to gateways) | Critical | `check_connectivity_loss()` |
| L2-02 | VLAN black hole (networkx subgraph) | Error | `check_vlan_black_hole()` |
| L2-03 | LAG/MCLAG integrity | Error | `check_lag_mclag_integrity()` |
| L2-04 | VC integrity | Critical | `check_vc_integrity()` |
| L2-05 | PoE budget overrun | Error | `check_poe_budget_overrun()` |
| L2-06 | PoE disable on active port | Critical | `check_poe_disable_on_active()` |
| L2-07 | Port capacity saturation | Error/Warning | `check_port_capacity_saturation()` |
| L2-08 | LACP misconfiguration | Warning | `check_lacp_misconfiguration()` |
| L2-09 | MTU mismatch | Warning | `check_mtu_mismatch()` |

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
6. Updated virtual state feeds into all 37 checks

Uses telemetry `LatestValueCache` for live LLDP/port data in topology prediction.

### Dependencies

- `netaddr` — IP/subnet math for overlap detection (L1-01, L1-02, L1-08, L1-09)
- `networkx` — Graph algorithms for VLAN black hole detection (L2-02)
