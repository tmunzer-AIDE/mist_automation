# Digital Twin — Proactive Configuration Impact Analysis

The Digital Twin is a pre-deployment simulation engine that validates proposed Mist configuration changes against a virtual representation of the current network state before execution. It detects configuration conflicts, topology disruptions, routing issues, security policy violations, and L2 loop risks — catching problems before they reach production.

## How It Works

### The Core Concept

Traditional impact analysis is **reactive**: it monitors devices *after* a configuration change is deployed and reports on real-world impact. The Digital Twin is **proactive**: it simulates the change against a virtual network state and identifies issues *before* deployment.

### The Flow

```
User intent (natural language or API payload)
  |
  v
LLM translates intent -> Mist API write payloads
  |
  v
Digital Twin intercepts writes
  |
  |-- 1. Resolve virtual state (backup base + staged writes)
  |-- 2. Compile effective device configs (template inheritance)
  |-- 3. Build predicted topology (live telemetry + compiled configs)
  |-- 4. Run 37 validation checks across 5 layers
  |
  v
Report issues with severity + remediation hints
  |
  |-- Issues found -> LLM proposes fixes -> re-simulate (loop)
  '-- Clean -> User approves -> Execute writes -> IA monitors outcome
```

### Intent-Based UX Example

**User** (in chat panel):
> "Push template Retail-Standard to the 5 new sites in the West region, and assign subnet 10.50.x.0/24 to each."

**Behind the scenes:**
1. The LLM translates this into 5 PUT payloads (one per site)
2. The LLM calls `digital_twin(action="simulate", writes=[...])`
3. The Twin resolves virtual state from backup snapshots
4. The config compiler detects the template change and finds ALL sites using Retail-Standard
5. For each site, it compiles the effective per-device config (template + site setting + device overrides)
6. Layer 1 checks detect: subnet 10.50.3.0/24 is already used on the Rennes site
7. Layer 2 topology checks verify connectivity won't break

**AI responds:**
> "I'm ready to deploy the 5 sites. However, my pre-deployment test detected an IP conflict on the Nantes site (10.50.3.0/24 overlaps with Rennes). Shall I change Nantes to 10.50.6.0/24 before deploying?"

**User:** "Yes, go ahead."

The LLM fixes the payload, re-simulates (clean), and calls `digital_twin(action="approve")`. User confirms via the elicitation dialog, and writes are executed against the Mist API.

## Architecture

### Module Structure

```
backend/app/modules/digital_twin/
├── __init__.py
├── models.py                  # TwinSession, StagedWrite, CheckResult, PredictionReport
├── schemas.py                 # REST API response DTOs
├── CLAUDE.md                  # Module documentation for AI agents
├── SKILL.md                   # LLM agent skill for auto-activation
├── workers/
│   └── cleanup_worker.py      # APScheduler nightly cleanup (4:00 UTC)
└── services/
    ├── twin_service.py        # Core orchestration: simulate, approve, execute
    ├── config_compiler.py     # Template inheritance resolution + impact scope detection
    ├── state_resolver.py      # Build virtual state from backup + staged writes
    ├── prediction_service.py  # Run checks across all 5 layers, build PredictionReport
    ├── predicted_topology.py  # Build SiteTopology from compiled configs + live telemetry
    ├── config_checks.py       # 14 Layer 1 config conflict checks
    ├── topology_checks.py     # 9 Layer 2 topology prediction checks
    ├── routing_checks.py      # 5 Layer 3 routing prediction checks
    ├── security_checks.py     # 6 Layer 4 security policy checks
    ├── l2_checks.py           # 3 Layer 5 L2/STP prediction checks
    ├── template_resolver.py   # Resolve Mist template assignments for L1-06/L1-07
    └── endpoint_parser.py     # Parse Mist API URLs into structured metadata
```

**API endpoints:** `backend/app/api/v1/digital_twin.py`
**MCP tool:** `backend/app/modules/mcp_server/tools/digital_twin.py`
**Frontend:** `frontend/src/app/shared/components/ai-chat-panel/twin-result-card.component.ts`

### Data Model

**TwinSession** (MongoDB document, 7-day TTL):
- Tracks a simulation session from creation through validation to deployment
- Status lifecycle: `pending` -> `validating` -> `awaiting_approval` -> `approved` -> `executing` -> `deployed`
- Stores staged writes, validation results, remediation history, and IA session links

**StagedWrite**: A single proposed API write (method, endpoint, body) with parsed metadata (object_type, site_id, object_id).

**CheckResult**: Result of one validation check with severity, details, and remediation hints.

**PredictionReport**: Aggregated check results with counts and overall severity.

### Entry Points

| Entry Point | Mechanism | Status |
|-------------|-----------|--------|
| LLM Chat | `digital_twin` MCP tool (simulate/approve/reject) | Done |
| Workflow Executor | `twin_session_var` ContextVar in `MistService._api_call()` | Done |
| Backup Restore | Pre-check via `validate_with_twin()` in RestoreService | Done |

### Config Compilation Pipeline

