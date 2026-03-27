"""Unit tests for MistWsManager.

The WS manager wraps thread-based mistapi.websockets.sites.DeviceStatsEvents.
We test the logic (site chunking, state management, status reporting) with
mocked DeviceStatsEvents, NOT actual WebSocket connections.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_ws(ready: bool = True):
    """Create a mock DeviceStatsEvents instance."""
    ws = MagicMock()
    ws.ready.return_value = ready
    ws.connect.return_value = None
    ws.disconnect.return_value = None
    ws.on_message.return_value = None
    return ws


def _make_queue() -> asyncio.Queue:
    return asyncio.Queue(maxsize=10_000)


def _make_api_session() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests: construction
# ---------------------------------------------------------------------------


class TestMistWsManagerInit:
    """Test construction and initial state."""

    def test_creates_with_session_and_queue(self):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        assert mgr._connections == []
        assert mgr._subscribed_sites == []

    def test_initial_status(self):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        status = mgr.get_status()
        assert status["connections"] == 0
        assert status["sites_subscribed"] == 0
        assert status["all_ready"] is True  # vacuously true with no connections


# ---------------------------------------------------------------------------
# Tests: site chunking
# ---------------------------------------------------------------------------


class TestMistWsManagerChunking:
    """Test that sites are grouped into chunks of 1000."""

    def test_chunk_sites_small(self):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        sites = [f"site-{i}" for i in range(50)]
        chunks = mgr._chunk_sites(sites)
        assert len(chunks) == 1
        assert len(chunks[0]) == 50

    def test_chunk_sites_exactly_1000(self):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        sites = [f"site-{i}" for i in range(1000)]
        chunks = mgr._chunk_sites(sites)
        assert len(chunks) == 1
        assert len(chunks[0]) == 1000

    def test_chunk_sites_over_1000(self):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        sites = [f"site-{i}" for i in range(1500)]
        chunks = mgr._chunk_sites(sites)
        assert len(chunks) == 2
        assert len(chunks[0]) == 1000
        assert len(chunks[1]) == 500

    def test_chunk_sites_empty(self):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        chunks = mgr._chunk_sites([])
        assert chunks == []


# ---------------------------------------------------------------------------
# Tests: start with mocked DeviceStatsEvents
# ---------------------------------------------------------------------------


class TestMistWsManagerStart:
    """Test start creates connections for site chunks."""

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_start_creates_one_connection_for_small_list(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mock_ws_cls.return_value = _make_mock_ws()

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        await mgr.start(["site-1", "site-2", "site-3"])

        assert mock_ws_cls.call_count == 1
        assert len(mgr._connections) == 1
        assert mgr._subscribed_sites == ["site-1", "site-2", "site-3"]

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_start_creates_two_connections_for_1500_sites(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mock_ws_cls.return_value = _make_mock_ws()

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        sites = [f"site-{i}" for i in range(1500)]
        await mgr.start(sites)

        assert mock_ws_cls.call_count == 2
        assert len(mgr._connections) == 2
        assert len(mgr._subscribed_sites) == 1500

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_start_registers_on_message_callback(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mock_ws = _make_mock_ws()
        mock_ws_cls.return_value = mock_ws

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        await mgr.start(["site-1"])

        mock_ws.on_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_start_calls_connect_with_background(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mock_ws = _make_mock_ws()
        mock_ws_cls.return_value = mock_ws

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        await mgr.start(["site-1"])

        mock_ws.connect.assert_called_once_with(run_in_background=True)

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_start_with_empty_sites_does_nothing(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        await mgr.start([])

        assert mock_ws_cls.call_count == 0
        assert mgr._connections == []


# ---------------------------------------------------------------------------
# Tests: stop
# ---------------------------------------------------------------------------


class TestMistWsManagerStop:
    """Test stop disconnects all connections."""

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_stop_disconnects_all(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mock_ws = _make_mock_ws()
        mock_ws_cls.return_value = mock_ws

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        await mgr.start(["site-1"])
        await mgr.stop()

        mock_ws.disconnect.assert_called_once()
        assert mgr._connections == []
        assert mgr._subscribed_sites == []


# ---------------------------------------------------------------------------
# Tests: get_status
# ---------------------------------------------------------------------------


class TestMistWsManagerStatus:
    """Test status reporting."""

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_status_after_start(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mock_ws = _make_mock_ws(ready=True)
        mock_ws_cls.return_value = mock_ws

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        await mgr.start(["site-1", "site-2"])

        status = mgr.get_status()
        assert status["connections"] == 1
        assert status["sites_subscribed"] == 2
        assert status["all_ready"] is True

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_status_not_ready(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mock_ws = _make_mock_ws(ready=False)
        mock_ws_cls.return_value = mock_ws

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        await mgr.start(["site-1"])

        status = mgr.get_status()
        assert status["all_ready"] is False


# ---------------------------------------------------------------------------
# Tests: message bridging callback
# ---------------------------------------------------------------------------


class TestMistWsManagerBridge:
    """Test the thread-to-asyncio message bridge callback."""

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_bridge_callback_puts_message_in_queue(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mock_ws = _make_mock_ws()
        mock_ws_cls.return_value = mock_ws

        queue = _make_queue()
        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=queue,
        )
        await mgr.start(["site-1"])

        # Simulate calling the bridge method (as the WS thread would via on_message callback)
        # _on_ws_message uses loop.call_soon_threadsafe to post into the queue
        test_msg = {"event": "data", "channel": "/sites/s1/stats/devices", "data": "{}"}
        mgr._on_ws_message(test_msg)

        # Give the event loop a chance to process
        await asyncio.sleep(0.05)

        assert queue.qsize() == 1
        assert queue.get_nowait() == test_msg

        await mgr.stop()
