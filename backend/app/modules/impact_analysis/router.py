"""
Config Change Impact Analysis REST API routes.
"""

from __future__ import annotations

import structlog
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.tasks import create_background_task
from app.dependencies import require_admin, require_impact_role
from app.models.system import SystemConfig
from app.models.user import User
from app.modules.impact_analysis.models import (
    ConfigChangeEvent,
    DeviceType,
    MonitoringSession,
    SessionStatus,
)
from app.modules.impact_analysis.schemas import (
    ConfigChangeEventResponse,
    CreateSessionRequest,
    DeviceIncidentResponse,
    ImpactSettingsResponse,
    ImpactSettingsUpdate,
    SessionChatRequest,
    SessionChatResponse,
    SessionDetailResponse,
    SessionListResponse,
    SessionLogEntryResponse,
    SessionLogListResponse,
    SessionResponse,
    SessionSummaryResponse,
    SleDataResponse,
    TimelineEntryResponse,
)
from app.modules.impact_analysis.services import session_manager

router = APIRouter(tags=["Impact Analysis"])
logger = structlog.get_logger(__name__)


# ── Shared helpers ────────────────────────────────────────────────────────


def _session_to_response(session: MonitoringSession) -> SessionResponse:
    """Build a list-level SessionResponse from a MonitoringSession document."""
    has_impact = session.impact_severity != "none"

    return SessionResponse(
        id=str(session.id),
        site_id=session.site_id,
        site_name=session.site_name,
        device_mac=session.device_mac,
        device_name=session.device_name,
        device_type=session.device_type.value,
        status=session.status.value,
        config_change_count=len(session.config_changes),
        incident_count=len(session.incidents),
        has_impact=has_impact,
        impact_severity=session.impact_severity,
        duration_minutes=session.duration_minutes,
        polls_completed=session.polls_completed,
        polls_total=session.polls_total,
        progress=session.progress,
        monitoring_started_at=session.monitoring_started_at,
        monitoring_ends_at=session.monitoring_ends_at,
        completed_at=session.completed_at,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _session_to_detail_response(session: MonitoringSession) -> SessionDetailResponse:
    """Build a full SessionDetailResponse from a MonitoringSession document."""
    base = _session_to_response(session)
    return SessionDetailResponse(
        **base.model_dump(),
        org_id=session.org_id,
        config_changes=[
            ConfigChangeEventResponse(
                event_type=c.event_type,
                device_mac=c.device_mac,
                device_name=c.device_name,
                timestamp=c.timestamp,
                webhook_event_id=c.webhook_event_id,
                payload_summary=c.payload_summary,
                config_diff=c.config_diff,
                device_model=c.device_model,
                firmware_version=c.firmware_version,
                commit_user=c.commit_user,
                commit_method=c.commit_method,
            )
            for c in session.config_changes
        ],
        incidents=[
            DeviceIncidentResponse(
                event_type=i.event_type,
                device_mac=i.device_mac,
                device_name=i.device_name,
                timestamp=i.timestamp,
                webhook_event_id=i.webhook_event_id,
                severity=i.severity,
                is_revert=i.is_revert,
                resolved=i.resolved,
                resolved_at=i.resolved_at,
            )
            for i in session.incidents
        ],
        sle_data=(
            SleDataResponse(
                baseline=session.sle_baseline,
                snapshots=session.sle_snapshots,
                delta=session.sle_delta,
                drill_down=session.sle_drill_down,
            )
            if session.sle_baseline or session.sle_snapshots or session.sle_delta
            else None
        ),
        topology_baseline=session.topology_baseline,
        topology_latest=session.topology_latest,
        validation_results=session.validation_results,
        ai_assessment=session.ai_assessment,
        ai_assessment_error=session.ai_assessment_error,
        timeline=[
            TimelineEntryResponse(
                timestamp=e.timestamp,
                type=e.type.value,
                title=e.title,
                severity=e.severity,
                data=e.data,
            )
            for e in session.timeline
        ],
    )


async def _get_session(session_id: PydanticObjectId) -> MonitoringSession:
    """Fetch a session by ID or raise 404."""
    session = await MonitoringSession.get(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


# ── Session CRUD ──────────────────────────────────────────────────────────


@router.get("/impact-analysis/sessions", response_model=SessionListResponse)
async def list_sessions(
    status_filter: str | None = Query(None, alias="status", description="Comma-separated status filter"),
    site_id: str | None = Query(None, description="Filter by site ID"),
    device_type: str | None = Query(None, description="Filter by device type: ap, switch, gateway"),
    limit: int = Query(25, ge=1, le=100),
    skip: int = Query(0, ge=0),
    _current_user: User = Depends(require_impact_role),
) -> SessionListResponse:
    """List monitoring sessions with optional filtering."""
    query: dict = {}

    if status_filter:
        statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
        if statuses:
            query["status"] = {"$in": statuses}

    if site_id:
        query["site_id"] = site_id

    if device_type:
        query["device_type"] = device_type

    pipeline: list[dict] = [{"$match": query}, {"$sort": {"created_at": -1}}]
    facet_pipeline = pipeline + [
        {
            "$facet": {
                "total": [{"$count": "n"}],
                "items": [{"$skip": skip}, {"$limit": limit}],
            }
        }
    ]

    results = await MonitoringSession.aggregate(facet_pipeline).to_list()
    row = results[0] if results else {}
    total = row.get("total", [{}])[0].get("n", 0) if row.get("total") else 0
    item_dicts = row.get("items", [])

    # Re-fetch as documents so we get proper Pydantic model instances
    item_ids = [item["_id"] for item in item_dicts]
    sessions = await MonitoringSession.find({"_id": {"$in": item_ids}}).sort("-created_at").to_list()

    return SessionListResponse(
        sessions=[_session_to_response(s) for s in sessions],
        total=total,
    )


@router.post("/impact-analysis/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: CreateSessionRequest,
    _current_user: User = Depends(require_impact_role),
) -> SessionResponse:
    """Manually trigger a monitoring session for a device."""
    # Resolve site name and org_id from Mist
    from app.services.mist_service_factory import create_mist_service

    try:
        mist = await create_mist_service()
        site_info = await mist.get_site(request.site_id)
        site_name = site_info.get("name", "")
        org_id = site_info.get("org_id", "")
    except Exception as e:
        logger.error("create_session_site_lookup_failed", site_id=request.site_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch site info from Mist",
        ) from e

    config_event = ConfigChangeEvent(
        event_type="MANUAL_TRIGGER",
        device_mac=request.device_mac,
        device_name="",
    )

    device_type = DeviceType(request.device_type)

    # Use device-type defaults when user omits duration/interval
    from app.modules.impact_analysis.models import get_monitoring_defaults

    default_duration, default_interval = get_monitoring_defaults(device_type)
    duration = request.duration_minutes if request.duration_minutes is not None else default_duration
    interval = request.interval_minutes if request.interval_minutes is not None else default_interval

    session, is_new = await session_manager.create_or_merge_session(
        site_id=request.site_id,
        site_name=site_name,
        org_id=org_id,
        device_mac=request.device_mac,
        device_name="",
        device_type=device_type,
        config_event=config_event,
        duration_minutes=duration,
        interval_minutes=interval,
    )

    if is_new:
        from app.modules.impact_analysis.workers.monitoring_worker import run_monitoring_pipeline

        create_background_task(
            run_monitoring_pipeline(str(session.id)),
            name=f"impact-monitor-{session.id}",
        )

    logger.info(
        "session_created_manual",
        session_id=str(session.id),
        is_new=is_new,
        device_mac=request.device_mac,
        user_id=str(_current_user.id),
    )

    return _session_to_response(session)


@router.post("/impact-analysis/sessions/{session_id}/cancel", response_model=SessionResponse)
async def cancel_session(
    session_id: PydanticObjectId,
    _current_user: User = Depends(require_impact_role),
) -> SessionResponse:
    """Cancel an active or alert session."""
    session = await session_manager.cancel_session(str(session_id))
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or not in a cancellable state",
        )

    logger.info("session_cancelled", session_id=str(session_id), user_id=str(_current_user.id))
    return _session_to_response(session)


@router.post("/impact-analysis/sessions/{session_id}/reanalyze", response_model=SessionDetailResponse)
async def reanalyze_session(
    session_id: PydanticObjectId,
    _current_user: User = Depends(require_impact_role),
) -> SessionDetailResponse:
    """Re-run AI analysis on a completed or alert session."""
    session = await _get_session(session_id)

    if session.status != SessionStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reanalyze a session in '{session.status.value}' state. "
            "Only completed sessions can be reanalyzed.",
        )

    from app.modules.impact_analysis.services.analysis_service import analyze_session

    logger.info("session_reanalyze_started", session_id=str(session_id), user_id=str(_current_user.id))

    try:
        assessment = await analyze_session(session)
        session.ai_assessment = assessment
        session.ai_assessment_error = None
    except Exception as e:
        logger.error("session_reanalyze_failed", session_id=str(session_id), error=str(e))
        session.ai_assessment_error = "Analysis failed. Please try again later."

    session.update_timestamp()
    await session.save()

    return _session_to_detail_response(session)


