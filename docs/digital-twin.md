# Digital Twin — Proactive Configuration Impact Analysis

The Digital Twin is a pre-deployment simulation engine that validates proposed Mist configuration changes against a virtual representation of the current network state before execution. It detects configuration conflicts, topology disruptions, routing issues, security policy violations, and L2 loop risks — catching problems before they reach production.

## How It Works

### The Core Concept

Traditional impact analysis is **reactive**: it monitors devices *after* a configuration change is deployed and reports on real-world impact. The Digital Twin is **proactive**: it simulates the change against a virtual network state and identifies issues *before* deployment.

### The Flow

```
User intent (natural language or API payload)
  │
  ▼
LLM translates intent → Mist API write payloads
  │
  ▼
Digital Twin intercepts writes
  │
  ├── 1. Resolve virtual state (backup base + live delta)
  ├── 2. Apply proposed writes to virtual state
  ├── 3. Run 37 validation checks across 5 layers
  │
  ▼
Report issues with severity + remediation hints
  │
  ├── Issues found → LLM proposes fixes → re-simulate (loop)
  └── Clean → User approves → Execute writes → IA monitors outcome
```

### Intent-Based UX Example

**User** (in chat panel):
> "Push template Retail-Standard to the 5 new sites in the West region, and assign subnet 10.50.x.0/24 to each."

**Behind the scenes:**
1. The LLM translates this into 5 PUT payloads (one per site)
2. The LLM calls `digital_twin(action="simulate", writes=[...])`
3. The Twin resolves virtual state from backup snapshots
4. Layer 1 checks detect: subnet 10.50.3.0/24 is already used on the Rennes site

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
└── services/
    ├── __init__.py
    ├── twin_service.py        # Core orchestration: simulate, approve, execute
    ├── state_resolver.py      # Build virtual state from backup + staged writes
    ├── prediction_service.py  # Run checks, build PredictionReport
    ├── config_checks.py       # 14 Layer 1 config conflict checks
    └── endpoint_parser.py     # Parse Mist API URLs into structured metadata
```

**API endpoints:** `backend/app/api/v1/digital_twin.py`
**MCP tool:** `backend/app/modules/mcp_server/tools/digital_twin.py`

### Data Model

**TwinSession** (MongoDB document, 24h TTL):
- Tracks a simulation session from creation through validation to deployment
- Status lifecycle: `pending` → `validating` → `awaiting_approval` → `approved` → `executing` → `deployed`
- Stores staged writes, validation results, remediation history, and IA session links

**StagedWrite**: A single proposed API write (method, endpoint, body) with parsed metadata (object_type, site_id, object_id).

**CheckResult**: Result of one validation check with severity, details, and remediation hints.

**PredictionReport**: Aggregated check results with counts and overall severity.

### Entry Points

| Entry Point | Mechanism | Phase |
|-------------|-----------|-------|
| LLM Chat | `digital_twin` MCP tool (simulate/approve/reject) | 1 |
| Workflow Executor | `twin_session_var` ContextVar in `MistService._api_call()` | 2 |
| Backup Restore | Twin intercepts restore writes | 3 |

### State Resolution

The Twin needs a virtual representation of the current Mist network state to validate against. It builds this from:

1. **Backup snapshots** (base) — latest version of each affected object from the backup system (40+ org-level, 12 site-level object types)
2. **Live API delta** — for objects being modified, fetches current state to detect changes since last backup
3. **Staged writes** — applies proposed changes in sequence: POST creates, PUT merges, DELETE removes

The resulting virtual state is keyed by `(object_type, site_id, object_id)` tuples.

## Validation Checks

### Layer 1: Config Conflict Detection (Phase 1 — 14 checks)

Pure JSON analysis — no topology or live telemetry needed.

| ID | Check | Severity | What It Catches |
|----|-------|----------|-----------------|
| L1-01 | IP/subnet overlap | Critical | Same subnet used across different sites (e.g., 10.50.3.0/24 on both Nantes and Rennes) |
| L1-02 | Subnet collision within site | Critical | Two networks on the same site with overlapping IP ranges |
| L1-03 | VLAN ID collision | Error | Same VLAN ID mapped to different network names on a site |
| L1-04 | Duplicate SSID | Error | Same SSID name broadcast on the same site |
| L1-05 | Port profile conflict | Error | Two profiles claiming the same physical switch port |
| L1-06 | Template override crush | Warning | Template push would silently overwrite site-level customizations |
| L1-07 | Unresolved template variables | Error | Template uses `{{ var_name }}` but site's vars dict doesn't define it |
| L1-08 | DHCP scope overlap | Error | Overlapping DHCP ranges on the same subnet |
| L1-09 | DHCP server misconfiguration | Error | Gateway IP outside subnet, DHCP range outside subnet |
| L1-10 | DNS/NTP consistency | Warning | Devices missing DNS or NTP configuration |
| L1-11 | SSID airtime overhead | Warning/Error | More than 4 SSIDs (~3% beacon overhead each). Warning at 5, error at 6+ |
| L1-12 | PSK rotation client impact | Warning | Changing a PSK will disconnect N currently-active clients |
| L1-13 | RF template impact | Warning | Channel/power changes in RF template affect active APs |
| L1-14 | Client capacity impact | Warning/Error | Reducing max_clients below or near current client count |

### Layer 2: Topology Impact Prediction (Phase 2 — 9 checks)

Uses predicted topology built from virtual state via the existing topology builder.

| ID | Check | What It Catches |
|----|-------|-----------------|
| L2-01 | Connectivity loss | BFS path to gateways broken |
| L2-02 | VLAN black hole | VLAN can't reach destination because trunk links don't carry it |
| L2-03 | LAG/MCLAG integrity | Removing a member port breaks an aggregate link |
| L2-04 | VC integrity | Config change would break virtual chassis |
| L2-05 | PoE budget overrun | Adding devices exceeds PSU capacity |
| L2-06 | PoE disable on active port | Disabling PoE on a port currently delivering power |
| L2-07 | Port capacity saturation | Deploying more devices than available switch ports |
| L2-08 | LACP misconfiguration | LAG member ports with mismatched speed/duplex/mode |
| L2-09 | MTU mismatch | Different MTU values on connected interfaces |

### Layer 3-5 (Phase 3)

- **Layer 3** (5 checks): Routing prediction — OSPF/BGP adjacency, default gateway gap, VRF consistency
- **Layer 4** (6 checks): Security policy — firewall rule shadows, NAC conflicts, guest SSID without isolation
- **Layer 5** (3 checks): L2 loop/STP — root bridge shift, loop risk without STP, BPDU filter on trunk

## MCP Tool API

The `digital_twin` MCP tool supports 5 actions:

### `simulate`
Validate proposed writes. Pass a JSON array of `{method, endpoint, body}` objects.

```json
{
  "action": "simulate",
  "writes": "[{\"method\": \"PUT\", \"endpoint\": \"/api/v1/sites/abc/setting\", \"body\": {\"vars\": {\"vlan\": \"100\"}}}]"
}
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

