"""REST API for Digital Twin session management."""

from fastapi import APIRouter

router = APIRouter(tags=["Digital Twin"])


@router.get("/digital-twin/health")
async def digital_twin_health():
    """Health check for the Digital Twin module."""
    return {"status": "ok", "module": "digital_twin"}
