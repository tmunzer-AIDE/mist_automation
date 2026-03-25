"""Webhook event handler for config change impact analysis.

Routes device-events to the appropriate session manager action:
- TRIGGER events → create or merge monitoring session
- INCIDENT events → append incident to active session
- REVERT events → append critical incident, trigger early analysis
- RESOLUTION events → resolve matching incidents
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from app.core.tasks import create_background_task
from app.models.system import SystemConfig
from app.modules.impact_analysis.models import (
    ACTIVE_STATUSES,
    ConfigChangeEvent,
    DeviceIncident,
    DeviceType,
    MonitoringSession,
    SessionStatus,
)
from app.modules.impact_analysis.services import session_manager

logger = structlog.get_logger(__name__)

# Events that start/merge a monitoring session
TRIGGER_EVENTS = {"AP_CONFIGURED", "SW_CONFIGURED", "GW_CONFIGURED"}

# Events that indicate problems during monitoring
INCIDENT_EVENTS = {
    "AP_DISCONNECTED",
    "SW_DISCONNECTED",
    "GW_DISCONNECTED",
    "AP_CONFIG_FAILED",
    "SW_CONFIG_FAILED",
    "GW_CONFIG_FAILED",
    "SW_VC_PORT_DOWN",
    "GW_VPN_PATH_DOWN",
    "GW_TUNNEL_DOWN",
    "SW_OSPF_NEIGHBOR_DOWN",
    "GW_OSPF_NEIGHBOR_DOWN",
    "SW_BGP_NEIGHBOR_DOWN",
    "GW_BGP_NEIGHBOR_DOWN",
}

# Config reverted by device — triggers early analysis
REVERT_EVENTS = {
    "SW_CONFIG_REVERTED",
    "GW_CONFIG_REVERTED",
}

# Events that resolve incidents
RESOLUTION_EVENTS = {
    "AP_CONNECTED",
    "SW_CONNECTED",
    "GW_CONNECTED",
    "SW_VC_PORT_UP",
    "GW_VPN_PATH_UP",
    "GW_TUNNEL_UP",
}

# Map resolution events to the incident event type they resolve
RESOLUTION_TO_INCIDENT: dict[str, str] = {
    "AP_CONNECTED": "AP_DISCONNECTED",
    "SW_CONNECTED": "SW_DISCONNECTED",
    "GW_CONNECTED": "GW_DISCONNECTED",
    "SW_VC_PORT_UP": "SW_VC_PORT_DOWN",
    "GW_VPN_PATH_UP": "GW_VPN_PATH_DOWN",
    "GW_TUNNEL_UP": "GW_TUNNEL_DOWN",
}

# Map event prefix to device type
_EVENT_PREFIX_TO_TYPE: dict[str, DeviceType] = {
    "AP_": DeviceType.AP,
    "SW_": DeviceType.SWITCH,
    "GW_": DeviceType.GATEWAY,
}


def _infer_device_type(event_type: str) -> DeviceType:
    for prefix, dtype in _EVENT_PREFIX_TO_TYPE.items():
        if event_type.startswith(prefix):
            return dtype
    return DeviceType.SWITCH  # fallback


def _extract_device_info(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    """Extract (device_mac, device_name, site_id, org_id) from enriched payload."""
    device_mac = payload.get("mac") or payload.get("device_mac") or payload.get("ap_mac") or ""
    device_name = payload.get("device_name") or payload.get("ap") or payload.get("switch_name") or ""
    site_id = payload.get("site_id") or ""
    org_id = payload.get("org_id") or ""
    return device_mac, device_name, site_id, org_id


async def handle_device_event(
    webhook_event_id: str,
    event_type: str,
    enriched_payload: dict[str, Any],
) -> None:
    """Route a device-event to the impact analysis module."""
    if not event_type:
        return

    # Check if impact analysis is enabled
    config = await SystemConfig.get_config()
    if not config.impact_analysis_enabled:
        return

    device_mac, device_name, site_id, org_id = _extract_device_info(enriched_payload)
    if not device_mac or not site_id:
        logger.debug("impact_event_skipped", reason="missing_device_mac_or_site_id", event_type=event_type)
        return

    if event_type in TRIGGER_EVENTS:
        await _handle_trigger(
            webhook_event_id,
            event_type,
            device_mac,
            device_name,
            site_id,
            org_id,
            enriched_payload,
            config,
        )
    elif event_type in INCIDENT_EVENTS:
        await _handle_incident(
            webhook_event_id,
            event_type,
            device_mac,
            device_name,
            site_id=site_id,
            org_id=org_id,
            severity="warning",
        )
    elif event_type in REVERT_EVENTS:
        await _handle_revert(
            webhook_event_id,
            event_type,
            device_mac,
            device_name,
        )
    elif event_type in RESOLUTION_EVENTS:
        await _handle_resolution(event_type, device_mac)


async def _handle_trigger(
    webhook_event_id: str,
    event_type: str,
    device_mac: str,
    device_name: str,
    site_id: str,
    org_id: str,
    payload: dict[str, Any],
    config: SystemConfig,
) -> None:
    """Handle a config trigger event — create or merge monitoring session."""
    device_type = _infer_device_type(event_type)
    site_name = payload.get("site_name") or ""

    config_event = ConfigChangeEvent(
        event_type=event_type,
        device_mac=device_mac,
        device_name=device_name,
        timestamp=datetime.now(timezone.utc),
        webhook_event_id=webhook_event_id,
        payload_summary={
            k: v
            for k, v in payload.items()
            if k in ("type", "device_name", "mac", "site_name", "text", "audit_id", "device_type", "commit_log")
        },
        config_diff=payload.get("config_diff"),
        device_model=payload.get("model") or "",
        firmware_version=payload.get("version") or "",
        commit_user=payload.get("commit_user") or "",
        commit_method=payload.get("commit_method") or "",
    )

    session, is_new = await session_manager.create_or_merge_session(
        site_id=site_id,
        site_name=site_name,
        org_id=org_id,
        device_mac=device_mac,
        device_name=device_name,
        device_type=device_type,
        config_event=config_event,
        duration_minutes=config.impact_analysis_default_duration_minutes,
        interval_minutes=config.impact_analysis_default_interval_minutes,
    )

    if is_new:
        # Import here to avoid circular imports
        from app.modules.impact_analysis.workers.monitoring_worker import run_monitoring_pipeline

        create_background_task(
            run_monitoring_pipeline(str(session.id)),
            name=f"impact-pipeline-{session.id}",
        )

    logger.info(
        "impact_trigger_handled",
        session_id=str(session.id),
        is_new=is_new,
        event_type=event_type,
        device_mac=device_mac,
    )


async def _handle_incident(
    webhook_event_id: str,
    event_type: str,
    device_mac: str,
    device_name: str,
    site_id: str = "",
    org_id: str = "",
    severity: str = "warning",
) -> None:
    """Handle an incident event — append to active session if exists, or check topology correlation."""
    session = await _find_active_session(device_mac)
    if session:
        incident = DeviceIncident(
            event_type=event_type,
            device_mac=device_mac,
            device_name=device_name,
            timestamp=datetime.now(timezone.utc),
            webhook_event_id=webhook_event_id,
            severity=severity,
        )
        await session_manager.add_incident(session, incident)

        logger.info(
            "impact_incident_added",
            session_id=str(session.id),
            event_type=event_type,
            device_mac=device_mac,
        )
        return

    # If no direct match AND it's a disconnect event, check topology correlation
    if event_type in _DISCONNECT_EVENTS and site_id:
        try:
            await _check_topology_correlation(webhook_event_id, event_type, device_mac, device_name, site_id, org_id)
        except Exception as exc:
            logger.warning(
                "topology_correlation_failed",
                event_type=event_type,
                device_mac=device_mac,
                site_id=site_id,
                error=str(exc),
            )


# Disconnect events eligible for topology correlation
_DISCONNECT_EVENTS = {"AP_DISCONNECTED", "SW_DISCONNECTED", "GW_DISCONNECTED"}


async def _check_topology_correlation(
    webhook_event_id: str,
    event_type: str,
    device_mac: str,
    device_name: str,
    site_id: str,
    org_id: str,
) -> None:
    """Check if a disconnected device's path to a gateway goes through a monitored device."""
    # Find all active sessions at this site
    active_sessions = await MonitoringSession.find(
        MonitoringSession.site_id == site_id,
        {"status": {"$in": [s.value for s in ACTIVE_STATUSES]}},
    ).to_list()

    if not active_sessions:
        return

    # Resolve org_id from the first session if not provided
    effective_org_id = org_id or active_sessions[0].org_id

    # Build topology for the site
    from app.modules.impact_analysis.services.topology_service import build_site_topology

    topology = await build_site_topology(site_id, effective_org_id)
    if not topology:
        return

    from app.modules.impact_analysis.topology.builder import bfs_path

    # Find gateways in topology
    gateways = [d for d in topology.devices.values() if d.device_type == "gateway"]
    if not gateways:
        return

    disconnected_dev = topology.resolve_device(device_mac)

    for session in active_sessions:
        monitored_dev = topology.resolve_device(session.device_mac)
        if not monitored_dev:
            continue

        correlated = False

        # Strategy 1: If disconnected device is in topology, check if monitored device
        # is on its path to any gateway (BFS path analysis)
        if disconnected_dev:
            for gw in gateways:
                path_devices, _path_conns = bfs_path(topology, disconnected_dev.id, gw.id)
                if not path_devices:
                    continue
                path_ids = [d.id for d in path_devices]
                if monitored_dev.id in path_ids:
                    correlated = True
                    break

        # Strategy 2: Check if the disconnected device is a direct neighbor of the
        # monitored device. Applies when:
        # - disconnected_dev not in topology at all (removed from LLDP)
        # - disconnected_dev in topology but has no edges (APs appear in device stats
        #   but searchSiteSwOrGwPorts only returns switch/gateway LLDP, so APs have
        #   no connections in the topology graph)
        if not correlated:
            # Check if the monitored device has a topology neighbor matching the MAC
            mac_normalized = device_mac.lower().replace(":", "")
            for conn in topology.neighbors(monitored_dev.id):
                neighbor_id = (
                    conn.remote_device_id if conn.local_device_id == monitored_dev.id else conn.local_device_id
                )
                neighbor = topology.devices.get(neighbor_id)
                if neighbor and neighbor.mac.lower().replace(":", "") == mac_normalized:
                    correlated = True
                    break

        # Strategy 3: For AP disconnects at a site where a switch/gateway is being
        # monitored — APs connect through switches, so if a switch config change
        # caused the AP to disconnect, we should correlate it.
        # This is the broadest check, used when topology path/neighbor checks fail
        # (e.g., AP has no edges in the graph).
        if not correlated and event_type == "AP_DISCONNECTED" and monitored_dev.device_type in ("switch", "gateway"):
            correlated = True
            logger.info(
                "topology_correlation_inferred",
                reason="ap_disconnect_at_monitored_switch_site",
                monitored_device=session.device_mac,
                disconnected_device=device_mac,
            )

        if correlated:
            incident = DeviceIncident(
                event_type=event_type,
                device_mac=device_mac,
                device_name=device_name,
                timestamp=datetime.now(timezone.utc),
                webhook_event_id=webhook_event_id,
                severity="warning",
                is_revert=False,
            )
            await session_manager.add_incident(session, incident)
            logger.info(
                "topology_correlated_incident",
                session_id=str(session.id),
                monitored_device=session.device_mac,
                disconnected_device=device_mac,
                event_type=event_type,
            )
            break  # Only correlate to one session


