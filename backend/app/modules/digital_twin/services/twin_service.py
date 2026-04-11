"""
Core Digital Twin service: create sessions, run simulations, approve/execute.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from beanie import PydanticObjectId

from app.modules.digital_twin.models import (
    RemediationAttempt,
    StagedWrite,
    TwinSession,
    TwinSessionStatus,
)
from app.modules.digital_twin.services.endpoint_parser import parse_endpoint
from app.modules.digital_twin.services.prediction_service import (
    build_prediction_report,
    run_layer1_checks,
)
from app.modules.digital_twin.services.state_resolver import (
    apply_staged_writes,
    collect_affected_metadata,
    load_base_state_from_backup,
)

logger = structlog.get_logger(__name__)


def _parse_and_enrich_writes(writes: list[dict[str, Any]]) -> list[StagedWrite]:
    """Parse raw write dicts into StagedWrite objects with endpoint metadata."""
    staged: list[StagedWrite] = []
    for i, w in enumerate(writes):
        parsed = parse_endpoint(w.get("method", "PUT"), w.get("endpoint", ""))
        staged.append(
            StagedWrite(
                sequence=i,
                method=w.get("method", "PUT"),
                endpoint=w.get("endpoint", ""),
                body=w.get("body"),
                object_type=parsed.object_type,
                site_id=parsed.site_id,
                object_id=parsed.object_id,
            )
        )
    return staged


async def simulate(
    user_id: str,
    org_id: str,
    writes: list[dict[str, Any]],
    source: str = "llm_chat",
    source_ref: str | None = None,
    existing_session_id: str | None = None,
) -> TwinSession:
    """Run a simulation: stage writes, resolve state, run checks, return results.

    If existing_session_id is provided, updates that session (remediation iteration).
    Otherwise creates a new TwinSession.
    """
    staged_writes = _parse_and_enrich_writes(writes)
    affected_sites, affected_types = collect_affected_metadata(staged_writes)

    old_severity = "clean"
    if existing_session_id:
        session = await TwinSession.get(PydanticObjectId(existing_session_id))
        if not session:
            raise ValueError(f"Twin session {existing_session_id} not found")
        old_severity = session.overall_severity
        session.staged_writes = staged_writes
        session.affected_sites = affected_sites
        session.affected_object_types = affected_types
        session.remediation_count += 1
    else:
        session = TwinSession(
            user_id=PydanticObjectId(user_id),
            org_id=org_id,
            source=source,
            source_ref=source_ref,
            staged_writes=staged_writes,
            affected_sites=affected_sites,
            affected_object_types=affected_types,
        )

    session.status = TwinSessionStatus.VALIDATING
    session.update_timestamp()
    await session.save()

    # Resolve virtual state
    base_state, refs = await load_base_state_from_backup(org_id, staged_writes)
    virtual_state = apply_staged_writes(base_state, staged_writes)

    # Compile effective device configs (template inheritance + variable resolution)
    from app.modules.digital_twin.services.config_compiler import compile_virtual_state

    virtual_state, all_impacted_sites = await compile_virtual_state(virtual_state, staged_writes, org_id)
    # Expand affected_sites with template-impacted sites
    affected_sites = sorted(all_impacted_sites | set(affected_sites))
    session.affected_sites = affected_sites

    session.base_snapshot_refs = refs
    session.live_fetched_at = datetime.now(timezone.utc)

    # Run Layer 1 checks
    check_results = await run_layer1_checks(virtual_state, staged_writes, org_id)

    # Run Layer 2 checks if any sites are affected
    if affected_sites:
        from app.modules.digital_twin.services.prediction_service import run_layer2_checks

        l2_results = await run_layer2_checks(virtual_state, staged_writes, org_id, set(affected_sites))
        check_results.extend(l2_results)

        from app.modules.digital_twin.services.prediction_service import (
            run_layer3_checks,
            run_layer4_checks,
            run_layer5_checks,
        )

        l3_results = await run_layer3_checks(virtual_state, staged_writes, org_id, set(affected_sites))
        check_results.extend(l3_results)

        l4_results = await run_layer4_checks(virtual_state, staged_writes, org_id)
        check_results.extend(l4_results)

        l5_results = await run_layer5_checks(virtual_state, staged_writes, org_id, set(affected_sites))
        check_results.extend(l5_results)

    # Build report
    report = build_prediction_report(check_results)

    # Track remediation history
    if existing_session_id and session.remediation_count > 0:
        old_failing_ids = set()
        if session.prediction_report:
            old_failing_ids = {
                r.check_id for r in session.prediction_report.check_results if r.status in ("error", "critical")
            }
        new_failing = {r.check_id for r in check_results if r.status in ("error", "critical")}

        session.remediation_history.append(
            RemediationAttempt(
                attempt=session.remediation_count,
                previous_severity=old_severity if existing_session_id else "clean",
                new_severity=report.overall_severity,
                fixed_checks=sorted(old_failing_ids - new_failing),
                introduced_checks=sorted(new_failing - old_failing_ids),
            )
        )

    session.prediction_report = report
    session.overall_severity = report.overall_severity
    session.status = TwinSessionStatus.AWAITING_APPROVAL
    session.update_timestamp()
    await session.save()

    logger.info(
        "twin_simulation_complete",
        session_id=str(session.id),
        severity=report.overall_severity,
        checks=report.total_checks,
        issues=report.errors + report.critical + report.warnings,
    )

    return session


async def approve_and_execute(session_id: str, user_id: str | None = None) -> TwinSession:
    """Approve a twin session and execute all staged writes against Mist API."""
    from app.services.mist_service_factory import create_mist_service

    session = await TwinSession.get(PydanticObjectId(session_id))
    if not session:
        raise ValueError(f"Twin session {session_id} not found")
    if user_id and str(session.user_id) != user_id:
        raise ValueError("Session not found")
    if session.status != TwinSessionStatus.AWAITING_APPROVAL:
        raise ValueError(f"Session is in '{session.status.value}' state, not awaiting_approval")

    session.status = TwinSessionStatus.APPROVED
    session.update_timestamp()
    await session.save()

    session.status = TwinSessionStatus.EXECUTING
    session.update_timestamp()
    await session.save()

    mist = await create_mist_service()
    errors: list[str] = []

    for write in sorted(session.staged_writes, key=lambda w: w.sequence):
        try:
            if write.method == "POST":
                result = await mist.api_post(write.endpoint, write.body or {})
            elif write.method == "PUT":
                result = await mist.api_put(write.endpoint, write.body or {})
            elif write.method == "DELETE":
                await mist.api_delete(write.endpoint)
                result = None
            else:
                continue
            write.synthetic_response = result if isinstance(result, dict) else {}
        except Exception as e:
            errors.append(f"Write #{write.sequence} failed")
            logger.error("twin_write_failed", write=write.sequence, endpoint=write.endpoint, error=str(e))

    if errors:
        session.status = TwinSessionStatus.FAILED
        session.ai_assessment = f"Execution failed: {'; '.join(errors)}"
    else:
        session.status = TwinSessionStatus.DEPLOYED

    session.update_timestamp()
    await session.save()

    logger.info(
        "twin_execution_complete",
        session_id=str(session.id),
        status=session.status.value,
        writes=len(session.staged_writes),
        errors=len(errors),
    )

    return session


async def reject_session(session_id: str, user_id: str | None = None) -> TwinSession:
    """Reject a twin session."""
    session = await TwinSession.get(PydanticObjectId(session_id))
    if not session:
        raise ValueError(f"Twin session {session_id} not found")
    if user_id and str(session.user_id) != user_id:
        raise ValueError("Session not found")
    session.status = TwinSessionStatus.REJECTED
    session.update_timestamp()
    await session.save()
    return session


async def get_session(session_id: str) -> TwinSession | None:
    """Get a twin session by ID."""
    return await TwinSession.get(PydanticObjectId(session_id))


async def list_sessions(
    user_id: str,
    status: str | None = None,
    limit: int = 20,
) -> list[TwinSession]:
    """List twin sessions for a user, optionally filtered by status."""
    query: dict[str, Any] = {"user_id": PydanticObjectId(user_id)}
    if status:
        query["status"] = status
    return await TwinSession.find(query).sort([("created_at", -1)]).limit(limit).to_list()


async def intercept_write(
    session_id: str,
    method: str,
    endpoint: str,
    body: dict[str, Any] | None,
) -> dict[str, Any]:
    """Intercept a Mist API write and stage it in the Twin session.

    Called from MistService._api_call() when twin_session_var is set.
    Returns a synthetic response so the caller can continue.
    """
    session = await TwinSession.get(PydanticObjectId(session_id))
    if not session:
        raise ValueError(f"Twin session {session_id} not found")

    parsed = parse_endpoint(method.upper(), endpoint)
    write = StagedWrite(
        sequence=len(session.staged_writes),
        method=method.upper(),
        endpoint=endpoint,
        body=body,
        object_type=parsed.object_type,
        site_id=parsed.site_id,
        object_id=parsed.object_id,
    )
    session.staged_writes.append(write)
    session.update_timestamp()
    await session.save()

    logger.info("twin_write_intercepted", session_id=session_id, method=method, endpoint=endpoint)

    # Return synthetic response so caller can continue
    return body or {}
