# AP Power Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-driven AP power scheduling module that automatically disables AP radios during configured off-hours windows (per-site, timezone-aware) and re-enables them as clients appear, with real-time Mist WebSocket client tracking and full audit logging.

**Architecture:** New `power_scheduling` module with Beanie MongoDB models, an in-memory per-site state machine protected by asyncio locks, timezone-aware APScheduler cron jobs (reusing the existing `WorkflowScheduler` singleton), and a dedicated Mist clients WebSocket manager. Mist device profiles batch AP radio changes to minimise API call volume. Full structlog + MongoDB audit trail on every event.

**Tech Stack:** FastAPI, Beanie/MongoDB, APScheduler with `pytz`, `mistapi` WebSocket, structlog, Angular 21 + Angular Material.

**Spec:** `docs/superpowers/specs/2026-03-30-ap-power-scheduling-design.md`

---

## File Map

**Create (backend):**
- `backend/app/modules/power_scheduling/__init__.py`
- `backend/app/modules/power_scheduling/models.py`
- `backend/app/modules/power_scheduling/state.py`
- `backend/app/modules/power_scheduling/router.py`
- `backend/app/modules/power_scheduling/services/__init__.py`
- `backend/app/modules/power_scheduling/services/scheduling_service.py`
- `backend/app/modules/power_scheduling/services/rrm_service.py`
- `backend/app/modules/power_scheduling/services/client_ws_service.py`
- `backend/app/modules/power_scheduling/workers/__init__.py`
- `backend/app/modules/power_scheduling/workers/schedule_worker.py`
- `backend/tests/unit/test_power_scheduling/__init__.py`
- `backend/tests/unit/test_power_scheduling/test_rrm_service.py`
- `backend/tests/unit/test_power_scheduling/test_eligibility.py`
- `backend/tests/unit/test_power_scheduling/test_worker.py`
- `backend/tests/integration/test_power_scheduling_api.py`

**Create (frontend):**
- `frontend/src/app/features/power-scheduling/power-scheduling.routes.ts`
- `frontend/src/app/features/power-scheduling/power-scheduling.service.ts`
- `frontend/src/app/features/power-scheduling/list/power-scheduling-list.component.ts`
- `frontend/src/app/features/power-scheduling/list/power-scheduling-list.component.html`
- `frontend/src/app/features/power-scheduling/list/power-scheduling-list.component.scss`
- `frontend/src/app/features/power-scheduling/detail/power-scheduling-detail.component.ts`
- `frontend/src/app/features/power-scheduling/detail/power-scheduling-detail.component.html`
- `frontend/src/app/features/power-scheduling/detail/power-scheduling-detail.component.scss`

**Modify:**
- `backend/app/modules/__init__.py` — add `AppModule` entry
- `backend/app/main.py` — start client WS + startup recovery in lifespan
- `frontend/src/app/app.routes.ts` — add lazy route
- `frontend/src/app/layout/sidebar/nav-items.config.ts` — add nav entry

---

## Task 1: Data Models

**Files:**
- Create: `backend/app/modules/power_scheduling/models.py`
- Test: `backend/tests/unit/test_power_scheduling/test_models.py` (validation only, no DB)

- [ ] **Step 1: Write the test**

```python
# backend/tests/unit/test_power_scheduling/test_models.py
import pytest
from pydantic import ValidationError
from app.modules.power_scheduling.models import PowerSchedule, PowerScheduleLog, ScheduleWindow


class TestScheduleWindow:
    def test_valid_window(self):
        w = ScheduleWindow(days=[0, 1, 2, 3, 4], start="22:00", end="06:00")
        assert w.days == [0, 1, 2, 3, 4]
        assert w.start == "22:00"

    def test_invalid_day(self):
        with pytest.raises(ValidationError):
            ScheduleWindow(days=[7], start="22:00", end="06:00")

    def test_invalid_time_format(self):
        with pytest.raises(ValidationError):
            ScheduleWindow(days=[0], start="10pm", end="06:00")


class TestPowerSchedule:
    def test_defaults(self):
        s = PowerSchedule(
            site_id="abc", site_name="HQ", timezone="America/New_York",
            windows=[ScheduleWindow(days=[0, 1, 2, 3, 4], start="22:00", end="06:00")],
            off_profile_id="prof-123",
        )
        assert s.neighbor_rssi_threshold_dbm == -65
        assert s.grace_period_minutes == 5
        assert s.roam_rssi_threshold_dbm == -75
        assert s.enabled is True
        assert s.current_status == "IDLE"
        assert s.critical_ap_macs == []
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd backend && python -m pytest tests/unit/test_power_scheduling/test_models.py -v
```
Expected: `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Implement models**

```python
# backend/app/modules/power_scheduling/models.py
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import BaseModel, Field, field_validator
from pymongo import ASCENDING, IndexModel

from app.models.mixins import TimestampMixin

_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


class ScheduleWindow(BaseModel):
    days: list[int] = Field(..., description="0=Mon … 6=Sun")
    start: str = Field(..., description="HH:MM in site local time")
    end: str = Field(..., description="HH:MM in site local time")

    @field_validator("days")
    @classmethod
    def validate_days(cls, v: list[int]) -> list[int]:
        if not v or any(d < 0 or d > 6 for d in v):
            raise ValueError("days must be 0-6 (Mon-Sun)")
        return v

    @field_validator("start", "end")
    @classmethod
    def validate_time(cls, v: str) -> str:
        if not _TIME_RE.match(v):
            raise ValueError("time must be HH:MM")
        return v


class PowerSchedule(TimestampMixin, Document):
    site_id: str = Field(..., description="Mist site ID")
    site_name: str = Field(..., description="Human-readable site name")
    timezone: str = Field(..., description="IANA timezone, auto-fetched from Mist on create")
    windows: list[ScheduleWindow] = Field(..., description="Off-hours windows")
    off_profile_id: str = Field(..., description="Mist device profile ID with radios disabled")
    neighbor_rssi_threshold_dbm: int = Field(default=-65, description="Min RSSI to consider APs as RF neighbors")
    roam_rssi_threshold_dbm: int = Field(default=-75, description="Client RSSI below which pre-enable neighbors")
    grace_period_minutes: int = Field(default=5, description="Wait after AP empties before disabling")
    critical_ap_macs: list[str] = Field(default_factory=list, description="APs never disabled (v1; v2 uses wxtags)")
    enabled: bool = Field(default=True)
    current_status: Literal["IDLE", "OFF_HOURS"] = Field(default="IDLE", description="Persisted for startup recovery")
    last_transition_at: datetime | None = Field(default=None)

    class Settings:
        name = "power_schedules"
        indexes = [
            IndexModel([("site_id", ASCENDING)], unique=True, name="site_id_unique"),
        ]


class PowerScheduleLog(Document):
    site_id: str = Field(...)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: Literal[
        "WINDOW_START", "WINDOW_END",
        "CATCHUP_START", "CATCHUP_END",
        "AP_DISABLED", "AP_PENDING", "AP_ENABLED",
        "GRACE_TIMER_START", "GRACE_TIMER_EXPIRED",
        "CLIENT_DETECTED", "CLIENT_LEFT",
        "PROFILE_CREATED",
        "ERROR",
    ] = Field(...)
    ap_mac: str | None = Field(default=None)
    details: dict = Field(default_factory=dict)

    class Settings:
        name = "power_schedule_logs"
        indexes = [
            IndexModel([("site_id", ASCENDING), ("timestamp", ASCENDING)]),
        ]
```

- [ ] **Step 4: Run test — expect pass**

```bash
cd backend && python -m pytest tests/unit/test_power_scheduling/test_models.py -v
```
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/power_scheduling/models.py \
        backend/app/modules/power_scheduling/__init__.py \
        backend/app/modules/power_scheduling/services/__init__.py \
        backend/app/modules/power_scheduling/workers/__init__.py \
        backend/tests/unit/test_power_scheduling/__init__.py \
        backend/tests/unit/test_power_scheduling/test_models.py
git commit -m "feat(power-scheduling): add data models"
```

---

## Task 2: In-Memory State

**Files:**
- Create: `backend/app/modules/power_scheduling/state.py`
- Test: `backend/tests/unit/test_power_scheduling/test_state.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/unit/test_power_scheduling/test_state.py
import asyncio
import pytest
from app.modules.power_scheduling.state import get_state, clear_state, PowerScheduleState


class TestStateStore:
    @pytest.fixture(autouse=True)
    def cleanup(self):
        yield
        asyncio.get_event_loop().run_until_complete(clear_state("site-1"))

    def test_get_state_creates_idle(self):
        state = get_state("site-1")
        assert state.status == "IDLE"
        assert state.disabled_aps == {}
        assert state.pending_disable == set()
        assert state.client_map == {}

    def test_get_state_returns_same_instance(self):
        s1 = get_state("site-1")
        s2 = get_state("site-1")
        assert s1 is s2

    def test_separate_sites_have_separate_state(self):
        s1 = get_state("site-1")
        s2 = get_state("site-2")
        s1.status = "OFF_HOURS"
        assert s2.status == "IDLE"
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd backend && python -m pytest tests/unit/test_power_scheduling/test_state.py -v
```

- [ ] **Step 3: Implement state**

```python
# backend/app/modules/power_scheduling/state.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

_states: dict[str, "PowerScheduleState"] = {}
_locks: dict[str, asyncio.Lock] = {}


@dataclass
class PowerScheduleState:
    status: Literal["IDLE", "TRANSITIONING_OFF", "OFF_HOURS", "TRANSITIONING_ON"] = "IDLE"
    # {ap_mac: original_profile_id | None}
    disabled_aps: dict[str, str | None] = field(default_factory=dict)
    # APs with clients or whose neighbor has clients — not yet disabled
    pending_disable: set[str] = field(default_factory=set)
    # {ap_mac: {client_mac, ...}} — live from clients WS
    client_map: dict[str, set[str]] = field(default_factory=dict)
    # {ap_mac: asyncio.Task} — grace timer tasks per AP
    grace_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    # {ap_mac: [(neighbor_mac, rssi_dbm)]} — cached at window start
    rf_neighbor_map: dict[str, list[tuple[str, int]]] = field(default_factory=dict)


def get_state(site_id: str) -> PowerScheduleState:
    """Get or create in-memory state for a site."""
    if site_id not in _states:
        _states[site_id] = PowerScheduleState()
        _locks[site_id] = asyncio.Lock()
    return _states[site_id]


def get_lock(site_id: str) -> asyncio.Lock:
    """Get the asyncio lock for a site (call get_state first)."""
    if site_id not in _locks:
        _locks[site_id] = asyncio.Lock()
    return _locks[site_id]


async def clear_state(site_id: str) -> None:
    """Cancel grace tasks and remove state for a site."""
    state = _states.pop(site_id, None)
    _locks.pop(site_id, None)
    if state:
        for task in state.grace_tasks.values():
            task.cancel()
```

