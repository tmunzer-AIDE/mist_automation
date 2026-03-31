# Grace Timer TOCTOU Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the race condition in `_grace_timer` where a client joining an AP during the Mist API call window results in the AP's radios being disabled while a client is connected.

**Architecture:** After the grace period elapses, `_grace_timer` checks eligibility under the lock, releases it, then makes a Mist API call — creating a TOCTOU window. The fix adds a post-API re-check under the lock; if a client arrived during the window, the override is immediately restored (rollback). The state machine (`protected_aps`) is only mutated under the lock.

**Tech Stack:** Python 3.10+, asyncio, pytest-asyncio (`asyncio_mode = "auto"`), `unittest.mock`

---

## Background: The Bug

`_grace_timer` in `backend/app/modules/power_scheduling/services/scheduling_service.py`:

```python
async def _grace_timer(site_id, ap_mac, schedule):
    await asyncio.sleep(...)
    async with get_lock(site_id):
        state.grace_tasks.pop(ap_mac, None)
        if not can_disable(ap_mac, state, schedule):  # ← checked under lock
            return
    # ← LOCK RELEASED HERE
    await _clear_ap_override(site_id, ap_mac)           # ← TOCTOU WINDOW
    async with get_lock(site_id):
        state.protected_aps.discard(ap_mac)             # ← state mutated after window
```

Between lock release and the API call completing, `_handle_client_join` may fire:
- It adds the client to `client_map`
- It sees `ap_mac in state.protected_aps` → `was_disabled = False` → does NOT re-add override
- Then `_clear_ap_override` completes and `protected_aps.discard(ap_mac)` runs
- Result: active client on an AP with disabled radios

## Background: Stale Tests

The existing `test_scheduling_service.py` was written against a previous architecture.
It references `state.disabled_aps`, `state.pending_disable`, and `_assign_profile` — none of
which exist in the current code. These tests fail today and must be updated as part of this plan.

---

## Files

- Modify: `backend/app/modules/power_scheduling/services/scheduling_service.py` — fix `_grace_timer` only
- Modify: `backend/tests/unit/test_power_scheduling/test_scheduling_service.py` — fix stale tests + add grace timer race tests

---

## Task 1: Fix the stale tests

The test file references `state.disabled_aps`, `state.pending_disable`, and `_assign_profile` — none of
which exist in the current state model. Replace the entire test file content so it matches the actual API.

**Files:**
- Modify: `backend/tests/unit/test_power_scheduling/test_scheduling_service.py`

- [ ] **Step 1.1: Run the existing test file to confirm it fails**

```bash
cd backend && .venv/bin/pytest tests/unit/test_power_scheduling/test_scheduling_service.py -v 2>&1 | head -40
```

Expected: multiple ERRORS or FAILURES (AttributeError on `state.disabled_aps` etc.)

- [ ] **Step 1.2: Replace the test file with updated tests that match the current implementation**

Read `backend/app/modules/power_scheduling/services/scheduling_service.py` and `backend/app/modules/power_scheduling/state.py` first to understand the current state fields (`protected_aps`, `client_map`, `grace_tasks`, `rf_neighbor_map`, `total_non_critical_aps`, `status`).

The current `start_off_hours` flow:
1. `fetch_rf_neighbor_map` → populates `state.rf_neighbor_map`
2. `_get_ap_inventory` → lists APs
3. APs with clients or covered neighbors → `_batch_set_ap_overrides` → added to `state.protected_aps`
4. Remaining APs are covered by the off profile → `_update_profile_radio` disables them
5. `state.status = "OFF_HOURS"`, `state.protected_aps = set(to_protect)`

The current `end_off_hours` flow:
1. Cancels all grace tasks
2. `_batch_clear_ap_overrides` on all `state.protected_aps`
3. `_update_profile_radio(off_profile_id, {})` restores the profile
4. `state.protected_aps.clear()`, `state.status = "IDLE"`

Replace the file with:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.power_scheduling.models import PowerSchedule, ScheduleWindow
from app.modules.power_scheduling.services.scheduling_service import end_off_hours, start_off_hours
from app.modules.power_scheduling.state import clear_state, get_state

_MODULE = "app.modules.power_scheduling.services.scheduling_service"


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


