# AP Power Scheduling — Design Spec

**Date:** 2026-03-30  
**Status:** Approved  
**Module:** `power_scheduling`  
**Autonomy level:** B (detect + recommend) → C (auto-act) based on confidence  

---

## Overview

Automatically disable AP radios during configured off-hours windows to save energy, then re-enable them as clients appear. Fully self-driven with safety guardrails: APs are never disabled if they or their RF neighbors have active clients. Real-time client tracking via Mist WebSocket ensures seamless coverage when someone comes in during off-hours.

---

## Data Sources

| Source | Usage |
|--------|-------|
| Mist API | Site timezone, AP inventory, device profile CRUD, RF neighbor data (`GET /api/v1/sites/{site_id}/rrm/neighbors/band/{band}` for bands `24`, `5`, `6` — merged across bands) |
| `/sites/{site_id}/stats/clients` WS | Real-time client association, disassociation, RSSI per AP |
| `LatestValueCache` | 30s fallback for client counts when WS lags |
| MongoDB | `PowerSchedule` config, `PowerScheduleLog` audit trail |
| APScheduler | Timezone-aware cron jobs for window start/end |

---

## Module Structure

```
backend/app/modules/power_scheduling/
  __init__.py                  # AppModule registration
  models.py                    # PowerSchedule, PowerScheduleLog
  router.py                    # REST endpoints
  services/
    scheduling_service.py      # Core on/off logic, state machine
    client_ws_service.py       # Mist clients WS handler
  workers/
    schedule_worker.py         # APScheduler job registration, startup recovery
```

---

## Data Models

### `PowerSchedule` (MongoDB document, one per site)

```python
site_id: str
site_name: str
timezone: str                        # IANA, auto-fetched from Mist API on create/update
windows: list[ScheduleWindow]        # [{days: [0-6], start: "22:00", end: "06:00"}]
off_profile_id: str                  # Mist device profile ID (radios disabled), created at setup
neighbor_rssi_threshold_dbm: int     # default -65
grace_period_minutes: int            # default 5 — wait before re-disabling empty AP
critical_ap_macs: list[str]          # v1 — always-on APs; v2 will use Mist wxtag lookup
enabled: bool
current_status: Literal["IDLE", "OFF_HOURS"]   # persisted for catch-up recovery
last_transition_at: datetime | None
```

### `PowerScheduleLog` (MongoDB document, append-only audit trail)

```python
site_id: str
timestamp: datetime
event_type: Literal[
    "WINDOW_START", "WINDOW_END",
    "CATCHUP_START", "CATCHUP_END",        # direction: "off" | "on"
    "AP_DISABLED", "AP_PENDING", "AP_ENABLED",
    "GRACE_TIMER_START", "GRACE_TIMER_EXPIRED",
    "CLIENT_DETECTED", "CLIENT_LEFT",
    "PROFILE_CREATED",
    "ERROR",
]
ap_mac: str | None
details: dict                              # context: reason, client_mac, rssi, profile_id, error, etc.
```

### `PowerScheduleState` (in-memory, keyed by `site_id`)

```python
status: Literal["IDLE", "TRANSITIONING_OFF", "OFF_HOURS", "TRANSITIONING_ON"]
disabled_aps: dict[str, str | None]        # {ap_mac: original_profile_id | None}
pending_disable: set[str]                  # APs waiting: has clients or neighbor has clients
client_map: dict[str, set[str]]            # {ap_mac: {client_mac, ...}} — live from WS
grace_timers: dict[str, datetime]          # {ap_mac: time it became empty}
rf_neighbor_map: dict[str, list[tuple[str, int]]]  # {ap_mac: [(neighbor_mac, rssi_dbm)]}
```

---

## RF Neighbor Map

Fetched once at the start of each `TRANSITIONING_OFF` and cached in `PowerScheduleState.rf_neighbor_map`.

**Endpoint:** `GET /api/v1/sites/{site_id}/rrm/neighbors/band/{band}`
Called for each band: `24`, `5`, `6` — results merged across bands.

**Merge strategy:** for each AP pair `(ap_mac, neighbor_mac)`, keep the **best RSSI** (highest value) across all bands. If two APs can hear each other well on any band, they are RF neighbors for coverage purposes.

```python
async def fetch_rf_neighbor_map(site_id: str) -> dict[str, list[tuple[str, int]]]:
    result: dict[str, dict[str, int]] = {}  # {ap_mac: {neighbor_mac: best_rssi}}
    for band in ("24", "5", "6"):
        data = await mist_api.get(f"/sites/{site_id}/rrm/neighbors/band/{band}")
        for entry in data.get("results", []):
            ap_mac = entry["mac"]
            for nbr in entry.get("neighbors", []):
                nbr_mac, rssi = nbr["mac"], int(nbr["rssi"])
                current = result.setdefault(ap_mac, {})
                current[nbr_mac] = max(current.get(nbr_mac, -999), rssi)
    return {ap: list(nbrs.items()) for ap, nbrs in result.items()}
```