- [ ] **Step 4: Run test — expect pass**

```bash
cd backend && python -m pytest tests/unit/test_power_scheduling/test_state.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/power_scheduling/state.py \
        backend/tests/unit/test_power_scheduling/test_state.py
git commit -m "feat(power-scheduling): add in-memory state store"
```

---

## Task 3: RRM Service

**Files:**
- Create: `backend/app/modules/power_scheduling/services/rrm_service.py`
- Test: `backend/tests/unit/test_power_scheduling/test_rrm_service.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/unit/test_power_scheduling/test_rrm_service.py
import pytest
from unittest.mock import AsyncMock, patch
from app.modules.power_scheduling.services.rrm_service import merge_rrm_responses, fetch_rf_neighbor_map


class TestMergeRrmResponses:
    def test_merge_best_rssi_across_bands(self):
        band5 = {"results": [{"mac": "aa", "neighbors": [{"mac": "bb", "rssi": -60.0}]}]}
        band24 = {"results": [{"mac": "aa", "neighbors": [{"mac": "bb", "rssi": -55.0}]}]}
        result = merge_rrm_responses([band5, band24])
        # Should keep best (highest) RSSI: -55
        assert result["aa"] == [("bb", -55)]

    def test_merge_multiple_neighbors(self):
        band5 = {"results": [
            {"mac": "aa", "neighbors": [{"mac": "bb", "rssi": -49.0}, {"mac": "cc", "rssi": -66.0}]},
        ]}
        result = merge_rrm_responses([band5])
        assert ("bb", -49) in result["aa"]
        assert ("cc", -66) in result["aa"]

    def test_missing_results_key(self):
        result = merge_rrm_responses([{}])
        assert result == {}

    def test_empty_neighbors(self):
        band5 = {"results": [{"mac": "aa", "neighbors": []}]}
        result = merge_rrm_responses([band5])
        assert result == {"aa": []}


class TestFetchRfNeighborMap:
    @pytest.mark.asyncio
    async def test_calls_all_three_bands(self):
        mock_mist = AsyncMock()
        mock_mist.get = AsyncMock(return_value={"results": []})
        with patch("app.modules.power_scheduling.services.rrm_service.create_mist_service",
                   return_value=mock_mist):
            await fetch_rf_neighbor_map("site-1")
        assert mock_mist.get.call_count == 3
        calls = [c.args[0] for c in mock_mist.get.call_args_list]
        assert any("24" in c for c in calls)
        assert any("/5" in c for c in calls)
        assert any("/6" in c for c in calls)
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd backend && python -m pytest tests/unit/test_power_scheduling/test_rrm_service.py -v
```

- [ ] **Step 3: Implement**

```python
# backend/app/modules/power_scheduling/services/rrm_service.py
from __future__ import annotations

import structlog
from app.services.mist_service_factory import create_mist_service

log = structlog.get_logger(__name__)


def merge_rrm_responses(responses: list[dict]) -> dict[str, list[tuple[str, int]]]:
    """Merge RRM neighbor results across bands, keeping best (highest) RSSI per pair."""
    best: dict[str, dict[str, int]] = {}
    for response in responses:
        for entry in response.get("results", []):
            ap_mac: str = entry["mac"]
            for nbr in entry.get("neighbors", []):
                nbr_mac: str = nbr["mac"]
                rssi: int = int(nbr["rssi"])
                ap_best = best.setdefault(ap_mac, {})
                ap_best[nbr_mac] = max(ap_best.get(nbr_mac, -999), rssi)
    return {ap: list(nbrs.items()) for ap, nbrs in best.items()}


async def fetch_rf_neighbor_map(site_id: str) -> dict[str, list[tuple[str, int]]]:
    """Fetch RF neighbor map from Mist RRM API, merged across 2.4/5/6 GHz bands."""
    mist = await create_mist_service()
    responses = []
    for band in ("24", "5", "6"):
        try:
            data = await mist.get(f"/api/v1/sites/{site_id}/rrm/neighbors/band/{band}")
            responses.append(data)
        except Exception as exc:
            log.warning("rrm_band_fetch_failed", site_id=site_id, band=band, error=str(exc))
    return merge_rrm_responses(responses)
```

- [ ] **Step 4: Run test — expect pass**

```bash
cd backend && python -m pytest tests/unit/test_power_scheduling/test_rrm_service.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/power_scheduling/services/rrm_service.py \
        backend/tests/unit/test_power_scheduling/test_rrm_service.py
git commit -m "feat(power-scheduling): add RRM neighbor service"
```

---

## Task 4: Eligibility Check + Startup Recovery Utility

**Files:**
- Create: `backend/app/modules/power_scheduling/services/eligibility.py`
- Test: `backend/tests/unit/test_power_scheduling/test_eligibility.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/unit/test_power_scheduling/test_eligibility.py
from datetime import datetime, timezone
import pytest
import pytz
from app.modules.power_scheduling.services.eligibility import can_disable, compute_expected_status
from app.modules.power_scheduling.models import PowerSchedule, ScheduleWindow
from app.modules.power_scheduling.state import PowerScheduleState


def _make_schedule(**kwargs) -> PowerSchedule:
    defaults = dict(
        site_id="s1", site_name="HQ", timezone="UTC", off_profile_id="p1",
        windows=[ScheduleWindow(days=[0, 1, 2, 3, 4], start="22:00", end="06:00")],
    )
    defaults.update(kwargs)
    return PowerSchedule.model_construct(**defaults)


def _make_state(**kwargs) -> PowerScheduleState:
    s = PowerScheduleState()
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


class TestCanDisable:
    def test_empty_ap_no_neighbors_can_disable(self):
        state = _make_state(client_map={}, rf_neighbor_map={"ap1": [("ap2", -70)]})
        schedule = _make_schedule(neighbor_rssi_threshold_dbm=-65)
        # neighbor rssi -70 < -65 threshold, so neighbor is NOT considered close
        assert can_disable("ap1", state, schedule) is True

    def test_ap_with_clients_cannot_disable(self):
        state = _make_state(client_map={"ap1": {"client-mac"}}, rf_neighbor_map={})
        assert can_disable("ap1", state, _make_schedule()) is False

    def test_critical_ap_cannot_disable(self):
        state = _make_state(client_map={}, rf_neighbor_map={})
        schedule = _make_schedule(critical_ap_macs=["ap1"])
        assert can_disable("ap1", state, schedule) is False

    def test_neighbor_with_clients_blocks_disable(self):
        state = _make_state(
            client_map={"ap2": {"client-mac"}},
            rf_neighbor_map={"ap1": [("ap2", -50)]},  # strong signal — within threshold
        )
        schedule = _make_schedule(neighbor_rssi_threshold_dbm=-65)
        assert can_disable("ap1", state, schedule) is False

    def test_neighbor_below_threshold_does_not_block(self):
        state = _make_state(
            client_map={"ap2": {"client-mac"}},
            rf_neighbor_map={"ap1": [("ap2", -80)]},  # weak signal — outside threshold
        )
        schedule = _make_schedule(neighbor_rssi_threshold_dbm=-65)
        assert can_disable("ap1", state, schedule) is True


class TestComputeExpectedStatus:
    def test_inside_window_returns_off_hours(self):
        schedule = _make_schedule(
            timezone="UTC",
            windows=[ScheduleWindow(days=[0,1,2,3,4,5,6], start="22:00", end="06:00")],
        )
        # Monday 23:00 UTC — inside window
        now = datetime(2026, 3, 30, 23, 0, tzinfo=timezone.utc)  # Monday
        assert compute_expected_status(schedule, now) == "OFF_HOURS"

    def test_outside_window_returns_idle(self):
        schedule = _make_schedule(
            timezone="UTC",
            windows=[ScheduleWindow(days=[0,1,2,3,4,5,6], start="22:00", end="06:00")],
        )
        # Monday 14:00 UTC — outside window
        now = datetime(2026, 3, 30, 14, 0, tzinfo=timezone.utc)
        assert compute_expected_status(schedule, now) == "IDLE"

    def test_after_midnight_inside_window(self):
        schedule = _make_schedule(
            timezone="UTC",
            windows=[ScheduleWindow(days=[0,1,2,3,4,5,6], start="22:00", end="06:00")],
        )
        # Tuesday 02:00 UTC — inside the Mon→Tue crossing window
        now = datetime(2026, 3, 31, 2, 0, tzinfo=timezone.utc)
        assert compute_expected_status(schedule, now) == "OFF_HOURS"

    def test_wrong_day_returns_idle(self):
        schedule = _make_schedule(
            timezone="UTC",
            windows=[ScheduleWindow(days=[0,1,2,3,4], start="22:00", end="06:00")],  # weekdays
        )
        # Saturday 23:00 UTC
        now = datetime(2026, 4, 4, 23, 0, tzinfo=timezone.utc)  # Saturday
        assert compute_expected_status(schedule, now) == "IDLE"
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd backend && python -m pytest tests/unit/test_power_scheduling/test_eligibility.py -v
```

- [ ] **Step 3: Implement**

