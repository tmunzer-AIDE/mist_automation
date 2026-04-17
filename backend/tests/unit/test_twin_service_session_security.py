"""Unit tests for Digital Twin remediation session ownership/org validation."""

from __future__ import annotations

import pytest
from beanie import PydanticObjectId

from app.modules.digital_twin.services import twin_service


class _FakeSession:
    def __init__(self, *, user_id: str, org_id: str, status=None):
        self.user_id = PydanticObjectId(user_id)
        self.org_id = org_id
        self.overall_severity = "clean"
        self.staged_writes = []
        self.affected_sites = []
        self.affected_object_types = []
        self.remediation_count = 0
        self.base_snapshot_refs = []
        self.live_fetched_at = None
        self.prediction_report = None
        self.status = status if status is not None else twin_service.TwinSessionStatus.AWAITING_APPROVAL
        self.ai_assessment = None
        self.remediation_history = []

    def update_timestamp(self) -> None:
        return None

    async def save(self) -> None:
        return None


@pytest.mark.unit
class TestTwinServiceSessionSecurity:
    async def test_remediation_simulate_rejects_foreign_session(self, monkeypatch):
        existing_session_id = "507f1f77bcf86cd799439011"
        owner_user_id = "507f1f77bcf86cd799439012"
        caller_user_id = "507f1f77bcf86cd799439013"

        fake_session = _FakeSession(user_id=owner_user_id, org_id="org-1")

        async def fake_get(_id):
            return fake_session

        monkeypatch.setattr(twin_service.TwinSession, "get", fake_get)

        with pytest.raises(ValueError, match="not found"):
            await twin_service.simulate(
                user_id=caller_user_id,
                org_id="org-1",
                writes=[],
                existing_session_id=existing_session_id,
            )

    async def test_remediation_simulate_rejects_org_mismatch(self, monkeypatch):
        existing_session_id = "507f1f77bcf86cd799439011"
        owner_user_id = "507f1f77bcf86cd799439012"

        fake_session = _FakeSession(user_id=owner_user_id, org_id="org-A")

        async def fake_get(_id):
            return fake_session

        monkeypatch.setattr(twin_service.TwinSession, "get", fake_get)

        with pytest.raises(ValueError, match="org mismatch"):
            await twin_service.simulate(
                user_id=owner_user_id,
                org_id="org-B",
                writes=[],
                existing_session_id=existing_session_id,
            )

    @pytest.mark.parametrize(
        "blocked_status",
        [
            # Terminal — cannot re-simulate
            "EXECUTING",
            "DEPLOYED",
            "REJECTED",
            # In-progress / transient — cannot re-simulate (race protection)
            "VALIDATING",
            "PENDING",
        ],
    )
    async def test_remediation_simulate_rejects_blocked_states(self, monkeypatch, blocked_status):
        """Re-simulate must refuse to mutate sessions that are in-progress
        (PENDING/VALIDATING) or terminal (EXECUTING/DEPLOYED/REJECTED).
        Regression guard for concurrent races and audit-trail integrity.
        """
        existing_session_id = "507f1f77bcf86cd799439011"
        owner_user_id = "507f1f77bcf86cd799439012"

        fake_session = _FakeSession(
            user_id=owner_user_id,
            org_id="org-1",
            status=getattr(twin_service.TwinSessionStatus, blocked_status),
        )

        async def fake_get(_id):
            return fake_session

        monkeypatch.setattr(twin_service.TwinSession, "get", fake_get)

        with pytest.raises(ValueError, match="cannot be re-simulated"):
            await twin_service.simulate(
                user_id=owner_user_id,
                org_id="org-1",
                writes=[],
                existing_session_id=existing_session_id,
            )

    async def test_remediation_simulate_loses_atomic_claim_when_status_flipped(self, monkeypatch):
        """If two simulate() calls race and the second one sees an allowed
        prior status during the in-Python check but the underlying status has
        already flipped to VALIDATING by the time the find_one_and_update
        runs, the atomic claim returns None and the second call must raise.
        """
        existing_session_id = "507f1f77bcf86cd799439011"
        owner_user_id = "507f1f77bcf86cd799439012"

        fake_session = _FakeSession(
            user_id=owner_user_id,
            org_id="org-1",
            status=twin_service.TwinSessionStatus.AWAITING_APPROVAL,
        )

        async def fake_get(_id):
            return fake_session

        monkeypatch.setattr(twin_service.TwinSession, "get", fake_get)

        class _LosingMotor:
            async def find_one_and_update(self, *_args, **_kwargs):
                return None  # claim lost — another simulate already won

        monkeypatch.setattr(
            twin_service.TwinSession,
            "get_motor_collection",
            classmethod(lambda cls: _LosingMotor()),
        )

        with pytest.raises(ValueError, match="no longer in a re-simulatable state"):
            await twin_service.simulate(
                user_id=owner_user_id,
                org_id="org-1",
                writes=[],
                existing_session_id=existing_session_id,
            )