When a template is modified, the config compiler:

1. **Detect template changes** — scans staged writes for org-level template modifications (network, gateway, site, RF, AP templates)
2. **Find impacted sites** — queries BackupObject(type="info") for all sites where the template assignment field matches the changed template ID (zero API calls)
3. **Fetch derived config** — gets current `getSiteSettingDerived` from SiteDataCoordinator cache (already merged by Mist), falls back to backup
4. **Apply proposed changes** — merges the template delta into the derived config locally
5. **Compile per-device configs**:
   - **Switch**: `derived_setting.{port_usages, networks, dhcpd_config}` + `device.port_config` (shallow merge, device wins)
   - **Gateway**: `gw_template` + `device_profile` + `device` (shallow for most fields, deep merge for `port_config` to preserve template fields like `aggregated`, `ae_idx`)
6. **Resolve variables** — substitute `{{ var_name }}` patterns from `site_setting.vars`
7. **Build topology** — feed compiled configs + live LLDP/port data from telemetry cache into the topology builder

### Predicted Topology

The topology builder uses live data from the telemetry `LatestValueCache`:
- **Switch LLDP**: `clients[]` array from WebSocket (MAC + port_ids, source="lldp") — enough to build the device-to-device link graph
- **Port status**: `if_stat` from WebSocket (per-port up/down, tx/rx)
- **PoE data**: `module_stat[].poe.{max_power, power_draw}` from WebSocket
- **VC links**: `module_stat[].vc_links[]` from WebSocket
- **AP LLDP**: `lldp_stat` / `lldp_stats` from WebSocket (full LLDP with switch chassis_id + port)
- **Fallback**: `searchSiteSwOrGwPorts` API if telemetry is not active

## Validation Checks (37 total)

### Layer 1: Config Conflict Detection (14 checks)

Pure JSON analysis on compiled device configs.

| ID | Check | Severity | What It Catches |
|----|-------|----------|-----------------|
| L1-01 | IP/subnet overlap | Critical | Same subnet used across different sites |
| L1-02 | Subnet collision within site | Critical | Two networks on the same site with overlapping IP ranges |
| L1-03 | VLAN ID collision | Error | Same VLAN ID mapped to different network names on a site |
| L1-04 | Duplicate SSID | Error | Same SSID name broadcast on the same site |
| L1-05 | Port profile conflict | Error | Two profiles claiming the same physical switch port |
| L1-06 | Template override crush | Warning | Template push would silently overwrite site-level customizations |
| L1-07 | Unresolved template variables | Error | Template uses `{{ var_name }}` but site's vars dict doesn't define it |
| L1-08 | DHCP scope overlap | Error | Overlapping DHCP ranges on the same subnet |
| L1-09 | DHCP server misconfiguration | Error | Gateway IP outside subnet, DHCP range outside subnet |
| L1-10 | DNS/NTP consistency | Warning | Devices missing DNS or NTP configuration |
| L1-11 | SSID airtime overhead | Warning/Error | More than 4 SSIDs (~3% beacon overhead each) |
| L1-12 | PSK rotation client impact | Warning | Changing a PSK will disconnect N currently-active clients (live count from telemetry) |
| L1-13 | RF template impact | Warning | Channel/power changes in RF template affect active APs (live count from telemetry) |
| L1-14 | Client capacity impact | Warning/Error | Reducing max_clients below or near current client count (live count from telemetry) |

### Layer 2: Topology Impact Prediction (9 checks)

Uses predicted topology built from compiled configs + live telemetry data.

| ID | Check | Severity | What It Catches |
|----|-------|----------|-----------------|
| L2-01 | Connectivity loss | Critical | BFS path to gateways broken in predicted topology |
| L2-02 | VLAN black hole | Error | VLAN can't reach destination because trunk links don't carry it |
| L2-03 | LAG/MCLAG integrity | Error | Removing a member port breaks an aggregate link |
| L2-04 | VC integrity | Critical | Config change would break virtual chassis |
| L2-05 | PoE budget overrun | Error | Adding devices exceeds PSU capacity |
| L2-06 | PoE disable on active port | Critical | Disabling PoE on a port currently delivering power |
| L2-07 | Port capacity saturation | Error | Deploying more devices than available switch ports |
| L2-08 | LACP misconfiguration | Warning | LAG member ports with mismatched speed/duplex/mode |
| L2-09 | MTU mismatch | Warning | Different MTU values on connected interfaces |

### Layer 3: Routing Prediction (5 checks)

Rule-based routing adjacency analysis.

| ID | Check | Severity | What It Catches |
|----|-------|----------|-----------------|
| L3-01 | Default gateway gap | Critical | IRB subnet on switch but no OSPF/BGP/static route to gateway |
| L3-02 | OSPF adjacency break | Critical | Subnet/interface change would break an OSPF neighbor relationship |
| L3-03 | BGP peer break | Critical | IP change would invalidate a configured BGP peer session |
| L3-04 | VRF consistency | Error | Route leaking or VRF membership inconsistency |
| L3-05 | WAN failover path impact | Warning | WAN link config change could affect failover behavior |