```python
# backend/app/modules/power_scheduling/services/eligibility.py
from __future__ import annotations

from datetime import datetime, time

import pytz

from app.modules.power_scheduling.models import PowerSchedule, ScheduleWindow
from app.modules.power_scheduling.state import PowerScheduleState


def can_disable(ap_mac: str, state: PowerScheduleState, schedule: PowerSchedule) -> bool:
    """Return True if AP is eligible to be disabled now."""
    if ap_mac in schedule.critical_ap_macs:
        return False
    if state.client_map.get(ap_mac):
        return False
    for neighbor_mac, rssi in state.rf_neighbor_map.get(ap_mac, []):
        if rssi > schedule.neighbor_rssi_threshold_dbm:
            if state.client_map.get(neighbor_mac):
                return False
    return True


def _time_in_window(now_time: time, start: time, end: time) -> bool:
    """Check if now_time falls in [start, end) handling midnight crossings."""
    if start <= end:
        return start <= now_time < end
    # Crosses midnight: e.g. 22:00 → 06:00
    return now_time >= start or now_time < end


def compute_expected_status(schedule: PowerSchedule, now_utc: datetime) -> str:
    """Return 'OFF_HOURS' if now falls inside any window, else 'IDLE'."""
    tz = pytz.timezone(schedule.timezone)
    now_local = now_utc.astimezone(tz)
    now_time = now_local.time()
    now_weekday = now_local.weekday()  # 0=Mon, 6=Sun

    for window in schedule.windows:
        start = time(*map(int, window.start.split(":")))
        end = time(*map(int, window.end.split(":")))

        # For midnight-crossing windows, yesterday's start day is also relevant
        crosses_midnight = start > end
        active_days = set(window.days)
        if crosses_midnight:
            # After midnight: the "active" day is the day the window started (yesterday)
            yesterday = (now_weekday - 1) % 7
            if (now_weekday in active_days and now_time < end) or \
               (yesterday in active_days and now_time >= start):
                return "OFF_HOURS"
        else:
            if now_weekday in active_days and _time_in_window(now_time, start, end):
                return "OFF_HOURS"

    return "IDLE"
```

- [ ] **Step 4: Run test — expect pass**

```bash
cd backend && python -m pytest tests/unit/test_power_scheduling/test_eligibility.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/power_scheduling/services/eligibility.py \
        backend/tests/unit/test_power_scheduling/test_eligibility.py
git commit -m "feat(power-scheduling): add eligibility check and startup recovery utility"
```

---

## Task 5: Client Stats WebSocket Service

**Files:**
- Create: `backend/app/modules/power_scheduling/services/client_ws_service.py`

Note: The `mistapi` library uses `DeviceStatsEvents` for `/sites/{id}/stats/devices`. For client stats, check `mistapi.websockets.sites` for the equivalent class (likely `ClientsStatsEvents`). If not available, use `mistapi.websockets.SiteEvents` with an event filter. The pattern is identical to `MistWsManager` — see `backend/app/modules/telemetry/services/mist_ws_manager.py`.

- [ ] **Step 1: Implement**

```python
# backend/app/modules/power_scheduling/services/client_ws_service.py
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

import structlog

log = structlog.get_logger(__name__)

# Callback signature: (site_id: str, event_type: "join"|"leave"|"update", client_mac: str, ap_mac: str, rssi: int | None)
ClientEventCallback = Callable[[str, str, str, str, int | None], None]


class ClientStatsWsManager:
    """
    Subscribes to /sites/{site_id}/stats/clients via Mist WebSocket.

    Uses the same thread-bridge pattern as MistWsManager:
    the mistapi WS runs in a background thread and posts events
    to the asyncio event loop via call_soon_threadsafe().

    Find the correct mistapi class for client stats in:
        mistapi.websockets.sites  (look for ClientsStatsEvents or similar)
    If not available, use the generic WebSocket approach with channel filtering.
    """

    def __init__(self, api_session: Any, on_event: ClientEventCallback) -> None:
        self._api_session = api_session
        self._on_event = on_event
        self._connections: list[Any] = []
        self._subscribed_sites: list[str] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._prev_snapshots: dict[str, dict[str, str]] = {}  # {site_id: {client_mac: ap_mac}}

    async def start(self, site_ids: list[str]) -> None:
        self._loop = asyncio.get_running_loop()
        self._subscribed_sites = list(site_ids)
        for site_id in site_ids:
            await self._subscribe_site(site_id)

    async def add_site(self, site_id: str) -> None:
        if site_id not in self._subscribed_sites:
            self._subscribed_sites.append(site_id)
            await self._subscribe_site(site_id)

    async def remove_site(self, site_id: str) -> None:
        # Reconnect without this site
        self._subscribed_sites = [s for s in self._subscribed_sites if s != site_id]
        self._prev_snapshots.pop(site_id, None)
        await self.stop()
        if self._subscribed_sites:
            await self.start(self._subscribed_sites)

    async def stop(self) -> None:
        for conn in self._connections:
            try:
                conn.disconnect()
            except Exception:
                pass
        self._connections.clear()

    async def _subscribe_site(self, site_id: str) -> None:
        """
        Subscribe to client stats for a single site.

        TODO: Replace Any with the actual mistapi client WS class.
        Check `mistapi.websockets.sites` for `ClientsStatsEvents` or equivalent.
        Pattern mirrors MistWsManager._subscribe_site() using DeviceStatsEvents.
        """
        try:
            # REPLACE with actual mistapi import and class:
            # from mistapi.websockets.sites import ClientsStatsEvents
            # ws = ClientsStatsEvents(
            #     mist_session=self._api_session,
            #     site_ids=[site_id],
            #     auto_reconnect=True,
            # )
            # ws.on_message(lambda msg: self._bridge(site_id, msg))
            # ws.connect(run_in_background=True)
            # self._connections.append(ws)
            log.info("client_ws_subscribed", site_id=site_id)
        except Exception as exc:
            log.error("client_ws_subscribe_failed", site_id=site_id, error=str(exc))

    def _bridge(self, site_id: str, msg: dict[str, Any]) -> None:
        """Thread-safe bridge from WS thread to asyncio loop."""
        if self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._process, site_id, msg)
        except RuntimeError:
            pass

    def _process(self, site_id: str, msg: dict[str, Any]) -> None:
        """
        Process a Mist clients stats WS message.

        Mist sends a snapshot of currently connected clients per site.
        Each client object has at minimum: mac, ap_mac, rssi, connected (bool).
        Verify exact field names against live WS or Mist API documentation.
        Detect joins/leaves by comparing against previous snapshot.
        """
        if msg.get("event") != "data":
            return

        clients: list[dict] = msg.get("data", [])
        # Build current snapshot: {client_mac: ap_mac} for connected clients
        current: dict[str, str] = {
            c["mac"]: c["ap_mac"]
            for c in clients
            if c.get("connected", True) and c.get("mac") and c.get("ap_mac")
        }
        prev = self._prev_snapshots.get(site_id, {})

        # Detect joins
        for client_mac, ap_mac in current.items():
            if client_mac not in prev:
                rssi = next((c.get("rssi") for c in clients if c.get("mac") == client_mac), None)
                self._on_event(site_id, "join", client_mac, ap_mac, rssi)
            elif prev[client_mac] != ap_mac:
                # Roamed: leave old AP, join new AP
                self._on_event(site_id, "leave", client_mac, prev[client_mac], None)
                rssi = next((c.get("rssi") for c in clients if c.get("mac") == client_mac), None)
                self._on_event(site_id, "join", client_mac, ap_mac, rssi)

        # Detect leaves
        for client_mac, ap_mac in prev.items():
            if client_mac not in current:
                self._on_event(site_id, "leave", client_mac, ap_mac, None)

        # RSSI updates for connected clients (for roam pre-enable)
        for c in clients:
            if c.get("connected") and c.get("rssi") is not None:
                self._on_event(site_id, "update", c["mac"], c.get("ap_mac", ""), c["rssi"])

        self._prev_snapshots[site_id] = current
```

- [ ] **Step 2: Verify no import errors**

```bash
cd backend && python -c "from app.modules.power_scheduling.services.client_ws_service import ClientStatsWsManager; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/modules/power_scheduling/services/client_ws_service.py
git commit -m "feat(power-scheduling): add client stats WebSocket service"
```

---

## Task 6: Scheduling Service — Core Transitions

**Files:**
- Create: `backend/app/modules/power_scheduling/services/scheduling_service.py`
- Test: `backend/tests/unit/test_power_scheduling/test_scheduling_service.py`

- [ ] **Step 1: Write tests for start_off_hours**

```python
# backend/tests/unit/test_power_scheduling/test_scheduling_service.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.modules.power_scheduling.models import PowerSchedule, ScheduleWindow
from app.modules.power_scheduling.state import get_state, clear_state, PowerScheduleState
from app.modules.power_scheduling.services.scheduling_service import start_off_hours, end_off_hours


def _make_schedule(site_id="s1", critical_ap_macs=None, **kwargs):
    return PowerSchedule.model_construct(
        site_id=site_id,
        site_name="HQ",
        timezone="UTC",
        off_profile_id="off-prof",
        neighbor_rssi_threshold_dbm=-65,
        roam_rssi_threshold_dbm=-75,
        grace_period_minutes=5,
        critical_ap_macs=critical_ap_macs or [],
        windows=[ScheduleWindow(days=list(range(7)), start="22:00", end="06:00")],
        **kwargs,
    )


class TestStartOffHours:
    @pytest.fixture(autouse=True)
    def cleanup(self):
        yield
        asyncio.get_event_loop().run_until_complete(clear_state("s1"))

    @pytest.mark.asyncio
    async def test_zero_client_ap_gets_disabled(self):
        schedule = _make_schedule()
        ap_inventory = [{"mac": "ap1", "deviceprofile_id": None}]
        rf_neighbors = {}
        client_map = {}

        with patch("app.modules.power_scheduling.services.scheduling_service.fetch_rf_neighbor_map",
                   return_value=rf_neighbors), \
             patch("app.modules.power_scheduling.services.scheduling_service._get_ap_inventory",
                   return_value=ap_inventory), \
             patch("app.modules.power_scheduling.services.scheduling_service._assign_profile",
                   new_callable=AsyncMock) as mock_assign, \
             patch("app.modules.power_scheduling.services.scheduling_service._log_event",
                   new_callable=AsyncMock):
            state = get_state("s1")
            state.client_map = client_map
            await start_off_hours(schedule)

        assert "ap1" in state.disabled_aps
        mock_assign.assert_awaited_once_with("s1", "ap1", "off-prof")

    @pytest.mark.asyncio
    async def test_ap_with_clients_goes_to_pending(self):
        schedule = _make_schedule()
        ap_inventory = [{"mac": "ap1", "deviceprofile_id": None}]

        with patch("app.modules.power_scheduling.services.scheduling_service.fetch_rf_neighbor_map",
                   return_value={}), \
             patch("app.modules.power_scheduling.services.scheduling_service._get_ap_inventory",
                   return_value=ap_inventory), \
             patch("app.modules.power_scheduling.services.scheduling_service._assign_profile",
                   new_callable=AsyncMock), \
             patch("app.modules.power_scheduling.services.scheduling_service._log_event",
                   new_callable=AsyncMock):
            state = get_state("s1")
            state.client_map = {"ap1": {"client-mac"}}
            await start_off_hours(schedule)

        assert "ap1" in state.pending_disable
        assert "ap1" not in state.disabled_aps

    @pytest.mark.asyncio
    async def test_state_becomes_off_hours(self):
        schedule = _make_schedule()
        with patch("app.modules.power_scheduling.services.scheduling_service.fetch_rf_neighbor_map",
                   return_value={}), \
             patch("app.modules.power_scheduling.services.scheduling_service._get_ap_inventory",
                   return_value=[]), \
             patch("app.modules.power_scheduling.services.scheduling_service._log_event",
                   new_callable=AsyncMock):
            state = get_state("s1")
            await start_off_hours(schedule)

        assert state.status == "OFF_HOURS"
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd backend && python -m pytest tests/unit/test_power_scheduling/test_scheduling_service.py -v
```

