"""Monitoring pipeline for config change impact analysis.

One async coroutine per session. Phases:
  0. PENDING — 5s batching window for rapid-fire config events
  1. BASELINE_CAPTURE — historical SLE + initial topology snapshot
  1.5. AWAITING_CONFIG — wait for CONFIGURED event (pre-config triggers only)
  2. MONITORING — two parallel branches:
     A) Device validation (2/5/10 min by device type) → VALIDATING
     C) SLE monitoring (10min x 6 = 60min, site-level)
  3. Terminal — COMPLETED (impact tracked via impact_severity)

Webhook event monitoring (Branch B) is handled by the event_handler module —
events keep routing as long as the session is in ACTIVE_STATUSES.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from beanie import PydanticObjectId

from app.core.websocket import ws_manager
from app.models.system import SystemConfig
from app.modules.impact_analysis.models import (
    ACTIVE_STATUSES,
    DeviceIncident,
    MonitoringSession,
    SessionStatus,
    TimelineEntry,
    TimelineEntryType,
    get_monitoring_defaults,
)
from app.modules.impact_analysis.services import session_manager, sle_service, template_service, topology_service
from app.modules.impact_analysis.services.session_manager import (
    append_timeline_entry,
    broadcast_session_update,
    escalate_impact,
)
from app.modules.impact_analysis.services.site_data_coordinator import SiteDataCoordinator
from app.services.mist_service_factory import create_mist_service

logger = structlog.get_logger(__name__)

# SLE monitoring runs 60 min regardless of device type
_SLE_POLLS_TOTAL = 6
_SLE_INTERVAL_SECONDS = 600  # 10 minutes


async def recover_active_sessions() -> int:
    """Resume monitoring pipelines for sessions that were active when the backend stopped.

    Called during application startup (lifespan). Finds all sessions in
    non-terminal active states and restarts their monitoring pipelines.
    """
    from app.core.tasks import create_background_task

    active_sessions = await MonitoringSession.find(
        {"status": {"$in": [s.value for s in ACTIVE_STATUSES]}},
    ).to_list()

    if not active_sessions:
        return 0

    for session in active_sessions:
        logger.info(
            "recovering_session",
            session_id=str(session.id),
            status=session.status,
            device_mac=session.device_mac,
        )
        create_background_task(
            run_monitoring_pipeline(str(session.id)),
            name=f"impact-recovery-{session.id}",
        )

    logger.info("impact_sessions_recovered", count=len(active_sessions))
    return len(active_sessions)


async def run_monitoring_pipeline(session_id: str) -> None:
    """Main monitoring pipeline — one coroutine per session."""
    session = await MonitoringSession.get(PydanticObjectId(session_id))
    if not session:
        logger.error("monitoring_pipeline_session_not_found", session_id=session_id)
        return

    try:
        coordinator = SiteDataCoordinator.get_or_create(session.site_id)

        # Shared Mist API session — reused across all SLE calls in the pipeline
        mist = await create_mist_service()
        shared_api_session = mist.get_session()

        # Per-session logger for diagnostics
        from app.modules.impact_analysis.services.session_logger import SessionLogger

        session_log = SessionLogger(session_id)
        await session_log.info("init", f"Pipeline started for {session.device_name or session.device_mac}")

        # ── Phase 0: PENDING (5s batching window) ─────────────────────────
        if session.status == SessionStatus.PENDING:
            await _interruptible_sleep(session_id, 5)
            session = await MonitoringSession.get(PydanticObjectId(session_id))
            if not session or session.status in {SessionStatus.CANCELLED, SessionStatus.FAILED}:
                return

        # ── Phase 1: BASELINE_CAPTURE ─────────────────────────────────────
        if session.status in {SessionStatus.PENDING, SessionStatus.BASELINE_CAPTURE}:
            if session.status == SessionStatus.PENDING:
                await session_manager.transition(session, SessionStatus.BASELINE_CAPTURE)
            session.progress = {"phase": session.status.value, "message": "Capturing SLE baseline...", "percent": 5}
            session.update_timestamp()
            await session.save()
            await broadcast_session_update(session)

            change_time = session.config_changes[0].timestamp if session.config_changes else session.created_at
            site_data = await coordinator.fetch_site_data(
                session.site_id, session.org_id, device_type=session.device_type.value
            )

            device_id = session.device_mist_id
            if not device_id and site_data.topology:
                dev = site_data.topology.resolve_device(session.device_mac)
                if dev:
                    device_id = dev.id
                    session.device_mist_id = device_id

            sle_baseline = await sle_service.capture_baseline(
                session.site_id,
                session.org_id,
                session.device_type.value,
                device_id=device_id,
                before_timestamp=change_time,
                api_session=shared_api_session,
            )

            session.sle_baseline = sle_baseline
            if site_data.topology:
                session.topology_baseline = topology_service.capture_topology_snapshot(site_data.topology)

            # Capture LLDP clients via targeted device-type stats call
            session.device_clients = await _fetch_device_clients(
                session.site_id,
                session.org_id,
                session.device_mac,
                session.device_type.value,
                api_session=shared_api_session,
                session_log=session_log,
            )
            logger.info(
                "baseline_device_clients",
                session_id=session_id,
                device_mac=session.device_mac,
                device_type=session.device_type.value,
                clients_found=len(session.device_clients),
            )

            # Capture template configs for config drift detection
            session.template_baseline = await template_service.capture_template_snapshot(
                session.site_id, session.org_id, api_session=shared_api_session
            )

            session.progress = {"phase": session.status.value, "message": "Baseline captured", "percent": 10}
            session.update_timestamp()
            await session.save()
            await broadcast_session_update(session)

        # ── Phase 1.5: AWAITING_CONFIG (pre-config triggers only) ─────────
        if session.status in {SessionStatus.BASELINE_CAPTURE, SessionStatus.AWAITING_CONFIG}:
            if _is_pre_config_session(session) and not _has_configured_event(session):
                if session.status == SessionStatus.BASELINE_CAPTURE:
                    await session_manager.transition(session, SessionStatus.AWAITING_CONFIG)

                session.progress = {
                    "phase": "awaiting_config",
                    "message": "Waiting for config to be applied to device...",
                    "percent": 12,
                }
                session.update_timestamp()
                await session.save()
                await broadcast_session_update(session)

                config_arrived = await _wait_for_config_applied(session_id, timeout_seconds=600)

                session = await MonitoringSession.get(PydanticObjectId(session_id))
                if not session:
                    return
                if session.status in {SessionStatus.CANCELLED, SessionStatus.FAILED}:
                    return

                if not config_arrived and session.status == SessionStatus.AWAITING_CONFIG:
                    session.awaiting_config_warnings.append(
                        "No CONFIGURED event received within 10 minutes. Proceeding to monitoring."
                    )
                    timeout_incident = DeviceIncident(
                        event_type="CONFIG_WAIT_TIMEOUT",
                        device_mac=session.device_mac,
                        device_name=session.device_name,
                        timestamp=datetime.now(timezone.utc),
                        severity="warning",
                    )
                    await session_manager.add_incident(session, timeout_incident)

                session = await MonitoringSession.get(PydanticObjectId(session_id))
                if not session or session.status in {
                    SessionStatus.CANCELLED,
                    SessionStatus.FAILED,
                }:
                    return

        # ── Phase 2: MONITORING — parallel branches ───────────────────────
        if session.status in {SessionStatus.BASELINE_CAPTURE, SessionStatus.AWAITING_CONFIG}:
            await session_manager.transition(session, SessionStatus.MONITORING)
            session.monitoring_started_at = datetime.now(timezone.utc)
            session.monitoring_ends_at = session.monitoring_started_at + timedelta(
                seconds=_SLE_POLLS_TOTAL * _SLE_INTERVAL_SECONDS
            )
            session.update_timestamp()
            await session.save()

        if session.status == SessionStatus.MONITORING:
            # Launch both branches in parallel
            validation_task = asyncio.create_task(
                _run_device_validation(session_id, coordinator),
                name=f"validation-{session_id}",
            )
            sle_task = asyncio.create_task(
                _run_sle_monitoring(session_id, shared_api_session),
                name=f"sle-{session_id}",
            )

            # Wait for both to complete (validation finishes first, SLE runs 60 min)
            await asyncio.gather(validation_task, sle_task, return_exceptions=True)

        # ── Phase 2 (recovery): VALIDATING — SLE still running ───────────
        elif session.status == SessionStatus.VALIDATING:
            # Recovery case: validation already done, just resume SLE monitoring
            logger.info("resuming_sle_monitoring", session_id=session_id)
            await _run_sle_monitoring(session_id, shared_api_session)

        # ── Phase 3: Finalize ─────────────────────────────────────────────
        await _finalize_session(session_id)

    except asyncio.CancelledError:
        logger.info("monitoring_pipeline_cancelled", session_id=session_id)
    except Exception as e:
        logger.error("monitoring_pipeline_failed", session_id=session_id, error=str(e))
        try:
            session = await MonitoringSession.get(PydanticObjectId(session_id))
            if session and session.status not in {
                SessionStatus.COMPLETED,
                SessionStatus.CANCELLED,
            }:
                session.status = SessionStatus.FAILED
                session.progress = {"phase": "failed", "message": "Pipeline error", "percent": 0}
                session.completed_at = datetime.now(timezone.utc)
                session.update_timestamp()
                await session.save()
                await ws_manager.broadcast(
                    f"impact:{session.id}",
                    {"type": "session_failed", "data": {"error": "Pipeline error"}},
                )
        except Exception:
            pass


# ── Branch A: Device Validation ──────────────────────────────────────────


async def _run_device_validation(session_id: str, coordinator: SiteDataCoordinator | None = None) -> None:
    """Run device-type-specific validation checks after a short wait.

    AP: 2 min, Switch: 5 min, Gateway: 10 min.
    Uses SiteDataCoordinator for data (device stats, ports, topology). Transitions to VALIDATING.
    Template drift is deferred to finalization (after SLE completes).
    """
    session = await MonitoringSession.get(PydanticObjectId(session_id))
    if not session or session.status not in {SessionStatus.MONITORING, SessionStatus.VALIDATING}:
        return

    # Wait device-type-specific duration
    duration_min, interval_min = get_monitoring_defaults(session.device_type)
    wait_seconds = duration_min * 60
    logger.info(
        "device_validation_waiting",
        session_id=session_id,
        device_type=session.device_type.value,
        wait_seconds=wait_seconds,
    )
    await _interruptible_sleep(session_id, wait_seconds)

    # Re-read after sleep
    session = await MonitoringSession.get(PydanticObjectId(session_id))
    if not session or session.status not in {SessionStatus.MONITORING}:
        return  # Cancelled, failed, or already past MONITORING

    session.progress = {"phase": "monitoring", "message": "Running validation checks...", "percent": 50}
    session.update_timestamp()
    await session.save()
    await broadcast_session_update(session)

    # Fetch validation data via SiteDataCoordinator (cached, shared across sessions)
    if not coordinator:
        coordinator = SiteDataCoordinator.get_or_create(session.site_id)
    site_data = await coordinator.fetch_site_data(session.site_id, session.org_id)
    topology = site_data.topology
    device_stats = site_data.device_stats
    port_stats = site_data.port_stats
    device_configs = site_data.device_configs

    # Fallback: populate device_clients if baseline missed them
    if not session.device_clients:
        clients = await _fetch_device_clients(
            session.site_id,
            session.org_id,
            session.device_mac,
            session.device_type.value,
        )
        if clients:
            await MonitoringSession.find_one(MonitoringSession.id == session.id).update(
                {"$set": {"device_clients": clients}}
            )
            logger.info("device_clients_fallback", session_id=session_id, clients_found=len(clients))

    # Store port stats for the monitored device (used by AI prompt)
    device_mac_lower = session.device_mac.lower()
    device_ports = [
        p
        for p in port_stats
        if isinstance(p, dict) and (p.get("mac") or p.get("device_mac") or "").lower() == device_mac_lower
    ]
    if device_ports:
        await MonitoringSession.find_one(MonitoringSession.id == session.id).update(
            {"$set": {"device_port_stats": device_ports}}
        )

    # Update topology_latest for validation checks
    if topology:
        session = await MonitoringSession.get(PydanticObjectId(session_id))
        if not session:
            return
        session.topology_latest = topology_service.capture_topology_snapshot(topology)
        session.update_timestamp()
        await session.save()

    # Run validation checks
    try:
        from app.modules.impact_analysis.services.validation_service import run_validations

        session = await MonitoringSession.get(PydanticObjectId(session_id))
        if not session:
            return
        validation_results = await run_validations(
            session,
            device_stats=device_stats,
            port_stats=port_stats,
            topology=topology,
            device_configs=device_configs,
        )

        # Save validation results via atomic update to avoid race with SLE branch
        await MonitoringSession.find_one(MonitoringSession.id == session.id).update(
            {"$set": {"validation_results": validation_results}}
        )
    except Exception as e:
        logger.warning("validation_failed", session_id=session_id, error=str(e))
        validation_results = {
            "overall_status": "error",
            "error": "Validation checks encountered an internal error",
        }
        await MonitoringSession.find_one(MonitoringSession.id == PydanticObjectId(session_id)).update(
            {"$set": {"validation_results": validation_results}}
        )

    # Record in timeline
    overall = validation_results.get("overall_status", "pass") if validation_results else "error"
    severity = "critical" if overall == "fail" else ("warning" if overall == "warn" else "info")
    await append_timeline_entry(
        session,
        TimelineEntry(
            type=TimelineEntryType.VALIDATION,
            title="Validation checks completed",
            severity=severity,
            data={"overall_status": overall, "results": validation_results},
        ),
    )

    # Broadcast validation results
    await ws_manager.broadcast(
        f"impact:{session.id}",
        {
            "type": "validation_completed",
            "data": {"overall_status": overall, "results": validation_results},
        },
    )

    # Escalate impact based on validation result directly (don't wait for AI interpretation)
    if overall == "fail":
        session = await MonitoringSession.get(PydanticObjectId(session_id))
        if session:
            await escalate_impact(session, "critical")
    elif overall == "warn":
        session = await MonitoringSession.get(PydanticObjectId(session_id))
        if session:
            await escalate_impact(session, "warning")

    # Also trigger AI analysis for detailed assessment
    if overall in ("fail", "warn"):
        await trigger_ai_analysis(
            session_id,
            trigger="validation",
            trigger_context={"overall_status": overall, "results": validation_results},
        )

    # Transition to VALIDATING (SLE monitoring continues)
    session = await MonitoringSession.get(PydanticObjectId(session_id))
    if session and session.status == SessionStatus.MONITORING:
        session.progress = {"phase": "validating", "message": "SLE monitoring in progress...", "percent": 60}
        session.update_timestamp()
        await session.save()
        await session_manager.transition(session, SessionStatus.VALIDATING)
        await broadcast_session_update(session)


# ── Branch C: SLE Monitoring ─────────────────────────────────────────────


async def _run_sle_monitoring(session_id: str, api_session: Any = None) -> None:
    """Run site-level SLE monitoring for 60 minutes (6 polls x 10 min).

    Compares each snapshot to baseline and triggers AI analysis on degradation.
    """
    session = await MonitoringSession.get(PydanticObjectId(session_id))
    if not session:
        return

    config = await SystemConfig.get_config()
    sle_threshold = config.impact_analysis_sle_threshold_percent

    # Determine starting poll (for recovery)
    sle_poll = len(session.sle_snapshots)

    for poll_num in range(sle_poll, _SLE_POLLS_TOTAL):
        await _interruptible_sleep(session_id, _SLE_INTERVAL_SECONDS)

        # Re-read session (detect cancel/fail)
        session = await MonitoringSession.get(PydanticObjectId(session_id))
        if not session:
            return
        if session.status in {SessionStatus.CANCELLED, SessionStatus.FAILED}:
            return

        # Capture SLE snapshot
        snapshot = await sle_service.capture_snapshot(
            session.site_id, session.org_id, session.device_type.value, api_session=api_session
        )

        # Compute running delta against baseline
        all_snapshots = list(session.sle_snapshots) + [snapshot]
        sle_delta = sle_service.compute_delta(
            session.sle_baseline or {},
            all_snapshots,
            sle_threshold,
        )

        # Save via atomic operations to avoid race with validation branch
        await MonitoringSession.find_one(MonitoringSession.id == session.id).update(
            {
                "$push": {"sle_snapshots": snapshot},
                "$set": {"sle_delta": sle_delta},
                "$inc": {"polls_completed": 1},
            }
        )

        # Record SLE check in timeline
        degraded = sle_delta.get("overall_degraded", False) if sle_delta else False
        degraded_names = sle_delta.get("degraded_metric_names", []) if sle_delta else []
        sle_severity = "warning" if degraded else "info"
        await append_timeline_entry(
            session,
            TimelineEntry(
                type=TimelineEntryType.SLE_CHECK,
                title=f"SLE check {poll_num + 1}/{_SLE_POLLS_TOTAL}",
                severity=sle_severity,
                data={
                    "poll_number": poll_num + 1,
                    "metrics": snapshot,
                    "degraded": degraded,
                    "degraded_metrics": degraded_names,
                },
            ),
        )

        # Broadcast progress
        # Progress: 60-95% range for SLE monitoring phase
        percent = int(60 + (poll_num + 1) / _SLE_POLLS_TOTAL * 35)
        await MonitoringSession.find_one(MonitoringSession.id == session.id).update(
            {
                "$set": {
                    "progress": {
                        "phase": session.status.value,
                        "message": f"SLE check {poll_num + 1}/{_SLE_POLLS_TOTAL}",
                        "percent": percent,
                    }
                }
            }
        )

        # Re-read for broadcast
        session = await MonitoringSession.get(PydanticObjectId(session_id))
        if session:
            await broadcast_session_update(session)
            await ws_manager.broadcast(
                f"impact:{session.id}",
                {
                    "type": "sle_snapshot",
                    "data": {"poll_number": poll_num + 1, "metrics": snapshot, "delta": sle_delta},
                },
            )

        # If SLE degraded, trigger AI analysis
        if degraded and degraded_names:
            await trigger_ai_analysis(
                session_id,
                trigger="sle_degradation",
                trigger_context={"degraded_metrics": degraded_names, "delta": sle_delta},
            )

    # Final SLE drill-down if degradation detected
    session = await MonitoringSession.get(PydanticObjectId(session_id))
    if session and session.sle_delta and session.sle_delta.get("overall_degraded"):
        degraded_names = session.sle_delta.get("degraded_metric_names", [])
        if degraded_names:
            drill_down = await sle_service.drill_down_device_sle(
                session.site_id,
                session.org_id,
                degraded_names,
                session.device_type.value,
                api_session=api_session,
            )
            await MonitoringSession.find_one(MonitoringSession.id == session.id).update(
                {"$set": {"sle_drill_down": drill_down}}
            )


# ── AI Analysis (event-driven) ───────────────────────────────────────────


async def trigger_ai_analysis(
    session_id: str,
    trigger: str,
    trigger_context: dict[str, Any] | None = None,
) -> None:
    """Trigger AI analysis when a problem is detected.

    Called from validation branch, SLE branch, or event handler.
    Skips if AI assessment already exists (prevents concurrent duplicate calls).
    """
    session = await MonitoringSession.get(PydanticObjectId(session_id))
    if not session or session.status in {SessionStatus.CANCELLED, SessionStatus.FAILED, SessionStatus.COMPLETED}:
        return

    # Atomically claim the analysis slot to prevent concurrent duplicate runs.
    # Uses ai_analysis_in_progress as the mutex — allows re-analysis when a
    # previous one completed (in_progress=False) but blocks concurrent runs.
    claim_result = await MonitoringSession.find_one(
        MonitoringSession.id == session.id,
        {"ai_analysis_in_progress": {"$ne": True}},
    ).update({"$set": {"ai_analysis_in_progress": True}})
    if not claim_result or claim_result.modified_count == 0:
        logger.info("ai_analysis_skipped_already_in_progress", session_id=session_id, trigger=trigger)
        return

    logger.info(
        "triggering_ai_analysis",
        session_id=session_id,
        trigger=trigger,
    )

    try:
        from app.modules.impact_analysis.services.analysis_service import analyze_session

        result = await analyze_session(session, trigger=trigger, trigger_context=trigger_context)

        # Save AI assessment and release the in-progress lock via atomic update
        await MonitoringSession.find_one(MonitoringSession.id == session.id).update(
            {"$set": {"ai_assessment": result, "ai_analysis_in_progress": False}}
        )

        # Record in timeline
        has_impact = result.get("has_impact", False) if result else False
        ai_severity = result.get("severity", "info") if result else "info"
        await append_timeline_entry(
            session,
            TimelineEntry(
                type=TimelineEntryType.AI_ANALYSIS,
                title=f"AI analysis ({trigger})",
                severity=ai_severity if has_impact else "info",
                data={
                    "trigger": trigger,
                    "has_impact": has_impact,
                    "severity": ai_severity,
                    "summary": (result.get("summary", "")[:500] if result else ""),
                    "source": result.get("source", "unknown") if result else "unknown",
                },
            ),
        )

        # Broadcast AI result
        await ws_manager.broadcast(
            f"impact:{session.id}",
            {
                "type": "ai_analysis_completed",
                "data": {
                    "trigger": trigger,
                    "has_impact": has_impact,
                    "severity": ai_severity,
                    "summary": (result.get("summary", "")[:500] if result else ""),
                },
            },
        )

        # If AI found impact, escalate severity (session continues monitoring)
        if has_impact:
            session = await MonitoringSession.get(PydanticObjectId(session_id))
            if session and session.status in {SessionStatus.MONITORING, SessionStatus.VALIDATING}:
                await escalate_impact(session, ai_severity)
                await ws_manager.broadcast(
                    "impact:alerts",
                    {
                        "type": "impact_alert",
                        "data": {
                            "session_id": str(session.id),
                            "device_name": session.device_name,
                            "device_type": session.device_type.value,
                            "site_name": session.site_name,
                            "severity": ai_severity,
                            "summary": (result.get("summary", "")[:200] if result else "Impact detected"),
                            "has_revert": any(i.is_revert for i in session.incidents),
                        },
                    },
                )

    except ImportError:
        logger.debug("analysis_service_not_available", session_id=session_id)
        await MonitoringSession.find_one(MonitoringSession.id == PydanticObjectId(session_id)).update(
            {"$set": {"ai_analysis_in_progress": False}}
        )
    except Exception as e:
        logger.warning("ai_analysis_failed", session_id=session_id, trigger=trigger, error=str(e))
        await MonitoringSession.find_one(MonitoringSession.id == PydanticObjectId(session_id)).update(
            {"$set": {"ai_assessment_error": f"AI analysis unavailable ({trigger})", "ai_analysis_in_progress": False}}
        )


# ── Finalization ─────────────────────────────────────────────────────────


async def _finalize_session(session_id: str) -> None:
    """Finalize the session after all monitoring branches complete."""
    session = await MonitoringSession.get(PydanticObjectId(session_id))
    if not session:
        return

    # Already in terminal state
    if session.status in {SessionStatus.COMPLETED, SessionStatus.CANCELLED, SessionStatus.FAILED}:
        return

    # Compute template drift (deferred from validation to finalization — saves ~6 API calls)
    if session.template_baseline:
        try:
            template_current = await template_service.capture_template_snapshot(session.site_id, session.org_id)
            template_drift = template_service.compute_template_drift(session.template_baseline, template_current)
            if template_drift:
                template_drift = template_service.correlate_with_config_events(template_drift, session.config_changes)
                await MonitoringSession.find_one(MonitoringSession.id == session.id).update(
                    {"$set": {"template_drift": template_drift}}
                )
        except Exception as e:
            logger.warning("template_drift_failed", session_id=session_id, error=str(e))

    # Re-read after potential template update
    session = await MonitoringSession.get(PydanticObjectId(session_id))
    if not session:
        return

    # All sessions transition to COMPLETED — impact is tracked via impact_severity
    if session.status in {SessionStatus.VALIDATING, SessionStatus.MONITORING}:
        await session_manager.transition(session, SessionStatus.COMPLETED)

        # Determine final impact severity from accumulated findings
        if any(i.is_revert for i in session.incidents):
            await escalate_impact(session, "critical")
        elif session.ai_assessment and session.ai_assessment.get("has_impact"):
            ai_sev = session.ai_assessment.get("severity", "warning")
            await escalate_impact(session, ai_sev)
        elif session.validation_results and session.validation_results.get("overall_status") == "fail":
            await escalate_impact(session, "warning")
        elif session.sle_delta and session.sle_delta.get("overall_degraded"):
            await escalate_impact(session, "warning")

        session = await MonitoringSession.get(PydanticObjectId(session_id))
        if session:
            session.progress = {"phase": session.status.value, "message": "Monitoring complete", "percent": 100}
            session.update_timestamp()
            await session.save()
            await broadcast_session_update(session)

    # Cleanup coordinator if no more active sessions for this site
    if session:
        remaining = await MonitoringSession.find(
            MonitoringSession.site_id == session.site_id,
            {"status": {"$in": [s.value for s in ACTIVE_STATUSES]}},
        ).count()
        if remaining == 0:
            SiteDataCoordinator.cleanup(session.site_id)


# ── Helper functions ─────────────────────────────────────────────────────


async def _fetch_device_clients(
    site_id: str,
    org_id: str,
    device_mac: str,
    device_type: str,
    api_session: Any = None,
    session_log: Any = None,
) -> list[dict[str, Any]]:
    """Fetch LLDP clients for a specific device via org-level stats endpoint.

    Uses ``listOrgDevicesStats(org_id, type, site_id, mac, fields="*")`` which
    returns the full device stats including the ``clients`` LLDP array.
    The site-level list endpoint strips this field.
    """
    import mistapi
    from mistapi.api.v1.orgs import stats as org_stats

    try:
        if not api_session:
            mist = await create_mist_service()
            api_session = mist.get_session()

        resp = await mistapi.arun(
            org_stats.listOrgDevicesStats,
            api_session,
            org_id,
            type=device_type,
            site_id=site_id,
            mac=device_mac,
            fields="*",
            limit=1,
        )

        if resp.status_code != 200 or not resp.data:
            if session_log:
                await session_log.warning(
                    "baseline",
                    f"listOrgDevicesStats(mac={device_mac}) failed: status={resp.status_code}",
                )
            return []

        results = resp.data if isinstance(resp.data, list) else resp.data.get("results", [])
        if not results:
            if session_log:
                await session_log.warning("baseline", f"No stats found for {device_mac}")
            return []

        dev_stat = results[0] if isinstance(results[0], dict) else {}
        clients = dev_stat.get("clients", [])

        if session_log:
            client_macs = [(c.get("mac", "?"), c.get("port_ids", [])) for c in clients if isinstance(c, dict)]
            await session_log.info(
                "baseline",
                f"Device {device_mac} ({dev_stat.get('name', '?')}): {len(clients)} LLDP clients",
                details={"clients": client_macs},
            )

        return clients
    except Exception as e:
        logger.warning("fetch_device_clients_failed", device_mac=device_mac, error=str(e))
        if session_log:
            await session_log.error("baseline", f"fetch_device_clients failed: {e}")

    return []


def _is_pre_config_session(session: MonitoringSession) -> bool:
    """Check if this session was triggered by a pre-config event (CONFIG_CHANGED_BY_*)."""
    if not session.config_changes:
        return False
    return "CONFIG_CHANGED_BY" in session.config_changes[0].event_type


def _has_configured_event(session: MonitoringSession) -> bool:
    """Check if a CONFIGURED event already arrived (fast push scenario)."""
    return any("CONFIGURED" in c.event_type and "CONFIG_CHANGED" not in c.event_type for c in session.config_changes)


async def _wait_for_config_applied(session_id: str, timeout_seconds: int) -> bool:
    """Wait for config to be applied (AWAITING_CONFIG → MONITORING transition).

    Returns True if config was applied, False on timeout.
    Raises CancelledError if session was cancelled/failed/alerted.
    """
    elapsed = 0
    while elapsed < timeout_seconds:
        chunk = min(10, timeout_seconds - elapsed)
        await asyncio.sleep(chunk)
        elapsed += chunk

        doc = await MonitoringSession.find_one(MonitoringSession.id == PydanticObjectId(session_id)).project(
            {"status": 1}
        )
        if not doc:
            raise asyncio.CancelledError()
        status = doc.get("status") if isinstance(doc, dict) else getattr(doc, "status", None)
        if status == SessionStatus.MONITORING.value or status == SessionStatus.MONITORING:
            return True
        if status in {SessionStatus.CANCELLED.value, SessionStatus.FAILED.value, "cancelled", "failed"}:
            raise asyncio.CancelledError()

    return False


async def _interruptible_sleep(session_id: str, total_seconds: int) -> None:
    """Sleep with periodic DB checks for cancellation.

    Uses status-only projection to avoid loading full documents every 10 seconds.
    """
    elapsed = 0
    while elapsed < total_seconds:
        chunk = min(10, total_seconds - elapsed)
        await asyncio.sleep(chunk)
        elapsed += chunk
        if elapsed < total_seconds:
            doc = await MonitoringSession.find_one(MonitoringSession.id == PydanticObjectId(session_id)).project(
                {"status": 1}
            )
            if not doc:
                raise asyncio.CancelledError()
            status = doc.get("status") if isinstance(doc, dict) else getattr(doc, "status", None)
            if status in {SessionStatus.CANCELLED.value, SessionStatus.FAILED.value, "cancelled", "failed"}:
                raise asyncio.CancelledError()