def _mock_ps_class():
    """Stub PowerSchedule ORM calls used inside the service (find_one().update())."""
    mock_cls = MagicMock()
    mock_query = MagicMock()
    mock_query.update = AsyncMock()
    mock_cls.find_one.return_value = mock_query
    return mock_cls, mock_query


class TestStartOffHours:
    @pytest.fixture(autouse=True)
    async def cleanup(self):
        yield
        await clear_state("s1")

    async def test_empty_ap_gets_profile_disabled(self):
        """AP with no clients is covered by the off-profile (not added to protected_aps)."""
        schedule = _make_schedule()
        ap_inventory = [{"mac": "ap1"}]
        mock_cls, _ = _mock_ps_class()

        with (
            patch(f"{_MODULE}.fetch_rf_neighbor_map", new_callable=AsyncMock, return_value={}),
            patch(f"{_MODULE}._get_ap_inventory", new_callable=AsyncMock, return_value=ap_inventory),
            patch(f"{_MODULE}._batch_set_ap_overrides", new_callable=AsyncMock),
            patch(f"{_MODULE}._update_profile_radio", new_callable=AsyncMock),
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            state = get_state("s1")
            state.client_map = {}
            await start_off_hours(schedule)

        assert "ap1" not in state.protected_aps

    async def test_ap_with_clients_added_to_protected(self):
        """AP with active clients gets a radio override (added to protected_aps)."""
        schedule = _make_schedule()
        ap_inventory = [{"mac": "ap1"}]
        mock_cls, _ = _mock_ps_class()

        with (
            patch(f"{_MODULE}.fetch_rf_neighbor_map", new_callable=AsyncMock, return_value={}),
            patch(f"{_MODULE}._get_ap_inventory", new_callable=AsyncMock, return_value=ap_inventory),
            patch(f"{_MODULE}._batch_set_ap_overrides", new_callable=AsyncMock),
            patch(f"{_MODULE}._update_profile_radio", new_callable=AsyncMock),
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            state = get_state("s1")
            state.client_map = {"ap1": {"client-a"}}
            await start_off_hours(schedule)

        assert "ap1" in state.protected_aps

    async def test_state_becomes_off_hours(self):
        schedule = _make_schedule()
        mock_cls, _ = _mock_ps_class()

        with (
            patch(f"{_MODULE}.fetch_rf_neighbor_map", new_callable=AsyncMock, return_value={}),
            patch(f"{_MODULE}._get_ap_inventory", new_callable=AsyncMock, return_value=[]),
            patch(f"{_MODULE}._update_profile_radio", new_callable=AsyncMock),
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            await start_off_hours(schedule)

        assert get_state("s1").status == "OFF_HOURS"

    async def test_critical_ap_never_touched(self):
        """Critical APs are skipped entirely — not disabled, not protected."""
        schedule = _make_schedule(critical_ap_macs=["ap1"])
        ap_inventory = [{"mac": "ap1"}, {"mac": "ap2"}]
        mock_cls, _ = _mock_ps_class()
        set_mock = AsyncMock()

        with (
            patch(f"{_MODULE}.fetch_rf_neighbor_map", new_callable=AsyncMock, return_value={}),
            patch(f"{_MODULE}._get_ap_inventory", new_callable=AsyncMock, return_value=ap_inventory),
            patch(f"{_MODULE}._batch_set_ap_overrides", set_mock),
            patch(f"{_MODULE}._update_profile_radio", new_callable=AsyncMock),
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            state = get_state("s1")
            state.client_map = {}
            await start_off_hours(schedule)

        # ap1 critical — never in protected_aps
        assert "ap1" not in state.protected_aps
        # ap2 had no clients — not protected either
        assert "ap2" not in state.protected_aps

    async def test_db_updated_to_off_hours(self):
        schedule = _make_schedule()
        mock_cls, mock_query = _mock_ps_class()

        with (
            patch(f"{_MODULE}.fetch_rf_neighbor_map", new_callable=AsyncMock, return_value={}),
            patch(f"{_MODULE}._get_ap_inventory", new_callable=AsyncMock, return_value=[]),
            patch(f"{_MODULE}._update_profile_radio", new_callable=AsyncMock),
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            await start_off_hours(schedule)

        mock_query.update.assert_awaited_once()
        assert mock_query.update.call_args[0][0]["$set"]["current_status"] == "OFF_HOURS"


class TestEndOffHours:
    @pytest.fixture(autouse=True)
    async def cleanup(self):
        yield
        await clear_state("s1")

    async def test_protected_aps_overrides_cleared(self):
        """end_off_hours clears radio overrides for all protected APs."""
        schedule = _make_schedule()
        mock_cls, _ = _mock_ps_class()
        clear_mock = AsyncMock()

        with (
            patch(f"{_MODULE}._batch_clear_ap_overrides", clear_mock),
            patch(f"{_MODULE}._update_profile_radio", new_callable=AsyncMock),
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            state = get_state("s1")
            state.status = "OFF_HOURS"
            state.protected_aps = {"ap1", "ap2"}
            await end_off_hours(schedule)

        clear_mock.assert_awaited_once()
        cleared_macs = set(clear_mock.call_args[0][1])
        assert cleared_macs == {"ap1", "ap2"}

    async def test_state_becomes_idle(self):
        schedule = _make_schedule()
        mock_cls, _ = _mock_ps_class()

        with (
            patch(f"{_MODULE}._batch_clear_ap_overrides", new_callable=AsyncMock),
            patch(f"{_MODULE}._update_profile_radio", new_callable=AsyncMock),
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            state = get_state("s1")
            state.status = "OFF_HOURS"
            state.protected_aps = {"ap1"}
            await end_off_hours(schedule)

        assert state.status == "IDLE"
        assert state.protected_aps == set()

    async def test_db_updated_to_idle(self):
        schedule = _make_schedule()
        mock_cls, mock_query = _mock_ps_class()

        with (
            patch(f"{_MODULE}._batch_clear_ap_overrides", new_callable=AsyncMock),
            patch(f"{_MODULE}._update_profile_radio", new_callable=AsyncMock),
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            state = get_state("s1")
            state.status = "OFF_HOURS"
            await end_off_hours(schedule)

        mock_query.update.assert_awaited_once()
        assert mock_query.update.call_args[0][0]["$set"]["current_status"] == "IDLE"
```

- [ ] **Step 1.3: Run updated tests to confirm they pass**

```bash
cd backend && .venv/bin/pytest tests/unit/test_power_scheduling/test_scheduling_service.py -v
```

Expected: all tests PASS (no ERRORS or FAILURES)

- [ ] **Step 1.4: Commit**

```bash
cd backend && git add tests/unit/test_power_scheduling/test_scheduling_service.py
git commit -m "test(power-scheduling): update scheduling_service tests to match current implementation"
```

---

## Task 2: Write the failing grace timer race condition test

Add a `TestGraceTimer` class to the same test file that covers both the happy path and the TOCTOU race. The test for the race injects a client into `state.client_map` *during* the `_clear_ap_override` API call by using a side effect on the mock — this simulates the concurrent join event.

**Files:**
- Modify: `backend/tests/unit/test_power_scheduling/test_scheduling_service.py`

- [ ] **Step 2.1: Add the grace timer tests to the end of the test file**

Append to `test_scheduling_service.py`:

```python
class TestGraceTimer:
    """Tests for _grace_timer TOCTOU fix.

    Strategy: mock asyncio.sleep to skip the wait, mock _clear_ap_override
    to optionally inject a client arrival during the API window, then assert
    the resulting state is correct.
    """

    @pytest.fixture(autouse=True)
    async def cleanup(self):
        yield
        await clear_state("s1")

    async def test_grace_timer_disables_empty_ap(self):
        """Normal path: AP empties, grace expires, override is cleared."""
        from app.modules.power_scheduling.services.scheduling_service import _grace_timer

        schedule = _make_schedule()
        state = get_state("s1")
        state.status = "OFF_HOURS"
        state.protected_aps = {"ap1"}
        state.client_map = {}  # AP already empty

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MODULE}._clear_ap_override", new_callable=AsyncMock) as mock_clear,
            patch(f"{_MODULE}._set_ap_override", new_callable=AsyncMock) as mock_set,
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}._broadcast_status", new_callable=AsyncMock),
        ):
            await _grace_timer("s1", "ap1", schedule)

        mock_clear.assert_awaited_once_with("s1", "ap1")
        mock_set.assert_not_awaited()  # no rollback needed
        assert "ap1" not in state.protected_aps

    async def test_grace_timer_rollback_when_client_arrives_during_api_call(self):
        """Race condition: client joins AP during _clear_ap_override API call.

        The mock simulates a client arriving while the Mist API is in-flight
        by adding the client to client_map inside the mock side-effect.
        After _grace_timer completes:
        - ap1 must still be in protected_aps (override restored)
        - _set_ap_override must have been called to restore the override
        """
        from app.modules.power_scheduling.services.scheduling_service import _grace_timer

        schedule = _make_schedule()
        state = get_state("s1")
        state.status = "OFF_HOURS"
        state.protected_aps = {"ap1"}
        state.client_map = {}  # empty when grace fires

        async def client_joins_during_api_call(site_id, ap_mac):
            # Simulate a client joining while the API call is in-flight
            state.client_map["ap1"] = {"client-x"}

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MODULE}._clear_ap_override", side_effect=client_joins_during_api_call),
            patch(f"{_MODULE}._set_ap_override", new_callable=AsyncMock) as mock_set,
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}._broadcast_status", new_callable=AsyncMock),
        ):
            await _grace_timer("s1", "ap1", schedule)

        # AP must still be protected — override was restored
        assert "ap1" in state.protected_aps
        mock_set.assert_awaited_once_with("s1", "ap1")

    async def test_grace_timer_no_op_if_ap_already_removed_from_protected(self):
        """If AP is removed from protected_aps before timer fires (e.g. end_off_hours),
        the timer exits early without calling the Mist API."""
        from app.modules.power_scheduling.services.scheduling_service import _grace_timer

        schedule = _make_schedule()
        state = get_state("s1")
        state.status = "OFF_HOURS"
        state.protected_aps = set()  # already removed
        state.client_map = {}

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MODULE}._clear_ap_override", new_callable=AsyncMock) as mock_clear,
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
        ):
            await _grace_timer("s1", "ap1", schedule)

        mock_clear.assert_not_awaited()  # early exit, no API call

    async def test_grace_timer_no_op_if_not_eligible_on_wakeup(self):
        """If can_disable returns False when the timer fires (client re-joined before
        grace expired), no API call is made."""
        from app.modules.power_scheduling.services.scheduling_service import _grace_timer

        schedule = _make_schedule()
        state = get_state("s1")
        state.status = "OFF_HOURS"
        state.protected_aps = {"ap1"}
        state.client_map = {"ap1": {"returning-client"}}  # client back before grace expired

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MODULE}._clear_ap_override", new_callable=AsyncMock) as mock_clear,
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
        ):
            await _grace_timer("s1", "ap1", schedule)

        mock_clear.assert_not_awaited()
        assert "ap1" in state.protected_aps  # unchanged