## Testing

### Unit Tests

Located in `backend/tests/unit/`:

| Test File | What It Tests | Count |
|-----------|--------------|-------|
| `test_endpoint_parser.py` | Mist API URL parsing (org/site patterns, singletons, unknown paths) | 18 |
| `test_state_resolver.py` | Virtual state merging (PUT/POST/DELETE, sequence ordering, metadata collection) | 7 |
| `test_config_checks.py` | All 14 L1 checks (pass cases, failure detection, edge cases) | 64 |
| `test_prediction_service.py` | Severity computation, report building, counts | 7 |

Run unit tests:
```bash
cd backend
.venv/bin/pytest tests/unit/test_endpoint_parser.py tests/unit/test_state_resolver.py tests/unit/test_config_checks.py tests/unit/test_prediction_service.py -v
```

### Integration Tests

Located in `backend/tests/integration/`:

| Test File | What It Tests |
|-----------|--------------|
| `test_digital_twin_api.py` | REST API endpoints (list, get, 404 handling) |

Run integration tests (requires MongoDB):
```bash
cd backend
.venv/bin/pytest tests/integration/test_digital_twin_api.py -v
```

## Dependencies

| Package | Purpose | License |
|---------|---------|---------|
| `netaddr` | IP/subnet math for overlap detection | BSD |
| `networkx` (Phase 2) | Graph algorithms for L2 cycle detection | BSD-3-Clause |

## Phasing

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Foundation + 14 L1 config checks + LLM chat entry point | Current |
| 2 | Topology prediction + 9 L2 checks + workflow entry point | Planned |
| 3 | Routing + security + L2 loop checks (L3-L5) + backup restore entry point | Planned |
| 4 | Impact Analysis bridge + prediction accuracy tracking | Planned |
| 5 | Batfish integration for deep L3 route computation | Future |

## Design Documents

- **Spec**: `docs/superpowers/specs/2026-04-11-digital-twin-design.md`
- **Phase 1 Plan**: `docs/superpowers/plans/2026-04-11-digital-twin-phase1.md`
