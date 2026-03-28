"""Unit tests for system health aggregation."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.v1.system_health import collect_system_health


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.command = AsyncMock(return_value={
        "collections": 12,
        "objects": 45321,
        "dataSize": 134742016,
    })
    db.client.server_info = AsyncMock(return_value={"uptime": 1209600})
    return db


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.info = AsyncMock(side_effect=lambda section: {
        "memory": {"used_memory": 25480396},
        "clients": {"connected_clients": 3},
        "server": {"uptime_in_seconds": 1209600},
    }.get(section, {}))
    r.ping = AsyncMock(return_value=True)
    r.aclose = AsyncMock()
    return r


@pytest.fixture
def mock_telemetry():
    """Patch telemetry module singletons."""
    with patch("app.api.v1.system_health.app.modules.telemetry") as mock:
        mock._influxdb_service = None
        mock._ws_manager = None
        mock._ingestion_service = None
        yield mock


@pytest.fixture
def mock_ws_manager():
    with patch("app.api.v1.system_health.ws_manager") as mock:
        mock.get_stats.return_value = {"connected_clients": 2, "active_channels": 3, "total_subscriptions": 5}
        yield mock


@pytest.fixture
def mock_scheduler():
    with patch("app.api.v1.system_health.get_scheduler") as mock:
        sched = MagicMock()
        sched._initialized = True
        sched.get_scheduled_workflows.return_value = [{"id": "1"}, {"id": "2"}]
        mock.return_value = sched
        yield mock


class TestCollectSystemHealth:
    async def test_returns_all_service_keys(self, mock_db, mock_redis):
        with (
            patch("app.api.v1.system_health.Database") as MockDB,
            patch("app.api.v1.system_health._get_redis_client", return_value=mock_redis),
        ):
            MockDB.get_database.return_value = mock_db
            result = await collect_system_health()

        assert "overall_status" in result
        assert "checked_at" in result
        assert "services" in result
        svc = result["services"]
        assert set(svc.keys()) == {"mongodb", "redis", "influxdb", "mist_websocket", "ingestion", "app_websocket", "scheduler"}

    async def test_mongodb_connected(self, mock_db, mock_redis):
        with (
            patch("app.api.v1.system_health.Database") as MockDB,
            patch("app.api.v1.system_health._get_redis_client", return_value=mock_redis),
        ):
            MockDB.get_database.return_value = mock_db
            result = await collect_system_health()

        mongo = result["services"]["mongodb"]
        assert mongo["status"] == "connected"
        assert mongo["collections"] == 12
        assert mongo["total_documents"] == 45321
        assert mongo["storage_size_mb"] == 128.5

    async def test_mongodb_failure(self, mock_redis):
        with (
            patch("app.api.v1.system_health.Database") as MockDB,
            patch("app.api.v1.system_health._get_redis_client", return_value=mock_redis),
        ):
            MockDB.get_database.side_effect = RuntimeError("not connected")
            result = await collect_system_health()

        assert result["services"]["mongodb"]["status"] == "disconnected"
        assert result["overall_status"] == "down"

    async def test_redis_connected(self, mock_db, mock_redis):
        with (
            patch("app.api.v1.system_health.Database") as MockDB,
            patch("app.api.v1.system_health._get_redis_client", return_value=mock_redis),
        ):
            MockDB.get_database.return_value = mock_db
            result = await collect_system_health()

        redis_health = result["services"]["redis"]
        assert redis_health["status"] == "connected"
        assert redis_health["connected_clients"] == 3

    async def test_redis_failure(self, mock_db):
        bad_redis = AsyncMock()
        bad_redis.ping = AsyncMock(side_effect=Exception("refused"))
        bad_redis.aclose = AsyncMock()
        with (
            patch("app.api.v1.system_health.Database") as MockDB,
            patch("app.api.v1.system_health._get_redis_client", return_value=bad_redis),
        ):
            MockDB.get_database.return_value = mock_db
            result = await collect_system_health()

        assert result["services"]["redis"]["status"] == "disconnected"
        assert result["overall_status"] == "down"