```

- [ ] **Step 2.2: Run the new tests to confirm the race test fails (bug is real)**

```bash
cd backend && .venv/bin/pytest tests/unit/test_power_scheduling/test_scheduling_service.py::TestGraceTimer -v
```

Expected output:
- `test_grace_timer_disables_empty_ap` — PASS (current code handles normal case)
- `test_grace_timer_rollback_when_client_arrives_during_api_call` — **FAIL** (bug present)
- `test_grace_timer_no_op_if_ap_already_removed_from_protected` — PASS
- `test_grace_timer_no_op_if_not_eligible_on_wakeup` — PASS

The failing test proves the bug: `ap1` gets removed from `protected_aps` even though a client arrived during the window.

---

## Task 3: Fix `_grace_timer`

**Files:**
- Modify: `backend/app/modules/power_scheduling/services/scheduling_service.py` (only `_grace_timer`, lines ~405–424)

- [ ] **Step 3.1: Replace `_grace_timer` with the race-safe version**

Find and replace the entire `_grace_timer` function:

**Before** (current buggy version):
```python
async def _grace_timer(site_id: str, ap_mac: str, schedule: PowerSchedule) -> None:
    """Wait grace period, then remove AP override if still eligible."""
    await asyncio.sleep(schedule.grace_period_minutes * 60)
    state = get_state(site_id)
    async with get_lock(site_id):
        state.grace_tasks.pop(ap_mac, None)
        if ap_mac not in state.protected_aps:
            return
        if not can_disable(ap_mac, state, schedule):
            return

    try:
        await _clear_ap_override(site_id, ap_mac)
        async with get_lock(site_id):
            state.protected_aps.discard(ap_mac)
        await _log_event(site_id, "GRACE_TIMER_EXPIRED", ap_mac=ap_mac)
        await _log_event(site_id, "AP_DISABLED", ap_mac=ap_mac, reason="grace_expired")
        await _broadcast_status(site_id, "OFF_HOURS")
    except Exception as exc:
        await _log_event(site_id, "ERROR", ap_mac=ap_mac, error=type(exc).__name__, action="grace_disable")
