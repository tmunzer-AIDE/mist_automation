# Conditional Validation Checks + Proactive OSPF/BGP Monitoring

## Context

The impact analysis validation service runs all checks for a device type regardless of whether the feature is configured on the device. This produces noise (e.g., "PoE Budget: pass" on a non-PoE switch). Additionally, the routing adjacency check (#11) is purely incident-driven — it can't proactively detect lost OSPF/BGP peers since it doesn't query the Mist API for peer state.

## Design

### 1. Conditional checks — skip irrelevant checks entirely

Add a pre-flight condition function for each of these 4 checks. If the condition returns false, the check is **not run and not included** in `validation_results`. The frontend data panel already handles missing checks gracefully (only renders what's in the results dict).

| Check | Pre-flight condition | Data source |
|-------|-----|-----|
| DHCP Health (#9) | Device has non-empty `dhcpd_config` in topology (baseline OR latest) | `session.topology_baseline` / `session.topology_latest` device objects |
| VC Integrity (#10a) | Device has `is_virtual_chassis=True` | Topology device object |
| LAG/MCLAG Integrity (#10b) | Device has `mclag_domain_id` set OR has ae interfaces in port_stats/config | Topology device object + port_stats |
| PoE Budget (#13) | Any port for device MAC in `port_stats` has `poe_enabled=True` or `poe_on=True` | `ValidationData.port_stats` |
| Routing Adjacency (#11) | Device has OSPF or BGP peers in `routing_baseline`, OR routing incidents exist | `session.routing_baseline` + `session.incidents` |

Implementation: Add a `_should_run_check(check_num, session, validation_data)` function that returns `bool`. Call it before each check in `run_validations()`. If false, skip the check (don't add it to results).

### 2. Split check #10 into VC Integrity + LAG/MCLAG Integrity

The current check #10 handles both VC and MCLAG in one check. Split it into two independent checks:

**Check #10a — VC Integrity**: Only runs when `is_virtual_chassis=True`. Checks VC member count, member roles (master/backup/linecard), and VC ICL link status. Compares baseline vs current topology groups.

**Check #10b — LAG/MCLAG Integrity**: Only runs when device has `mclag_domain_id` OR has ae (aggregated ethernet) interfaces. Checks:
- **MCLAG**: Domain membership, peer link status (same as current MCLAG logic)
- **LAG (ae interfaces)**: Detects ae interfaces from port_stats (port_id starts with `ae`). Checks member link status — if any ae member port is down, warns. If the ae interface itself is down, fails. Compares baseline port_stats ae state vs current.

Both report independently in validation results (`vc_integrity` and `lag_mclag_integrity` keys).

### 3. Proactive OSPF/BGP peer monitoring

Enhance the routing adjacency check (#11) to do a baseline-vs-current comparison of actual peer state from the Mist API.

#### Baseline capture (monitoring_worker.py)

During the BASELINE_CAPTURE phase, after capturing SLE baseline:
```python
routing_baseline = await _fetch_routing_peers(org_id, site_id, device_mac, api_session)
session.routing_baseline = routing_baseline
```

`_fetch_routing_peers()` calls:
- `searchOrgOspfStats(org_id, mac=device_mac, site_id=site_id)` — returns OSPF neighbor list
- `searchOrgBgpStats(org_id, mac=device_mac, site_id=site_id)` — returns BGP peer list

Stored on session as:
```python
routing_baseline: dict | None = Field(default=None)
# Structure:
# {
#   "ospf_peers": [{"neighbor_ip": "10.0.0.1", "state": "full", "area": "0.0.0.0", "neighbor_mac": "...", ...}],
#   "bgp_peers": [{"neighbor_ip": "10.0.0.2", "state": "established", "remote_as": 65001, "neighbor_mac": "...", ...}],
# }
```

#### Validation check (#11, enhanced)

Fetch current peers during validation:
```python
routing_current = await _fetch_routing_peers(org_id, site_id, device_mac)
```

Compare baseline vs current:
- **Lost peers**: Present in baseline but missing from current — **fail** if any
- **State degradation**: Peer present but state changed from "full"/"established" to something else — **warn**
- **New peers**: Present in current but not in baseline — **info** (not a problem, just notable)
- **No peers**: If baseline had 0 peers and current has 0 peers — skip (handled by pre-flight condition)

Keep existing incident-driven checks (OSPF_NEIGHBOR_DOWN, BGP_NEIGHBOR_DOWN) as supplementary signals.

#### Skip condition

If `routing_baseline` is None or has 0 OSPF peers AND 0 BGP peers AND no routing-related incidents exist, skip check #11 entirely.

### Files to modify

| File | Change |
|------|--------|
| `backend/app/modules/impact_analysis/models.py` | Add `routing_baseline: dict \| None` field to `MonitoringSession` |
| `backend/app/modules/impact_analysis/workers/monitoring_worker.py` | Add `_fetch_routing_peers()` call during baseline capture |
| `backend/app/modules/impact_analysis/services/validation_service.py` | Add `_should_run_check()` pre-flight; split check #10 into 10a (VC) + 10b (LAG/MCLAG); enhance check #11 with peer comparison |
| `frontend/.../models/impact-analysis.model.ts` | Update `VALIDATION_CHECK_LABELS` — replace `vc_mclag_integrity` with `vc_integrity` + `lag_mclag_integrity` |

### Verification

- Trigger impact analysis on a switch with DHCP, VC, PoE, and OSPF/BGP → all relevant checks run
- Trigger impact analysis on a switch without PoE or VC → those checks are skipped from results
- Trigger impact analysis on a switch in a LAG (ae interfaces) → LAG/MCLAG check runs, VC check skipped
- Trigger impact analysis on a gateway with BGP peers → routing check shows peer comparison
- Trigger impact analysis on a device with no routing → routing check is skipped
