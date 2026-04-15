"""Unit tests for the IngestionService."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.telemetry.services.cov_filter import CoVFilter
from app.modules.telemetry.services.influxdb_service import InfluxDBService
from app.modules.telemetry.services.latest_value_cache import LatestValueCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_influxdb_mock() -> InfluxDBService:
    """Create a mock InfluxDBService with an async write_points."""
    svc = MagicMock(spec=InfluxDBService)
    svc.write_points = AsyncMock()
    return svc


def _make_ws_message(site_id: str, payload: dict) -> dict:
    """Build a WebSocket message dict matching Mist format."""
    return {
        "event": "data",
        "channel": f"/sites/{site_id}/stats/devices",
        "data": json.dumps(payload),
    }


def _ap_payload(mac: str = "aabbccddeeff") -> dict:
    """Minimal full-stats AP payload (has model + radio_stat)."""
    return {
        "mac": mac,
        "name": "AP-Test",
        "model": "AP45",
        "type": "ap",
        "cpu_util": 42,
        "mem_total_kb": 1048576,
        "mem_used_kb": 524288,
        "num_clients": 5,
        "uptime": 3600,
        "last_seen": 1774576960,
        "radio_stat": {
            "band_5": {
                "channel": 36,
                "power": 20,
                "bandwidth": 80,
                "util_all": 30,
                "noise_floor": -95,
                "num_clients": 5,
            },
        },
    }


def _basic_ap_payload(mac: str = "aabbccddeeff") -> dict:
    """Basic AP payload (no model) -- should be skipped by extractors."""
    return {
        "mac": mac,
        "uptime": 3600,
        "ip_stat": {"ip": "10.0.0.1"},
        "last_seen": 1774576960,
    }


def _switch_payload(mac: str = "112233445566") -> dict:
    """Minimal switch payload."""
    return {
        "mac": mac,
        "name": "SW-Core-01",
        "type": "switch",
        "cpu_stat": {"idle": 80},
        "memory_stat": {"usage": 45},
        "uptime": 7200,
        "last_seen": 1774576960,
        "module_stat": [],
    }


# ---------------------------------------------------------------------------
# Tests: construction
# ---------------------------------------------------------------------------


class TestIngestionServiceInit:
    """Test IngestionService construction."""

    def test_creates_with_dependencies(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        assert svc._running is False
        assert svc._messages_processed == 0

    def test_get_queue_returns_bounded_queue(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        q = svc.get_queue()
        assert isinstance(q, asyncio.Queue)
        assert q.maxsize == 10_000

    def test_custom_queue_size(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
            queue_maxsize=100,
        )
        assert svc.get_queue().maxsize == 100


# ---------------------------------------------------------------------------
# Tests: message processing
# ---------------------------------------------------------------------------


class TestIngestionServiceProcessMessage:
    """Test _process_message logic."""

    @pytest.mark.asyncio
    async def test_processes_ap_message_updates_cache(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        cache = LatestValueCache()
        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=cache,
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("site-1", _ap_payload())
        await svc._process_message(msg)

        # Cache should have the device
        cached = cache.get("aabbccddeeff")
        assert cached is not None
        assert cached["mac"] == "aabbccddeeff"

    @pytest.mark.asyncio
    async def test_processes_ap_message_writes_to_influxdb(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("site-1", _ap_payload())
        await svc._process_message(msg)

        # InfluxDB should receive at least device_summary + radio_stats
        assert influxdb.write_points.called
        points = influxdb.write_points.call_args[0][0]
        measurements = [p["measurement"] for p in points]
        assert "device_summary" in measurements

    @pytest.mark.asyncio
    async def test_processes_ap_message_increments_counter(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("site-1", _ap_payload())
        await svc._process_message(msg)
        assert svc._messages_processed == 1

    @pytest.mark.asyncio
    async def test_skips_basic_ap_messages(self):
        """Basic AP payloads (no model) produce zero extractor points -- nothing written."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        cache = LatestValueCache()
        svc = IngestionService(
            influxdb=influxdb,
            cache=cache,
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("site-1", _basic_ap_payload())
        await svc._process_message(msg)

        # Basic AP messages are intentionally not cached (they are partial payloads).
        cached = cache.get("aabbccddeeff")
        assert cached is None

        # But no points to write to InfluxDB
        if influxdb.write_points.called:
            points = influxdb.write_points.call_args[0][0]
            assert len(points) == 0

    @pytest.mark.asyncio
    async def test_extracts_site_id_from_channel(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("978c48e6-6ef6-11e6-8bbf-02e208b2d34f", _ap_payload())
        await svc._process_message(msg)

        points = influxdb.write_points.call_args[0][0]
        summary = next(p for p in points if p["measurement"] == "device_summary")
        assert summary["tags"]["site_id"] == "978c48e6-6ef6-11e6-8bbf-02e208b2d34f"

    @pytest.mark.asyncio
    async def test_non_data_event_is_ignored(self):
        """Messages with event != 'data' should be ignored."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = {"event": "subscribe_ok", "channel": "/sites/s1/stats/devices"}
        await svc._process_message(msg)
        assert svc._messages_processed == 0

    @pytest.mark.asyncio
    async def test_malformed_json_data_is_handled(self):
        """data field with invalid JSON should not crash."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = {
            "event": "data",
            "channel": "/sites/s1/stats/devices",
            "data": "not valid json{{{",
        }
        await svc._process_message(msg)
        # Should not crash, message counter stays at 0
        assert svc._messages_processed == 0


# ---------------------------------------------------------------------------
# Tests: CoV filtering integration
# ---------------------------------------------------------------------------


class TestIngestionServiceCoVFiltering:
    """Test that CoV filtering is applied to non-summary measurements."""

    @pytest.mark.asyncio
    async def test_device_summary_always_written(self):
        """device_summary points should always be written (no CoV)."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("site-1", _ap_payload())
        # Process the same message twice
        await svc._process_message(msg)
        await svc._process_message(msg)

        # Both calls should include device_summary
        assert influxdb.write_points.call_count == 2
        for call in influxdb.write_points.call_args_list:
            points = call[0][0]
            summaries = [p for p in points if p["measurement"] == "device_summary"]
            assert len(summaries) == 1

    @pytest.mark.asyncio
    async def test_radio_stats_filtered_on_no_change(self):
        """Identical radio_stats continue to write monotonic counter fields."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("site-1", _ap_payload())

        # First write: all points pass
        await svc._process_message(msg)
        first_points = influxdb.write_points.call_args[0][0]
        first_radios = [p for p in first_points if p["measurement"] == "radio_stats"]
        assert len(first_radios) == 1  # band_5

        # Second write: radio_stats is still emitted because several fields are
        # configured as "always" in CoV thresholds (monotonic counters).
        await svc._process_message(msg)
        second_points = influxdb.write_points.call_args[0][0]
        second_radios = [p for p in second_points if p["measurement"] == "radio_stats"]
        assert len(second_radios) == 1

    @pytest.mark.asyncio
    async def test_radio_stats_passes_on_significant_change(self):
        """radio_stats should pass CoV when value changes beyond threshold."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )

        # First message
        payload1 = _ap_payload()
        await svc._process_message(_make_ws_message("site-1", payload1))

        # Second message with significant util_all change (>5.0 threshold)
        payload2 = _ap_payload()
        payload2["radio_stat"]["band_5"]["util_all"] = 50  # was 30, delta = 20
        await svc._process_message(_make_ws_message("site-1", payload2))

        second_points = influxdb.write_points.call_args[0][0]
        second_radios = [p for p in second_points if p["measurement"] == "radio_stats"]
        assert len(second_radios) == 1

    @pytest.mark.asyncio
    async def test_gateway_health_always_written(self):
        """gateway_health points should always be written (like device_summary)."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        gw_payload = {
            "mac": "aabb11223344",
            "type": "gateway",
            "model": "SRX300",
            "cpu_stat": {"idle": 90},
            "memory_stat": {"usage": 30},
            "uptime": 99999,
            "last_seen": 1774576960,
        }
        msg = _make_ws_message("site-1", gw_payload)
        await svc._process_message(msg)
        await svc._process_message(msg)

        # Both should have gateway_health
        for call in influxdb.write_points.call_args_list:
            points = call[0][0]
            healths = [p for p in points if p["measurement"] == "gateway_health"]
            assert len(healths) == 1