- [ ] **Step 3: Implement scheduling service**

```python
# backend/app/modules/power_scheduling/services/scheduling_service.py
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog

from app.core.tasks import create_background_task
from app.modules.power_scheduling.models import PowerSchedule, PowerScheduleLog
from app.modules.power_scheduling.services.eligibility import can_disable
from app.modules.power_scheduling.services.rrm_service import fetch_rf_neighbor_map
from app.modules.power_scheduling.state import PowerScheduleState, get_lock, get_state
from app.services.mist_service_factory import create_mist_service

log = structlog.get_logger(__name__).bind(module="power_scheduling")


# ---------------------------------------------------------------------------
# Mist API helpers
# ---------------------------------------------------------------------------

async def _get_ap_inventory(site_id: str) -> list[dict[str, Any]]:
    """Return list of AP dicts with at least 'mac' and 'deviceprofile_id'."""
    mist = await create_mist_service()
    data = await mist.get(f"/api/v1/sites/{site_id}/devices?type=ap")
    return data.get("results", [])


async def _assign_profile(site_id: str, ap_mac: str, profile_id: str | None) -> None:
    """Set or clear the device profile on an AP."""
    mist = await create_mist_service()
    body: dict[str, Any] = {"deviceprofile_id": profile_id}
    await mist.put(f"/api/v1/sites/{site_id}/devices/{ap_mac}", body)


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

async def _log_event(
    site_id: str,
    event_type: str,
    ap_mac: str | None = None,
    **details: Any,
) -> None:
    entry = PowerScheduleLog(site_id=site_id, event_type=event_type, ap_mac=ap_mac, details=details)
    await entry.insert()
    log.info(event_type.lower(), site_id=site_id, ap_mac=ap_mac, **details)


# ---------------------------------------------------------------------------
# Main transitions
# ---------------------------------------------------------------------------

async def start_off_hours(schedule: PowerSchedule) -> None:
    """TRANSITIONING_OFF → OFF_HOURS: disable eligible APs, add rest to pending."""
    site_id = schedule.site_id
    state = get_state(site_id)

    async with get_lock(site_id):
        state.status = "TRANSITIONING_OFF"

    await _log_event(site_id, "WINDOW_START")

    # Fetch RF neighbors and AP inventory
    rf_map = await fetch_rf_neighbor_map(site_id)
    ap_inventory = await _get_ap_inventory(site_id)

    async with get_lock(site_id):
        state.rf_neighbor_map = rf_map
        state.pending_disable.clear()
        state.disabled_aps.clear()

    for ap in ap_inventory:
        ap_mac: str = ap["mac"]
        original_profile: str | None = ap.get("deviceprofile_id")

        async with get_lock(site_id):
            eligible = can_disable(ap_mac, state, schedule)

        if eligible:
            try:
                await _assign_profile(site_id, ap_mac, schedule.off_profile_id)
                async with get_lock(site_id):
                    state.disabled_aps[ap_mac] = original_profile
                await _log_event(site_id, "AP_DISABLED", ap_mac=ap_mac, original_profile=original_profile)
            except Exception as exc:
                await _log_event(site_id, "ERROR", ap_mac=ap_mac, error=str(exc), action="disable")
        else:
            async with get_lock(site_id):
                state.pending_disable.add(ap_mac)
            reason = "has_clients" if state.client_map.get(ap_mac) else "neighbor_has_clients"
            await _log_event(site_id, "AP_PENDING", ap_mac=ap_mac, reason=reason)

    async with get_lock(site_id):
        state.status = "OFF_HOURS"

    # Persist status
    await PowerSchedule.find_one(PowerSchedule.site_id == site_id).update(
        {"$set": {"current_status": "OFF_HOURS", "last_transition_at": datetime.now(timezone.utc)}}
    )


async def end_off_hours(schedule: PowerSchedule) -> None:
    """TRANSITIONING_ON → IDLE: restore all disabled APs."""
    site_id = schedule.site_id
    state = get_state(site_id)

    async with get_lock(site_id):
        state.status = "TRANSITIONING_ON"
        disabled = dict(state.disabled_aps)
        # Cancel any pending grace timers
        for task in state.grace_tasks.values():
            task.cancel()
        state.grace_tasks.clear()
        state.pending_disable.clear()

    for ap_mac, original_profile in disabled.items():
        try:
            await _assign_profile(site_id, ap_mac, original_profile)
            await _log_event(site_id, "AP_ENABLED", ap_mac=ap_mac, reason="window_end", original_profile=original_profile)
        except Exception as exc:
            await _log_event(site_id, "ERROR", ap_mac=ap_mac, error=str(exc), action="re-enable")

    async with get_lock(site_id):
        state.disabled_aps.clear()
        state.status = "IDLE"

    await _log_event(site_id, "WINDOW_END")
    await PowerSchedule.find_one(PowerSchedule.site_id == site_id).update(
        {"$set": {"current_status": "IDLE", "last_transition_at": datetime.now(timezone.utc)}}
    )


async def end_off_hours_catchup(schedule: PowerSchedule) -> None:
    """
    Startup recovery: in-memory state lost on restart.
    Query Mist API for APs currently assigned the off_profile_id and restore them.
    """
    site_id = schedule.site_id
    await _log_event(site_id, "CATCHUP_START", direction="on")

    ap_inventory = await _get_ap_inventory(site_id)
    for ap in ap_inventory:
        if ap.get("deviceprofile_id") == schedule.off_profile_id:
            try:
                await _assign_profile(site_id, ap["mac"], None)  # restore to site default
                await _log_event(site_id, "AP_ENABLED", ap_mac=ap["mac"], reason="catchup")
            except Exception as exc:
                await _log_event(site_id, "ERROR", ap_mac=ap["mac"], error=str(exc), action="catchup_re-enable")

    await PowerSchedule.find_one(PowerSchedule.site_id == site_id).update(
        {"$set": {"current_status": "IDLE", "last_transition_at": datetime.now(timezone.utc)}}
    )
    await _log_event(site_id, "CATCHUP_END", direction="on")


# ---------------------------------------------------------------------------
# OFF_HOURS event handlers
# ---------------------------------------------------------------------------

async def on_client_event(
    site_id: str,
    event_type: str,
    client_mac: str,
    ap_mac: str,
    rssi: int | None,
    schedule: PowerSchedule,
) -> None:
    """Handle client WS events during OFF_HOURS."""
    state = get_state(site_id)

    async with get_lock(site_id):
        if state.status != "OFF_HOURS":
            return

    if event_type == "join":
        await _handle_client_join(site_id, ap_mac, client_mac, state, schedule)
    elif event_type == "leave":
        await _handle_client_leave(site_id, ap_mac, client_mac, state, schedule)
    elif event_type == "update" and rssi is not None:
        await _handle_rssi_update(site_id, ap_mac, client_mac, rssi, state, schedule)


async def _handle_client_join(
    site_id: str,
    ap_mac: str,
    client_mac: str,
    state: PowerScheduleState,
    schedule: PowerSchedule,
) -> None:
    async with get_lock(site_id):
        state.client_map.setdefault(ap_mac, set()).add(client_mac)
        # Cancel grace timer if running
        if ap_mac in state.grace_tasks:
            state.grace_tasks.pop(ap_mac).cancel()

    await _log_event(site_id, "CLIENT_DETECTED", ap_mac=ap_mac, client_mac=client_mac)

    # Re-enable AP if it was disabled
    async with get_lock(site_id):
        was_disabled = ap_mac in state.disabled_aps
        original = state.disabled_aps.pop(ap_mac, None)

    if was_disabled:
        try:
            await _assign_profile(site_id, ap_mac, original)
            await _log_event(site_id, "AP_ENABLED", ap_mac=ap_mac, reason="client_arrived", client_mac=client_mac)
        except Exception as exc:
            await _log_event(site_id, "ERROR", ap_mac=ap_mac, error=str(exc), action="re-enable_on_client")

    # Enable RF-close disabled neighbors
    async with get_lock(site_id):
        neighbors = state.rf_neighbor_map.get(ap_mac, [])
        to_enable = [
            (nbr_mac, state.disabled_aps.pop(nbr_mac, None))
            for nbr_mac, rssi in neighbors
            if rssi > schedule.neighbor_rssi_threshold_dbm and nbr_mac in state.disabled_aps
        ]

    for nbr_mac, orig_prof in to_enable:
        try:
            await _assign_profile(site_id, nbr_mac, orig_prof)
            await _log_event(site_id, "AP_ENABLED", ap_mac=nbr_mac, reason="neighbor_coverage", triggering_ap=ap_mac)
        except Exception as exc:
            await _log_event(site_id, "ERROR", ap_mac=nbr_mac, error=str(exc), action="re-enable_neighbor")

    # Re-evaluate pending_disable APs now that client_map changed
    await _reevaluate_pending(site_id, state, schedule)


async def _handle_client_leave(
    site_id: str,
    ap_mac: str,
    client_mac: str,
    state: PowerScheduleState,
    schedule: PowerSchedule,
) -> None:
    async with get_lock(site_id):
        ap_clients = state.client_map.get(ap_mac, set())
        ap_clients.discard(client_mac)
        if not ap_clients:
            state.client_map.pop(ap_mac, None)
        is_now_empty = not bool(ap_clients)

    await _log_event(site_id, "CLIENT_LEFT", ap_mac=ap_mac, client_mac=client_mac)

    if is_now_empty and ap_mac in state.pending_disable:
        # Start grace timer
        await _log_event(site_id, "GRACE_TIMER_START", ap_mac=ap_mac, grace_minutes=schedule.grace_period_minutes)
        task = create_background_task(
            _grace_timer(site_id, ap_mac, schedule),
            name=f"grace-{site_id}-{ap_mac}",
        )
        async with get_lock(site_id):
            state.grace_tasks[ap_mac] = task

    await _reevaluate_pending(site_id, state, schedule)


async def _grace_timer(site_id: str, ap_mac: str, schedule: PowerSchedule) -> None:
    """Wait grace period, then disable AP if still empty and eligible."""
    await asyncio.sleep(schedule.grace_period_minutes * 60)
    state = get_state(site_id)
    async with get_lock(site_id):
        state.grace_tasks.pop(ap_mac, None)
        if ap_mac not in state.pending_disable:
            return
        if not can_disable(ap_mac, state, schedule):
            return
        original = next(
            (ap.get("deviceprofile_id") for ap in [] if ap.get("mac") == ap_mac),
            None,
        )
    try:
        # Fetch original profile at disable time
        mist = await create_mist_service()
        ap_data = await mist.get(f"/api/v1/sites/{site_id}/devices/{ap_mac}")
        original = ap_data.get("deviceprofile_id")
        await _assign_profile(site_id, ap_mac, schedule.off_profile_id)
        async with get_lock(site_id):
            state.pending_disable.discard(ap_mac)
            state.disabled_aps[ap_mac] = original
        await _log_event(site_id, "GRACE_TIMER_EXPIRED", ap_mac=ap_mac)
        await _log_event(site_id, "AP_DISABLED", ap_mac=ap_mac, reason="grace_expired", original_profile=original)
    except Exception as exc:
        await _log_event(site_id, "ERROR", ap_mac=ap_mac, error=str(exc), action="grace_disable")


async def _handle_rssi_update(
    site_id: str,
    ap_mac: str,
    client_mac: str,
    rssi: int,
    state: PowerScheduleState,
    schedule: PowerSchedule,
) -> None:
    """Pre-enable disabled neighbors when client RSSI is degrading."""
    if rssi >= schedule.roam_rssi_threshold_dbm:
        return

    async with get_lock(site_id):
        neighbors = state.rf_neighbor_map.get(ap_mac, [])
        to_enable = [
            (nbr_mac, state.disabled_aps.pop(nbr_mac, None))
            for nbr_mac, nbr_rssi in neighbors
            if nbr_rssi > schedule.neighbor_rssi_threshold_dbm and nbr_mac in state.disabled_aps
        ]

    for nbr_mac, orig_prof in to_enable:
        try:
            await _assign_profile(site_id, nbr_mac, orig_prof)
            await _log_event(
                site_id, "AP_ENABLED", ap_mac=nbr_mac,
                reason="rssi_pre_enable", client_mac=client_mac,
                current_ap=ap_mac, rssi=rssi,
            )
        except Exception as exc:
            await _log_event(site_id, "ERROR", ap_mac=nbr_mac, error=str(exc), action="rssi_pre_enable")


async def _reevaluate_pending(
    site_id: str, state: PowerScheduleState, schedule: PowerSchedule
) -> None:
    """Check if any pending_disable AP is now eligible after a client_map change."""
    async with get_lock(site_id):
        now_eligible = [ap for ap in state.pending_disable if can_disable(ap, state, schedule)]

    for ap_mac in now_eligible:
        await _log_event(site_id, "GRACE_TIMER_START", ap_mac=ap_mac, grace_minutes=schedule.grace_period_minutes)
        task = create_background_task(
            _grace_timer(site_id, ap_mac, schedule),
            name=f"grace-{site_id}-{ap_mac}",
        )
        async with get_lock(site_id):
            state.grace_tasks[ap_mac] = task
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd backend && python -m pytest tests/unit/test_power_scheduling/test_scheduling_service.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/power_scheduling/services/scheduling_service.py \
        backend/tests/unit/test_power_scheduling/test_scheduling_service.py
git commit -m "feat(power-scheduling): add scheduling service (state machine + event handlers)"
```

