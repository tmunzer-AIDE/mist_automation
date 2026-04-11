"""REST API for Digital Twin session management."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import require_admin
from app.models.user import User
from app.modules.digital_twin.schemas import (
    TwinSessionListResponse,
    TwinSessionResponse,
    session_to_response,
)
from app.modules.digital_twin.services import twin_service

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Digital Twin"])


@router.get("/digital-twin/sessions", response_model=TwinSessionListResponse)
async def list_twin_sessions(
    current_user: User = Depends(require_admin),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
):
    """List Digital Twin sessions for the current user."""
    sessions = await twin_service.list_sessions(
        user_id=str(current_user.id),
        status=status_filter,
        limit=limit,
    )
    return TwinSessionListResponse(
        sessions=[session_to_response(s) for s in sessions],
        total=len(sessions),
    )


@router.get("/digital-twin/sessions/{session_id}", response_model=TwinSessionResponse)
async def get_twin_session(
    session_id: str,
    current_user: User = Depends(require_admin),
):
    """Get a Digital Twin session by ID."""
    session = await twin_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session_to_response(session)


@router.post("/digital-twin/sessions/{session_id}/cancel")
async def cancel_twin_session(
    session_id: str,
    current_user: User = Depends(require_admin),
):
    """Cancel/reject a Digital Twin session."""
    try:
        session = await twin_service.reject_session(session_id)
        return {"status": session.status.value, "session_id": str(session.id)}
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found") from None
