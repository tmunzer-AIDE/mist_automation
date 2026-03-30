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
    """Return (mock_cls, mock_query) replacing PowerSchedule in the service module.

    The service calls: PowerSchedule.find_one(PowerSchedule.site_id == site_id).update(...)
    Because Beanie is not initialised in unit tests, PowerSchedule.site_id raises
    AttributeError before find_one is even called.  Replacing the entire class
    reference in the service module avoids this cleanly.
    """
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

    async def test_zero_client_ap_gets_disabled(self):
        schedule = _make_schedule()
        ap_inventory = [{"mac": "ap1", "deviceprofile_id": None}]
        mock_cls, _ = _mock_ps_class()

        with (
            patch(f"{_MODULE}.fetch_rf_neighbor_map", new_callable=AsyncMock, return_value={}),
            patch(f"{_MODULE}._get_ap_inventory", new_callable=AsyncMock, return_value=ap_inventory),
            patch(f"{_MODULE}._assign_profile", new_callable=AsyncMock) as mock_assign,
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            state = get_state("s1")
            state.client_map = {}
            await start_off_hours(schedule)

        assert "ap1" in state.disabled_aps
        mock_assign.assert_awaited_once_with("s1", "ap1", "off-prof")

    async def test_ap_with_clients_goes_to_pending(self):
        schedule = _make_schedule()
        ap_inventory = [{"mac": "ap1", "deviceprofile_id": None}]
        mock_cls, _ = _mock_ps_class()

        with (
            patch(f"{_MODULE}.fetch_rf_neighbor_map", new_callable=AsyncMock, return_value={}),
            patch(f"{_MODULE}._get_ap_inventory", new_callable=AsyncMock, return_value=ap_inventory),
            patch(f"{_MODULE}._assign_profile", new_callable=AsyncMock),
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            state = get_state("s1")
            state.client_map = {"ap1": {"client-mac"}}
            await start_off_hours(schedule)

        assert "ap1" in state.pending_disable
        assert "ap1" not in state.disabled_aps

    async def test_state_becomes_off_hours(self):
        schedule = _make_schedule()
        mock_cls, _ = _mock_ps_class()

        with (
            patch(f"{_MODULE}.fetch_rf_neighbor_map", new_callable=AsyncMock, return_value={}),
            patch(f"{_MODULE}._get_ap_inventory", new_callable=AsyncMock, return_value=[]),
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            state = get_state("s1")
            await start_off_hours(schedule)

        assert state.status == "OFF_HOURS"

    async def test_multiple_aps_mixed_eligibility(self):
        """APs without clients are disabled; those with clients go to pending."""
        schedule = _make_schedule()
        ap_inventory = [
            {"mac": "ap1", "deviceprofile_id": "orig-prof"},
            {"mac": "ap2", "deviceprofile_id": None},
        ]
        mock_cls, _ = _mock_ps_class()

        with (
            patch(f"{_MODULE}.fetch_rf_neighbor_map", new_callable=AsyncMock, return_value={}),
            patch(f"{_MODULE}._get_ap_inventory", new_callable=AsyncMock, return_value=ap_inventory),
            patch(f"{_MODULE}._assign_profile", new_callable=AsyncMock) as mock_assign,
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            state = get_state("s1")
            state.client_map = {"ap2": {"client-mac"}}
            await start_off_hours(schedule)

        assert "ap1" in state.disabled_aps
        assert state.disabled_aps["ap1"] == "orig-prof"
        assert "ap2" in state.pending_disable
        assert "ap2" not in state.disabled_aps
        mock_assign.assert_awaited_once_with("s1", "ap1", "off-prof")

    async def test_original_profile_preserved(self):
        """The original deviceprofile_id is stored in disabled_aps for restore."""
        schedule = _make_schedule()
        ap_inventory = [{"mac": "ap1", "deviceprofile_id": "my-orig-profile"}]
        mock_cls, _ = _mock_ps_class()

        with (
            patch(f"{_MODULE}.fetch_rf_neighbor_map", new_callable=AsyncMock, return_value={}),
            patch(f"{_MODULE}._get_ap_inventory", new_callable=AsyncMock, return_value=ap_inventory),
            patch(f"{_MODULE}._assign_profile", new_callable=AsyncMock),
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            state = get_state("s1")
            state.client_map = {}
            await start_off_hours(schedule)

        assert state.disabled_aps["ap1"] == "my-orig-profile"

    async def test_db_update_called_with_off_hours(self):
        """DB is updated to OFF_HOURS after transition."""
        schedule = _make_schedule()
        mock_cls, mock_query = _mock_ps_class()

        with (
            patch(f"{_MODULE}.fetch_rf_neighbor_map", new_callable=AsyncMock, return_value={}),
            patch(f"{_MODULE}._get_ap_inventory", new_callable=AsyncMock, return_value=[]),
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            await start_off_hours(schedule)

        mock_query.update.assert_awaited_once()
        call_args = mock_query.update.call_args[0][0]
        assert call_args["$set"]["current_status"] == "OFF_HOURS"


class TestEndOffHours:
    @pytest.fixture(autouse=True)
    async def cleanup(self):
        yield
        await clear_state("s1")

    async def test_disabled_aps_restored(self):
        schedule = _make_schedule()
        mock_cls, _ = _mock_ps_class()

        with (
            patch(f"{_MODULE}._assign_profile", new_callable=AsyncMock) as mock_assign,
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            state = get_state("s1")
            state.status = "OFF_HOURS"
            state.disabled_aps = {"ap1": "orig-prof", "ap2": None}
            await end_off_hours(schedule)

        assert mock_assign.await_count == 2
        calls = {c.args[1]: c.args[2] for c in mock_assign.await_args_list}
        assert calls["ap1"] == "orig-prof"
        assert calls["ap2"] is None

    async def test_state_becomes_idle(self):
        schedule = _make_schedule()
        mock_cls, _ = _mock_ps_class()

        with (
            patch(f"{_MODULE}._assign_profile", new_callable=AsyncMock),
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            state = get_state("s1")
            state.status = "OFF_HOURS"
            state.disabled_aps = {"ap1": None}
            await end_off_hours(schedule)

        assert state.status == "IDLE"
        assert state.disabled_aps == {}

    async def test_pending_disable_cleared(self):
        schedule = _make_schedule()
        mock_cls, _ = _mock_ps_class()

        with (
            patch(f"{_MODULE}._assign_profile", new_callable=AsyncMock),
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            state = get_state("s1")
            state.status = "OFF_HOURS"
            state.pending_disable = {"ap1", "ap2"}
            await end_off_hours(schedule)

        assert state.pending_disable == set()

    async def test_db_update_called_with_idle(self):
        """DB is updated to IDLE after window end."""
        schedule = _make_schedule()
        mock_cls, mock_query = _mock_ps_class()

        with (
            patch(f"{_MODULE}._assign_profile", new_callable=AsyncMock),
            patch(f"{_MODULE}._log_event", new_callable=AsyncMock),
            patch(f"{_MODULE}.PowerSchedule", mock_cls),
        ):
            state = get_state("s1")
            state.status = "OFF_HOURS"
            await end_off_hours(schedule)

        mock_query.update.assert_awaited_once()
        call_args = mock_query.update.call_args[0][0]
        assert call_args["$set"]["current_status"] == "IDLE"