# ── Session logs ──────────────────────────────────────────────────────────


@router.get("/impact-analysis/sessions/{session_id}/logs", response_model=SessionLogListResponse)
async def get_session_logs(
    session_id: PydanticObjectId,
    limit: int = Query(100, ge=1, le=1000),
    skip: int = Query(0, ge=0),
    level: str | None = None,
    _current_user: User = Depends(require_impact_role),
) -> SessionLogListResponse:
    """Get diagnostic logs for a monitoring session."""
    from app.modules.impact_analysis.models import SessionLogEntry

    query: dict = {"session_id": str(session_id)}
    if level:
        query["level"] = level

    total = await SessionLogEntry.find(query).count()
    logs = await SessionLogEntry.find(query).sort("+timestamp").skip(skip).limit(limit).to_list()

    return SessionLogListResponse(
        logs=[
            SessionLogEntryResponse(
                id=str(log.id),
                session_id=log.session_id,
                timestamp=log.timestamp,
                level=log.level,
                phase=log.phase,
                message=log.message,
                details=log.details,
            )
            for log in logs
        ],
        total=total,
    )


# ── Dashboard summary ─────────────────────────────────────────────────────


@router.get("/impact-analysis/summary", response_model=SessionSummaryResponse)
async def get_summary(
    _current_user: User = Depends(require_impact_role),
) -> SessionSummaryResponse:
    """Get dashboard summary counts for impact analysis sessions."""
    counts = await session_manager.get_session_summary()
    return SessionSummaryResponse(**counts)


