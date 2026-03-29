"""Webhook event handler for config change impact analysis.

Routes device-events to the appropriate session manager action:
- PRE_CONFIG events → create or merge monitoring session (primary trigger)
- CONFIGURED events → confirm config applied (AWAITING_CONFIG → MONITORING), or fallback trigger
- CONFIG_FAILED events → alert if awaiting config, incident if monitoring
- INCIDENT events → append incident to active session
- REVERT events → append critical incident, trigger early analysis
- RESOLUTION events → resolve matching incidents
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from beanie import PydanticObjectId

from app.core.tasks import create_background_task
from app.models.system import SystemConfig
from app.modules.impact_analysis.models import (
    ACTIVE_STATUSES,
    ConfigChangeEvent,
    DeviceIncident,
    DeviceType,
    MonitoringSession,
    SessionStatus,
    TimelineEntry,
    TimelineEntryType,
    get_monitoring_defaults,
)
from app.modules.impact_analysis.services import session_manager
from app.modules.impact_analysis.services.session_manager import append_timeline_entry

logger = structlog.get_logger(__name__)

# Primary triggers — config changed in Mist cloud (before push to device)
PRE_CONFIG_EVENTS = {
    "AP_CONFIG_CHANGED_BY_USER",
    "AP_CONFIG_CHANGED_BY_RRM",
    "SW_CONFIG_CHANGED_BY_USER",
    "GW_CONFIG_CHANGED_BY_USER",
}

# Config applied to device — transitions AWAITING_CONFIG → MONITORING, or fallback trigger
CONFIGURED_EVENTS = {"AP_CONFIGURED", "SW_CONFIGURED", "GW_CONFIGURED"}

# Config failed to apply — alert if in AWAITING_CONFIG, incident if in MONITORING
CONFIG_FAILED_EVENTS = {"AP_CONFIG_FAILED", "SW_CONFIG_FAILED", "GW_CONFIG_FAILED"}

# Events that indicate problems during monitoring (CONFIG_FAILED handled separately above)
INCIDENT_EVENTS = {
    "AP_DISCONNECTED",
    "SW_DISCONNECTED",
    "GW_DISCONNECTED",
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

    if event_type in PRE_CONFIG_EVENTS:
        await _handle_pre_config_trigger(
            webhook_event_id,
            event_type,
            device_mac,
            device_name,
            site_id,
            org_id,
            enriched_payload,
            config,
        )
    elif event_type in CONFIGURED_EVENTS:
        await _handle_configured(
            webhook_event_id,
            event_type,
            device_mac,
            device_name,
            site_id,
            org_id,
            enriched_payload,
            config,
        )
    elif event_type in CONFIG_FAILED_EVENTS:
        await _handle_config_failed(
            webhook_event_id,
            event_type,
            device_mac,
            device_name,
            site_id=site_id,
            org_id=org_id,
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


async def _build_config_event(
    webhook_event_id: str,
    event_type: str,
    device_mac: str,
    device_name: str,
    payload: dict[str, Any],
) -> ConfigChangeEvent:
    """Build a ConfigChangeEvent from a webhook payload.

    For PRE_CONFIG events (CONFIG_CHANGED_BY_*), looks up the corresponding
    audit webhook to extract before/after config state and admin details.
    """
    config_before: dict | None = None
    config_after: dict | None = None
    change_message = ""
    commit_user = payload.get("commit_user") or ""

    # Look up audit webhook for before/after config diff
    audit_id = payload.get("audit_id")
    if audit_id:
        audit_data = await _lookup_audit(audit_id)
        if audit_data:
            config_before = audit_data.get("before")
            config_after = audit_data.get("after")
            change_message = audit_data.get("message", "")
            if not commit_user:
                commit_user = audit_data.get("admin_name", "")

    return ConfigChangeEvent(
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
        config_before=config_before,
        config_after=config_after,
        change_message=change_message,
        device_model=payload.get("model") or "",
        firmware_version=payload.get("version") or "",
        commit_user=commit_user,
        commit_method=payload.get("commit_method") or "",
    )


async def _lookup_audit(audit_id: str) -> dict[str, Any] | None:
    """Look up an audit webhook event to extract before/after config data.

    Searches by the audit's ``id`` field in the payload, since the webhook router
    stores audit events with standard webhook_id (not ``audit_{id}``).
    """
    try:
        from app.modules.automation.models.webhook import WebhookEvent

        audit_event = await WebhookEvent.find_one({"payload.id": audit_id, "webhook_type": "audits"})
        if not audit_event or not audit_event.payload:
            return None

        p = audit_event.payload
        result: dict[str, Any] = {
            "admin_name": p.get("admin_name") or "",
            "message": p.get("message") or "",
        }

        # Parse before/after JSON strings into dicts
        before_raw = p.get("before")
        if isinstance(before_raw, str):
            try:
                result["before"] = json.loads(before_raw)
            except (json.JSONDecodeError, ValueError):
                result["before"] = {"raw": before_raw}
        elif isinstance(before_raw, dict):
            result["before"] = before_raw

        after_raw = p.get("after")
        if isinstance(after_raw, str):
            try:
                result["after"] = json.loads(after_raw)
            except (json.JSONDecodeError, ValueError):
                result["after"] = {"raw": after_raw}
        elif isinstance(after_raw, dict):
            result["after"] = after_raw

        return result
    except Exception as e:
        logger.debug("audit_lookup_failed", audit_id=audit_id, error=str(e))
        return None


async def _ensure_change_group(
    audit_id: str | None,
    org_id: str,
    site_id: str,
    site_name: str,
    event_type: str,
    payload: dict[str, Any],
    session_id: PydanticObjectId,
) -> PydanticObjectId | None:
    """Create or find a ChangeGroup for this audit_id and link the session."""
    if not audit_id:
        return None

    try:
        from app.modules.impact_analysis.services import change_group_service

        # Infer change source from event type
        if "AP_" in event_type:
            change_source = "ap_config"
        elif "SW_" in event_type:
            change_source = "switch_config"
        elif "GW_" in event_type:
            change_source = "gateway_config"
        else:
            change_source = "config"

        # Build description from audit data if available
        change_description = payload.get("text") or f"{event_type} at {site_name}"

        triggered_by = payload.get("commit_user") or payload.get("admin_name") or None

        group, _is_new = await change_group_service.get_or_create_group(
            audit_id=audit_id,
            org_id=org_id,
            site_id=site_id,
            change_source=change_source,
            change_description=change_description,
            triggered_by=triggered_by,
        )

        await change_group_service.add_session_to_group(group.id, session_id)
        return group.id
    except Exception:
        logger.warning("change_group_assignment_failed", audit_id=audit_id, session_id=str(session_id), exc_info=True)
        return None


async def _handle_pre_config_trigger(
    webhook_event_id: str,
    event_type: str,
    device_mac: str,
    device_name: str,
    site_id: str,
    org_id: str,
    payload: dict[str, Any],
    config: SystemConfig,
) -> None:
    """Handle a pre-config trigger (CONFIG_CHANGED_BY_*) — create or merge monitoring session."""
    device_type = _infer_device_type(event_type)
    site_name = payload.get("site_name") or ""
    config_event = await _build_config_event(webhook_event_id, event_type, device_mac, device_name, payload)
    duration, interval = get_monitoring_defaults(device_type)

    session, is_new = await session_manager.create_or_merge_session(
        site_id=site_id,
        site_name=site_name,
        org_id=org_id,
        device_mac=device_mac,
        device_name=device_name,
        device_type=device_type,
        config_event=config_event,
        duration_minutes=duration,
        interval_minutes=interval,
    )

    # Record config change in timeline
    await _add_timeline_and_tag(session, webhook_event_id, event_type, device_name, "info")

    # Assign to change group if audit_id present
    audit_id = payload.get("audit_id")
    if audit_id and session.change_group_id is None:
        group_id = await _ensure_change_group(
            audit_id=audit_id,
            org_id=org_id,
            site_id=site_id,
            site_name=site_name,
            event_type=event_type,
            payload=payload,
            session_id=session.id,
        )
        if group_id:
            await MonitoringSession.find_one(MonitoringSession.id == session.id).update(
                {"$set": {"change_group_id": group_id}}
            )
            session.change_group_id = group_id

    if is_new:
        from app.modules.impact_analysis.workers.monitoring_worker import run_monitoring_pipeline

        create_background_task(
            run_monitoring_pipeline(str(session.id)),
            name=f"impact-pipeline-{session.id}",
        )

    logger.info(
        "impact_pre_config_trigger",
        session_id=str(session.id),
        is_new=is_new,
        event_type=event_type,
        device_mac=device_mac,
    )


async def _handle_configured(
    webhook_event_id: str,
    event_type: str,
    device_mac: str,
    device_name: str,
    site_id: str,
    org_id: str,
    payload: dict[str, Any],
    config: SystemConfig,
) -> None:
    """Handle a CONFIGURED event — confirm config applied or fallback trigger.

    - Session in AWAITING_CONFIG → transition to MONITORING (normal flow)
    - Session in PENDING/BASELINE_CAPTURE → append event (pipeline will detect it)
    - Session in MONITORING → merge (re-config during monitoring)
    - No session → fallback: create new session and start pipeline
    """
    session = await _find_active_session(device_mac)
    config_event = await _build_config_event(webhook_event_id, event_type, device_mac, device_name, payload)

    if session:
        if session.status == SessionStatus.AWAITING_CONFIG:
            await session_manager.config_applied(session, config_event)
            logger.info(
                "impact_config_applied",
                session_id=str(session.id),
                event_type=event_type,
                device_mac=device_mac,
            )
        elif session.status in {SessionStatus.PENDING, SessionStatus.BASELINE_CAPTURE}:
            # Config applied before baseline finished — record it, pipeline will skip AWAITING_CONFIG
            # Use atomic $push/$set to avoid race condition with concurrent events
            config_event_dict = config_event.model_dump(mode="json")
            await MonitoringSession.find_one(MonitoringSession.id == session.id).update(
                {
                    "$push": {"config_changes": config_event_dict},
                    "$set": {
                        "config_applied_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                    },
                }
            )
            logger.info(
                "impact_configured_during_baseline",
                session_id=str(session.id),
                event_type=event_type,
                device_mac=device_mac,
            )
        else:
            # In MONITORING/VALIDATING — merge: append event, reset polls
            duration, interval = get_monitoring_defaults(session.device_type)
            session, _ = await session_manager.create_or_merge_session(
                site_id=session.site_id,
                site_name=session.site_name,
                org_id=session.org_id,
                device_mac=device_mac,
                device_name=device_name,
                device_type=session.device_type,
                config_event=config_event,
                duration_minutes=duration,
                interval_minutes=interval,
            )
            await _add_timeline_and_tag(session, webhook_event_id, event_type, device_name, "info")
            logger.info(
                "impact_configured_merge",
                session_id=str(session.id),
                event_type=event_type,
                device_mac=device_mac,
            )
        return

    # No active session — fallback trigger: create new session
    device_type = _infer_device_type(event_type)
    site_name = payload.get("site_name") or ""
    duration, interval = get_monitoring_defaults(device_type)

    session, is_new = await session_manager.create_or_merge_session(
        site_id=site_id,
        site_name=site_name,
        org_id=org_id,
        device_mac=device_mac,
        device_name=device_name,
        device_type=device_type,
        config_event=config_event,
        duration_minutes=duration,
        interval_minutes=interval,
    )

    await _add_timeline_and_tag(session, webhook_event_id, event_type, device_name, "info")

    # Assign to change group if audit_id present
    audit_id = payload.get("audit_id")
    if audit_id and session.change_group_id is None:
        group_id = await _ensure_change_group(
            audit_id=audit_id,
            org_id=org_id,
            site_id=site_id,
            site_name=site_name,
            event_type=event_type,
            payload=payload,
            session_id=session.id,
        )
        if group_id:
            await MonitoringSession.find_one(MonitoringSession.id == session.id).update(
                {"$set": {"change_group_id": group_id}}
            )
            session.change_group_id = group_id

    if is_new:
        from app.modules.impact_analysis.workers.monitoring_worker import run_monitoring_pipeline

        create_background_task(
            run_monitoring_pipeline(str(session.id)),
            name=f"impact-pipeline-{session.id}",
        )

    logger.info(
        "impact_configured_fallback_trigger",
        session_id=str(session.id),
        is_new=is_new,
        event_type=event_type,
        device_mac=device_mac,
    )


async def _handle_config_failed(
    webhook_event_id: str,
    event_type: str,
    device_mac: str,
    device_name: str,
    site_id: str = "",
    org_id: str = "",
) -> None:
    """Handle CONFIG_FAILED — alert immediately if awaiting config, else treat as incident."""
    from app.core.websocket import ws_manager

    session = await _find_active_session(device_mac)

    if session and session.status == SessionStatus.AWAITING_CONFIG:
        # Config failed to apply — lifecycle failure + critical impact
        incident = DeviceIncident(
            event_type=event_type,
            device_mac=device_mac,
            device_name=device_name,
            timestamp=datetime.now(timezone.utc),
            webhook_event_id=webhook_event_id,
            severity="critical",
        )
        await session_manager.add_incident(session, incident)
        await session_manager.escalate_impact(session, "critical")
        await session_manager.transition(session, SessionStatus.FAILED)

        # Use targeted $set instead of full save to avoid overwriting transition state
        await MonitoringSession.find_one(MonitoringSession.id == session.id).update(
            {"$set": {"progress": {"phase": "failed", "message": "Config failed to apply", "percent": 100}}}
        )
        session.progress = {"phase": "failed", "message": "Config failed to apply", "percent": 100}

        await ws_manager.broadcast(
            "impact:alerts",
            {
                "type": "impact_alert",
                "data": {
                    "session_id": str(session.id),
                    "device_name": session.device_name,
                    "device_type": session.device_type,
                    "site_name": session.site_name,
                    "severity": "critical",
                    "summary": f"Configuration failed to apply to {session.device_name or session.device_mac}",
                    "has_revert": False,
                },
            },
        )

        logger.info(
            "impact_config_failed_alert",
            session_id=str(session.id),
            event_type=event_type,
            device_mac=device_mac,
        )
        return

    # Session in MONITORING or other active state — treat as normal incident
    if session:
        incident = DeviceIncident(
            event_type=event_type,
            device_mac=device_mac,
            device_name=device_name,
            timestamp=datetime.now(timezone.utc),
            webhook_event_id=webhook_event_id,
            severity="warning",
        )
        await session_manager.add_incident(session, incident)
        logger.info(
            "impact_config_failed_incident",
            session_id=str(session.id),
            event_type=event_type,
            device_mac=device_mac,
        )
        return

    # No session — fall through to incident handler for topology correlation
    await _handle_incident(
        webhook_event_id, event_type, device_mac, device_name, site_id=site_id, org_id=org_id, severity="warning"
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
        await _add_timeline_and_tag(session, webhook_event_id, event_type, device_name, severity)

        # Escalate impact directly based on incident severity
        impact_level = "critical" if severity == "critical" else "warning"
        await session_manager.escalate_impact(session, impact_level)

        # Trigger AI analysis on bad events during active monitoring
        if session.status in {SessionStatus.MONITORING, SessionStatus.VALIDATING}:
            await _maybe_trigger_ai(session, event_type, device_name)

        logger.info(
            "impact_incident_added",
            session_id=str(session.id),
            event_type=event_type,
            device_mac=device_mac,
        )
        return

    # If no direct match AND it's a disconnect event, check correlation
    if event_type in _DISCONNECT_EVENTS and site_id:
        try:
            if event_type == "AP_DISCONNECTED":
                # AP disconnects: check switch stats LLDP clients for direct link
                await _check_ap_switch_correlation(webhook_event_id, device_mac, device_name, site_id, org_id)
            else:
                # SW/GW disconnects: use topology path analysis
                await _check_topology_correlation(
                    webhook_event_id, event_type, device_mac, device_name, site_id, org_id
                )
        except Exception as exc:
            logger.warning(
                "disconnect_correlation_failed",
                event_type=event_type,
                device_mac=device_mac,
                site_id=site_id,
                error=str(exc),
                exc_info=True,
            )


# Disconnect events eligible for correlation
_DISCONNECT_EVENTS = {"AP_DISCONNECTED", "SW_DISCONNECTED", "GW_DISCONNECTED"}


async def _check_ap_switch_correlation(
    webhook_event_id: str,
    ap_mac: str,
    ap_name: str,
    site_id: str,
    org_id: str,
) -> None:
    """Check if a disconnected AP was connected to a monitored switch via LLDP.

    Uses the ``device_clients`` array stored on the MonitoringSession at baseline
    (captured from switch device stats). No API call needed.
    """
    ap_mac_normalized = ap_mac.lower().replace(":", "")

    # Find active switch sessions at this site that have LLDP client data
    switch_sessions = await MonitoringSession.find(
        MonitoringSession.site_id == site_id,
        MonitoringSession.device_type == DeviceType.SWITCH,
        {"status": {"$in": [s.value for s in ACTIVE_STATUSES]}},
    ).to_list()

    if not switch_sessions:
        return

    for session in switch_sessions:
        for client in session.device_clients:
            if not isinstance(client, dict):
                continue
            client_mac = (client.get("mac") or "").lower().replace(":", "")
            if client_mac == ap_mac_normalized:
                port_ids = client.get("port_ids", [])
                incident = DeviceIncident(
                    event_type="AP_DISCONNECTED",
                    device_mac=ap_mac,
                    device_name=ap_name,
                    timestamp=datetime.now(timezone.utc),
                    webhook_event_id=webhook_event_id,
                    severity="warning",
                    is_revert=False,
                )
                await session_manager.add_incident(session, incident)
                await _add_timeline_and_tag(session, webhook_event_id, "AP_DISCONNECTED", ap_name, "warning")
                if session.status in {SessionStatus.MONITORING, SessionStatus.VALIDATING}:
                    await _maybe_trigger_ai(session, "AP_DISCONNECTED", ap_name)
                logger.info(
                    "ap_switch_correlated_incident",
                    session_id=str(session.id),
                    switch_mac=session.device_mac,
                    ap_mac=ap_mac,
                    port_ids=port_ids,
                )
                return  # Only correlate to one session

    logger.info(
        "ap_switch_correlation_no_match",
        ap_mac=ap_mac,
        site_id=site_id,
        sessions_checked=len(switch_sessions),
        total_clients=sum(len(s.device_clients) for s in switch_sessions),
    )


async def _check_topology_correlation(
    webhook_event_id: str,
    event_type: str,
    device_mac: str,
    device_name: str,
    site_id: str,
    org_id: str,
) -> None:
    """Check if a disconnected device is a neighbor of a monitored device.

    Uses stored topology from the session (topology_latest or topology_baseline)
    instead of making live API calls. Also checks device_clients (LLDP neighbors).
    """
    # Find all active sessions at this site
    active_sessions = await MonitoringSession.find(
        MonitoringSession.site_id == site_id,
        {"status": {"$in": [s.value for s in ACTIVE_STATUSES]}},
    ).to_list()

    if not active_sessions:
        return

    mac_normalized = device_mac.lower().replace(":", "")

    for session in active_sessions:
        correlated = False

        # Strategy 1: Check device_clients (LLDP neighbors captured at baseline)
        for client in session.device_clients:
            if isinstance(client, dict):
                client_mac = (client.get("mac") or "").lower().replace(":", "")
                if client_mac == mac_normalized:
                    correlated = True
                    break

        # Strategy 2: Check stored topology for neighbor/path relationships
        if not correlated:
            topo = session.topology_latest or session.topology_baseline
            if topo:
                from app.modules.impact_analysis.services.topology_service import (
                    build_adjacency,
                    find_device_id_by_mac,
                    get_topology_connections,
                    get_topology_devices,
                )

                devices = get_topology_devices(topo)
                connections = get_topology_connections(topo)
                adj = build_adjacency(connections)

                monitored_id = find_device_id_by_mac(devices, session.device_mac)
                disconnected_id = find_device_id_by_mac(devices, device_mac)

                if monitored_id and disconnected_id:
                    # Check if disconnected device is a direct neighbor
                    if disconnected_id in adj.get(monitored_id, []):
                        correlated = True

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
            await _add_timeline_and_tag(session, webhook_event_id, event_type, device_name, "warning")
            if session.status in {SessionStatus.MONITORING, SessionStatus.VALIDATING}:
                await _maybe_trigger_ai(session, event_type, device_name)
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
    await _add_timeline_and_tag(session, webhook_event_id, event_type, device_name, "critical")

    # Config revert is a critical finding — escalate severity, let monitoring continue
    await session_manager.escalate_impact(session, "critical")
    if session.status in {SessionStatus.MONITORING, SessionStatus.VALIDATING}:
        await _maybe_trigger_ai(session, event_type, device_name)

    logger.info(
        "impact_revert_detected",
        session_id=str(session.id),
        event_type=event_type,
        device_mac=device_mac,
    )


async def _handle_resolution(event_type: str, device_mac: str) -> None:
    """Handle a resolution event — resolve matching incidents."""
    incident_event_type = RESOLUTION_TO_INCIDENT.get(event_type, event_type)
    session = await MonitoringSession.find_one(
        MonitoringSession.device_mac == device_mac,
        {"status": {"$in": [s.value for s in ACTIVE_STATUSES]}},
    )

    # Fallback: find sessions with correlated incidents from this device
    if not session:
        session = await MonitoringSession.find_one(
            {
                "incidents": {"$elemMatch": {"device_mac": device_mac, "resolved": False}},
                "status": {"$in": [s.value for s in ACTIVE_STATUSES]},
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


# ── Timeline and webhook tagging helpers ─────────────────────────────────


async def _add_timeline_and_tag(
    session: MonitoringSession,
    webhook_event_id: str | None,
    event_type: str,
    device_name: str,
    severity: str,
) -> None:
    """Add a timeline entry for a routed webhook event and tag the WebhookEvent."""
    # Add timeline entry
    await append_timeline_entry(
        session,
        TimelineEntry(
            type=TimelineEntryType.WEBHOOK_EVENT,
            title=f"{event_type}: {device_name or 'unknown'}",
            severity=severity,
            data={"event_type": event_type, "device_name": device_name, "webhook_event_id": webhook_event_id},
        ),
    )

    # Tag the WebhookEvent.routed_to with "impact_analysis"
    if webhook_event_id:
        try:
            from app.modules.automation.models.webhook import WebhookEvent

            await WebhookEvent.find_one(WebhookEvent.id == webhook_event_id).update(
                {"$addToSet": {"routed_to": "impact_analysis"}}
            )
        except Exception:
            logger.debug("webhook_tagging_failed", webhook_event_id=webhook_event_id, exc_info=True)


async def _maybe_trigger_ai(session: MonitoringSession, event_type: str, device_name: str) -> None:
    """Trigger AI analysis for bad device events during active monitoring."""
    from app.modules.impact_analysis.workers.monitoring_worker import trigger_ai_analysis

    create_background_task(
        trigger_ai_analysis(
            str(session.id),
            trigger="webhook_event",
            trigger_context={"event_type": event_type, "device_name": device_name},
        ),
        name=f"impact-ai-{session.id}-{event_type}",
    )
