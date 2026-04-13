"""Unit tests for Twin session rejection semantics."""

import pytest
from beanie import PydanticObjectId

from app.modules.digital_twin.models import TwinSessionStatus
from app.modules.digital_twin.services import twin_service


class _FakeSession:
    def __init__(self, status: TwinSessionStatus, user_id: str):
        self.id = PydanticObjectId("507f1f77bcf86cd799439011")
        self.user_id = PydanticObjectId(user_id)
        self.status = status
        self.saved = False

    def update_timestamp(self) -> None:
        return None

    async def save(self) -> None:
        self.saved = True


@pytest.mark.unit
async def test_reject_session_rejects_malformed_id():
    with pytest.raises(twin_service.TwinApprovalError) as exc:
        await twin_service.reject_session("not-an-object-id", user_id="507f1f77bcf86cd799439011")

    assert exc.value.code == twin_service.TwinApprovalErrorCode.NOT_FOUND


@pytest.mark.unit
async def test_reject_session_requires_awaiting_approval(monkeypatch):
    user_id = "507f1f77bcf86cd799439011"
    session = _FakeSession(status=TwinSessionStatus.VALIDATING, user_id=user_id)

    async def fake_get(_id):
        return session

    monkeypatch.setattr(twin_service.TwinSession, "get", fake_get)

    with pytest.raises(twin_service.TwinApprovalError) as exc:
        await twin_service.reject_session("507f1f77bcf86cd799439011", user_id=user_id)

    assert exc.value.code == twin_service.TwinApprovalErrorCode.NOT_AWAITING_APPROVAL


@pytest.mark.unit
async def test_reject_session_updates_status_when_allowed(monkeypatch):
    user_id = "507f1f77bcf86cd799439011"
    session = _FakeSession(status=TwinSessionStatus.AWAITING_APPROVAL, user_id=user_id)

    async def fake_get(_id):
        return session

    monkeypatch.setattr(twin_service.TwinSession, "get", fake_get)

    result = await twin_service.reject_session("507f1f77bcf86cd799439011", user_id=user_id)

    assert result.status == TwinSessionStatus.REJECTED
    assert result.saved is True
