"""Monitoring pipeline for config change impact analysis.

One async coroutine per session. Phases:
  0. PENDING — 5s batching window for rapid-fire config events
  1. BASELINE_CAPTURE — historical SLE + initial topology snapshot
  2. MONITORING — poll loop fetching site data via SiteDataCoordinator
  3. ANALYZING — SLE delta, validation checks, AI assessment
  4. Terminal — COMPLETED or ALERT based on findings
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from beanie import PydanticObjectId

from app.core.websocket import ws_manager
from app.models.system import SystemConfig
from app.modules.impact_analysis.models import (
    ACTIVE_STATUSES,
    MonitoringSession,
    SessionStatus,
)
from app.modules.impact_analysis.services import session_manager, sle_service, topology_service
from app.modules.impact_analysis.services.session_manager import broadcast_session_update
from app.modules.impact_analysis.services.site_data_coordinator import SiteDataCoordinator

logger = structlog.get_logger(__name__)


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
            site_data = await coordinator.fetch_site_data(session.site_id, session.org_id)

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
            )

            session.sle_baseline = sle_baseline
            if site_data.topology:
                session.topology_baseline = topology_service.capture_topology_snapshot(site_data.topology)
            session.update_timestamp()
            await session.save()
            session.progress = {
                "phase": session.status.value,
                "message": "Baseline captured, starting monitoring...",
                "percent": 10,
            }
            session.update_timestamp()
            await session.save()
            await broadcast_session_update(session)

        # ── Phase 2: MONITORING (poll loop) ───────────────────────────────
        # Safe default for poll_num (used if we skip directly to while loop)
        poll_num = session.polls_completed

        if session.status in {SessionStatus.BASELINE_CAPTURE, SessionStatus.MONITORING}:
            if session.status == SessionStatus.BASELINE_CAPTURE:
                await session_manager.transition(session, SessionStatus.MONITORING)
                session.monitoring_started_at = datetime.now(timezone.utc)
                session.monitoring_ends_at = session.monitoring_started_at + timedelta(minutes=session.duration_minutes)
                await session.save()
            else:
                # Resuming from recovery — log where we're picking up
                logger.info(
                    "monitoring_resumed",
                    session_id=session_id,
                    polls_completed=session.polls_completed,
                    polls_total=session.polls_total,
                )

            poll_num = session.polls_completed

        while poll_num < session.polls_total:
            # Wait for next poll interval
            wait_seconds = session.interval_minutes * 60
            await _interruptible_sleep(session_id, wait_seconds)

            # Re-read session from DB (detect merge/cancel/revert-triggered analyzing)
            session = await MonitoringSession.get(PydanticObjectId(session_id))
            if not session:
                return
            if session.status in {SessionStatus.CANCELLED, SessionStatus.FAILED}:
                return
            if session.status == SessionStatus.ANALYZING:
                break  # Revert triggered early analysis

            # Handle merge (polls_completed reset to 0 by session_manager)
            if session.polls_completed < poll_num:
                poll_num = session.polls_completed
                # Recalculate timing if merge reset it
                if not session.monitoring_started_at:
                    session.monitoring_started_at = datetime.now(timezone.utc)
                    session.monitoring_ends_at = session.monitoring_started_at + timedelta(
                        minutes=session.duration_minutes
                    )
                    await session.save()

            # Check for org-level upgrade opportunity
            await SiteDataCoordinator.maybe_upgrade_to_org_level(session.org_id)

            # Fetch site data (cached if another session just fetched)
            site_data = await coordinator.fetch_site_data(session.site_id, session.org_id)

            # Extract device-specific SLE snapshot from shared site data
            snapshot = sle_service.extract_site_sle(site_data.sle_overview, session.device_type.value)
            session.sle_snapshots.append(snapshot)
            session.polls_completed = poll_num + 1

            # Calculate progress percentage (10-70% range for monitoring phase)
            percent = int(10 + (poll_num + 1) / session.polls_total * 60)
            session.progress = {
                "phase": "monitoring",
                "message": f"Poll {poll_num + 1}/{session.polls_total}",
                "percent": percent,
            }
            session.update_timestamp()
            await session.save()

            await broadcast_session_update(session)

            # Broadcast SLE snapshot for live chart updates
            await ws_manager.broadcast(
                f"impact:{session.id}",
                {
                    "type": "sle_snapshot",
                    "data": {"poll_number": poll_num + 1, "metrics": snapshot},
                },
            )

            poll_num += 1

        # Phase 3: ANALYZING
        # Re-read to get latest state (incidents may have been added during monitoring)
        session = await MonitoringSession.get(PydanticObjectId(session_id))
        if not session or session.status in {SessionStatus.CANCELLED, SessionStatus.FAILED}:
            return

        if session.status != SessionStatus.ANALYZING:
            await session_manager.transition(session, SessionStatus.ANALYZING)

        session.progress = {"phase": session.status.value, "message": "Capturing final topology...", "percent": 72}
        session.update_timestamp()
        await session.save()
        await broadcast_session_update(session)

        # Final topology capture
        site_data = await coordinator.fetch_site_data(session.site_id, session.org_id)
        if site_data.topology:
            session.topology_latest = topology_service.capture_topology_snapshot(site_data.topology)

        # Compute SLE delta
        config = await SystemConfig.get_config()
        session.sle_delta = sle_service.compute_delta(
            session.sle_baseline or {},
            session.sle_snapshots,
            config.impact_analysis_sle_threshold_percent,
        )

        # Drill down if degradation detected
        if session.sle_delta and session.sle_delta.get("overall_degraded"):
            degraded_names = session.sle_delta.get("degraded_metric_names", [])
            if degraded_names:
                session.sle_drill_down = await sle_service.drill_down_device_sle(
                    session.site_id,
                    session.org_id,
                    degraded_names,
                    session.device_type.value,
                )

        session.update_timestamp()
        await session.save()
        session.progress = {"phase": session.status.value, "message": "Running validation checks...", "percent": 75}
        session.update_timestamp()
        await session.save()
        await broadcast_session_update(session)

        # Run validation checks (Phase 6)
        try:
            from app.modules.impact_analysis.services.validation_service import run_validations

            session.validation_results = await run_validations(session, site_data)
        except ImportError:
            logger.debug("validation_service_not_available", session_id=session_id)
            session.validation_results = {"overall_status": "skipped", "reason": "Validation service not yet available"}
        except Exception as e:
            logger.warning("validation_failed", session_id=session_id, error=str(e))
            session.validation_results = {
                "overall_status": "error",
                "error": "Validation checks encountered an internal error",
            }

        session.update_timestamp()
        await session.save()
        session.progress = {"phase": session.status.value, "message": "AI analyzing impact...", "percent": 85}
        session.update_timestamp()
        await session.save()
        await broadcast_session_update(session)

        # AI analysis (Phase 7)
        try:
            from app.modules.impact_analysis.services.analysis_service import analyze_session

            session.ai_assessment = await analyze_session(session)
        except ImportError:
            logger.debug("analysis_service_not_available", session_id=session_id)
            session.ai_assessment_error = "AI analysis not yet available"
        except Exception as e:
            logger.warning("ai_analysis_failed", session_id=session_id, error=str(e))
            session.ai_assessment_error = "AI analysis unavailable"

        session.update_timestamp()
        await session.save()

        # Determine final status
        has_impact = (
            (session.sle_delta and session.sle_delta.get("overall_degraded"))
            or (session.validation_results and session.validation_results.get("overall_status") == "fail")
            or (session.ai_assessment and session.ai_assessment.get("has_impact"))
            or any(i.is_revert for i in session.incidents)
        )
        final_status = SessionStatus.ALERT if has_impact else SessionStatus.COMPLETED
        await session_manager.transition(session, final_status)
        session.progress = {"phase": session.status.value, "message": "Analysis complete", "percent": 100}
        session.update_timestamp()
        await session.save()
        await broadcast_session_update(session)

        # Notify all connected clients when a session reaches ALERT status
        if final_status == SessionStatus.ALERT:
            await ws_manager.broadcast(
                "impact:alerts",
                {
                    "type": "impact_alert",
                    "data": {
                        "session_id": str(session.id),
                        "device_name": session.device_name,
                        "device_type": session.device_type,
                        "site_name": session.site_name,
                        "severity": (
                            session.ai_assessment.get("severity", "warning") if session.ai_assessment else "warning"
                        ),
                        "summary": (
                            session.ai_assessment.get("summary", "")[:200]
                            if session.ai_assessment
                            else "Impact detected after configuration change"
                        ),
                        "has_revert": any(i.is_revert for i in session.incidents),
                    },
                },
            )

        # Cleanup coordinator if no more active sessions for this site
        remaining = await MonitoringSession.find(
            MonitoringSession.site_id == session.site_id,
            {"status": {"$in": [s.value for s in ACTIVE_STATUSES]}},
        ).count()
        if remaining == 0:
            SiteDataCoordinator.cleanup(session.site_id)

    except asyncio.CancelledError:
        logger.info("monitoring_pipeline_cancelled", session_id=session_id)
    except Exception as e:
        logger.error("monitoring_pipeline_failed", session_id=session_id, error=str(e))
        try:
            session = await MonitoringSession.get(PydanticObjectId(session_id))
            if session and session.status not in {
                SessionStatus.COMPLETED,
                SessionStatus.ALERT,
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


async def _interruptible_sleep(session_id: str, total_seconds: int) -> None:
    """Sleep with periodic DB checks for cancellation.

    Checks every 10 seconds whether the session has been cancelled, failed,
    or transitioned to analyzing (revert-triggered early analysis).
    """
    elapsed = 0
    while elapsed < total_seconds:
        chunk = min(10, total_seconds - elapsed)
        await asyncio.sleep(chunk)
        elapsed += chunk
        if elapsed < total_seconds:
            session = await MonitoringSession.get(PydanticObjectId(session_id))
            if not session or session.status in {
                SessionStatus.CANCELLED,
                SessionStatus.FAILED,
            }:
                raise asyncio.CancelledError()
            if session.status == SessionStatus.ANALYZING:
                return  # Revert triggered early analysis — exit sleep, let caller handle