### Layer 4: Security Policy Analysis (6 checks)

Mist security/NAC policies analyzed as structured JSON.

| ID | Check | Severity | What It Catches |
|----|-------|----------|-----------------|
| L4-01 | Guest SSID security violation | Critical | Guest SSID without client isolation or RFC1918 blocking |
| L4-02 | NAC auth server dependency | Critical | Removing an auth server that active NAC rules depend on |
| L4-03 | NAC VLAN assignment conflict | Error | Two NAC rules assigning conflicting VLANs to same match criteria |
| L4-04 | Unreachable destination | Error | Policy references a network that doesn't exist |
| L4-05 | Service policy object reference | Error | Service references non-existent application or address group |
| L4-06 | Firewall rule shadow | Warning | New rule never matches because a broader rule precedes it |

### Layer 5: L2 Loop & STP Prediction (3 checks)

Heuristic checks based on config analysis (no STP simulator).

| ID | Check | Severity | What It Catches |
|----|-------|----------|-----------------|
| L5-01 | L2 loop risk | Critical | New trunk link creating redundant path without STP (networkx cycle detection) |
| L5-02 | BPDU filter on trunk | Critical | Enabling BPDU filter on a trunk port disables STP protection |
| L5-03 | STP root bridge shift | Warning | Bridge priority change could elect a new root, causing reconvergence |

## MCP Tool API

The `digital_twin` MCP tool supports 5 actions:

### `simulate`
Validate proposed writes. Pass an array of `{method, endpoint, body}` objects.

```json
[
  {"method": "PUT", "endpoint": "/api/v1/sites/abc/setting", "body": {"vars": {"vlan": "100"}}},
  {"method": "POST", "endpoint": "/api/v1/sites/abc/wlans", "body": {"ssid": "Guest"}}
]
```

Returns check results with severity, details, and remediation hints.

### `approve`
Deploy staged writes after user confirmation (elicitation dialog).

### `reject`
Cancel the simulation session.

### `status`
Check current session state and last validation results.

### `history`
List recent simulation sessions.

## REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/digital-twin/sessions` | List sessions (filter by status, paginate) |
| GET | `/api/v1/digital-twin/sessions/{id}` | Get session details with full prediction report |
| POST | `/api/v1/digital-twin/sessions/{id}/cancel` | Cancel/reject a session |

All endpoints require admin role.

## Frontend Integration

**Chat Panel** (`ai-chat-panel`):
- `TwinResultCardComponent`: renders simulation results with severity-colored left border, stacked progress bar, collapsible issues list
- `twin_approve` elicitation: deployment confirmation card with writes/sites/remediation counts and Deploy/Cancel buttons

## Testing

### Unit Tests (246 tests)

Located in `backend/tests/unit/`:

| Test File | What It Tests | Count |
|-----------|--------------|-------|
| `test_endpoint_parser.py` | Mist API URL parsing | 18 |
| `test_state_resolver.py` | Virtual state merging | 7 |
| `test_config_checks.py` | 14 L1 config conflict checks | 64 |
| `test_prediction_service.py` | Severity computation, report building, check ID verification | 8 |
| `test_predicted_topology.py` | Synthetic RawSiteData construction | 5 |
| `test_topology_checks.py` | 9 L2 topology checks | 30 |
| `test_routing_checks.py` | 5 L3 routing checks | 32 |
| `test_security_checks.py` | 6 L4 security checks | 36 |
| `test_l2_checks.py` | 3 L5 STP/loop checks | 16 |
| `test_config_compiler.py` | Config compilation, template detection, variable resolution | 30 |

Run all tests:
```bash
cd backend
.venv/bin/pytest tests/unit/test_endpoint_parser.py tests/unit/test_state_resolver.py \
  tests/unit/test_config_checks.py tests/unit/test_prediction_service.py \
  tests/unit/test_predicted_topology.py tests/unit/test_topology_checks.py \
  tests/unit/test_routing_checks.py tests/unit/test_security_checks.py \
  tests/unit/test_l2_checks.py tests/unit/test_config_compiler.py -v
```

### Integration Tests

Located in `backend/tests/integration/`:

| Test File | What It Tests |
|-----------|--------------|
| `test_digital_twin_api.py` | REST API endpoints (list, get, 404 handling) |

## Dependencies

| Package | Purpose | License |
|---------|---------|---------|
| `netaddr` | IP/subnet math for overlap detection | BSD |
| `networkx` | Graph algorithms for L2 cycle detection and VLAN propagation | BSD-3-Clause |

## Phasing

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Foundation + 14 L1 config checks + LLM chat + frontend | Done |
| 2 | 9 L2 topology checks + workflow integration + ContextVar interception | Done |
| 3 | 14 L3-L5 routing/security/STP checks + backup restore integration | Done |
| Config Compiler | Template inheritance resolution + impact scope + telemetry topology | Done |
| 4 | Impact Analysis bridge + prediction accuracy tracking | Next |
| 5 | Batfish integration for deep L3 route computation | Future |
