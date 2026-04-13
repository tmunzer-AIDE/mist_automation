# Digital Twin Check Descriptions — Design Spec

**Date:** 2026-04-12
**Branch:** feature/digital-twin-ui

## Problem

The Digital Twin session detail UI shows check results with an ID and a name (e.g., `PORT-DISC — Port Profile Disconnect Risk`) but gives no indication of what each check actually validates. Users unfamiliar with the check catalog cannot understand what passed or failed without reading external documentation.

## Goal

Add a plain-English description to every check result, visible inline below the check name on every row (pass, info, warning, error, critical) without requiring any user interaction.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Display style | Inline subtitle (always visible) | No hover required; self-documenting for first-time users |
| Data source | Backend `description` field on `CheckResult` | Co-located with check logic; available via API to future consumers (MCP, LLM) |
| Scope | All statuses (pass, info, warning, error, critical) | Even passing checks benefit from "what did this validate?" context |
| Skipped checks | No change | Already filtered from the UI in `checksByLayer` |

## Backend Changes

### 1. `models.py` — `CheckResult`

Add one field with an empty-string default so all existing call sites remain valid:

```python
description: str = ""
```

### 2. Check functions — descriptions per check

Every check function that constructs a `CheckResult` receives a `description=` kwarg. The strings are:

**Layer 0 — Input Validation** (`services/twin_service.py`)

| check_id | description |
|---|---|
| `SYS-00` | Verifies that an organization context (org_id) is present before simulation can proceed. |
| `SYS-01-{i}` | Validates that the staged write targets a well-formed, recognized Mist API endpoint. |
| `SYS-02-{i}` | Confirms the target site exists in backup data so baseline state can be built. |
| `SYS-03-{i}` | Confirms the target object ID exists in backup data for PUT/DELETE operations. |

**Layer 1 — Config Conflicts** (`checks/config_conflicts.py`, `checks/template_checks.py`)

| check_id | description |
|---|---|
| `CFG-SUBNET` | Checks all network subnets pairwise for IP address range overlaps. |
| `CFG-VLAN` | Detects VLAN IDs assigned to more than one network, which causes forwarding ambiguity. |
| `CFG-SSID` | Flags duplicate SSIDs among enabled WLANs on the same site. |
| `CFG-DHCP-RNG` | Checks all DHCP server scopes pairwise for overlapping address ranges. |
| `CFG-DHCP-CFG` | Validates that each DHCP scope's gateway and address range fall within the network's subnet. |
| `TMPL-VAR` | Detects Jinja2 `{{ variable }}` placeholders in device or site config that are not defined in site vars. |

**Layer 2 — Topology** (`checks/connectivity.py`, `checks/port_impact.py`)

| check_id | description |
|---|---|
| `CONN-PHYS` | Detects devices that were reachable from a gateway in baseline but become isolated after the change. |
| `CONN-VLAN` | Detects VLANs that lose all gateway L3 interfaces after the change, cutting off inter-VLAN routing. |
| `CONN-VLAN-PATH` | Detects devices that lose gateway reachability within a specific VLAN's L2 subgraph (e.g., a switchport trunk change silently drops an AP's WLAN VLAN). |
| `PORT-DISC` | Compares switch/gateway port profiles to find LLDP-confirmed neighbors that would be disconnected or lose VLAN membership. |
| `PORT-CLIENT` | Estimates the number of wireless clients affected by APs disconnected by port profile changes. |

**Layer 3 — Routing** (`checks/routing.py`)

| check_id | description |
|---|---|
| `ROUTE-GW` | Detects routed networks (with subnet/gateway config) that have no corresponding L3 interface on any gateway device. |
| `ROUTE-OSPF` | Checks that OSPF peer IPs from live telemetry remain reachable within the predicted gateway interface subnets. |
| `ROUTE-BGP` | Checks that BGP peer IPs from live telemetry remain reachable within the predicted gateway interface subnets. |
| `ROUTE-WAN` | Detects WAN ports removed from gateway devices, which reduces redundancy and available bandwidth. |

