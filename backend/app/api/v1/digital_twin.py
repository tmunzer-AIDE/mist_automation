"""REST API for Digital Twin session management."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import require_admin
from app.models.user import User
from app.modules.digital_twin.schemas import (
    TwinSessionDetailResponse,
    TwinSessionListResponse,
    session_to_detail_response,
    session_to_response,
)
from app.modules.digital_twin.services import twin_service

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Digital Twin"])


def _approve_error_response(error_msg: str) -> tuple[int, str]:
    """Map service ValueError messages to safe, actionable API responses."""
    msg = (error_msg or "").lower()

    if "not found" in msg:
        return status.HTTP_404_NOT_FOUND, "Session not found"
    if "not awaiting_approval" in msg:
        return status.HTTP_400_BAD_REQUEST, "Session is not awaiting approval"
    if "no validation report" in msg:
        return status.HTTP_400_BAD_REQUEST, "Session has no validation report"
    if "blocking validation issues" in msg:
        return status.HTTP_400_BAD_REQUEST, "Session has blocking validation issues"
    if "preflight validation errors" in msg:
        return status.HTTP_400_BAD_REQUEST, "Session has preflight validation errors"

    return status.HTTP_400_BAD_REQUEST, "Session cannot be approved"


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
    session = await twin_service.get_session(session_id)
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
    except ValueError as e:
        status_code, detail = _approve_error_response(str(e))
        raise HTTPException(status_code=status_code, detail=detail) from None
