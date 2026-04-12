"""
Core Digital Twin service: create sessions, run simulations, approve/execute.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

import structlog
from beanie import PydanticObjectId

from app.modules.digital_twin.models import (
    CheckResult,
    RemediationAttempt,
    StagedWrite,
    TwinSession,
    TwinSessionStatus,
)
from app.modules.digital_twin.services.endpoint_parser import parse_endpoint
from app.modules.digital_twin.services.snapshot_analyzer import (
    analyze_site_with_context,
    build_prediction_report,
)
from app.modules.digital_twin.services.site_snapshot import (
    build_site_snapshot,
    fetch_live_data,
    load_site_snapshot_source_data,
)
from app.modules.digital_twin.services.label_resolver import (
    fetch_object_names_by_type,
    fetch_site_names,
    format_object_label,
)
from app.modules.digital_twin.services.state_resolver import (
    apply_staged_writes,
    canonicalize_object_type,
    collect_affected_metadata,
    load_base_state_from_backup,
)
from app.modules.digital_twin.services.twin_logging import (
    bind_twin_session,
    drain_buffer,
)

logger = structlog.get_logger(__name__)

_SITE_ANALYSIS_CONCURRENCY = 8
_REDACTED = "***"
_SENSITIVE_KEYS = {
    "password",
    "secret",
    "token",
    "api_token",
    "access_token",
    "ssh_key",
    "private_key",
    "psk",
}


def _sanitize_for_log(value: Any, *, depth: int = 0) -> Any:
    """Redact sensitive keys and trim deeply nested payloads for log readability."""
    if depth > 4:
        return "<truncated>"

    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            if key_lower in _SENSITIVE_KEYS or key_lower.endswith("_password") or key_lower.endswith("_secret"):
                sanitized[key] = _REDACTED
            else:
                sanitized[key] = _sanitize_for_log(item, depth=depth + 1)
        return sanitized

    if isinstance(value, list):
        if len(value) > 50:
            return [_sanitize_for_log(v, depth=depth + 1) for v in value[:50]] + ["<truncated>"]
        return [_sanitize_for_log(v, depth=depth + 1) for v in value]

    return value


def _write_log_context(write: StagedWrite) -> dict[str, Any]:
    """Return a stable log context payload for one staged write."""
    body = write.body or {}
    return {
        "sequence": write.sequence,
        "method": write.method,
        "endpoint": write.endpoint,
        "object_type": write.object_type,
        "site_id": write.site_id,
        "object_id": write.object_id,
        "body_keys": sorted(body.keys()),
        "body": _sanitize_for_log(body),
    }


def _has_blocking_preflight_errors(check_results: list[CheckResult]) -> bool:
    """Return True when Layer-0 SYS checks report blocking errors."""
    return any(
        r.layer == 0 and r.check_id.startswith("SYS-") and r.status in ("error", "critical") for r in check_results
    )


def _parse_and_enrich_writes(
    writes: list[dict[str, Any]],
) -> tuple[list[StagedWrite], list[CheckResult]]:
    """Parse raw write dicts into StagedWrite objects with endpoint metadata.

    Returns (staged_writes, parse_errors). Parse errors are CheckResult objects
    in the SYS-01 family, using check_id="SYS-01-{i}" where ``i`` is the
    write sequence, and should be included in the PredictionReport.
    """
    staged: list[StagedWrite] = []
    parse_errors: list[CheckResult] = []
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
        if parsed.error:
            logger.warning(
                "twin_write_parse_error",
                sequence=i,
                endpoint=w.get("endpoint", ""),
                error=parsed.error,
            )
            parse_errors.append(
                CheckResult(
                    check_id=f"SYS-01-{i}",
                    check_name="Endpoint Validation",
                    layer=0,
                    status="error",
                    summary=f"Write #{i}: invalid endpoint '{w.get('endpoint', '')}'",
                    details=[parsed.error],
                    remediation_hint="Use valid Mist API endpoints like /api/v1/sites/{site_id}/wlans or /api/v1/orgs/{org_id}/networks. Resource names must match the Mist API (e.g., 'wlans' not 'wlan').",
                    description="Validates that the staged write targets a well-formed, recognized Mist API endpoint.",
                )
            )
    return staged, parse_errors


async def _validate_write_targets(org_id: str, staged_writes: list[StagedWrite]) -> list[CheckResult]:
    """Validate write targets exist in backup state for trustworthy simulation.

    This guards against LLM placeholder endpoints (caught by parser) and
    unresolved IDs that do not exist in backup snapshots.
    """
    from app.modules.backup.models import BackupObject

    errors: list[CheckResult] = []
    singleton_types = {"settings", "info", "data"}

    if not (org_id or "").strip():
        return [
            CheckResult(
                check_id="SYS-00",
                check_name="Simulation Context Validation",
                layer=0,
                status="error",
                summary="Simulation org context is missing (org_id is empty)",
                details=[
                    "Digital Twin preflight cannot validate targets without an organization scope.",
                    "Current request resolved org_id to an empty value.",
                ],
                remediation_hint="Configure Mist Organization ID in settings, then re-run simulation.",
                description="Verifies that an organization context (org_id) is present before simulation can proceed.",
            )
        ]

    site_cache: dict[str, bool] = {}
    object_cache: dict[tuple[str, str | None, str], bool] = {}

    async def _site_exists(site_id: str) -> bool:
        if site_id in site_cache:
            return site_cache[site_id]

        # Site records can exist in different shapes depending on backup history:
        # - site-level singleton: object_type="info", site_id=<site_id>
        # - legacy site-level singleton: object_type="site", object_id=<site_id>
        # - org-level sites list: object_type="sites", object_id=<site_id>
        # - any site-scoped object carrying site_id=<site_id>
        doc = await BackupObject.find(
            {
                "org_id": org_id,
                "is_deleted": False,
                "$or": [
                    {"object_type": "info", "site_id": site_id},
                    {"object_type": "site", "object_id": site_id},
                    {"object_type": "sites", "object_id": site_id},
                    {"site_id": site_id},
                ],
            }
        ).first_or_none()
        site_cache[site_id] = doc is not None
        return site_cache[site_id]

    async def _object_exists(object_type: str, site_id: str | None, object_id: str) -> bool:
        cache_key = (object_type, site_id, object_id)
        if cache_key in object_cache:
            return object_cache[cache_key]

        query: dict[str, Any] = {
            "object_type": object_type,
            "org_id": org_id,
            "object_id": object_id,
            "is_deleted": False,
        }
        if site_id:
            query["site_id"] = site_id

        doc = await BackupObject.find(query).first_or_none()

        # Fallback: tolerate legacy/mismatched object_type labels in older backups
        # as long as the target object_id exists within the same org/site scope.
        if doc is None:
            fallback_query: dict[str, Any] = {
                "org_id": org_id,
                "object_id": object_id,
                "is_deleted": False,
            }
            if site_id:
                fallback_query["site_id"] = site_id
            doc = await BackupObject.find(fallback_query).first_or_none()

        object_cache[cache_key] = doc is not None
        return object_cache[cache_key]

    for write in staged_writes:
        canonical_type = canonicalize_object_type(write.object_type) if write.object_type else None

        if write.site_id and not await _site_exists(write.site_id):
            errors.append(
                CheckResult(
                    check_id=f"SYS-02-{write.sequence}",
                    check_name="Write Target Validation",
                    layer=0,
                    status="error",
                    summary=(f"Write #{write.sequence}: site_id '{write.site_id}' was not found in backup data"),
                    details=[
                        f"Endpoint: {write.endpoint}",
                        "Simulation requires site context in backup snapshots for the selected org.",
                    ],
                    remediation_hint=(
                        "Verify org/site selection and run a backup for this site if snapshots are missing."
                    ),
                    description="Confirms the target site exists in backup data so baseline state can be built.",
                )
            )
            continue

        if (
            write.method in ("PUT", "DELETE")
            and canonical_type
            and canonical_type not in singleton_types
            and write.object_id
        ):
            if not await _object_exists(canonical_type, write.site_id, write.object_id):
                errors.append(
                    CheckResult(
                        check_id=f"SYS-03-{write.sequence}",
                        check_name="Write Target Validation",
                        layer=0,
                        status="error",
                        summary=(
                            f"Write #{write.sequence}: target object '{write.object_id}' "
                            f"for type '{canonical_type}' was not found in backup data"
                        ),
                        details=[
                            f"Endpoint: {write.endpoint}",
                            "PUT/DELETE simulations require existing object IDs to build baseline state.",
                        ],
                        remediation_hint=("Use a real object UUID for the target resource (or POST for new objects)."),
                        description="Confirms the target object ID exists in backup data for PUT/DELETE operations.",
                    )
                )

    return errors


async def simulate(
    user_id: str,
    org_id: str,
    writes: list[dict[str, Any]],
    source: str = "mcp",
    source_ref: str | None = None,
    existing_session_id: str | None = None,
) -> TwinSession:
    """Run a simulation: stage writes, resolve state, run checks, return results.

    If existing_session_id is provided, updates that session (remediation iteration).
    Otherwise creates a new TwinSession.
    """
    staged_writes, parse_errors = _parse_and_enrich_writes(writes)
    target_errors = await _validate_write_targets(org_id, staged_writes)
    preflight_errors = bool(parse_errors or target_errors)
    affected_sites, affected_types = collect_affected_metadata(staged_writes)

    # Resolve human-readable object label (uses backup data, resolved once at
    # session creation and never refreshed — names captured at simulate-time).
    object_names = await fetch_object_names_by_type(
        org_id=org_id, writes=staged_writes
    )
    affected_object_label = format_object_label(
        object_types=affected_types,
        object_names_by_type=object_names,
    )

    old_severity = "clean"
    if existing_session_id:
        session = await TwinSession.get(PydanticObjectId(existing_session_id))
        if not session:
            raise ValueError(f"Twin session {existing_session_id} not found")
        if str(session.user_id) != user_id:
            raise ValueError("Twin session not found")
        if session.org_id != org_id:
            raise ValueError("Twin session org mismatch")
        old_severity = session.overall_severity
        session.staged_writes = staged_writes
        session.affected_sites = affected_sites
        session.affected_object_types = affected_types
        session.affected_object_label = affected_object_label
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
            affected_object_label=affected_object_label,
        )

    session.status = TwinSessionStatus.VALIDATING
    session.base_snapshot_refs = []
    session.live_fetched_at = None
    session.update_timestamp()
    await session.save()

    simulation_phase = "remediate" if session.remediation_count > 0 else "simulate"
    with bind_twin_session(str(session.id), phase=simulation_phase):
        logger.info(
            "twin_simulation_started",
            session_id=str(session.id),
            source=source,
            source_ref=source_ref,
            remediation_count=session.remediation_count,
            writes_count=len(staged_writes),
            affected_sites=affected_sites,
            affected_object_types=affected_types,
            affected_object_label=affected_object_label,
        )

        for write in sorted(staged_writes, key=lambda w: w.sequence):
            logger.info("twin_write_staged", **_write_log_context(write))

        # Include parser/target validation errors in the report.
        check_results: list[CheckResult] = [*parse_errors, *target_errors]

        logger.info(
            "twin_preflight_completed",
            has_errors=preflight_errors,
            parse_error_count=len(parse_errors),
            target_error_count=len(target_errors),
        )

        for issue in check_results:
            if issue.layer == 0 and issue.check_id.startswith("SYS-"):
                logger.warning(
                    "twin_preflight_issue",
                    check_id=issue.check_id,
                    status=issue.status,
                    summary=issue.summary,
                    details=issue.details,
                    remediation_hint=issue.remediation_hint,
                )

        if not preflight_errors:
            logger.info("twin_state_resolution_started")
            # Resolve virtual state
            base_state, refs = await load_base_state_from_backup(org_id, staged_writes)
            logger.info(
                "twin_base_state_loaded",
                base_state_objects=len(base_state),
                base_snapshot_refs=len(refs),
            )
            # Persist the resolved base state so the detail view can compute diffs
            # for each staged write against the original backup snapshot.
            # Tuple keys are stringified because Mongo can't store tuple keys directly.
            session.resolved_state = {str(k): v for k, v in base_state.items()}
            virtual_state = apply_staged_writes(base_state, staged_writes)
            logger.info("twin_virtual_state_applied", virtual_state_objects=len(virtual_state))

            # Compile effective device configs (template inheritance + variable resolution)
            from app.modules.digital_twin.services.config_compiler import compile_base_state, compile_virtual_state

            virtual_state, all_impacted_sites = await compile_virtual_state(virtual_state, staged_writes, org_id)
            # Expand affected_sites with template-impacted sites
            affected_sites = sorted(set(all_impacted_sites) | set(affected_sites))
            session.affected_sites = affected_sites
            logger.info(
                "twin_virtual_state_compiled",
                virtual_state_objects=len(virtual_state),
                impacted_sites=all_impacted_sites,
                effective_affected_sites=affected_sites,
            )

            # Resolve site labels once the full fan-out is known (template edits may
            # expand the scoped sites — we want labels for ALL tested sites).
            session.affected_site_labels = await fetch_site_names(
                org_id=org_id, site_ids=affected_sites
            )
            logger.info(
                "twin_site_labels_resolved",
                site_ids=affected_sites,
                site_labels=session.affected_site_labels,
            )

            # Compile the baseline the same way as predicted so port-based checks
            # compare apples-to-apples. Without this, baseline reads raw backup
            # device configs while predicted is template-merged, producing
            # asymmetric port_config data that silently defeats PORT-DISC and the
            # per-VLAN reachability diff.
            baseline_state = await compile_base_state(affected_sites, org_id)
            logger.info("twin_baseline_state_compiled", baseline_state_objects=len(baseline_state))

            session.base_snapshot_refs = refs
            session.live_fetched_at = datetime.now(timezone.utc)

            # ── Snapshot-based analysis ──
            # For each affected site: build baseline + predicted snapshots, run all checks
            semaphore = asyncio.Semaphore(min(_SITE_ANALYSIS_CONCURRENCY, len(affected_sites)))

            async def _analyze_one_site(sid: str) -> list:
                async with semaphore:
                    logger.info("twin_site_analysis_started", site_id=sid)
                    live_data = await fetch_live_data(sid, org_id)
                    snapshot_source_data = await load_site_snapshot_source_data(sid, org_id)
                    baseline_snap = await build_site_snapshot(
                        sid,
                        org_id,
                        live_data,
                        state_overrides=baseline_state,
                        source_data=snapshot_source_data,
                    )
                    predicted_snap = await build_site_snapshot(
                        sid,
                        org_id,
                        live_data,
                        state_overrides=virtual_state,
                        source_data=snapshot_source_data,
                    )
                    logger.info(
                        "twin_site_snapshot_built",
                        site_id=sid,
                        baseline_devices=len(baseline_snap.devices),
                        baseline_networks=len(baseline_snap.networks),
                        baseline_wlans=len(baseline_snap.wlans),
                        predicted_devices=len(predicted_snap.devices),
                        predicted_networks=len(predicted_snap.networks),
                        predicted_wlans=len(predicted_snap.wlans),
                    )
                    site_check_results = analyze_site_with_context(
                        baseline_snap,
                        predicted_snap,
                        affected_types,
                    )
                    logger.info(
                        "twin_site_analysis_completed",
                        site_id=sid,
                        check_results=len(site_check_results),
                    )
                    return site_check_results

            if affected_sites:
                site_results = await asyncio.gather(*[_analyze_one_site(sid) for sid in affected_sites])
                for site_result in site_results:
                    check_results.extend(site_result)

        # Build report
        report = build_prediction_report(check_results)
        logger.info(
            "twin_prediction_report_built",
            total_checks=report.total_checks,
            passed=report.passed,
            warnings=report.warnings,
            errors=report.errors,
            critical=report.critical,
            skipped=report.skipped,
            overall_severity=report.overall_severity,
            execution_safe=report.execution_safe,
            summary=report.summary,
        )

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
        if _has_blocking_preflight_errors(check_results):
            session.status = TwinSessionStatus.FAILED
            session.ai_assessment = "Preflight validation failed. Fix endpoint/target issues and re-run simulation."
        else:
            session.status = TwinSessionStatus.AWAITING_APPROVAL
            session.ai_assessment = None

        logger.info(
            "twin_simulation_complete",
            session_id=str(session.id),
            severity=report.overall_severity,
            checks=report.total_checks,
            issues=report.errors + report.critical + report.warnings,
        )

    # Drain captured logs before persistence so they're saved with the session.
    captured = drain_buffer(str(session.id))
    if captured:
        session.simulation_logs.extend(captured)
        if len(session.simulation_logs) > 1000:
            session.simulation_logs = session.simulation_logs[-1000:]

    session.update_timestamp()
    await session.save()

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
    if not session.prediction_report:
        raise ValueError("Session has no validation report")
    if not session.prediction_report.execution_safe:
        raise ValueError("Session has blocking validation issues and cannot be approved")
    if _has_blocking_preflight_errors(session.prediction_report.check_results):
        raise ValueError("Session has preflight validation errors and cannot be approved")

    session.status = TwinSessionStatus.APPROVED
    session.update_timestamp()
    await session.save()

    session.status = TwinSessionStatus.EXECUTING
    session.update_timestamp()
    await session.save()

    with bind_twin_session(str(session.id), phase="execute"):
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

            # Create IA monitoring sessions for post-deployment validation
            try:
                from app.modules.digital_twin.services.twin_ia_bridge import create_ia_sessions_for_deployment

                ia_ids = await create_ia_sessions_for_deployment(session)
                session.ia_session_ids = ia_ids
                logger.info(
                    "twin_ia_bridge_complete",
                    session_id=str(session.id),
                    ia_sessions=len(ia_ids),
                )
            except Exception as e:
                logger.warning("twin_ia_bridge_failed", session_id=str(session.id), error=str(e))

        logger.info(
            "twin_execution_complete",
            session_id=str(session.id),
            status=session.status.value,
            writes=len(session.staged_writes),
            errors=len(errors),
        )

    # Drain captured logs before persistence so they're saved with the session.
    captured = drain_buffer(str(session.id))
    if captured:
        session.simulation_logs.extend(captured)
        if len(session.simulation_logs) > 1000:
            session.simulation_logs = session.simulation_logs[-1000:]

    session.update_timestamp()
    await session.save()

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
    source: str | None = None,
    search: str | None = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[TwinSession], int]:
    """List twin sessions for a user, optionally filtered by status, source, or search term."""
    query: dict[str, Any] = {"user_id": PydanticObjectId(user_id)}
    if status:
        query["status"] = status
    if source:
        query["source"] = source
    if search:
        search_value = search.strip()
        if search_value:
            query["source_ref"] = {"$regex": f"^{re.escape(search_value)}", "$options": "i"}
    total = await TwinSession.find(query).count()
    sessions = await TwinSession.find(query).sort([("created_at", -1)]).skip(skip).limit(limit).to_list()
    return sessions, total


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
