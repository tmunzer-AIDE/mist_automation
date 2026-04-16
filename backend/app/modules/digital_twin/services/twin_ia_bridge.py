"""
Bridge between Digital Twin and Impact Analysis.

After a Twin session deploys config changes, this service creates
IA monitoring sessions for affected devices to validate the real-world
outcome matches the Twin's prediction.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.core.tasks import create_background_task
from app.modules.digital_twin.models import TwinSession
from app.modules.digital_twin.services.site_snapshot import normalize_mac

logger = structlog.get_logger(__name__)


async def create_ia_sessions_for_deployment(session: TwinSession) -> list[str]:
    """Create Impact Analysis monitoring sessions after Twin deployment.

    For each affected site in the Twin session, identifies devices that
    were likely impacted by the staged writes and creates IA monitoring
    sessions to track post-change behavior.

    Returns list of created IA session IDs.
    """
    from app.modules.impact_analysis.models import ConfigChangeEvent
    from app.modules.impact_analysis.services.session_manager import create_or_merge_session
    from app.modules.impact_analysis.workers.monitoring_worker import run_monitoring_pipeline

    ia_session_ids: list[str] = []

    # Build a ConfigChangeEvent from the Twin deployment
    config_event = ConfigChangeEvent(
        event_type="TWIN_DEPLOYMENT",
        device_mac="",  # Will be set per device
        device_name="",
        timestamp=session.updated_at or session.created_at,
        payload_summary={
            "twin_session_id": str(session.id),
            "writes_count": len(session.staged_writes),
            "overall_severity": session.overall_severity,
        },
    )

    # Freeze the prediction report for comparison later
    frozen_prediction = None
    if session.prediction_report:
        frozen_prediction = session.prediction_report.model_dump()

    # For each affected site, find devices and create sessions
    for site_id in session.affected_sites:
        try:
            devices = await _get_devices_at_site(site_id, session)
            for device in devices:
                device_event = config_event.model_copy(
                    update={
                        "device_mac": device["mac"],
                        "device_name": device.get("name", device["mac"]),
                    }
                )

                device_type_str = device.get("type") or device.get("device_type", "switch")
                device_type = _parse_device_type(device_type_str)

                ia_session, is_new = await create_or_merge_session(
                    site_id=site_id,
                    site_name=device.get("site_name", site_id),
                    org_id=session.org_id,
                    device_mac=device["mac"],
                    device_name=device.get("name", device["mac"]),
                    device_type=device_type,
                    config_event=device_event,
                    duration_minutes=60,
                    interval_minutes=10,
                )

                # Tag with Twin session
                ia_session.twin_session_id = str(session.id)
                ia_session.twin_prediction = frozen_prediction
                await ia_session.save()

                ia_session_ids.append(str(ia_session.id))

                if is_new:
                    create_background_task(
                        run_monitoring_pipeline(str(ia_session.id)),
                        name=f"twin-ia-pipeline-{ia_session.id}",
                    )

                logger.info(
                    "twin_ia_session_created",
                    twin_session_id=str(session.id),
                    ia_session_id=str(ia_session.id),
                    device_mac=device["mac"],
                    is_new=is_new,
                )
        except Exception as e:
            logger.warning("twin_ia_session_failed", site_id=site_id, error=str(e))

    return ia_session_ids


async def _get_devices_at_site(site_id: str, session: TwinSession) -> list[dict[str, Any]]:
    """Get devices at a site that were affected by the Twin deployment.

    Tries telemetry cache first, falls back to backup data.
    """
    devices: list[dict[str, Any]] = []

    # Check telemetry cache for live device list
    try:
        from app.modules.telemetry import _latest_cache

        if _latest_cache:
            cached = _latest_cache.get_all_for_site(site_id, max_age_seconds=120)
            for stats in cached:
                dev_type = stats.get("type", "")
                if dev_type in ("switch", "gateway", "ap"):
                    devices.append(
                        {
                            "mac": normalize_mac(stats.get("mac", "")),
                            "name": stats.get("name", stats.get("hostname", "")),
                            "type": dev_type,
                            "site_name": stats.get("site_name", site_id),
                        }
                    )
            if devices:
                return devices
    except Exception:
        pass

    # Fallback: backup device data
    from app.modules.backup.models import BackupObject

    backups = (
        await BackupObject.find({"object_type": "devices", "site_id": site_id, "is_deleted": False})
        .sort([("version", -1)])
        .to_list()
    )

    seen: set[str] = set()
    for b in backups:
        if b.object_id in seen:
            continue
        seen.add(b.object_id)
        cfg = b.configuration
        devices.append(
            {
                "mac": normalize_mac(cfg.get("mac") or b.object_id),
                "name": cfg.get("name", ""),
                "type": cfg.get("type", cfg.get("device_type", "switch")),
                "site_name": site_id,
            }
        )

    return devices


def _parse_device_type(device_type_str: str):
    """Parse device type string to DeviceType enum."""
    from app.modules.impact_analysis.models import DeviceType

    mapping = {"ap": DeviceType.AP, "switch": DeviceType.SWITCH, "gateway": DeviceType.GATEWAY}
    return mapping.get(device_type_str.lower(), DeviceType.SWITCH)