---

## Task 7: APScheduler Worker + Startup Recovery

**Files:**
- Create: `backend/app/modules/power_scheduling/workers/schedule_worker.py`
- Test: `backend/tests/unit/test_power_scheduling/test_worker.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/unit/test_power_scheduling/test_worker.py
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.modules.power_scheduling.models import PowerSchedule, ScheduleWindow
from app.modules.power_scheduling.workers.schedule_worker import (
    register_schedule_jobs,
    deregister_schedule_jobs,
    run_startup_recovery,
)


def _make_schedule(site_id="s1", current_status="IDLE", timezone="UTC"):
    return PowerSchedule.model_construct(
        id="507f1f77bcf86cd799439011",
        site_id=site_id,
        site_name="HQ",
        timezone=timezone,
        off_profile_id="p1",
        windows=[ScheduleWindow(days=list(range(7)), start="22:00", end="06:00")],
        current_status=current_status,
        last_transition_at=None,
        enabled=True,
    )


class TestRegisterJobs:
    def test_adds_two_jobs_per_window(self):
        mock_scheduler = MagicMock()
        schedule = _make_schedule()
        register_schedule_jobs(schedule, mock_scheduler)
        # 1 window × 2 jobs (off + on)
        assert mock_scheduler.add_job.call_count == 2

    def test_job_ids_are_namespaced(self):
        mock_scheduler = MagicMock()
        register_schedule_jobs(_make_schedule(site_id="xyz"), mock_scheduler)
        job_ids = [c.kwargs["id"] for c in mock_scheduler.add_job.call_args_list]
        assert all("xyz" in jid for jid in job_ids)

    def test_deregister_removes_jobs(self):
        mock_scheduler = MagicMock()
        mock_scheduler.get_job.return_value = MagicMock()
        deregister_schedule_jobs("s1", mock_scheduler)
        mock_scheduler.remove_job.assert_called()


class TestStartupRecovery:
    @pytest.mark.asyncio
    async def test_missed_off_triggers_start(self):
        schedule = _make_schedule(current_status="IDLE")
        # now is inside the window (23:00 UTC Monday)
        now = datetime(2026, 3, 30, 23, 0, tzinfo=timezone.utc)
        with patch("app.modules.power_scheduling.workers.schedule_worker.start_off_hours",
                   new_callable=AsyncMock) as mock_start, \
             patch("app.modules.power_scheduling.workers.schedule_worker.end_off_hours_catchup",
                   new_callable=AsyncMock):
            await run_startup_recovery(schedule, now)
        mock_start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missed_on_triggers_catchup(self):
        schedule = _make_schedule(current_status="OFF_HOURS")
        # now is outside window (14:00 UTC)
        now = datetime(2026, 3, 30, 14, 0, tzinfo=timezone.utc)
        with patch("app.modules.power_scheduling.workers.schedule_worker.start_off_hours",
                   new_callable=AsyncMock), \
             patch("app.modules.power_scheduling.workers.schedule_worker.end_off_hours_catchup",
                   new_callable=AsyncMock) as mock_catchup:
            await run_startup_recovery(schedule, now)
        mock_catchup.assert_awaited_once()
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd backend && python -m pytest tests/unit/test_power_scheduling/test_worker.py -v
```

- [ ] **Step 3: Implement worker**

```python
# backend/app/modules/power_scheduling/workers/schedule_worker.py
from __future__ import annotations

from datetime import datetime, timezone

import pytz
import structlog
from apscheduler.triggers.cron import CronTrigger

from app.modules.power_scheduling.models import PowerSchedule
from app.modules.power_scheduling.services.eligibility import compute_expected_status
from app.modules.power_scheduling.services.scheduling_service import (
    end_off_hours_catchup,
    on_client_event,
    start_off_hours,
    end_off_hours,
)

log = structlog.get_logger(__name__).bind(module="power_scheduling")

# Module-level reference to the ClientStatsWsManager (set during app startup)
_client_ws_manager = None


def get_client_ws_manager():
    return _client_ws_manager


def register_schedule_jobs(schedule: PowerSchedule, scheduler) -> None:
    """Register APScheduler on/off cron jobs for a schedule."""
    tz = pytz.timezone(schedule.timezone)
    for i, window in enumerate(schedule.windows):
        off_h, off_m = map(int, window.start.split(":"))
        on_h, on_m = map(int, window.end.split(":"))
        days_str = ",".join(str(d) for d in window.days)

        scheduler.add_job(
            _start_off_hours_job,
            trigger=CronTrigger(
                day_of_week=days_str, hour=off_h, minute=off_m, timezone=tz
            ),
            id=f"ps_off_{schedule.site_id}_{i}",
            kwargs={"site_id": schedule.site_id},
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        scheduler.add_job(
            _end_off_hours_job,
            trigger=CronTrigger(hour=on_h, minute=on_m, timezone=tz),
            id=f"ps_on_{schedule.site_id}_{i}",
            kwargs={"site_id": schedule.site_id},
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
    log.info("schedule_jobs_registered", site_id=schedule.site_id, windows=len(schedule.windows))


def deregister_schedule_jobs(site_id: str, scheduler) -> None:
    """Remove all APScheduler jobs for a site."""
    # Remove up to 20 windows worth of jobs
    for i in range(20):
        for direction in ("off", "on"):
            job_id = f"ps_{direction}_{site_id}_{i}"
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)


async def _start_off_hours_job(site_id: str) -> None:
    schedule = await PowerSchedule.find_one(PowerSchedule.site_id == site_id)
    if schedule and schedule.enabled:
        await start_off_hours(schedule)


async def _end_off_hours_job(site_id: str) -> None:
    schedule = await PowerSchedule.find_one(PowerSchedule.site_id == site_id)
    if schedule and schedule.enabled:
        await end_off_hours(schedule)


async def run_startup_recovery(schedule: PowerSchedule, now: datetime | None = None) -> None:
    """Detect missed transitions and catch up."""
    if now is None:
        now = datetime.now(timezone.utc)
    expected = compute_expected_status(schedule, now)
    site_id = schedule.site_id

    if expected == "OFF_HOURS" and schedule.current_status == "IDLE":
        log.info("catchup_start_off", site_id=site_id)
        await start_off_hours(schedule)
    elif expected == "IDLE" and schedule.current_status == "OFF_HOURS":
        log.info("catchup_start_on", site_id=site_id)
        await end_off_hours_catchup(schedule)


async def startup_power_scheduling(api_session) -> None:
    """
    Called from app lifespan. Registers all enabled schedule jobs,
    starts client WS subscriptions, and runs startup recovery.
    """
    global _client_ws_manager
    from app.workers import get_scheduler
    from app.modules.power_scheduling.services.client_ws_service import ClientStatsWsManager

    schedules = await PowerSchedule.find(PowerSchedule.enabled == True).to_list()  # noqa: E712
    if not schedules:
        return

    scheduler = get_scheduler().scheduler

    # Create a single ClientStatsWsManager for all sites
    site_ids = [s.site_id for s in schedules]

    def _client_event_bridge(site_id: str, event_type: str, client_mac: str, ap_mac: str, rssi) -> None:
        from app.core.tasks import create_background_task
        import asyncio
        loop = asyncio.get_event_loop()

        async def _dispatch():
            sched = await PowerSchedule.find_one(PowerSchedule.site_id == site_id)
            if sched:
                await on_client_event(site_id, event_type, client_mac, ap_mac, rssi, sched)

        loop.call_soon_threadsafe(lambda: create_background_task(_dispatch(), name=f"ps-event-{site_id}"))

    _client_ws_manager = ClientStatsWsManager(api_session=api_session, on_event=_client_event_bridge)
    await _client_ws_manager.start(site_ids)

    # Register APScheduler jobs
    for schedule in schedules:
        register_schedule_jobs(schedule, scheduler)

    # Startup recovery
    for schedule in schedules:
        await run_startup_recovery(schedule)

    log.info("power_scheduling_started", sites=len(schedules))
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd backend && python -m pytest tests/unit/test_power_scheduling/test_worker.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/power_scheduling/workers/schedule_worker.py \
        backend/tests/unit/test_power_scheduling/test_worker.py
git commit -m "feat(power-scheduling): add APScheduler worker and startup recovery"
```