# ── SLE data ──────────────────────────────────────────────────────────────


@router.get("/impact-analysis/sessions/{session_id}/sle-data", response_model=SleDataResponse)
async def get_sle_data(
    session_id: PydanticObjectId,
    _current_user: User = Depends(require_impact_role),
) -> SleDataResponse:
    """Get SLE chart data for a session (baseline, snapshots, delta, drill-down)."""
    session = await _get_session(session_id)

    return SleDataResponse(
        baseline=session.sle_baseline,
        snapshots=session.sle_snapshots,
        delta=session.sle_delta,
        drill_down=session.sle_drill_down,
    )


# ── Session chat ──────────────────────────────────────────────────────────


def _build_session_context(session: MonitoringSession) -> str:
    """Build a context string describing the current session state for the LLM."""
    lines = [
        f"Impact Analysis Session for {session.device_type.value} '{session.device_name or session.device_mac}'",
        f"Site: {session.site_name} | Status: {session.status.value} | Impact: {session.impact_severity}",
        f"Config changes: {len(session.config_changes)} | Incidents: {len(session.incidents)}",
    ]
    if session.config_changes:
        latest = session.config_changes[-1]
        lines.append(f"Latest config event: {latest.event_type} at {latest.timestamp.isoformat()}")
        if latest.commit_user:
            lines.append(f"  Committed by: {latest.commit_user} via {latest.commit_method}")
    if session.validation_results:
        overall = session.validation_results.get("overall_status", "unknown")
        lines.append(f"Validation: {overall}")
        for check_name, check_data in session.validation_results.items():
            if isinstance(check_data, dict) and "status" in check_data:
                lines.append(f"  - {check_name}: {check_data['status']}")
                if check_data.get("details"):
                    for d in check_data["details"][:3]:
                        lines.append(f"    {d}")
    if session.sle_delta:
        degraded = session.sle_delta.get("degraded_metric_names", [])
        if degraded:
            lines.append(f"SLE degraded metrics: {', '.join(degraded)}")
    if session.ai_assessment:
        summary = session.ai_assessment.get("summary", "")
        if summary:
            lines.append(f"AI assessment summary: {summary[:500]}")
    if session.incidents:
        for inc in session.incidents[:5]:
            resolved = " (resolved)" if inc.resolved else ""
            lines.append(f"Incident: {inc.event_type} [{inc.severity}]{resolved}")
    # Include recent timeline entries for context
    recent_entries = session.timeline[-10:] if session.timeline else []
    if recent_entries:
        lines.append("\nRecent timeline:")
        for e in recent_entries:
            lines.append(f"  [{e.timestamp.strftime('%H:%M:%S')}] {e.type.value}: {e.title}")
    return "\n".join(lines)


