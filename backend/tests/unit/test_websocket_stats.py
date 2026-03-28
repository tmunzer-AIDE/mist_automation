"""Unit tests for WebSocketManager.get_stats()."""

from unittest.mock import MagicMock

from app.core.websocket import WebSocketManager


class TestWebSocketManagerStats:
    def test_empty_manager_stats(self):
        mgr = WebSocketManager()
        stats = mgr.get_stats()
        assert stats["connected_clients"] == 0
        assert stats["active_channels"] == 0
        assert stats["total_subscriptions"] == 0

    def test_stats_with_clients_and_channels(self):
        mgr = WebSocketManager()
        ws1 = MagicMock()
        ws2 = MagicMock()
        mgr._client_channels[ws1] = {"ch1", "ch2"}
        mgr._client_channels[ws2] = {"ch1"}
        mgr._channels["ch1"] = {ws1, ws2}
        mgr._channels["ch2"] = {ws1}
        mgr._last_pong[ws1] = 1.0
        mgr._last_pong[ws2] = 2.0

        stats = mgr.get_stats()
        assert stats["connected_clients"] == 2
        assert stats["active_channels"] == 2
        assert stats["total_subscriptions"] == 3