---

## Task 8: REST Router

**Files:**
- Create: `backend/app/modules/power_scheduling/router.py`
- Test: `backend/tests/integration/test_power_scheduling_api.py`

- [ ] **Step 1: Write integration tests**

```python
# backend/tests/integration/test_power_scheduling_api.py
import pytest
from unittest.mock import AsyncMock, patch


VALID_PAYLOAD = {
    "site_id": "site-abc",
    "site_name": "HQ",
    "windows": [{"days": [0, 1, 2, 3, 4], "start": "22:00", "end": "06:00"}],
    "grace_period_minutes": 5,
    "critical_ap_macs": [],
}


class TestCreateSchedule:
    @pytest.mark.asyncio
    async def test_create_returns_201(self, client, test_db):
        with patch("app.modules.power_scheduling.router._setup_mist_profile",
                   new_callable=AsyncMock, return_value="prof-id"), \
             patch("app.modules.power_scheduling.router._fetch_site_timezone",
                   new_callable=AsyncMock, return_value="America/New_York"), \
             patch("app.modules.power_scheduling.router._register_jobs"):
            resp = await client.post("/api/v1/power-scheduling/sites/site-abc", json=VALID_PAYLOAD)
        assert resp.status_code == 201
        data = resp.json()
        assert data["site_id"] == "site-abc"
        assert data["timezone"] == "America/New_York"

    @pytest.mark.asyncio
    async def test_duplicate_site_returns_409(self, client, test_db):
        with patch("app.modules.power_scheduling.router._setup_mist_profile",
                   new_callable=AsyncMock, return_value="prof-id"), \
             patch("app.modules.power_scheduling.router._fetch_site_timezone",
                   new_callable=AsyncMock, return_value="UTC"), \
             patch("app.modules.power_scheduling.router._register_jobs"):
            await client.post("/api/v1/power-scheduling/sites/site-abc", json=VALID_PAYLOAD)
            resp = await client.post("/api/v1/power-scheduling/sites/site-abc", json=VALID_PAYLOAD)
        assert resp.status_code == 409


class TestListSchedules:
    @pytest.mark.asyncio
    async def test_list_returns_empty(self, client, test_db):
        resp = await client.get("/api/v1/power-scheduling/sites")
        assert resp.status_code == 200
        assert resp.json() == []


class TestManualTrigger:
    @pytest.mark.asyncio
    async def test_trigger_start(self, client, test_db):
        with patch("app.modules.power_scheduling.router._setup_mist_profile",
                   new_callable=AsyncMock, return_value="prof-id"), \
             patch("app.modules.power_scheduling.router._fetch_site_timezone",
                   new_callable=AsyncMock, return_value="UTC"), \
             patch("app.modules.power_scheduling.router._register_jobs"), \
             patch("app.modules.power_scheduling.router.start_off_hours",
                   new_callable=AsyncMock):
            await client.post("/api/v1/power-scheduling/sites/site-abc", json=VALID_PAYLOAD)
            resp = await client.post(
                "/api/v1/power-scheduling/sites/site-abc/trigger",
                json={"action": "start"},
            )
        assert resp.status_code == 200
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd backend && python -m pytest tests/integration/test_power_scheduling_api.py -v
```

- [ ] **Step 3: Implement router**