@router.post("/impact-analysis/sessions/{session_id}/chat", response_model=SessionChatResponse)
async def session_chat(
    session_id: PydanticObjectId,
    request: SessionChatRequest,
    current_user: User = Depends(require_impact_role),
) -> SessionChatResponse:
    """Send a message to the AI about this monitoring session.

    The AI has full context about the session (config changes, validation results,
    SLE metrics, incidents, timeline) and access to MCP tools for querying app data.
    """
    from app.modules.llm.router import (
        _agent_result_metadata,
        _check_llm_rate_limit,
        _load_external_mcp_clients,
        _load_or_create_thread,
        _make_tool_notifier,
        _mcp_user_session,
        _usage_dict_from_agent,
    )

    _check_llm_rate_limit(str(current_user.id))

    from app.modules.llm.services.agent_service import AIAgentService
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import _sanitize_for_prompt

    session = await _get_session(session_id)

    # Build system prompt with session context
    system_prompt = (
        "You are an AI network engineer assistant analyzing the impact of a configuration change "
        "on a Juniper Mist network device. You have access to MCP tools to query backups, "
        "workflows, device stats, and other app data. Be concise and technical. "
        "Reference specific checks, metrics, and device details in your answers.\n\n"
        f"Session context:\n{_sanitize_for_prompt(_build_session_context(session), max_len=4000)}"
    )

    # Get or create conversation thread for this session
    thread = await _load_or_create_thread(
        session.conversation_thread_id, current_user.id, "impact_analysis_chat", []
    )

    # Persist thread ID on session if this is the first message
    if not session.conversation_thread_id:
        await MonitoringSession.find_one(
            MonitoringSession.id == session.id,
            MonitoringSession.conversation_thread_id == None,  # noqa: E711
        ).update({"$set": {"conversation_thread_id": str(thread.id)}})

    # Set/update system prompt
    if not thread.messages:
        thread.add_message("system", system_prompt)
    elif thread.messages and thread.messages[0].role == "system":
        thread.messages[0].content = system_prompt

    # Add user message and persist
    thread.add_message("user", request.message)
    await thread.save()

    # Run agent with MCP tools (local + optional external)
    llm = await create_llm_service()
    elicit_channel = f"llm:{request.stream_id}" if request.stream_id else None
    external = await _load_external_mcp_clients(request.mcp_config_ids or [])
    async with _mcp_user_session(
        current_user.id, elicitation_channel=elicit_channel, extra_clients=external
    ) as mcp_clients:
        # Include conversation history
        history = thread.get_messages_for_llm(max_turns=10)
        context_summary = ""
        if len(history) > 2:
            prior_turns = [f"{m['role']}: {m['content'][:200]}" for m in history[1:-1]]
            context_summary = "\n\nPrior conversation:\n" + "\n".join(prior_turns[-6:])

        agent = AIAgentService(llm=llm, mcp_clients=mcp_clients, max_iterations=10)
        result = await agent.run(
            task=request.message,
            system_prompt=system_prompt + context_summary,
            on_tool_call=_make_tool_notifier(request.stream_id),
        )

    reply = result.result

    # Store assistant reply
    thread.add_message("assistant", reply, metadata=_agent_result_metadata(result))
    await thread.save()

    # Append chat messages to session timeline so other WS clients see them
    from app.modules.impact_analysis.models import TimelineEntry, TimelineEntryType

    user_entry = TimelineEntry(
        type=TimelineEntryType.CHAT_MESSAGE,
        title=request.message[:200],
        data={"role": "user", "content": request.message},
    )
    ai_entry = TimelineEntry(
        type=TimelineEntryType.CHAT_MESSAGE,
        title=reply[:200],
        data={"role": "assistant", "content": reply},
    )
    await session_manager.append_timeline_entry(session, user_entry)
    await session_manager.append_timeline_entry(session, ai_entry)

    logger.info(
        "session_chat_message",
        session_id=str(session_id),
        user_id=str(current_user.id),
        thread_id=str(thread.id),
    )

    return SessionChatResponse(
        reply=reply,
        thread_id=str(thread.id),
        usage=_usage_dict_from_agent(result),
    )