The map is also used during `OFF_HOURS` for the `rssi_degrading` pre-enable logic without an additional API call.

---

## Eligibility Check

An AP can be disabled if ALL of:
1. Not in `critical_ap_macs`
2. `client_map[ap_mac]` is empty
3. For all `(neighbor_mac, rssi)` in `rf_neighbor_map[ap_mac]` where `rssi > neighbor_rssi_threshold_dbm`: `client_map[neighbor_mac]` is empty

```python
def can_disable(ap_mac: str, state: PowerScheduleState, schedule: PowerSchedule) -> bool:
    if ap_mac in schedule.critical_ap_macs:
        return False
    if state.client_map.get(ap_mac):
        return False
    for neighbor_mac, rssi in state.rf_neighbor_map.get(ap_mac, []):
        if rssi > schedule.neighbor_rssi_threshold_dbm:
            if state.client_map.get(neighbor_mac):
                return False
    return True
```

---

## State Machine

```
IDLE
  → start_off_hours() → TRANSITIONING_OFF

TRANSITIONING_OFF
  1. Fetch RF neighbor map from Mist API (see below) → cache in state
  2. Fetch AP inventory from Mist API
  3. For each AP (excluding critical):
     - can_disable() == True  → assign off_profile_id → disabled_aps
     - can_disable() == False → pending_disable
  4. Log WINDOW_START + AP_DISABLED/AP_PENDING per AP
  → OFF_HOURS

OFF_HOURS
  → on client_detected(ap_mac, client_mac):
      update client_map
      if ap_mac in disabled_aps → restore profile → log AP_ENABLED(reason=client_arrived)
      enable RF neighbors of ap_mac that are in disabled_aps → log AP_ENABLED(reason=neighbor_coverage)
      log CLIENT_DETECTED

  → on client_left(ap_mac, client_mac):
      update client_map
      if client_map[ap_mac] is now empty:
          start grace_timer[ap_mac] → log GRACE_TIMER_START
      re-evaluate can_disable() for all APs in pending_disable
      log CLIENT_LEFT

  → on grace_timer_expired(ap_mac):
      if client_map[ap_mac] still empty and can_disable():
          assign off_profile_id → move to disabled_aps → log AP_DISABLED, GRACE_TIMER_EXPIRED

  → on rssi_degrading(client_mac, current_ap_mac):
      # client RSSI on current AP below roam_rssi_threshold → likely about to roam
      # pre-enable ALL RF-close disabled neighbors of current_ap_mac (we don't know the exact target)
      for neighbor_mac in rf_neighbor_map[current_ap_mac] where rssi > neighbor_rssi_threshold_dbm:
          if neighbor_mac in disabled_aps:
              restore profile → log AP_ENABLED(reason=rssi_pre_enable)

  → end_off_hours() → TRANSITIONING_ON

TRANSITIONING_ON
  1. For each ap_mac in disabled_aps: restore original_profile_id (or site default)
  2. Clear pending_disable, grace_timers, disabled_aps
  3. Log WINDOW_END + AP_ENABLED per AP
  → IDLE
```

---

## Worker & APScheduler Integration

### Startup sequence (`schedule_worker.py`)

1. Load all `PowerSchedule` where `enabled=True`
2. For each schedule:
   - Register APScheduler `CronTrigger` jobs with `timezone=pytz.timezone(schedule.timezone)`:
     - `power_schedule_off_{site_id}_{i}` → `start_off_hours(site_id)`
     - `power_schedule_on_{site_id}_{i}` → `end_off_hours(site_id)`
   - Subscribe to `/sites/{site_id}/stats/clients` via `MistWsManager` (persistent, never closed while enabled)
3. Run **missed window recovery**:

```python
for schedule in enabled_schedules:
    expected = compute_expected_status(schedule, now_local)
    if expected == "OFF_HOURS" and schedule.current_status == "IDLE":
        log.info("catchup", direction="off", site_id=schedule.site_id)
        await start_off_hours(schedule.site_id)   # log CATCHUP_START … CATCHUP_END
    elif expected == "IDLE" and schedule.current_status == "OFF_HOURS":
        log.info("catchup", direction="on", site_id=schedule.site_id)
        await end_off_hours_catchup(schedule.site_id)  # log CATCHUP_START … CATCHUP_END
```

### `end_off_hours_catchup()` (no in-memory state)

Since `PowerScheduleState` is lost on restart, the catch-up re-enable queries Mist API directly:
1. `GET /sites/{site_id}/devices` — find all APs with `deviceprofile_id == off_profile_id`
2. For each: restore profile to site default (or `None`) → log `AP_ENABLED(reason=catchup)`
3. Update `schedule.current_status = "IDLE"`

