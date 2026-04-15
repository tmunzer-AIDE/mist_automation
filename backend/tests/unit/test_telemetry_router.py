"""Integration-style tests for telemetry router endpoints.

Uses the shared httpx AsyncClient fixture with mocked telemetry singletons.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetLatestStats:
    """Tests for GET /telemetry/latest/{mac}."""

    async def test_returns_fresh_stats(self, client):
        """When cache has fresh data, returns it with fresh=True."""
        from app.modules.telemetry.services.latest_value_cache import LatestValueCache

        cache = LatestValueCache()
        cache.update("aabbccddeeff", {"cpu_util": 42, "site_id": "test-site"})

        with patch("app.modules.telemetry._latest_cache", cache):
            resp = await client.get("/api/v1/telemetry/latest/aabbccddeeff")

        assert resp.status_code == 200
        data = resp.json()
        assert data["mac"] == "aabbccddeeff"
        assert data["fresh"] is True
        assert data["stats"]["cpu_util"] == 42

    async def test_returns_stale_stats(self, client):
        """When cache data is old, returns it with fresh=False."""
        from app.modules.telemetry.services.latest_value_cache import LatestValueCache

        cache = LatestValueCache()
        cache.update("aabbccddeeff", {"cpu_util": 42})
        cache._entries["aabbccddeeff"]["updated_at"] = time.time() - 120

        with patch("app.modules.telemetry._latest_cache", cache):
            resp = await client.get("/api/v1/telemetry/latest/aabbccddeeff")

        assert resp.status_code == 200
        data = resp.json()
        assert data["fresh"] is False
        assert data["stats"]["cpu_util"] == 42

    async def test_returns_empty_when_not_cached(self, client):
        """When MAC not in cache, returns fresh=False with no stats."""
        from app.modules.telemetry.services.latest_value_cache import LatestValueCache

        cache = LatestValueCache()
        with patch("app.modules.telemetry._latest_cache", cache):
            resp = await client.get("/api/v1/telemetry/latest/000000000000")

        assert resp.status_code == 200
        data = resp.json()
        assert data["fresh"] is False
        assert data["stats"] is None

    async def test_returns_empty_when_cache_not_initialized(self, client):
        """When telemetry is disabled (no cache), returns gracefully."""
        with patch("app.modules.telemetry._latest_cache", None):
            resp = await client.get("/api/v1/telemetry/latest/aabbccddeeff")

        assert resp.status_code == 200
        assert resp.json()["fresh"] is False

    async def test_rejects_invalid_mac(self, client):
        """Invalid MAC format returns 400."""
        from app.modules.telemetry.services.latest_value_cache import LatestValueCache

        with patch("app.modules.telemetry._latest_cache", LatestValueCache()):
            resp = await client.get("/api/v1/telemetry/latest/INVALID-MAC")

        assert resp.status_code == 400

    async def test_accepts_colon_mac(self, client):
        """Colon-separated MAC is accepted and normalized."""
        from app.modules.telemetry.services.latest_value_cache import LatestValueCache

        cache = LatestValueCache()
        cache.update("aabbccddeeff", {"cpu_util": 42})
        with patch("app.modules.telemetry._latest_cache", cache):
            resp = await client.get("/api/v1/telemetry/latest/aa:bb:cc:dd:ee:ff")

        assert resp.status_code == 200
        assert resp.json()["mac"] == "aabbccddeeff"


class TestQueryRange:
    """Tests for GET /telemetry/query/range."""

    async def test_returns_503_when_disabled(self, client):
        """When InfluxDB service is not initialized, returns 503."""
        with patch("app.modules.telemetry._influxdb_service", None):
            resp = await client.get(
                "/api/v1/telemetry/query/range",
                params={"mac": "aabbccddeeff", "measurement": "device_summary"},
            )
        assert resp.status_code == 503

    async def test_returns_data_on_success(self, client):
        """Returns query results from InfluxDB."""
        mock_svc = AsyncMock()
        mock_svc.query_range = AsyncMock(
            return_value=[
                {"_time": "2026-03-26T10:00:00Z", "cpu_util": 42.5},
            ]
        )

        with patch("app.modules.telemetry._influxdb_service", mock_svc):
            resp = await client.get(
                "/api/v1/telemetry/query/range",
                params={"mac": "aabbccddeeff", "measurement": "device_summary", "start": "-1h"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["points"][0]["cpu_util"] == 42.5

    async def test_rejects_invalid_measurement(self, client):
        """Invalid measurement returns 400."""
        mock_svc = AsyncMock()
        with patch("app.modules.telemetry._influxdb_service", mock_svc):
            resp = await client.get(
                "/api/v1/telemetry/query/range",
                params={"mac": "aabbccddeeff", "measurement": "DROP_BUCKET"},
            )
        assert resp.status_code == 400

    async def test_rejects_invalid_mac(self, client):
        """Invalid MAC in query param returns 400."""
        mock_svc = AsyncMock()
        with patch("app.modules.telemetry._influxdb_service", mock_svc):
            resp = await client.get(
                "/api/v1/telemetry/query/range",
                params={"mac": "'; DELETE --", "measurement": "device_summary"},
            )
        assert resp.status_code == 400

    async def test_rejects_invalid_start(self, client):
        """Invalid start duration returns 400."""
        mock_svc = AsyncMock()
        with patch("app.modules.telemetry._influxdb_service", mock_svc):
            resp = await client.get(
                "/api/v1/telemetry/query/range",
                params={"mac": "aabbccddeeff", "measurement": "device_summary", "start": "DROP BUCKET"},
            )
        assert resp.status_code == 400

    async def test_normalizes_mac_in_response(self, client):
        """Colon-format MAC is normalized in the response."""
        mock_svc = AsyncMock()
        mock_svc.query_range = AsyncMock(return_value=[])

        with patch("app.modules.telemetry._influxdb_service", mock_svc):
            resp = await client.get(
                "/api/v1/telemetry/query/range",
                params={"mac": "aa:bb:cc:dd:ee:ff", "measurement": "device_summary"},
            )

        assert resp.status_code == 200
        assert resp.json()["mac"] == "aabbccddeeff"


class TestQueryAggregate:
    """Tests for GET /telemetry/query/aggregate."""

    async def test_returns_503_when_disabled(self, client):
        with patch("app.modules.telemetry._influxdb_service", None):
            resp = await client.get(
                "/api/v1/telemetry/query/aggregate",
                params={
                    "site_id": "12345678-1234-1234-1234-123456789012",
                    "field": "cpu_util",
                },
            )
        assert resp.status_code == 503

    async def test_returns_aggregated_data(self, client):
        mock_svc = AsyncMock()
        mock_svc.query_aggregate = AsyncMock(
            return_value=[
                {"_time": "2026-03-26T10:00:00Z", "_value": 45.2},
                {"_time": "2026-03-26T10:05:00Z", "_value": 48.7},
            ]
        )

        with patch("app.modules.telemetry._influxdb_service", mock_svc):
            resp = await client.get(
                "/api/v1/telemetry/query/aggregate",
                params={
                    "site_id": "12345678-1234-1234-1234-123456789012",
                    "field": "cpu_util",
                    "agg": "mean",
                    "window": "5m",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

    async def test_rejects_invalid_agg(self, client):
        mock_svc = AsyncMock()
        with patch("app.modules.telemetry._influxdb_service", mock_svc):
            resp = await client.get(
                "/api/v1/telemetry/query/aggregate",
                params={
                    "site_id": "12345678-1234-1234-1234-123456789012",
                    "field": "cpu_util",
                    "agg": "DELETE",
                },
            )
        assert resp.status_code == 400

    async def test_rejects_invalid_field_injection(self, client):
        mock_svc = AsyncMock()
        with patch("app.modules.telemetry._influxdb_service", mock_svc):
            resp = await client.get(
                "/api/v1/telemetry/query/aggregate",
                params={
                    "site_id": "12345678-1234-1234-1234-123456789012",
                    "field": 'cpu"; MALICIOUS',
                },
            )
        assert resp.status_code == 400

    async def test_rejects_invalid_site_id(self, client):
        mock_svc = AsyncMock()
        with patch("app.modules.telemetry._influxdb_service", mock_svc):
            resp = await client.get(
                "/api/v1/telemetry/query/aggregate",
                params={"site_id": "not-a-uuid", "field": "cpu_util"},
            )
        assert resp.status_code == 400

    async def test_rejects_invalid_window(self, client):
        mock_svc = AsyncMock()
        with patch("app.modules.telemetry._influxdb_service", mock_svc):
            resp = await client.get(
                "/api/v1/telemetry/query/aggregate",
                params={
                    "site_id": "12345678-1234-1234-1234-123456789012",
                    "field": "cpu_util",
                    "window": "abc",
                },
            )
        assert resp.status_code == 400


class TestTelemetrySettings:
    """Tests for GET /telemetry/settings (read-only, env-var-driven)."""

    async def test_get_settings(self, client, test_db):
        """Returns current telemetry settings from env vars."""
        resp = await client.get("/api/v1/telemetry/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "influxdb_url" in data
        assert "influxdb_token_set" in data
        assert "influxdb_org" in data
        assert "influxdb_bucket" in data
        # Token value never returned, only boolean flag
        assert "influxdb_token" not in data
        # Removed fields should not appear
        assert "telemetry_enabled" not in data
        assert "telemetry_retention_days" not in data

    async def test_put_settings_removed(self, client, test_db):
        """PUT endpoint no longer exists."""
        resp = await client.put(
            "/api/v1/telemetry/settings",
            json={"influxdb_url": "http://influx:8086"},
        )
        assert resp.status_code == 405


class TestReconnect:
    """Tests for POST /telemetry/reconnect."""

    async def test_reconnect_when_ws_not_initialized(self, client):
        with (
            patch(
                "app.modules.telemetry.services.lifecycle.stop_telemetry_pipeline",
                new_callable=AsyncMock,
            ) as mock_stop,
            patch(
                "app.modules.telemetry.services.lifecycle.start_telemetry_pipeline",
                new_callable=AsyncMock,
                return_value={"connections": 0, "sites": 0},
            ) as mock_start,
        ):
            resp = await client.post("/api/v1/telemetry/reconnect")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reconnected"] is True
        assert data["connections"] == 0
        assert data["sites"] == 0
        mock_stop.assert_awaited_once()
        mock_start.assert_awaited_once()

    async def test_reconnect_success(self, client):
        with (
            patch(
                "app.modules.telemetry.services.lifecycle.stop_telemetry_pipeline",
                new_callable=AsyncMock,
            ) as mock_stop,
            patch(
                "app.modules.telemetry.services.lifecycle.start_telemetry_pipeline",
                new_callable=AsyncMock,
                return_value={"connections": 1, "sites": 2},
            ) as mock_start,
        ):
            resp = await client.post("/api/v1/telemetry/reconnect")

        assert resp.status_code == 200
        data = resp.json()
        assert data["reconnected"] is True
        assert data["connections"] == 1
        assert data["sites"] == 2
        mock_stop.assert_awaited_once()
        mock_start.assert_awaited_once()

    async def test_reconnect_no_sites_skips_start(self, client):
        """When no sites are subscribed, stop is called but start is not."""
        mock_ws = AsyncMock()
        mock_ws._subscribed_sites = []
        mock_ws.stop = AsyncMock()
        mock_ws.start = AsyncMock()
        mock_ws.get_status = MagicMock(return_value={"connections": 0, "sites_subscribed": 0})

        with patch("app.modules.telemetry._ws_manager", mock_ws):
            resp = await client.post("/api/v1/telemetry/reconnect")

        assert resp.status_code == 200
        assert resp.json()["reconnected"] is True
        mock_ws.stop.assert_called_once()
        mock_ws.start.assert_not_called()

    async def test_reconnect_exception_returns_gracefully(self, client):
        """Exception during reconnect is caught and returns reconnected=False."""
        with (
            patch(
                "app.modules.telemetry.services.lifecycle.stop_telemetry_pipeline",
                new_callable=AsyncMock,
            ) as mock_stop,
            patch(
                "app.modules.telemetry.services.lifecycle.start_telemetry_pipeline",
                new_callable=AsyncMock,
                side_effect=Exception("connection error"),
            ),
        ):
            resp = await client.post("/api/v1/telemetry/reconnect")

        assert resp.status_code == 200
        data = resp.json()
        assert data["reconnected"] is False
        assert data["message"] == "Pipeline reconnection failed"
        assert mock_stop.await_count == 2
