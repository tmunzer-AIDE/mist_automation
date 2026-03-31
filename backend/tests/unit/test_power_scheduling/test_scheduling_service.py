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

        assert "ap1" not in state.protected_aps
        assert "ap2" not in state.protected_aps
        set_mock.assert_not_awaited()

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
