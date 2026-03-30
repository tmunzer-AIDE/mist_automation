import pytest
import pytest_asyncio
from app.modules.power_scheduling.state import get_state, clear_state, PowerScheduleState


class TestStateStore:
    @pytest_asyncio.fixture(autouse=True)
    async def cleanup(self):
        yield
        await clear_state("site-1")
        await clear_state("site-2")

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
