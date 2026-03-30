import asyncio

import pytest_asyncio

from app.modules.power_scheduling.state import clear_state, get_state


class TestStateStore:
    @pytest_asyncio.fixture(autouse=True)
    async def cleanup(self):
        yield
        await clear_state("site-1")
        await clear_state("site-2")
        await clear_state("site-cancel")

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

    async def test_clear_state_cancels_grace_tasks(self):
        state = get_state("site-cancel")
        task = asyncio.create_task(asyncio.sleep(9999))
        state.grace_tasks["ap1"] = task
        await clear_state("site-cancel")
        assert task.cancelled()
