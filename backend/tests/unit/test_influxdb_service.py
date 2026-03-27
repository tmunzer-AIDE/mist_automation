"""Unit tests for InfluxDBService with mocked InfluxDB client."""

from unittest.mock import AsyncMock

import pytest

from app.modules.telemetry.services.influxdb_service import InfluxDBService


class TestInfluxDBServiceInit:
    """Test construction and configuration."""

    def test_creates_with_defaults(self):
        svc = InfluxDBService(
            url="http://localhost:8086",
            token="test-token",
            org="test-org",
            bucket="test-bucket",
        )
        assert svc.url == "http://localhost:8086"
        assert svc.org == "test-org"
        assert svc.bucket == "test-bucket"
        assert svc._client is None

    def test_custom_buffer_size(self):
        svc = InfluxDBService(
            url="http://localhost:8086",
            token="t",
            org="o",
            bucket="b",
            buffer_size=100,
        )
        assert svc._buffer.maxsize == 100


class TestInfluxDBServiceWritePoints:
    """Test write_points queues data correctly."""

    @pytest.mark.asyncio
    async def test_write_points_adds_to_buffer(self):
        svc = InfluxDBService(url="http://localhost:8086", token="t", org="o", bucket="b")
        points = [{"measurement": "device_summary", "tags": {"mac": "aa:bb"}, "fields": {"cpu": 42}, "time": 1000}]
        await svc.write_points(points)
        assert svc._buffer.qsize() == 1

    @pytest.mark.asyncio
    async def test_write_points_multiple(self):
        svc = InfluxDBService(url="http://localhost:8086", token="t", org="o", bucket="b")
        for i in range(5):
            await svc.write_points([{"measurement": "m", "tags": {}, "fields": {"v": i}, "time": i}])
        assert svc._buffer.qsize() == 5

    @pytest.mark.asyncio
    async def test_write_points_drops_when_buffer_full(self):
        svc = InfluxDBService(url="http://localhost:8086", token="t", org="o", bucket="b", buffer_size=2)
        for i in range(5):
            await svc.write_points([{"measurement": "m", "tags": {}, "fields": {"v": i}, "time": i}])
        # Buffer should have at most 2 items (others dropped)
        assert svc._buffer.qsize() <= 2


class TestInfluxDBServiceFlush:
    """Test flush drains buffer and writes to InfluxDB."""

    @pytest.mark.asyncio
    async def test_flush_writes_buffered_points(self):
        svc = InfluxDBService(url="http://localhost:8086", token="t", org="o", bucket="b")
        # Mock the write API
        mock_write_api = AsyncMock()
        svc._write_api = mock_write_api

        for i in range(3):
            await svc.write_points([{"measurement": "m", "tags": {}, "fields": {"v": i}, "time": i}])

        await svc._flush()
        assert mock_write_api.write.called
        assert svc._buffer.qsize() == 0

    @pytest.mark.asyncio
    async def test_flush_does_nothing_when_empty(self):
        svc = InfluxDBService(url="http://localhost:8086", token="t", org="o", bucket="b")
        mock_write_api = AsyncMock()
        svc._write_api = mock_write_api
        await svc._flush()
        assert not mock_write_api.write.called


class TestInfluxDBServiceStats:
    """Test stats tracking."""

    @pytest.mark.asyncio
    async def test_stats_reports_buffer_size(self):
        svc = InfluxDBService(url="http://localhost:8086", token="t", org="o", bucket="b")
        await svc.write_points([{"measurement": "m", "tags": {}, "fields": {"v": 1}, "time": 1}])
        stats = svc.get_stats()
        assert stats["buffer_size"] == 1
        assert stats["connected"] is False