```python
# backend/app/modules/power_scheduling/router.py
from __future__ import annotations

from typing import Any

import structlog
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.dependencies import require_impact_role
from app.models.user import User
from app.modules.power_scheduling.models import PowerSchedule, PowerScheduleLog, ScheduleWindow
from app.modules.power_scheduling.services.scheduling_service import (
    end_off_hours,
    end_off_hours_catchup,
    start_off_hours,
)
from app.modules.power_scheduling.state import get_state
from app.services.mist_service_factory import create_mist_service

log = structlog.get_logger(__name__)
router = APIRouter(tags=["Power Scheduling"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ScheduleWindowSchema(BaseModel):
    days: list[int]
    start: str
    end: str


class CreateScheduleRequest(BaseModel):
    site_id: str
    site_name: str
    windows: list[ScheduleWindowSchema]
    grace_period_minutes: int = 5
    neighbor_rssi_threshold_dbm: int = -65
    roam_rssi_threshold_dbm: int = -75
    critical_ap_macs: list[str] = []
    enabled: bool = True


class ScheduleResponse(BaseModel):
    id: str
    site_id: str
    site_name: str
    timezone: str
    windows: list[ScheduleWindowSchema]
    off_profile_id: str
    grace_period_minutes: int
    neighbor_rssi_threshold_dbm: int
    roam_rssi_threshold_dbm: int
    critical_ap_macs: list[str]
    enabled: bool
    current_status: str


class ScheduleStatusResponse(BaseModel):
    site_id: str
    status: str
    disabled_ap_count: int
    pending_disable_count: int
    client_ap_count: int


class TriggerRequest(BaseModel):
    action: str  # "start" | "end"


class LogResponse(BaseModel):
    id: str
    site_id: str
    timestamp: str
    event_type: str
    ap_mac: str | None
    details: dict


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

async def _fetch_site_timezone(site_id: str) -> str:
    mist = await create_mist_service()
    data = await mist.get(f"/api/v1/sites/{site_id}")
    return data.get("timezone", "UTC")


async def _setup_mist_profile(site_id: str) -> str:
    """Create the power-schedule-off device profile in Mist and return its ID."""
    mist = await create_mist_service()
    body = {
        "name": f"power-schedule-off-{site_id}",
        "radio_config": {
            "band_24": {"disabled": True},
            "band_5": {"disabled": True},
            "band_6": {"disabled": True},
        },
    }
    result = await mist.post(f"/api/v1/sites/{site_id}/deviceprofiles", body)
    return result["id"]


def _register_jobs(schedule: PowerSchedule) -> None:
    from app.workers import get_scheduler
    from app.modules.power_scheduling.workers.schedule_worker import register_schedule_jobs
    register_schedule_jobs(schedule, get_scheduler().scheduler)


def _deregister_jobs(site_id: str) -> None:
    from app.workers import get_scheduler
    from app.modules.power_scheduling.workers.schedule_worker import deregister_schedule_jobs
    deregister_schedule_jobs(site_id, get_scheduler().scheduler)


def _schedule_to_response(s: PowerSchedule) -> ScheduleResponse:
    return ScheduleResponse(
        id=str(s.id),
        site_id=s.site_id,
        site_name=s.site_name,
        timezone=s.timezone,
        windows=[ScheduleWindowSchema(**w.model_dump()) for w in s.windows],
        off_profile_id=s.off_profile_id,
        grace_period_minutes=s.grace_period_minutes,
        neighbor_rssi_threshold_dbm=s.neighbor_rssi_threshold_dbm,
        roam_rssi_threshold_dbm=s.roam_rssi_threshold_dbm,
        critical_ap_macs=s.critical_ap_macs,
        enabled=s.enabled,
        current_status=s.current_status,
    )


async def _get_schedule_or_404(site_id: str) -> PowerSchedule:
    s = await PowerSchedule.find_one(PowerSchedule.site_id == site_id)
    if not s:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return s


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/power-scheduling/sites", response_model=list[ScheduleResponse])
async def list_schedules(_: User = Depends(require_impact_role)) -> list[ScheduleResponse]:
    schedules = await PowerSchedule.find_all().to_list()
    return [_schedule_to_response(s) for s in schedules]


@router.post("/power-scheduling/sites/{site_id}", response_model=ScheduleResponse,
             status_code=status.HTTP_201_CREATED)
async def create_schedule(
    site_id: str,
    body: CreateScheduleRequest,
    _: User = Depends(require_impact_role),
) -> ScheduleResponse:
    existing = await PowerSchedule.find_one(PowerSchedule.site_id == site_id)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Schedule already exists for this site")

    timezone_str = await _fetch_site_timezone(site_id)
    off_profile_id = await _setup_mist_profile(site_id)

    schedule = PowerSchedule(
        site_id=site_id,
        site_name=body.site_name,
        timezone=timezone_str,
        windows=[ScheduleWindow(**w.model_dump()) for w in body.windows],
        off_profile_id=off_profile_id,
        grace_period_minutes=body.grace_period_minutes,
        neighbor_rssi_threshold_dbm=body.neighbor_rssi_threshold_dbm,
        roam_rssi_threshold_dbm=body.roam_rssi_threshold_dbm,
        critical_ap_macs=body.critical_ap_macs,
        enabled=body.enabled,
    )
    await schedule.insert()

    if schedule.enabled:
        _register_jobs(schedule)
        from app.modules.power_scheduling.workers.schedule_worker import get_client_ws_manager
        ws = get_client_ws_manager()
        if ws:
            await ws.add_site(site_id)

    log.info("schedule_created", site_id=site_id)
    return _schedule_to_response(schedule)


@router.put("/power-scheduling/sites/{site_id}", response_model=ScheduleResponse)
async def update_schedule(
    site_id: str,
    body: CreateScheduleRequest,
    _: User = Depends(require_impact_role),
) -> ScheduleResponse:
    schedule = await _get_schedule_or_404(site_id)
    _deregister_jobs(site_id)

    schedule.windows = [ScheduleWindow(**w.model_dump()) for w in body.windows]
    schedule.grace_period_minutes = body.grace_period_minutes
    schedule.neighbor_rssi_threshold_dbm = body.neighbor_rssi_threshold_dbm
    schedule.roam_rssi_threshold_dbm = body.roam_rssi_threshold_dbm
    schedule.critical_ap_macs = body.critical_ap_macs
    schedule.enabled = body.enabled
    await schedule.save()

    if schedule.enabled:
        _register_jobs(schedule)

    return _schedule_to_response(schedule)


@router.delete("/power-scheduling/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    site_id: str,
    _: User = Depends(require_impact_role),
) -> None:
    schedule = await _get_schedule_or_404(site_id)
    _deregister_jobs(site_id)

    if schedule.current_status == "OFF_HOURS":
        await end_off_hours_catchup(schedule)

    # Remove Mist profile
    try:
        mist = await create_mist_service()
        await mist.delete(f"/api/v1/sites/{site_id}/deviceprofiles/{schedule.off_profile_id}")
    except Exception as exc:
        log.warning("profile_delete_failed", site_id=site_id, error=str(exc))

    from app.modules.power_scheduling.workers.schedule_worker import get_client_ws_manager
    ws = get_client_ws_manager()
    if ws:
        await ws.remove_site(site_id)

    from app.modules.power_scheduling.state import clear_state
    await clear_state(site_id)
    await schedule.delete()


@router.get("/power-scheduling/sites/{site_id}/status", response_model=ScheduleStatusResponse)
async def get_status(
    site_id: str,
    _: User = Depends(require_impact_role),
) -> ScheduleStatusResponse:
    await _get_schedule_or_404(site_id)
    state = get_state(site_id)
    return ScheduleStatusResponse(
        site_id=site_id,
        status=state.status,
        disabled_ap_count=len(state.disabled_aps),
        pending_disable_count=len(state.pending_disable),
        client_ap_count=len(state.client_map),
    )


@router.get("/power-scheduling/sites/{site_id}/logs", response_model=list[LogResponse])
async def get_logs(
    site_id: str,
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    event_type: str | None = Query(None),
    _: User = Depends(require_impact_role),
) -> list[LogResponse]:
    await _get_schedule_or_404(site_id)
    query = PowerScheduleLog.find(PowerScheduleLog.site_id == site_id)
    if event_type:
        query = query.find(PowerScheduleLog.event_type == event_type)
    logs = await query.sort(-PowerScheduleLog.timestamp).skip(skip).limit(limit).to_list()
    return [
        LogResponse(
            id=str(lg.id),
            site_id=lg.site_id,
            timestamp=lg.timestamp.isoformat(),
            event_type=lg.event_type,
            ap_mac=lg.ap_mac,
            details=lg.details,
        )
        for lg in logs
    ]


@router.post("/power-scheduling/sites/{site_id}/trigger")
async def manual_trigger(
    site_id: str,
    body: TriggerRequest,
    _: User = Depends(require_impact_role),
) -> dict:
    schedule = await _get_schedule_or_404(site_id)
    if body.action == "start":
        from app.core.tasks import create_background_task
        create_background_task(start_off_hours(schedule), name=f"ps-manual-start-{site_id}")
        return {"status": "triggered", "action": "start"}
    elif body.action == "end":
        from app.core.tasks import create_background_task
        create_background_task(end_off_hours(schedule), name=f"ps-manual-end-{site_id}")
        return {"status": "triggered", "action": "end"}
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="action must be 'start' or 'end'")
```

- [ ] **Step 4: Run integration tests — expect pass**

```bash
cd backend && python -m pytest tests/integration/test_power_scheduling_api.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/power_scheduling/router.py \
        backend/tests/integration/test_power_scheduling_api.py
git commit -m "feat(power-scheduling): add REST router with CRUD, status, logs, trigger endpoints"
```

---

## Task 9: Module Registration + Lifespan Hook

**Files:**
- Modify: `backend/app/modules/__init__.py`
- Modify: `backend/app/modules/power_scheduling/__init__.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create module `__init__.py`**

```python
# backend/app/modules/power_scheduling/__init__.py
# Empty — module registered via AppModule in app/modules/__init__.py
```

- [ ] **Step 2: Add AppModule entry**

In `backend/app/modules/__init__.py`, add to the `MODULES` list (after the telemetry entry):

```python
AppModule(
    name="power_scheduling",
    router_module="app.modules.power_scheduling.router",
    model_imports=[
        ("app.modules.power_scheduling.models", "PowerSchedule"),
        ("app.modules.power_scheduling.models", "PowerScheduleLog"),
    ],
    tags=["Power Scheduling"],
),
```

- [ ] **Step 3: Add lifespan hook in main.py**

Find the telemetry startup block in `backend/app/main.py` (search for `start_telemetry_pipeline`) and add after it:

```python
try:
    from app.modules.power_scheduling.workers.schedule_worker import startup_power_scheduling
    # Re-use the Mist API session; create a fresh one for power scheduling
    from app.services.mist_service_factory import create_mist_service as _create_mist
    _ps_mist = await _create_mist()
    _ps_api_session = _ps_mist.get_session()
    await startup_power_scheduling(_ps_api_session)
    logger.info("power_scheduling_started")
except Exception as e:
    logger.warning("power_scheduling_start_failed", error=str(e))
```

- [ ] **Step 4: Smoke test — app starts without errors**

```bash
cd backend && python -c "from app.main import app; print('ok')"
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/__init__.py \
        backend/app/modules/power_scheduling/__init__.py \
        backend/app/main.py
git commit -m "feat(power-scheduling): register module and add lifespan startup hook"
```

---

## Task 10: Frontend — Service + Types

**Files:**
- Create: `frontend/src/app/features/power-scheduling/power-scheduling.service.ts`

- [ ] **Step 1: Implement service**

```typescript
// frontend/src/app/features/power-scheduling/power-scheduling.service.ts
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';

export interface ScheduleWindow {
  days: number[];
  start: string;
  end: string;
}

export interface PowerSchedule {
  id: string;
  site_id: string;
  site_name: string;
  timezone: string;
  windows: ScheduleWindow[];
  off_profile_id: string;
  grace_period_minutes: number;
  neighbor_rssi_threshold_dbm: number;
  roam_rssi_threshold_dbm: number;
  critical_ap_macs: string[];
  enabled: boolean;
  current_status: 'IDLE' | 'OFF_HOURS' | 'TRANSITIONING_OFF' | 'TRANSITIONING_ON';
}

export interface ScheduleStatus {
  site_id: string;
  status: string;
  disabled_ap_count: number;
  pending_disable_count: number;
  client_ap_count: number;
}

export interface ScheduleLog {
  id: string;
  site_id: string;
  timestamp: string;
  event_type: string;
  ap_mac: string | null;
  details: Record<string, unknown>;
}

export interface CreateScheduleRequest {
  site_id: string;
  site_name: string;
  windows: ScheduleWindow[];
  grace_period_minutes: number;
  neighbor_rssi_threshold_dbm: number;
  roam_rssi_threshold_dbm: number;
  critical_ap_macs: string[];
  enabled: boolean;
}

@Injectable({ providedIn: 'root' })
export class PowerSchedulingService {
  private readonly api = inject(ApiService);

  listSchedules(): Observable<PowerSchedule[]> {
    return this.api.get<PowerSchedule[]>('/power-scheduling/sites');
  }

  createSchedule(siteId: string, body: CreateScheduleRequest): Observable<PowerSchedule> {
    return this.api.post<PowerSchedule>(`/power-scheduling/sites/${siteId}`, body);
  }

  updateSchedule(siteId: string, body: CreateScheduleRequest): Observable<PowerSchedule> {
    return this.api.put<PowerSchedule>(`/power-scheduling/sites/${siteId}`, body);
  }

  deleteSchedule(siteId: string): Observable<void> {
    return this.api.delete<void>(`/power-scheduling/sites/${siteId}`);
  }

  getStatus(siteId: string): Observable<ScheduleStatus> {
    return this.api.get<ScheduleStatus>(`/power-scheduling/sites/${siteId}/status`);
  }

  getLogs(siteId: string, params?: { limit?: number; skip?: number; event_type?: string }): Observable<ScheduleLog[]> {
    return this.api.get<ScheduleLog[]>(`/power-scheduling/sites/${siteId}/logs`, params);
  }

  trigger(siteId: string, action: 'start' | 'end'): Observable<{ status: string }> {
    return this.api.post<{ status: string }>(`/power-scheduling/sites/${siteId}/trigger`, { action });
  }
}
```

- [ ] **Step 2: Verify compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep power-scheduling
```
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/features/power-scheduling/power-scheduling.service.ts
git commit -m "feat(power-scheduling): add Angular service and types"
```

---

## Task 11: Frontend — Components + Routing

**Files:**
- Create: all component files + routes file
- Modify: `frontend/src/app/app.routes.ts`, `frontend/src/app/layout/sidebar/nav-items.config.ts`

- [ ] **Step 1: Create routes file**

```typescript
// frontend/src/app/features/power-scheduling/power-scheduling.routes.ts
import { Routes } from '@angular/router';

