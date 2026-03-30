from unittest.mock import AsyncMock, patch

VALID_PAYLOAD = {
    "site_id": "site-abc",
    "site_name": "HQ",
    "windows": [{"days": [0, 1, 2, 3, 4], "start": "22:00", "end": "06:00"}],
    "grace_period_minutes": 5,
    "critical_ap_macs": [],
}


class TestCreateSchedule:
    async def test_create_returns_201(self, client, test_db):
        with (
            patch(
                "app.modules.power_scheduling.router._setup_mist_profile",
                new_callable=AsyncMock,
                return_value="prof-id",
            ),
            patch(
                "app.modules.power_scheduling.router._fetch_site_timezone",
                new_callable=AsyncMock,
                return_value="America/New_York",
            ),
            patch("app.modules.power_scheduling.router._register_jobs"),
        ):
            resp = await client.post("/api/v1/power-scheduling/sites/site-abc", json=VALID_PAYLOAD)
        assert resp.status_code == 201
        data = resp.json()
        assert data["site_id"] == "site-abc"
        assert data["timezone"] == "America/New_York"

    async def test_duplicate_site_returns_409(self, client, test_db):
        with (
            patch(
                "app.modules.power_scheduling.router._setup_mist_profile",
                new_callable=AsyncMock,
                return_value="prof-id",
            ),
            patch(
                "app.modules.power_scheduling.router._fetch_site_timezone",
                new_callable=AsyncMock,
                return_value="UTC",
            ),
            patch("app.modules.power_scheduling.router._register_jobs"),
        ):
            await client.post("/api/v1/power-scheduling/sites/site-abc", json=VALID_PAYLOAD)
            resp = await client.post("/api/v1/power-scheduling/sites/site-abc", json=VALID_PAYLOAD)
        assert resp.status_code == 409


class TestListSchedules:
    async def test_list_returns_empty(self, client, test_db):
        resp = await client.get("/api/v1/power-scheduling/sites")
        assert resp.status_code == 200
        assert resp.json() == []


class TestManualTrigger:
    async def test_trigger_start(self, client, test_db):
        with (
            patch(
                "app.modules.power_scheduling.router._setup_mist_profile",
                new_callable=AsyncMock,
                return_value="prof-id",
            ),
            patch(
                "app.modules.power_scheduling.router._fetch_site_timezone",
                new_callable=AsyncMock,
                return_value="UTC",
            ),
            patch("app.modules.power_scheduling.router._register_jobs"),
            patch(
                "app.modules.power_scheduling.router.start_off_hours",
                new_callable=AsyncMock,
            ),
        ):
            await client.post("/api/v1/power-scheduling/sites/site-abc", json=VALID_PAYLOAD)
            resp = await client.post(
                "/api/v1/power-scheduling/sites/site-abc/trigger",
                json={"action": "start"},
            )
        assert resp.status_code == 200
