from __future__ import annotations

from datetime import datetime, time

import pytz

from app.modules.power_scheduling.models import PowerSchedule
from app.modules.power_scheduling.state import PowerScheduleState


def can_disable(ap_mac: str, state: PowerScheduleState, schedule: PowerSchedule) -> bool:
    """Return True if AP is eligible to be disabled now."""
    if ap_mac in schedule.critical_ap_macs:
        return False
    if state.client_map.get(ap_mac):
        return False
    for neighbor_mac, rssi in state.rf_neighbor_map.get(ap_mac, []):
        if rssi > schedule.neighbor_rssi_threshold_dbm:
            if state.client_map.get(neighbor_mac):
                return False
    return True


def _time_in_window(now_time: time, start: time, end: time) -> bool:
    """Check if now_time falls in [start, end) handling midnight crossings."""
    if start <= end:
        return start <= now_time < end
    # Crosses midnight: e.g. 22:00 → 06:00
    return now_time >= start or now_time < end


def compute_expected_status(schedule: PowerSchedule, now_utc: datetime) -> str:
    """Return 'OFF_HOURS' if now falls inside any window, else 'IDLE'."""
    tz = pytz.timezone(schedule.timezone)
    now_local = now_utc.astimezone(tz)
    now_time = now_local.time()
    now_weekday = now_local.weekday()  # 0=Mon, 6=Sun

    for window in schedule.windows:
        start = time(*map(int, window.start.split(":")))
        end = time(*map(int, window.end.split(":")))

        # For midnight-crossing windows, yesterday's start day is also relevant
        crosses_midnight = start > end
        active_days = set(window.days)
        if crosses_midnight:
            # Evening side: window starts today (now_weekday must be active)
            evening = now_weekday in active_days and now_time >= start
            # Morning side (after midnight): window started yesterday
            yesterday = (now_weekday - 1) % 7
            morning = yesterday in active_days and now_time < end
            if evening or morning:
                return "OFF_HOURS"
        else:
            if now_weekday in active_days and _time_in_window(now_time, start, end):
                return "OFF_HOURS"

    return "IDLE"
