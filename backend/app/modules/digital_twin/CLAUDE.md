# Digital Twin Module

Part of mist_automation — see root `CLAUDE.md` for global architecture and conventions.

## Purpose

Pre-deployment simulation engine. Validates proposed Mist configuration changes against a virtual network state before execution. Detects config conflicts, topology issues, routing problems, security policy violations, and L2 loop risks.

## Architecture

### Entry Points

- **LLM Chat**: `digital_twin` MCP tool (`mcp_server/tools/digital_twin.py`) — LLM calls simulate/approve/reject
- **Workflow Executor** (Phase 2): `twin_session_var` ContextVar in `MistService._api_call()`
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
| L1 | 14 | Config conflicts: IP overlap, VLAN collision, SSID dupes, template vars, DHCP, etc. | Phase 1 |
| L2 | 9 | Topology: connectivity, VLAN black holes, LAG/VC, PoE | Phase 2 |
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

### Dependencies

- `netaddr` — IP/subnet math for overlap detection (L1-01, L1-02, L1-08, L1-09)
- `networkx` — Graph algorithms for L2 cycle detection (Phase 2)
