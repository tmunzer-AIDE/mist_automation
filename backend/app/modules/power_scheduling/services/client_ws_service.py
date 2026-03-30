from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import structlog
from mistapi.websockets.sites import ClientsStatsEvents

log = structlog.get_logger(__name__)

# Callback signature: (site_id: str, event_type: "join"|"leave"|"update", client_mac: str, ap_mac: str, rssi: int | None)
ClientEventCallback = Callable[[str, str, str, str, int | None], None]


class ClientStatsWsManager:
    """
    Subscribes to /sites/{site_id}/stats/clients via Mist WebSocket.

    Uses the same thread-bridge pattern as MistWsManager:
    the mistapi WS runs in a background thread and posts events
    to the asyncio event loop via call_soon_threadsafe().

    The Mist clients WS sends snapshot-style updates: each message contains
    the full list of currently connected clients. Joins/leaves are detected
    by comparing against the previous snapshot.
    """

    def __init__(self, api_session: Any, on_event: ClientEventCallback) -> None:
        self._api_session = api_session
        self._on_event = on_event
        self._connections: list[ClientsStatsEvents] = []
        self._subscribed_sites: list[str] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._prev_snapshots: dict[str, dict[str, str]] = {}  # {site_id: {client_mac: ap_mac}}

    async def start(self, site_ids: list[str]) -> None:
        self._loop = asyncio.get_running_loop()
        self._subscribed_sites = list(site_ids)
        for site_id in site_ids:
            await self._subscribe_site(site_id)

    async def add_site(self, site_id: str) -> None:
        if site_id not in self._subscribed_sites:
            self._subscribed_sites.append(site_id)
            await self._subscribe_site(site_id)

    async def remove_site(self, site_id: str) -> None:
        self._subscribed_sites = [s for s in self._subscribed_sites if s != site_id]
        self._prev_snapshots.pop(site_id, None)
        await self.stop()
        if self._subscribed_sites:
            await self.start(self._subscribed_sites)

    async def stop(self) -> None:
        for conn in self._connections:
            try:
                conn.disconnect()
            except Exception:
                pass
        self._connections.clear()

    async def _subscribe_site(self, site_id: str) -> None:
        """Subscribe to client stats for a single site via ClientsStatsEvents."""
        try:
            ws = ClientsStatsEvents(
                mist_session=self._api_session,
                site_ids=[site_id],
                auto_reconnect=True,
                max_reconnect_attempts=5,
                reconnect_backoff=2.0,
            )
            ws.on_message(lambda msg: self._bridge(site_id, msg))
            ws.connect(run_in_background=True)
            self._connections.append(ws)
            log.info("client_ws_subscribed", site_id=site_id)
        except Exception as exc:
            log.error("client_ws_subscribe_failed", site_id=site_id, error=str(exc))

    def _bridge(self, site_id: str, msg: dict[str, Any]) -> None:
        """Thread-safe bridge from WS thread to asyncio loop."""
        if self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._process, site_id, msg)
        except RuntimeError:
            pass

    def _process(self, site_id: str, msg: dict[str, Any]) -> None:
        """
        Process a Mist clients stats WS message.

        Mist sends a snapshot of currently connected clients per site.
        Each client object has at minimum: mac, ap_mac, rssi, connected (bool).
        Detect joins/leaves by comparing against previous snapshot.
        """
        if msg.get("event") != "data":
            return

        clients: list[dict] = msg.get("data", [])
        current: dict[str, str] = {
            c["mac"]: c["ap_mac"] for c in clients if c.get("connected", True) and c.get("mac") and c.get("ap_mac")
        }
        prev = self._prev_snapshots.get(site_id, {})

        # Detect joins and roams
        for client_mac, ap_mac in current.items():
            if client_mac not in prev:
                rssi = next((c.get("rssi") for c in clients if c.get("mac") == client_mac), None)
                self._on_event(site_id, "join", client_mac, ap_mac, rssi)
            elif prev[client_mac] != ap_mac:
                # Roamed: leave old AP, join new AP
                self._on_event(site_id, "leave", client_mac, prev[client_mac], None)
                rssi = next((c.get("rssi") for c in clients if c.get("mac") == client_mac), None)
                self._on_event(site_id, "join", client_mac, ap_mac, rssi)

        # Detect leaves
        for client_mac, ap_mac in prev.items():
            if client_mac not in current:
                self._on_event(site_id, "leave", client_mac, ap_mac, None)

        # RSSI updates for connected clients (for roam pre-enable)
        for c in clients:
            if c.get("connected") and c.get("rssi") is not None:
                self._on_event(site_id, "update", c["mac"], c.get("ap_mac", ""), c["rssi"])

        self._prev_snapshots[site_id] = current