# ── Session detail (must be AFTER sub-path routes to avoid catching /logs, /sle-data etc.)


@router.get("/impact-analysis/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: PydanticObjectId,
    _current_user: User = Depends(require_impact_role),
) -> SessionDetailResponse:
    """Get full session detail including SLE data, incidents, and AI assessment."""
    session = await _get_session(session_id)
    return _session_to_detail_response(session)


# ── Admin settings ────────────────────────────────────────────────────────


@router.get("/impact-analysis/settings", response_model=ImpactSettingsResponse)
async def get_settings(
    _current_user: User = Depends(require_admin),
) -> ImpactSettingsResponse:
    """Get current impact analysis settings (admin only)."""
    config = await SystemConfig.get_config()
    return ImpactSettingsResponse(
        impact_analysis_enabled=config.impact_analysis_enabled,
        impact_analysis_default_duration_minutes=config.impact_analysis_default_duration_minutes,
        impact_analysis_default_interval_minutes=config.impact_analysis_default_interval_minutes,
        impact_analysis_sle_threshold_percent=config.impact_analysis_sle_threshold_percent,
        impact_analysis_retention_days=config.impact_analysis_retention_days,
    )


@router.put("/impact-analysis/settings", response_model=ImpactSettingsResponse)
async def update_settings(
    update: ImpactSettingsUpdate,
    _current_user: User = Depends(require_admin),
) -> ImpactSettingsResponse:
    """Update impact analysis settings (admin only)."""
    config = await SystemConfig.get_config()

    updated_fields: list[str] = []
    for field_name in (
        "impact_analysis_enabled",
        "impact_analysis_default_duration_minutes",
        "impact_analysis_default_interval_minutes",
        "impact_analysis_sle_threshold_percent",
        "impact_analysis_retention_days",
    ):
        value = getattr(update, field_name)
        if value is not None:
            setattr(config, field_name, value)
            updated_fields.append(field_name)

    if updated_fields:
        config.update_timestamp()
        await config.save()
        logger.info(
            "impact_settings_updated",
            updated_fields=updated_fields,
            user_id=str(_current_user.id),
        )

    return ImpactSettingsResponse(
        impact_analysis_enabled=config.impact_analysis_enabled,
        impact_analysis_default_duration_minutes=config.impact_analysis_default_duration_minutes,
        impact_analysis_default_interval_minutes=config.impact_analysis_default_interval_minutes,
        impact_analysis_sle_threshold_percent=config.impact_analysis_sle_threshold_percent,
        impact_analysis_retention_days=config.impact_analysis_retention_days,
    )
