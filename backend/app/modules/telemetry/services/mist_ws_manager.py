"""Mist WebSocket Manager — lifecycle, auto-scaling, and thread-to-asyncio bridging.

Manages one or more ``mistapi.websockets.sites.DeviceStatsEvents`` connections.
Each connection handles up to 1000 site subscriptions. Messages received on
background WS threads are bridged into an ``asyncio.Queue`` via
``loop.call_soon_threadsafe()``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from mistapi.websockets.sites import DeviceStatsEvents

logger = structlog.get_logger(__name__)

_MAX_SITES_PER_CONNECTION = 1000


class MistWsManager:
    """Manages Mist WebSocket connections for device stats streaming."""

    def __init__(
        self,
        api_session: Any,
        message_queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        self._api_session = api_session
        self._message_queue = message_queue
        self._connections: list[DeviceStatsEvents] = []
        self._subscribed_sites: list[str] = []
        self._loop: asyncio.AbstractEventLoop | None = None

        # Stats
        self._messages_received = 0
        self._messages_bridge_dropped = 0
        self._last_message_at: float = 0
        self._started_at: float = 0

    def _chunk_sites(self, site_ids: list[str]) -> list[list[str]]:
        """Split site_ids into chunks of _MAX_SITES_PER_CONNECTION."""
        if not site_ids:
            return []
        n = _MAX_SITES_PER_CONNECTION
        return [site_ids[i : i + n] for i in range(0, len(site_ids), n)]

    def _on_ws_message(self, msg: dict[str, Any]) -> None:
        """Callback invoked from the WS thread — bridge message to asyncio.

        Uses ``loop.call_soon_threadsafe()`` to safely post the message into
        the asyncio queue from a non-asyncio thread.
        """
        self._messages_received += 1
        self._last_message_at = time.time()

        if self._loop is None:
            return

        try:
            self._loop.call_soon_threadsafe(self._message_queue.put_nowait, msg)
        except asyncio.QueueFull:
            self._messages_bridge_dropped += 1
            logger.debug("ws_bridge_queue_full")
        except RuntimeError:
            # Event loop closed
            pass

    async def start(self, site_ids: list[str]) -> None:
        """Subscribe to device stats for all sites, auto-scaling connections.

        Creates one ``DeviceStatsEvents`` per chunk of 1000 sites, registers
        the bridge callback, and starts each in a background thread.
        """
        self._loop = asyncio.get_running_loop()
        self._subscribed_sites = list(site_ids)
        chunks = self._chunk_sites(site_ids)

        if not chunks:
            logger.info("mist_ws_manager_no_sites")
            return

        for chunk in chunks:
            ws = DeviceStatsEvents(
                mist_session=self._api_session,
                site_ids=chunk,
                auto_reconnect=True,
                max_reconnect_attempts=5,
                reconnect_backoff=2.0,
            )
            ws.on_message(self._on_ws_message)
            ws.connect(run_in_background=True)
            self._connections.append(ws)

        self._started_at = time.time()
        logger.info(
            "mist_ws_manager_started",
            connections=len(self._connections),
            sites=len(self._subscribed_sites),
        )

    async def stop(self) -> None:
        """Disconnect all WebSocket connections."""
        for ws in self._connections:
            try:
                ws.disconnect()
            except Exception as e:
                logger.warning("mist_ws_disconnect_error", error=str(e))

        count = len(self._connections)
        self._connections = []
        self._subscribed_sites = []
        self._loop = None

        logger.info(
            "mist_ws_manager_stopped",
            connections_closed=count,
            messages_received=self._messages_received,
        )

    async def add_sites(self, site_ids: list[str]) -> None:
        """Dynamically subscribe to new sites.

        Determines if sites fit in an existing connection or creates new ones.
        For simplicity in this initial implementation, stops all connections
        and restarts with the combined list.
        """
        combined = list(set(self._subscribed_sites + site_ids))
        await self.stop()
        await self.start(combined)

    async def remove_sites(self, site_ids: list[str]) -> None:
        """Unsubscribe from sites.

        Stops all connections and restarts without the removed sites.
        """
        remaining = [s for s in self._subscribed_sites if s not in set(site_ids)]
        await self.stop()
        if remaining:
            await self.start(remaining)

    def get_status(self) -> dict[str, Any]:
        """Return connection status, site count, and message stats."""
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