**Layer 4 — Security** (`checks/security.py`)

| check_id | description |
|---|---|
| `SEC-GUEST` | Flags open (unauthenticated) SSIDs that do not have client isolation enabled, allowing lateral traffic between clients. |
| `SEC-POLICY` | Reports additions, removals, or modifications to security policies between baseline and predicted state. |
| `SEC-NAC` | Reports changes to NAC rules between baseline and predicted state. |

**Layer 5 — L2 Loops / STP** (`checks/stp.py`)

| check_id | description |
|---|---|
| `STP-ROOT` | Detects STP root bridge shifts caused by bridge priority changes, which trigger network-wide reconvergence. |
| `STP-BPDU` | Flags trunk ports with BPDU filter enabled, which disables STP loop protection on switch-to-switch uplinks. |
| `STP-LOOP` | Detects new L2 cycles introduced in the physical topology graph that could cause broadcast storms. |

## Frontend Changes

### 1. `models/twin-session.model.ts` — `CheckResultModel`

Add field:

```typescript
description: string;
```

### 2. `session-detail.component.html` — check rows

Both the **pass row** and the **fail row** get a name-block with a description subtitle.

**Pass row** (replaces the flat `<span class="check-name">` with a block):

```html
<div class="check-name-block">
  <span class="check-name">{{ check.check_name }}</span>
  @if (check.description) {
    <span class="check-description">{{ check.description }}</span>
  }
</div>
```

**Fail row** (same structure inside `.check-summary-row`, alongside the severity badge and expand icon):

```html
<div class="check-name-block">
  <span class="check-name">{{ check.check_name }}</span>
  @if (check.description) {
    <span class="check-description">{{ check.description }}</span>
  }
</div>
```

### 3. `session-detail.component.scss` — new styles

```scss
.check-name-block {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.check-description {
  font-size: 11px;
  color: var(--app-text-secondary);
  line-height: 1.4;
}
```

Two existing flex containers need `align-items: flex-start` (currently `center`) so the icon and badge align to the top of the taller name block:
- `.check-row.check-passed` — the pass/info row
- `.check-summary-row` — the collapsed header of the fail/warning/error/critical row

## Files to Change

| File | Change |
|---|---|
| `backend/app/modules/digital_twin/models.py` | Add `description: str = ""` to `CheckResult` |
| `backend/app/modules/digital_twin/checks/config_conflicts.py` | Add `description=` to all 5 `CheckResult` constructions |
| `backend/app/modules/digital_twin/checks/template_checks.py` | Add `description=` to both `CheckResult` constructions |
| `backend/app/modules/digital_twin/checks/connectivity.py` | Add `description=` to all `CheckResult` constructions (3 checks × pass+fail paths) |
| `backend/app/modules/digital_twin/checks/port_impact.py` | Add `description=` to all `CheckResult` constructions |
| `backend/app/modules/digital_twin/checks/routing.py` | Add `description=` to all `CheckResult` constructions (4 checks) |
| `backend/app/modules/digital_twin/checks/security.py` | Add `description=` to all `CheckResult` constructions (3 checks) |
| `backend/app/modules/digital_twin/checks/stp.py` | Add `description=` to all `CheckResult` constructions (3 checks) |
| `backend/app/modules/digital_twin/services/twin_service.py` | Add `description=` to SYS-00, SYS-01-{i}, SYS-02-{i}, SYS-03-{i} |
| `frontend/src/app/features/digital-twin/models/twin-session.model.ts` | Add `description: string` to `CheckResultModel` |
| `frontend/src/app/features/digital-twin/session-detail/session-detail.component.html` | Replace flat check-name spans with name-block + description |
| `frontend/src/app/features/digital-twin/session-detail/session-detail.component.scss` | Add `.check-name-block` and `.check-description` styles |

## Out of Scope

- No changes to the `PredictionReport` aggregation or severity logic
- No changes to skipped-check filtering
- No backend API endpoint changes (field added to existing response shape)
- No test changes required for existing unit tests (default `""` keeps all assertions valid)