### Schedule lifecycle (on API create/update/delete)

- Delete existing APScheduler jobs for `site_id`
- If still enabled: re-register fresh jobs with updated timezone/windows
- Update WS subscription accordingly
- On delete: also call `end_off_hours()` if `current_status == OFF_HOURS`, then delete Mist profile

### Midnight-crossing windows

APScheduler `CronTrigger(hour=22, minute=0)` and `CronTrigger(hour=6, minute=0)` handle this correctly — they fire independently on the correct calendar days in the site's timezone.

---

## Clients WebSocket Handler

`client_ws_service.py` registers a handler with `MistWsManager` for `/sites/{site_id}/stats/clients`.

Events parsed:
- `client_joined` / `assoc` → `on_client_detected(site_id, ap_mac, client_mac)`
- `client_left` / `disassoc` → `on_client_left(site_id, ap_mac, client_mac)`
- RSSI update → if RSSI < `-75 dBm` (configurable) on current AP, check if likely next AP is disabled → `on_rssi_degrading()`

The WS subscription is active as long as `PowerSchedule.enabled = True` — **not** scoped to the off-hours window. The live `client_map` is available continuously for future cross-module correlation use cases.

---

## Logging

### Structlog (every operation)

```python
log = structlog.get_logger().bind(site_id=site_id, module="power_scheduling")
log.info("ap_disabled", ap_mac=mac, reason="0_clients_and_neighbors", profile_id=off_profile_id)
log.info("ap_enabled", ap_mac=mac, reason="client_arrived", client_mac=client_mac)
log.warning("ap_profile_restore_failed", ap_mac=mac, error="<sanitized>")
log.info("catchup_triggered", direction="on", missed_since=str(last_transition_at))
```

### MongoDB (`PowerScheduleLog`)

Every significant event creates a log entry: every state transition, every AP action, every client event that triggered a decision, every error, every catch-up. This feeds:
- The frontend log table (status panel)
- Future "self-healing effectiveness" meta-feature (did the re-enable actually help?)

---

## API Endpoints

All endpoints under `/api/v1/power-scheduling/`, protected by `require_impact_role`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/sites` | List all schedules with current status |
| `POST` | `/sites/{site_id}` | Create — fetches timezone, creates Mist off-profile, registers jobs |
| `PUT` | `/sites/{site_id}` | Update — re-registers jobs, updates profile if needed |
| `DELETE` | `/sites/{site_id}` | Delete — removes Mist profile, re-enables any disabled APs, unregisters jobs |
| `GET` | `/sites/{site_id}/status` | Live state: status, disabled count, pending count, client_map summary |
| `GET` | `/sites/{site_id}/logs` | Paginated `PowerScheduleLog`, filterable by `event_type` and time range |
| `POST` | `/sites/{site_id}/trigger` | Manual override: `{action: "start" \| "end"}` — for testing |

---

## Frontend

New lazy-loaded area: `features/power-scheduling/`

**List view** (`/power-scheduling`):
- Card per configured site: status badge (`IDLE` / `OFF_HOURS`), next window, disabled AP count
- "Add site" button

**Detail/config view** (`/power-scheduling/{site_id}`):
- Schedule config: days-of-week selector, time range per window, grace period, RSSI threshold
- Critical APs: MAC list input (v1 — wxtag-based selection planned for v2)
- Status panel: live counts (disabled, pending, active clients), last log entries
- Manual trigger buttons: "Start now" / "End now"
- Log table: `PowerScheduleLog` with event type badges and AP/client context

**Real-time updates:** WebSocket channel `power_scheduling:{site_id}` — backend broadcasts on every state change and AP action.

---

## Future Enhancements (v2)

- **Wxtag-based critical APs**: replace `critical_ap_macs` list with Mist label lookup — admin tags APs in Mist, no duplicate config in our DB
- **InfluxDB-suggested windows**: analyze 14-day client count patterns, surface recommended off-hours windows in the UI
- **Cross-module correlation**: `client_map` (always-on WS) feeds into incident correlation engine and impact analysis
- **Zone webhook support**: enable/disable per-zone rather than per-site when Mist zone webhooks are added

---

## Reused Infrastructure

| Component | Usage |
|-----------|-------|
| `MistWsManager` | Clients WS subscription (extend to support `/stats/clients` channel) |
| `LatestValueCache` | 30s fallback for client counts |
| `create_mist_service()` | All Mist API calls |
| APScheduler | Already in app — reuse for cron jobs |
| `create_background_task()` | Grace timer monitoring |
| Mist RRM API | `GET /api/v1/sites/{site_id}/rrm/neighbors/band/{band}` — RF neighbor map, merged across 24/5/6 GHz bands |
| structlog | Structured logging throughout |