const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./list/power-scheduling-list.component').then((m) => m.PowerSchedulingListComponent),
  },
  {
    path: ':siteId',
    loadComponent: () =>
      import('./detail/power-scheduling-detail.component').then(
        (m) => m.PowerSchedulingDetailComponent,
      ),
  },
];

export default routes;
```

- [ ] **Step 2: Create list component**

```typescript
// frontend/src/app/features/power-scheduling/list/power-scheduling-list.component.ts
import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { PowerSchedule, PowerSchedulingService } from '../power-scheduling.service';

@Component({
  selector: 'app-power-scheduling-list',
  standalone: true,
  imports: [MatButtonModule, MatCardModule, MatChipsModule, MatIconModule, MatProgressSpinnerModule],
  templateUrl: './power-scheduling-list.component.html',
  styleUrl: './power-scheduling-list.component.scss',
})
export class PowerSchedulingListComponent implements OnInit {
  private readonly service = inject(PowerSchedulingService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  schedules = signal<PowerSchedule[]>([]);
  loading = signal(true);

  activeCount = computed(() => this.schedules().filter((s) => s.current_status === 'OFF_HOURS').length);

  ngOnInit(): void {
    this.service
      .listSchedules()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => { this.schedules.set(data); this.loading.set(false); },
        error: () => this.loading.set(false),
      });
  }

  openDetail(siteId: string): void {
    this.router.navigate(['/power-scheduling', siteId]);
  }
}
```

```html
<!-- frontend/src/app/features/power-scheduling/list/power-scheduling-list.component.html -->
<div class="page-header">
  <h1>AP Power Scheduling</h1>
  <span class="subtitle">{{ schedules().length }} sites configured · {{ activeCount() }} currently in off-hours</span>
</div>

@if (loading()) {
  <mat-spinner diameter="40"></mat-spinner>
} @else if (schedules().length === 0) {
  <div class="empty-state">
    <mat-icon>power_settings_new</mat-icon>
    <p>No sites configured. Add a site to get started.</p>
  </div>
} @else {
  <div class="schedule-grid">
    @for (s of schedules(); track s.site_id) {
      <mat-card class="schedule-card" (click)="openDetail(s.site_id)">
        <mat-card-header>
          <mat-card-title>{{ s.site_name }}</mat-card-title>
          <mat-card-subtitle>{{ s.timezone }}</mat-card-subtitle>
          <mat-chip [class]="'status-' + s.current_status.toLowerCase()">
            {{ s.current_status === 'OFF_HOURS' ? 'Off-Hours' : 'Active' }}
          </mat-chip>
        </mat-card-header>
        <mat-card-content>
          <p>{{ s.windows.length }} window(s) · Grace: {{ s.grace_period_minutes }}m</p>
        </mat-card-content>
      </mat-card>
    }
  </div>
}
```

```scss
// frontend/src/app/features/power-scheduling/list/power-scheduling-list.component.scss
.page-header { margin-bottom: 24px; }
.schedule-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.schedule-card { cursor: pointer; transition: box-shadow 0.2s; }
.schedule-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
.status-off_hours { background-color: var(--app-warning-color) !important; }
.empty-state { text-align: center; padding: 48px; color: var(--app-text-muted); }
```

- [ ] **Step 3: Create detail component (config + status + logs)**

```typescript
// frontend/src/app/features/power-scheduling/detail/power-scheduling-detail.component.ts
import { Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { FormArray, FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { MatChipsModule } from '@angular/material/chips';
import { PowerSchedule, ScheduleLog, ScheduleStatus, PowerSchedulingService } from '../power-scheduling.service';

@Component({
  selector: 'app-power-scheduling-detail',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule, MatCardModule, MatFormFieldModule,
    MatIconModule, MatInputModule, MatSelectModule,
    MatTableModule, MatChipsModule,
  ],
  templateUrl: './power-scheduling-detail.component.html',
  styleUrl: './power-scheduling-detail.component.scss',
})
export class PowerSchedulingDetailComponent implements OnInit {
  private readonly service = inject(PowerSchedulingService);
  private readonly route = inject(ActivatedRoute);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);

  siteId = signal('');
  schedule = signal<PowerSchedule | null>(null);
  status = signal<ScheduleStatus | null>(null);
  logs = signal<ScheduleLog[]>([]);
  loading = signal(true);
  saving = signal(false);

  form: FormGroup = this.fb.group({
    site_name: ['', Validators.required],
    grace_period_minutes: [5, [Validators.required, Validators.min(1)]],
    neighbor_rssi_threshold_dbm: [-65],
    roam_rssi_threshold_dbm: [-75],
    enabled: [true],
  });

  logColumns = ['timestamp', 'event_type', 'ap_mac', 'details'];

  ngOnInit(): void {
    const siteId = this.route.snapshot.paramMap.get('siteId') ?? '';
    this.siteId.set(siteId);
    this.loadData(siteId);
  }

  private loadData(siteId: string): void {
    this.service.getStatus(siteId).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (s) => this.status.set(s),
    });
    this.service.getLogs(siteId, { limit: 50 }).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (l) => { this.logs.set(l); this.loading.set(false); },
      error: () => this.loading.set(false),
    });
  }

  trigger(action: 'start' | 'end'): void {
    this.service
      .trigger(this.siteId(), action)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.loadData(this.siteId()));
  }
}
```

```html
<!-- frontend/src/app/features/power-scheduling/detail/power-scheduling-detail.component.html -->
<div class="page-header">
  <h1>{{ siteId() }}</h1>
  @if (status(); as s) {
    <mat-chip [class]="'status-' + s.status.toLowerCase()">{{ s.status }}</mat-chip>
    <span class="subtitle">{{ s.disabled_ap_count }} APs off · {{ s.pending_disable_count }} pending · {{ s.client_ap_count }} APs with clients</span>
  }
</div>

<div class="action-bar">
  <button mat-stroked-button (click)="trigger('start')">
    <mat-icon>power_off</mat-icon> Start Off-Hours
  </button>
  <button mat-stroked-button (click)="trigger('end')">
    <mat-icon>power</mat-icon> End Off-Hours
  </button>
</div>

@if (!loading()) {
  <div class="table-card">
    <table mat-table [dataSource]="logs()">
      <ng-container matColumnDef="timestamp">
        <th mat-header-cell *matHeaderCellDef>Time</th>
        <td mat-cell *matCellDef="let row">{{ row.timestamp | date:'short' }}</td>
      </ng-container>
      <ng-container matColumnDef="event_type">
        <th mat-header-cell *matHeaderCellDef>Event</th>
        <td mat-cell *matCellDef="let row"><code>{{ row.event_type }}</code></td>
      </ng-container>
      <ng-container matColumnDef="ap_mac">
        <th mat-header-cell *matHeaderCellDef>AP</th>
        <td mat-cell *matCellDef="let row">{{ row.ap_mac ?? '—' }}</td>
      </ng-container>
      <ng-container matColumnDef="details">
        <th mat-header-cell *matHeaderCellDef>Details</th>
        <td mat-cell *matCellDef="let row">{{ row.details | json }}</td>
      </ng-container>
      <tr mat-header-row *matHeaderRowDef="logColumns"></tr>
      <tr mat-row *matRowDef="let row; columns: logColumns;"></tr>
    </table>
  </div>
}
```

```scss
// frontend/src/app/features/power-scheduling/detail/power-scheduling-detail.component.scss
.page-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.action-bar { display: flex; gap: 8px; margin-bottom: 24px; }
.table-card { background: var(--app-surface); border-radius: 8px; overflow: hidden; }
.status-off_hours { background-color: var(--app-warning-color) !important; }
```

- [ ] **Step 4: Register routes and nav**

In `frontend/src/app/app.routes.ts`, inside the authenticated layout children array, add:

```typescript
{
  path: 'power-scheduling',
  loadChildren: () => import('./features/power-scheduling/power-scheduling.routes'),
},
```

In `frontend/src/app/layout/sidebar/nav-items.config.ts`, add to `NAV_ITEMS`:

```typescript
{
  label: 'Power Scheduling',
  icon: 'power_settings_new',
  route: '/power-scheduling',
  roles: ['impact_analysis', 'admin'],
},
```

- [ ] **Step 5: Verify compiles**

```bash
cd frontend && npx ng build --configuration=development 2>&1 | tail -20
```
Expected: build succeeds with no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/features/power-scheduling/ \
        frontend/src/app/app.routes.ts \
        frontend/src/app/layout/sidebar/nav-items.config.ts
git commit -m "feat(power-scheduling): add Angular list/detail components, routing, nav"
```

---

## Self-Review Notes

**Spec coverage:**
- ✅ `PowerSchedule` model with all fields including `roam_rssi_threshold_dbm`
- ✅ `PowerScheduleLog` with all `event_type` values
- ✅ `PowerScheduleState` in-memory with asyncio locks
- ✅ RRM API called for bands 24/5/6, merged by best RSSI
- ✅ `can_disable()` checks critical APs, client count, RF-neighbor client count
- ✅ `TRANSITIONING_OFF`: only disables 0-client APs with no active RF neighbors
- ✅ `OFF_HOURS` handlers: join (re-enable + neighbors), leave (grace timer), RSSI (pre-enable neighbors)
- ✅ Grace timer as cancellable asyncio task
- ✅ `end_off_hours()` cancels grace tasks, restores all profiles
- ✅ `end_off_hours_catchup()` queries Mist API (no in-memory state required)
- ✅ Startup recovery: both OFF→ON and ON→OFF directions
- ✅ APScheduler jobs with per-site pytz timezone
- ✅ Clients WS persistent (not scoped to off-hours window)
- ✅ `PowerScheduleLog` entries on every event + structlog
- ✅ All REST endpoints (list, create, update, delete, status, logs, trigger)
- ✅ `current_status` persisted for recovery
- ✅ Frontend service, list view, detail/log view, routing, nav

**Known gap requiring implementer action:**
- `client_ws_service.py` Task 5 has a TODO block: find the correct `mistapi` client stats WS class in `mistapi.websockets.sites` and replace the placeholder with the real implementation. The pattern is identical to `DeviceStatsEvents` in `mist_ws_manager.py`.
