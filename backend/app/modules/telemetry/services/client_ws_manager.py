# backend/app/modules/telemetry/services/client_ws_manager.py
"""Client WebSocket Manager — subscribes to /sites/{id}/stats/clients for client stats.

Identical pattern to MistWsManager but uses ClientsStatsEvents instead of DeviceStatsEvents.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from mistapi.websockets.sites import ClientsStatsEvents

logger = structlog.get_logger(__name__)

_MAX_SITES_PER_CONNECTION = 1000


class ClientWsManager:
    """Manages Mist WebSocket connections for wireless client stats streaming."""

    def __init__(
        self,
        api_session: Any,
        message_queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        self._api_session = api_session
        self._message_queue = message_queue
        self._connections: list[ClientsStatsEvents] = []
        self._subscribed_sites: list[str] = []
        self._loop: asyncio.AbstractEventLoop | None = None

        self._messages_received = 0
        self._messages_bridge_dropped = 0
        self._last_message_at: float = 0
        self._started_at: float = 0

    def _chunk_sites(self, site_ids: list[str]) -> list[list[str]]:
        n = _MAX_SITES_PER_CONNECTION
        return [site_ids[i : i + n] for i in range(0, len(site_ids), n)]

    def _on_ws_message(self, msg: dict[str, Any]) -> None:
        self._messages_received += 1
        self._last_message_at = time.time()
        if self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._safe_enqueue, msg)
        except RuntimeError:
            pass

    def _safe_enqueue(self, msg: dict[str, Any]) -> None:
        try:
            self._message_queue.put_nowait(msg)
        except asyncio.QueueFull:
            self._messages_bridge_dropped += 1

    async def start(self, site_ids: list[str]) -> None:
        self._loop = asyncio.get_running_loop()
        self._subscribed_sites = list(site_ids)
        chunks = self._chunk_sites(site_ids)

        if not chunks:
            logger.info("client_ws_manager_no_sites")
            return

        for chunk in chunks:
            ws = ClientsStatsEvents(
                mist_session=self._api_session,
                site_ids=chunk,
                auto_reconnect=True,
                max_reconnect_attempts=0,
                reconnect_backoff=2.0,
                max_reconnect_backoff=30.0,
            )
            ws.on_message(self._on_ws_message)
            ws.connect(run_in_background=True)
            self._connections.append(ws)

        self._started_at = time.time()
        logger.info(
            "client_ws_manager_started",
            connections=len(self._connections),
            sites=len(self._subscribed_sites),
        )

    async def stop(self) -> None:
        for ws in self._connections:
            try:
                ws.disconnect()
            except Exception as e:
                logger.warning("client_ws_disconnect_error", error=str(e))

        count = len(self._connections)
        self._connections = []
        self._subscribed_sites = []
        self._loop = None
        logger.info("client_ws_manager_stopped", connections_closed=count)

    async def add_sites(self, site_ids: list[str]) -> None:
        combined = list(set(self._subscribed_sites + site_ids))
        await self.stop()
        await self.start(combined)

    async def remove_sites(self, site_ids: list[str]) -> None:
        remaining = [s for s in self._subscribed_sites if s not in set(site_ids)]
        await self.stop()
        if remaining:
            await self.start(remaining)

    def get_status(self) -> dict[str, Any]:
        ready_list = []
        for ws in self._connections:
            try:
                ready_list.append(ws.ready())
            except Exception:
                ready_list.append(False)
        return {
            "connections": len(self._connections),
            "sites_subscribed": len(self._subscribed_sites),
            "all_ready": all(ready_list) if ready_list else True,
            "connections_ready": sum(1 for r in ready_list if r),
            "messages_received": self._messages_received,
            "messages_bridge_dropped": self._messages_bridge_dropped,
            "last_message_at": self._last_message_at,
            "started_at": self._started_at,
        }
