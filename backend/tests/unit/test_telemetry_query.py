"""Unit tests for InfluxDBService query methods with mocked InfluxDB client."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.telemetry.services.influxdb_service import InfluxDBService


def _make_svc() -> InfluxDBService:
    """Create an InfluxDBService with a mocked client."""
    svc = InfluxDBService(url="http://localhost:8086", token="t", org="o", bucket="test-bucket")
    svc._client = MagicMock()
    return svc


def _mock_tables(rows: list[dict]) -> list:
    """Build mock FluxTable/FluxRecord results."""
    records = []
    for row in rows:
        record = MagicMock()
        record.values = row
        records.append(record)

    table = MagicMock()
    table.records = records
    return [table]


class TestQueryRange:
    """Tests for query_range method."""

    async def test_returns_empty_when_no_client(self):
        svc = InfluxDBService(url="http://localhost:8086", token="t", org="o", bucket="b")
        result = await svc.query_range("aabbccddeeff", "device_summary")
        assert result == []

    async def test_returns_records_on_success(self):
        svc = _make_svc()
        rows = [
            {"_time": "2026-03-26T10:00:00Z", "cpu_util": 42.5, "mem_usage": 65.0},
            {"_time": "2026-03-26T10:00:30Z", "cpu_util": 43.1, "mem_usage": 64.8},
        ]
        mock_query_api = AsyncMock()
        mock_query_api.query = AsyncMock(return_value=_mock_tables(rows))
        svc._client.query_api = MagicMock(return_value=mock_query_api)

        result = await svc.query_range("aabbccddeeff", "device_summary", "-1h", "now()")
        assert len(result) == 2
        assert result[0]["cpu_util"] == 42.5
        assert result[1]["cpu_util"] == 43.1

    async def test_query_contains_mac_and_measurement(self):
        svc = _make_svc()
        mock_query_api = AsyncMock()
        mock_query_api.query = AsyncMock(return_value=[])
        svc._client.query_api = MagicMock(return_value=mock_query_api)

        await svc.query_range("aabbccddeeff", "radio_stats", "-30m", "now()")

        called_query = mock_query_api.query.call_args[0][0]
        assert '"radio_stats"' in called_query
        assert '"aabbccddeeff"' in called_query
        assert "range(start: -30m" in called_query

    async def test_returns_empty_on_exception(self):
        svc = _make_svc()
        mock_query_api = AsyncMock()
        mock_query_api.query = AsyncMock(side_effect=Exception("connection refused"))
        svc._client.query_api = MagicMock(return_value=mock_query_api)

        result = await svc.query_range("aabbccddeeff", "device_summary")
        assert result == []
        assert svc._last_error == "connection refused"


class TestQueryLatest:
    """Tests for query_latest method."""

    async def test_returns_none_when_no_client(self):
        svc = InfluxDBService(url="http://localhost:8086", token="t", org="o", bucket="b")
        result = await svc.query_latest("aabbccddeeff")
        assert result is None

    async def test_returns_single_record(self):
        svc = _make_svc()
        rows = [{"_time": "2026-03-26T10:00:30Z", "cpu_util": 55.0, "uptime": 86400}]
        mock_query_api = AsyncMock()
        mock_query_api.query = AsyncMock(return_value=_mock_tables(rows))
        svc._client.query_api = MagicMock(return_value=mock_query_api)

        result = await svc.query_latest("aabbccddeeff", "device_summary")
        assert result is not None
        assert result["cpu_util"] == 55.0

    async def test_returns_none_when_empty(self):
        svc = _make_svc()
        mock_query_api = AsyncMock()
        mock_query_api.query = AsyncMock(return_value=[])
        svc._client.query_api = MagicMock(return_value=mock_query_api)

        result = await svc.query_latest("aabbccddeeff")
        assert result is None

    async def test_returns_none_on_exception(self):
        svc = _make_svc()
        mock_query_api = AsyncMock()
        mock_query_api.query = AsyncMock(side_effect=Exception("timeout"))
        svc._client.query_api = MagicMock(return_value=mock_query_api)

        result = await svc.query_latest("aabbccddeeff")
        assert result is None


class TestQueryAggregate:
    """Tests for query_aggregate method."""

    async def test_returns_empty_when_no_client(self):
        svc = InfluxDBService(url="http://localhost:8086", token="t", org="o", bucket="b")
        result = await svc.query_aggregate(
            measurement="device_summary",
            field="cpu_util",
            site_id="12345678-1234-1234-1234-123456789012",
        )
        assert result == []

    async def test_returns_aggregated_records(self):
        svc = _make_svc()
        rows = [
            {"_time": "2026-03-26T10:00:00Z", "_value": 45.2},
            {"_time": "2026-03-26T10:05:00Z", "_value": 48.7},
        ]
        mock_query_api = AsyncMock()
        mock_query_api.query = AsyncMock(return_value=_mock_tables(rows))
        svc._client.query_api = MagicMock(return_value=mock_query_api)

        result = await svc.query_aggregate(
            measurement="device_summary",
            field="cpu_util",
            site_id="12345678-1234-1234-1234-123456789012",
            agg="mean",
            window="5m",
        )
        assert len(result) == 2
        assert result[0]["_value"] == 45.2

    async def test_query_contains_agg_and_window(self):
        svc = _make_svc()
        mock_query_api = AsyncMock()
        mock_query_api.query = AsyncMock(return_value=[])
        svc._client.query_api = MagicMock(return_value=mock_query_api)

        await svc.query_aggregate(
            measurement="device_summary",
            field="cpu_util",
            site_id="12345678-1234-1234-1234-123456789012",
            agg="max",
            window="10m",
        )
        called_query = mock_query_api.query.call_args[0][0]
        assert "fn: max" in called_query
        assert "every: 10m" in called_query
        assert '"cpu_util"' in called_query

    async def test_returns_empty_on_exception(self):
        svc = _make_svc()
        mock_query_api = AsyncMock()
        mock_query_api.query = AsyncMock(side_effect=Exception("bucket not found"))
        svc._client.query_api = MagicMock(return_value=mock_query_api)

        result = await svc.query_aggregate(
            measurement="device_summary",
            field="cpu_util",
            site_id="12345678-1234-1234-1234-123456789012",
        )
        assert result == []
        assert svc._last_error == "bucket not found"