async def _handle_revert(
    webhook_event_id: str,
    event_type: str,
    device_mac: str,
    device_name: str,
) -> None:
    """Handle a config revert event — critical incident + early analysis."""
    session = await _find_active_session(device_mac)
    if not session:
        return

    incident = DeviceIncident(
        event_type=event_type,
        device_mac=device_mac,
        device_name=device_name,
        timestamp=datetime.now(timezone.utc),
        webhook_event_id=webhook_event_id,
        severity="critical",
        is_revert=True,
    )
    await session_manager.add_incident(session, incident)

    # Skip remaining monitoring, go straight to analyzing
    if session.status == SessionStatus.MONITORING:
        await session_manager.transition(session, SessionStatus.ANALYZING)

    logger.info(
        "impact_revert_detected",
        session_id=str(session.id),
        event_type=event_type,
        device_mac=device_mac,
    )


async def _handle_resolution(event_type: str, device_mac: str) -> None:
    """Handle a resolution event — resolve matching incidents."""
    incident_event_type = RESOLUTION_TO_INCIDENT.get(event_type, event_type)
    # Also check ANALYZING sessions for resolution events
    session = await MonitoringSession.find_one(
        MonitoringSession.device_mac == device_mac,
        {"status": {"$in": [s.value for s in ACTIVE_STATUSES] + [SessionStatus.ANALYZING.value]}},
    )

    # Fallback: find sessions with correlated incidents from this device
    if not session:
        session = await MonitoringSession.find_one(
            {
                "incidents": {"$elemMatch": {"device_mac": device_mac, "resolved": False}},
                "status": {"$in": [s.value for s in ACTIVE_STATUSES] + [SessionStatus.ANALYZING.value]},
            }
        )

    if not session:
        return
    await session_manager.resolve_incident(session, incident_event_type, device_mac)


async def _find_active_session(device_mac: str) -> MonitoringSession | None:
    """Find an active monitoring session for the given device MAC."""
    return await MonitoringSession.find_one(
        MonitoringSession.device_mac == device_mac,
        {"status": {"$in": [s.value for s in ACTIVE_STATUSES]}},
    )
