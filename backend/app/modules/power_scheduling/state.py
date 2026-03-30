from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

_states: dict[str, "PowerScheduleState"] = {}
_locks: dict[str, asyncio.Lock] = {}


@dataclass
class PowerScheduleState:
    status: Literal["IDLE", "TRANSITIONING_OFF", "OFF_HOURS", "TRANSITIONING_ON"] = "IDLE"
    # {ap_mac: original_profile_id | None}
    disabled_aps: dict[str, str | None] = field(default_factory=dict)
    # APs with clients or whose neighbor has clients — not yet disabled
    pending_disable: set[str] = field(default_factory=set)
    # {ap_mac: {client_mac, ...}} — live from clients WS
    client_map: dict[str, set[str]] = field(default_factory=dict)
    # {ap_mac: asyncio.Task} — grace timer tasks per AP
    grace_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    # {ap_mac: [(neighbor_mac, rssi_dbm)]} — cached at window start
    rf_neighbor_map: dict[str, list[tuple[str, int]]] = field(default_factory=dict)


def get_state(site_id: str) -> PowerScheduleState:
    """Get or create in-memory state for a site."""
    if site_id not in _states:
        _states[site_id] = PowerScheduleState()
        _locks[site_id] = asyncio.Lock()
    return _states[site_id]


def get_lock(site_id: str) -> asyncio.Lock:
    """Get the asyncio lock for a site (call get_state first)."""
    if site_id not in _locks:
        _locks[site_id] = asyncio.Lock()
    return _locks[site_id]


async def clear_state(site_id: str) -> None:
    """Cancel grace tasks and remove state for a site."""
    state = _states.pop(site_id, None)
    _locks.pop(site_id, None)
    if state:
        for task in state.grace_tasks.values():
            task.cancel()
