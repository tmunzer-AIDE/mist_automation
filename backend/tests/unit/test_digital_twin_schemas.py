"""
Unit tests for Digital Twin API schemas.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.schemas import (
    RemediationAttemptResponse,
    StagedWriteResponse,
    TwinSessionDetailResponse,
    TwinSessionResponse,
    session_to_detail_response,
    session_to_response,
)


@pytest.mark.unit
class TestStagedWriteResponse:
    """Tests for StagedWriteResponse schema."""

    def test_construction_with_all_fields(self):
        sw = StagedWriteResponse(
            sequence=1,
            method="PUT",
            endpoint="/api/v1/sites/abc/wlans/xyz",
            body={"ssid": "TestNet"},
            object_type="wlan",
            site_id="abc",
            object_id="xyz",
        )
        assert sw.sequence == 1
        assert sw.method == "PUT"
        assert sw.endpoint == "/api/v1/sites/abc/wlans/xyz"
        assert sw.body == {"ssid": "TestNet"}
        assert sw.object_type == "wlan"
        assert sw.site_id == "abc"
        assert sw.object_id == "xyz"

    def test_optional_fields_default_to_none(self):
        sw = StagedWriteResponse(sequence=2, method="POST", endpoint="/api/v1/orgs/abc/wlans")
        assert sw.body is None
        assert sw.object_type is None
        assert sw.site_id is None
        assert sw.object_id is None

    def test_construction_from_dict(self):
        data = {"sequence": 3, "method": "DELETE", "endpoint": "/api/v1/sites/s1/wlans/w1"}
        sw = StagedWriteResponse(**data)
        assert sw.sequence == 3
        assert sw.method == "DELETE"


@pytest.mark.unit
class TestRemediationAttemptResponse:
    """Tests for RemediationAttemptResponse schema."""

    def test_construction_with_all_fields(self):
        ts = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        ra = RemediationAttemptResponse(
            attempt=1,
            changed_writes=[0, 2],
            previous_severity="error",
            new_severity="warning",
            fixed_checks=["L1-03"],
            introduced_checks=["L1-05"],
            timestamp=ts,
        )
        assert ra.attempt == 1
        assert ra.changed_writes == [0, 2]
        assert ra.previous_severity == "error"
        assert ra.new_severity == "warning"
        assert ra.fixed_checks == ["L1-03"]
        assert ra.introduced_checks == ["L1-05"]
        assert ra.timestamp == ts

    def test_defaults(self):
        ra = RemediationAttemptResponse(attempt=1)
        assert ra.changed_writes == []
        assert ra.previous_severity == ""
        assert ra.new_severity == ""
        assert ra.fixed_checks == []
        assert ra.introduced_checks == []
        assert ra.timestamp is None


@pytest.mark.unit
class TestTwinSessionResponse:
    """Tests for TwinSessionResponse schema including new source_ref field."""

    def test_source_ref_field_present(self):
        now = datetime.now(timezone.utc)
        r = TwinSessionResponse(
            id="abc",
            status="pending",
            source="llm_chat",
            source_ref="conv_123",
            overall_severity="clean",
            writes_count=0,
            created_at=now,
            updated_at=now,
        )
        assert r.source_ref == "conv_123"

    def test_source_ref_defaults_to_none(self):
        r = TwinSessionResponse(
            id="abc",
            status="pending",
            source="workflow",
            overall_severity="clean",
            writes_count=2,
        )
        assert r.source_ref is None

    def test_all_base_fields_present(self):
        now = datetime.now(timezone.utc)
        r = TwinSessionResponse(
            id="abc123",
            status="awaiting_approval",
            source="backup_restore",
            source_ref=None,
            overall_severity="error",
            writes_count=5,
            affected_sites=["site1", "site2"],
            remediation_count=1,
            created_at=now,
            updated_at=now,
        )
        assert r.id == "abc123"
        assert r.status == "awaiting_approval"
        assert r.source == "backup_restore"
        assert r.affected_sites == ["site1", "site2"]
        assert r.remediation_count == 1


@pytest.mark.unit
class TestTwinSessionDetailResponse:
    """Tests for TwinSessionDetailResponse schema."""

    def test_extends_base_response(self):
        r = TwinSessionDetailResponse(
            id="abc",
            status="pending",
            source="llm_chat",
            overall_severity="clean",
            writes_count=0,
        )
        # Fields from base class
        assert r.id == "abc"
        assert r.source_ref is None
        assert r.prediction_report is None

    def test_detail_fields_present(self):
        sw = StagedWriteResponse(sequence=0, method="PUT", endpoint="/api/v1/sites/s1/wlans/w1")
        ra = RemediationAttemptResponse(attempt=1)
        r = TwinSessionDetailResponse(
            id="abc",
            status="awaiting_approval",
            source="workflow",
            overall_severity="warning",
            writes_count=1,
            ai_assessment="Looks safe to deploy.",
            execution_safe=True,
            staged_writes=[sw],
            remediation_history=[ra],
        )
        assert r.ai_assessment == "Looks safe to deploy."
        assert r.execution_safe is True
        assert len(r.staged_writes) == 1
        assert r.staged_writes[0].sequence == 0
        assert len(r.remediation_history) == 1
        assert r.remediation_history[0].attempt == 1

    def test_defaults(self):
        r = TwinSessionDetailResponse(
            id="abc",
            status="pending",
            source="llm_chat",
            overall_severity="clean",
            writes_count=0,
        )
        assert r.ai_assessment is None
        assert r.execution_safe is True
        assert r.staged_writes == []
        assert r.remediation_history == []


def _make_session(
    *,
    status_value="pending",
    source="llm_chat",
    source_ref=None,
    overall_severity="clean",
    staged_writes=None,
    remediation_history=None,
    prediction_report=None,
    ai_assessment=None,
):
    """Build a mock TwinSession object."""
    session = MagicMock()
    session.id = "507f1f77bcf86cd799439011"
    session.status.value = status_value
    session.source = source
    session.source_ref = source_ref
    session.overall_severity = overall_severity
    session.staged_writes = staged_writes or []
    session.remediation_history = remediation_history or []
    session.remediation_count = len(remediation_history or [])
    session.affected_sites = ["site1"]
    session.prediction_report = prediction_report
    session.ai_assessment = ai_assessment
    session.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    session.updated_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    return session


@pytest.mark.unit
class TestSessionToResponse:
    """Tests for session_to_response() helper."""

    def test_maps_all_fields(self):
        session = _make_session(status_value="approved", source="workflow", source_ref="wf_abc")
        r = session_to_response(session)
        assert r.id == "507f1f77bcf86cd799439011"
        assert r.status == "approved"
        assert r.source == "workflow"
        assert r.source_ref == "wf_abc"
        assert r.overall_severity == "clean"
        assert r.writes_count == 0
        assert r.prediction_report is None

    def test_source_ref_none_when_not_set(self):
        session = _make_session()
        r = session_to_response(session)
        assert r.source_ref is None

    def test_writes_count_from_staged_writes_length(self):
        sw = MagicMock()
        session = _make_session(staged_writes=[sw, sw, sw])
        r = session_to_response(session)
        assert r.writes_count == 3


@pytest.mark.unit
class TestSessionToDetailResponse:
    """Tests for session_to_detail_response() helper."""

    def test_maps_staged_writes(self):
        sw = MagicMock()
        sw.sequence = 0
        sw.method = "PUT"
        sw.endpoint = "/api/v1/sites/s1/wlans/w1"
        sw.body = {"ssid": "MyNet"}
        sw.object_type = "wlan"
        sw.site_id = "s1"
        sw.object_id = "w1"
        session = _make_session(staged_writes=[sw])
        r = session_to_detail_response(session)
        assert len(r.staged_writes) == 1
        assert r.staged_writes[0].sequence == 0
        assert r.staged_writes[0].method == "PUT"
        assert r.staged_writes[0].body == {"ssid": "MyNet"}

    def test_maps_remediation_history(self):
        attempt = MagicMock()
        attempt.attempt = 1
        attempt.changed_writes = [0]
        attempt.previous_severity = "error"
        attempt.new_severity = "warning"
        attempt.fixed_checks = ["L1-03"]
        attempt.introduced_checks = []
        attempt.timestamp = datetime(2025, 3, 1, tzinfo=timezone.utc)
        session = _make_session(remediation_history=[attempt])
        r = session_to_detail_response(session)
        assert len(r.remediation_history) == 1
        assert r.remediation_history[0].attempt == 1
        assert r.remediation_history[0].previous_severity == "error"

    def test_ai_assessment_mapped(self):
        session = _make_session(ai_assessment="All checks passed.")
        r = session_to_detail_response(session)
        assert r.ai_assessment == "All checks passed."

    def test_execution_safe_from_report(self):
        report = MagicMock()
        report.total_checks = 5
        report.passed = 5
        report.warnings = 0
        report.errors = 0
        report.critical = 0
        report.skipped = 0
        report.check_results = []
        report.overall_severity = "clean"
        report.summary = ""
        report.execution_safe = False
        session = _make_session(prediction_report=report)
        r = session_to_detail_response(session)
        assert r.execution_safe is False

    def test_execution_safe_defaults_true_without_report(self):
        session = _make_session(prediction_report=None)
        r = session_to_detail_response(session)
        assert r.execution_safe is True

    def test_source_ref_propagated(self):
        session = _make_session(source_ref="chat_xyz")
        r = session_to_detail_response(session)
        assert r.source_ref == "chat_xyz"

    def test_prediction_report_preserves_check_decision_context(self):
        issue = CheckResult(
            check_id="ROUTE-GW",
            check_name="Default Gateway Gap",
            layer=3,
            status="error",
            summary="1 network missing a gateway L3 interface.",
            details=["Network 'Corp' has no gateway L3 interface; network VLAN=10"],
            affected_objects=["Corp"],
            affected_sites=["site-1"],
            remediation_hint="Add ip_config entries on a gateway for routed networks.",
            pre_existing=True,
            description="Detects routed networks with no corresponding gateway interface.",
        )
        passed = CheckResult(
            check_id="CONN-PHYS",
            check_name="Physical connectivity loss",
            layer=2,
            status="pass",
            summary="All devices retain gateway reachability.",
            description="Detects devices that become isolated from gateways.",
        )

        report = MagicMock()
        report.total_checks = 2
        report.passed = 1
        report.warnings = 0
        report.errors = 1
        report.critical = 0
        report.skipped = 0
        report.check_results = [issue, passed]
        report.overall_severity = "error"
        report.summary = "1 error(s), 1 pass"
        report.execution_safe = False

        session = _make_session(prediction_report=report)
        response = session_to_detail_response(session)

        assert response.prediction_report is not None
        assert response.prediction_report.total_checks == 2
        assert len(response.prediction_report.check_results) == 2

        route = next(c for c in response.prediction_report.check_results if c.check_id == "ROUTE-GW")
        assert route.status == "error"
        assert route.summary != ""
        assert route.details and "VLAN=10" in route.details[0]
        assert route.remediation_hint is not None
        assert route.description != ""
        assert route.pre_existing is True

        conn = next(c for c in response.prediction_report.check_results if c.check_id == "CONN-PHYS")
        assert conn.status == "pass"
        assert conn.summary != ""
        assert conn.description != ""


@pytest.mark.unit
class TestCheckResultDescription:
    """Tests for CheckResult description field."""

    def test_description_defaults_to_empty_string(self):
        result = CheckResult(
            check_id="TEST-01",
            check_name="Test check",
            layer=1,
            status="pass",
            summary="All good",
        )
        assert result.description == ""

    def test_description_accepts_string(self):
        result = CheckResult(
            check_id="TEST-01",
            check_name="Test check",
            layer=1,
            status="pass",
            summary="All good",
            description="Validates that the test thing works.",
        )
        assert result.description == "Validates that the test thing works."
