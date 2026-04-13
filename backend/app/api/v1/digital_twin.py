"""REST API for Digital Twin session management."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import require_admin
from app.models.user import User
from app.modules.digital_twin.models import SimulationLogEntry
from app.modules.digital_twin.schemas import (
    TwinSessionDetailResponse,
    TwinSessionListResponse,
    session_to_detail_response,
    session_to_response,
)
from app.modules.digital_twin.services import twin_service

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Digital Twin"])


def _filter_logs(
    entries: list[SimulationLogEntry],
    *,
    level: str | None,
    phase: str | None,
    search: str | None,
) -> list[SimulationLogEntry]:
    """Apply level/phase/search filters to a list of SimulationLogEntry."""
    results = entries
    if level:
        results = [e for e in results if e.level == level]
    if phase:
        results = [e for e in results if e.phase == phase]
    if search:
        needle = search.lower()
        results = [
            e
            for e in results
            if needle in e.event.lower()
            or any(needle in str(v).lower() for v in e.context.values())
        ]
    return results


def _approve_error_response(error: "twin_service.TwinApprovalError") -> tuple[int, str]:
    """Return deterministic API responses for Twin approval failures."""
    mapping: dict[twin_service.TwinApprovalErrorCode, tuple[int, str]] = {
        twin_service.TwinApprovalErrorCode.NOT_FOUND: (
            status.HTTP_404_NOT_FOUND,
            "Session not found",
        ),
        twin_service.TwinApprovalErrorCode.NOT_AWAITING_APPROVAL: (
            status.HTTP_400_BAD_REQUEST,
            "Session is not awaiting approval",
        ),
        twin_service.TwinApprovalErrorCode.NO_VALIDATION_REPORT: (
            status.HTTP_400_BAD_REQUEST,
            "Session has no validation report",
        ),
        twin_service.TwinApprovalErrorCode.BLOCKING_VALIDATION_ISSUES: (
            status.HTTP_400_BAD_REQUEST,
            "Session has blocking validation issues",
        ),
        twin_service.TwinApprovalErrorCode.PREFLIGHT_VALIDATION_ERRORS: (
            status.HTTP_400_BAD_REQUEST,
            "Session has preflight validation errors",
        ),
    }
    return mapping.get(error.code, (status.HTTP_400_BAD_REQUEST, "Session cannot be approved"))


@router.get("/digital-twin/sessions", response_model=TwinSessionListResponse)
async def list_twin_sessions(
    current_user: User = Depends(require_admin),
    status_filter: str | None = Query(None, alias="status"),
    source: str | None = Query(None),
    search: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """List Digital Twin sessions for the current user."""
    sessions, total = await twin_service.list_sessions(
        user_id=str(current_user.id),
        status=status_filter,
        source=source,
        search=search,
        skip=skip,
        limit=limit,
    )
    return TwinSessionListResponse(
        sessions=[session_to_response(s) for s in sessions],
        total=total,
    )


@router.get("/digital-twin/sessions/{session_id}", response_model=TwinSessionDetailResponse)
async def get_twin_session(
    session_id: str,
    current_user: User = Depends(require_admin),
):
    """Get a Digital Twin session by ID."""
    try:
        session = await twin_service.get_session(session_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found") from None
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if str(session.user_id) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session_to_detail_response(session)


@router.post("/digital-twin/sessions/{session_id}/cancel")
async def cancel_twin_session(
    session_id: str,
    current_user: User = Depends(require_admin),
):
    """Cancel/reject a Digital Twin session."""
    try:
        session = await twin_service.reject_session(session_id, user_id=str(current_user.id))
        return {"status": session.status.value, "session_id": str(session.id)}
    except twin_service.TwinApprovalError as e:
        if e.code == twin_service.TwinApprovalErrorCode.NOT_FOUND:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found") from None
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session is not awaiting approval") from None
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found") from None


@router.post("/digital-twin/sessions/{session_id}/approve", response_model=TwinSessionDetailResponse)
async def approve_twin_session(
    session_id: str,
    current_user: User = Depends(require_admin),
):
    """Approve a Digital Twin session and execute all staged writes."""
    try:
        session = await twin_service.approve_and_execute(
            session_id, user_id=str(current_user.id)
        )
        return session_to_detail_response(session)
    except twin_service.TwinApprovalError as e:
        status_code, detail = _approve_error_response(e)
        raise HTTPException(status_code=status_code, detail=detail) from None
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found") from None


@router.get(
    "/digital-twin/sessions/{session_id}/logs",
    response_model=list[SimulationLogEntry],
)
async def get_session_logs(
    session_id: str,
    level: str | None = Query(None, pattern="^(debug|info|warning|error)$"),
    phase: str | None = Query(
        None, pattern="^(simulate|remediate|approve|execute|other)$"
    ),
    search: str | None = Query(None, max_length=200),
    _current_user: User = Depends(require_admin),
) -> list[SimulationLogEntry]:
    """Return persisted simulation logs for an owned Twin session (admin role required)."""
    try:
        session = await twin_service.get_session(session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        ) from None
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    if str(session.user_id) != str(_current_user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    return _filter_logs(
        session.simulation_logs, level=level, phase=phase, search=search
    )
