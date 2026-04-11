"""
About endpoint — exposes third-party license information.
"""

import json
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_current_user_from_token
from app.models.user import User

router = APIRouter()
logger = structlog.get_logger(__name__)

_LICENSES_FILE = Path(__file__).parent.parent.parent / "data" / "licenses.json"


@router.get("/about/licenses")
async def get_licenses(_: User = Depends(get_current_user_from_token)):
    """Return third-party license information for backend and frontend dependencies."""
    if not _LICENSES_FILE.is_file():
        raise HTTPException(status_code=404, detail="License file not found")
    try:
        return json.loads(_LICENSES_FILE.read_text())
    except Exception:
        logger.exception("licenses_read_failed", path=str(_LICENSES_FILE))
        raise HTTPException(status_code=500, detail="Failed to read license data")