```

**After** (race-safe):
```python
async def _grace_timer(site_id: str, ap_mac: str, schedule: PowerSchedule) -> None:
    """Wait grace period, then remove AP override if still eligible.

    Postcondition invariant: if a client arrives between the pre-API eligibility
    check and the Mist API call completing, the override is immediately restored
    so the AP is never left disabled with an active client.
    """
    await asyncio.sleep(schedule.grace_period_minutes * 60)
    state = get_state(site_id)

    async with get_lock(site_id):
        state.grace_tasks.pop(ap_mac, None)
        if ap_mac not in state.protected_aps:
            return
        if not can_disable(ap_mac, state, schedule):
            return

    # Lock released — Mist API call happens here.
    # A client join event can fire concurrently; _handle_client_join will see
    # ap_mac still in protected_aps and skip re-adding the override (was_disabled=False),
    # so we must detect and correct this after the API call completes.
    try:
        await _clear_ap_override(site_id, ap_mac)
    except Exception as exc:
        await _log_event(site_id, "ERROR", ap_mac=ap_mac, error=type(exc).__name__, action="grace_disable")
        return

    # Re-check under lock: did a client arrive while the API call was in-flight?
    async with get_lock(site_id):
        still_eligible = can_disable(ap_mac, state, schedule)
        if still_eligible:
            state.protected_aps.discard(ap_mac)

    if still_eligible:
        await _log_event(site_id, "GRACE_TIMER_EXPIRED", ap_mac=ap_mac)
        await _log_event(site_id, "AP_DISABLED", ap_mac=ap_mac, reason="grace_expired")
        await _broadcast_status(site_id, "OFF_HOURS")
    else:
        # Client arrived during the API window. The override was already cleared by
        # _clear_ap_override — restore it immediately. ap_mac stays in protected_aps.
        try:
            await _set_ap_override(site_id, ap_mac)
            await _log_event(site_id, "AP_ENABLED", ap_mac=ap_mac, reason="grace_rollback_client_arrived")
        except Exception as exc:
            await _log_event(site_id, "ERROR", ap_mac=ap_mac, error=type(exc).__name__, action="grace_rollback")