# ---------------------------------------------------------------------------
# Tests: get_stats
# ---------------------------------------------------------------------------


class TestIngestionServiceStats:
    """Test get_stats returns expected metrics."""

    @pytest.mark.asyncio
    async def test_stats_after_processing(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("site-1", _ap_payload())
        await svc._process_message(msg)

        stats = svc.get_stats()
        assert stats["messages_processed"] == 1
        assert "queue_size" in stats
        assert "queue_capacity" in stats
        assert stats["running"] is False


# ---------------------------------------------------------------------------
# Tests: start / stop lifecycle
# ---------------------------------------------------------------------------


class TestIngestionServiceLifecycle:
    """Test start and stop manage the consumer task."""

    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        await svc.start()
        assert svc._running is True
        assert svc._task is not None
        await svc.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        await svc.start()
        task = svc._task
        await svc.stop()
        assert svc._running is False
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_consume_loop_processes_queued_messages(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        await svc.start()

        # Put a message into the queue
        msg = _make_ws_message("site-1", _ap_payload())
        await svc.get_queue().put(msg)

        # Allow the consume loop to pick it up
        await asyncio.sleep(0.1)

        assert svc._messages_processed == 1
        assert influxdb.write_points.called

        await svc.stop()


# ---------------------------------------------------------------------------
# Tests: WebSocket broadcast after ingestion
# ---------------------------------------------------------------------------


class TestIngestionServiceBroadcast:
    """Test that _process_message broadcasts device events to WebSocket subscribers."""

    @pytest.mark.asyncio
    async def test_broadcast_called_for_ap_after_processing(self):
        """After processing an AP message, device + site + org broadcasts are sent."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("site-1", _ap_payload(mac="aabbccddeeff"))

        with patch(
            "app.modules.telemetry.services.ingestion_service.ws_manager"
        ) as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await svc._process_message(msg)

            assert mock_ws.broadcast.await_count == 3
            device_call = mock_ws.broadcast.await_args_list[0]
            site_call = mock_ws.broadcast.await_args_list[1]
            org_call = mock_ws.broadcast.await_args_list[2]

            channel = device_call[0][0]
            payload = device_call[0][1]

            assert channel == "telemetry:device:aabbccddeeff"
            assert payload["device_type"] == "ap"
            assert "summary" in payload
            assert "bands" in payload
            assert payload["summary"]["cpu_util"] == 42
            assert payload["summary"]["num_clients"] == 5
            assert site_call[0][0] == "telemetry:site:site-1"
            assert org_call[0][0] == "telemetry:org"

    @pytest.mark.asyncio
    async def test_broadcast_called_for_switch_after_processing(self):
        """After processing a switch message, device + site + org broadcasts are sent."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("site-1", _switch_payload(mac="112233445566"))

        with patch(
            "app.modules.telemetry.services.ingestion_service.ws_manager"
        ) as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await svc._process_message(msg)

            assert mock_ws.broadcast.await_count == 3
            device_call = mock_ws.broadcast.await_args_list[0]
            site_call = mock_ws.broadcast.await_args_list[1]
            org_call = mock_ws.broadcast.await_args_list[2]

            channel = device_call[0][0]
            payload = device_call[0][1]

            assert channel == "telemetry:device:112233445566"
            assert payload["device_type"] == "switch"
            assert "summary" in payload
            assert "ports" in payload
            assert "modules" in payload
            assert "dhcp" in payload
            assert payload["summary"]["cpu_util"] == 20  # 100 - 80 idle
            assert site_call[0][0] == "telemetry:site:site-1"
            assert org_call[0][0] == "telemetry:org"

    @pytest.mark.asyncio
    async def test_broadcast_called_for_gateway_after_processing(self):
        """After processing a gateway message, device + site + org broadcasts are sent."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        gw_payload = {
            "mac": "aabb11223344",
            "type": "gateway",
            "model": "SRX300",
            "cpu_stat": {"idle": 85},
            "memory_stat": {"usage": 40},
            "uptime": 99999,
            "last_seen": 1774576960,
            "ha_state": "active",
            "config_status": "synced",
            "spu_stat": [
                {
                    "spu_cpu": 15,
                    "spu_current_session": 500,
                    "spu_max_session": 10000,
                    "spu_memory": 25,
                }
            ],
        }
        msg = _make_ws_message("site-1", gw_payload)

        with patch(
            "app.modules.telemetry.services.ingestion_service.ws_manager"
        ) as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await svc._process_message(msg)

            assert mock_ws.broadcast.await_count == 3
            device_call = mock_ws.broadcast.await_args_list[0]
            site_call = mock_ws.broadcast.await_args_list[1]
            org_call = mock_ws.broadcast.await_args_list[2]

            channel = device_call[0][0]
            payload = device_call[0][1]

            assert channel == "telemetry:device:aabb11223344"
            assert payload["device_type"] == "gateway"
            assert "summary" in payload
            assert "wan" in payload
            assert "dhcp" in payload
            assert "spu" in payload
            assert payload["summary"]["cpu_util"] == 15  # 100 - 85 idle
            assert payload["summary"]["ha_state"] == "active"
            assert payload["spu"]["spu_sessions"] == 500
            assert site_call[0][0] == "telemetry:site:site-1"
            assert org_call[0][0] == "telemetry:org"

    @pytest.mark.asyncio
    async def test_no_broadcast_when_mac_missing(self):
        """Messages without MAC don't trigger broadcast."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        payload_no_mac = {
            "type": "ap",
            "model": "AP45",
            "cpu_util": 10,
            "uptime": 100,
            "last_seen": 1774576960,
        }
        msg = _make_ws_message("site-1", payload_no_mac)

        with patch(
            "app.modules.telemetry.services.ingestion_service.ws_manager"
        ) as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await svc._process_message(msg)
            mock_ws.broadcast.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_broadcast_when_device_type_missing(self):
        """Messages without device_type don't trigger broadcast."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        # Basic payload: has mac but no type and model doesn't start with AP
        payload_no_type = {
            "mac": "aabbccddeeff",
            "uptime": 3600,
            "last_seen": 1774576960,
        }
        msg = _make_ws_message("site-1", payload_no_type)

        with patch(
            "app.modules.telemetry.services.ingestion_service.ws_manager"
        ) as mock_ws:
            mock_ws.broadcast = AsyncMock()
            await svc._process_message(msg)
            mock_ws.broadcast.assert_not_awaited()
