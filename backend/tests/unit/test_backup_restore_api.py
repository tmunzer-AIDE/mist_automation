"""Unit tests for backup restore endpoint flag validation."""

import pytest
from fastapi import HTTPException


@pytest.mark.unit
@pytest.mark.asyncio
async def test_restore_rejects_simulate_and_dry_run_together():
    from app.api.v1.backup import restore_object_version

    current_user = type("UserStub", (), {"id": "u-1"})()

    with pytest.raises(HTTPException) as exc:
        await restore_object_version(
            version_id="507f1f77bcf86cd799439011",
            dry_run=True,
            simulate=True,
            cascade=False,
            current_user=current_user,
        )

    assert exc.value.status_code == 400
    assert "mutually exclusive" in str(exc.value.detail)