```

- [ ] **Step 3.2: Run the full grace timer test class — all four tests must pass**

```bash
cd backend && .venv/bin/pytest tests/unit/test_power_scheduling/test_scheduling_service.py::TestGraceTimer -v
```

Expected: all four tests PASS

- [ ] **Step 3.3: Run the full power scheduling unit test suite**

```bash
cd backend && .venv/bin/pytest tests/unit/test_power_scheduling/ -v
```

Expected: all tests PASS

- [ ] **Step 3.4: Commit**

```bash
git add backend/app/modules/power_scheduling/services/scheduling_service.py \
        backend/tests/unit/test_power_scheduling/test_scheduling_service.py
git commit -m "fix(power-scheduling): close TOCTOU window in _grace_timer

Re-check AP eligibility under the lock after _clear_ap_override completes.
If a client joined during the API call window, immediately restore the
override so the AP is never left with disabled radios while a client is
connected."
```

---

## Self-Review

**Spec coverage:**
- ✅ Bug described: `_grace_timer` TOCTOU window between `can_disable` check and `_clear_ap_override` completion
- ✅ Fix: post-API re-check under lock, rollback to `_set_ap_override` if client arrived
- ✅ Tests: normal path, race path, early-exit paths
- ✅ Stale tests updated to match current state model

**Placeholder scan:** None found.

**Type consistency:** `_grace_timer(site_id: str, ap_mac: str, schedule: PowerSchedule)` — signature unchanged. `_set_ap_override(site_id, ap_mac)` — matches existing definition. `can_disable(ap_mac, state, schedule)` — matches existing definition.

**Known limitation:** If the rollback `_set_ap_override` itself fails, the AP has disabled radios but `protected_aps` still contains it. This is an eventual-consistency gap inherent to the architecture (Mist API is not transactional). `end_off_hours` will attempt to clear the override again at window end (idempotent). The error is logged for observability.
