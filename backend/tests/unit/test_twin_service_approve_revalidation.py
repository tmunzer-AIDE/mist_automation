"""Regression tests for the post-atomic-claim re-validation guard in
``twin_service.approve_and_execute`` (third-pass review fix C).

Scenario: safety checks pass on the first read, the atomic claim succeeds,
and the re-fetched session carries a concurrently-mutated prediction_report
that is no longer execution_safe. The approve path must abort before any
Mist write is dispatched and revert the status to ``AWAITING_APPROVAL``.
"""

from __future__ import annotations

from typing import Any

import pytest
from beanie import PydanticObjectId

from app.modules.digital_twin.models import (
    PredictionReport,
    TwinSessionStatus,
)
from app.modules.digital_twin.services import twin_service


class _FakeSession:
    """Minimal TwinSession stand-in for approve_and_execute."""

    def __init__(
        self, *, user_id: str, prediction_report: PredictionReport | None, status=TwinSessionStatus.AWAITING_APPROVAL
    ):
        self.id = PydanticObjectId("507f1f77bcf86cd799439011")
        self.user_id = PydanticObjectId(user_id)
        self.status = status
        self.prediction_report = prediction_report
        self.staged_writes: list[Any] = []
        self.ai_assessment = None
        self.ia_session_ids: list[str] = []
        self.simulation_logs: list[Any] = []
        self.updated_at = None

    def update_timestamp(self) -> None:
        return None

    async def save(self) -> None:
        return None


class _MotorStub:
    """Stub for ``TwinSession.get_motor_collection()``.

    Captures every update_one / find_one_and_update call so the test can
    assert the status was properly reverted.
    """

    def __init__(self, claim_result: dict | None):
        self._claim_result = claim_result
        self.find_one_and_update_calls: list[dict] = []
        self.update_one_calls: list[dict] = []

    async def find_one_and_update(self, query, update, **_):
        self.find_one_and_update_calls.append({"query": query, "update": update})
        return self._claim_result

    async def update_one(self, query, update, **_):
        self.update_one_calls.append({"query": query, "update": update})


def _make_report(execution_safe: bool) -> PredictionReport:
    """Build a minimal PredictionReport with the required fields."""
    return PredictionReport(
        total_checks=1,
        passed=1 if execution_safe else 0,
        warnings=0,
        errors=0 if execution_safe else 1,
        critical=0,
        overall_severity="clean" if execution_safe else "error",
        execution_safe=execution_safe,
        summary="ok" if execution_safe else "blocking validation issues",
        check_results=[],
    )


@pytest.mark.unit
class TestApproveAndExecuteRevalidation:
    async def test_revalidates_after_claim_blocks_when_report_becomes_unsafe(self, monkeypatch):
        user_id = "507f1f77bcf86cd799439012"
        session_id = "507f1f77bcf86cd799439011"

        # Session returned by the FIRST TwinSession.get — all checks pass.
        first_session = _FakeSession(user_id=user_id, prediction_report=_make_report(True))
        # Session returned by the SECOND TwinSession.get (after atomic claim) —
        # prediction_report was replaced by a concurrent re-simulate and is
        # now blocking.
        refreshed_session = _FakeSession(user_id=user_id, prediction_report=_make_report(False))

        call_count = {"n": 0}

        async def fake_get(_id):
            call_count["n"] += 1
            return first_session if call_count["n"] == 1 else refreshed_session

        monkeypatch.setattr(twin_service.TwinSession, "get", fake_get)

        motor_stub = _MotorStub(claim_result={"_id": session_id, "status": "awaiting_approval"})
        monkeypatch.setattr(twin_service.TwinSession, "get_motor_collection", classmethod(lambda cls: motor_stub))

        # Approve must raise and NOT call create_mist_service. If
        # create_mist_service were invoked, the test would error out because
        # it isn't stubbed.
        with pytest.raises(twin_service.TwinApprovalError) as exc:
            await twin_service.approve_and_execute(session_id, user_id=user_id)

        assert exc.value.code == twin_service.TwinApprovalErrorCode.BLOCKING_VALIDATION_ISSUES
        # Status must be reverted to awaiting_approval — one update_one call.
        assert len(motor_stub.update_one_calls) == 1
        reverted = motor_stub.update_one_calls[0]["update"]["$set"]
        assert reverted["status"] == TwinSessionStatus.AWAITING_APPROVAL.value

    async def test_revalidates_after_claim_blocks_when_report_disappears(self, monkeypatch):
        """Concurrent actor could clear prediction_report (e.g. via a
        re-simulate that crashed). Approve must abort with NO_VALIDATION_REPORT.
        """
        user_id = "507f1f77bcf86cd799439012"
        session_id = "507f1f77bcf86cd799439011"

        first_session = _FakeSession(user_id=user_id, prediction_report=_make_report(True))
        refreshed_session = _FakeSession(user_id=user_id, prediction_report=None)

        call_count = {"n": 0}

        async def fake_get(_id):
            call_count["n"] += 1
            return first_session if call_count["n"] == 1 else refreshed_session

        monkeypatch.setattr(twin_service.TwinSession, "get", fake_get)

        motor_stub = _MotorStub(claim_result={"_id": session_id, "status": "awaiting_approval"})
        monkeypatch.setattr(twin_service.TwinSession, "get_motor_collection", classmethod(lambda cls: motor_stub))

        with pytest.raises(twin_service.TwinApprovalError) as exc:
            await twin_service.approve_and_execute(session_id, user_id=user_id)

        assert exc.value.code == twin_service.TwinApprovalErrorCode.NO_VALIDATION_REPORT
        assert len(motor_stub.update_one_calls) == 1
