"""Unit tests for audit log query building in admin endpoints."""

import pytest
from datetime import datetime, timezone

from fastapi import HTTPException

from app.api.v1.admin import _build_audit_query


@pytest.mark.unit
class TestAuditQuery:
    def test_empty_query(self):
        q = _build_audit_query()
        assert q == {}

    def test_event_type_filter(self):
        q = _build_audit_query(event_type="user_login")
        assert q == {"event_type": "user_login"}

    def test_user_id_filter(self):
        q = _build_audit_query(user_id="abc123")
        assert q == {"user_id": "abc123"}

    def test_combined_event_and_user(self):
        q = _build_audit_query(event_type="user_login", user_id="abc123")
        assert q["event_type"] == "user_login"
        assert q["user_id"] == "abc123"

    def test_start_date_only(self):
        q = _build_audit_query(start_date="2026-01-01T00:00:00+00:00")
        assert "timestamp" in q
        assert "$gte" in q["timestamp"]
        assert q["timestamp"]["$gte"].tzinfo is not None

    def test_end_date_only(self):
        q = _build_audit_query(end_date="2026-12-31T23:59:59+00:00")
        assert "timestamp" in q
        assert "$lte" in q["timestamp"]

    def test_date_range(self):
        q = _build_audit_query(
            start_date="2026-01-01T00:00:00+00:00",
            end_date="2026-12-31T23:59:59+00:00",
        )
        assert "$gte" in q["timestamp"]
        assert "$lte" in q["timestamp"]

    def test_z_suffix_handled(self):
        q = _build_audit_query(start_date="2026-01-01T00:00:00Z")
        assert q["timestamp"]["$gte"].tzinfo is not None

    def test_invalid_date_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _build_audit_query(start_date="not-a-date")
        assert exc_info.value.status_code == 400

    def test_naive_date_becomes_utc(self):
        q = _build_audit_query(start_date="2026-06-15")
        assert q["timestamp"]["$gte"].tzinfo == timezone.utc

    def test_start_and_end_parsed_correctly(self):
        q = _build_audit_query(
            start_date="2026-03-01T10:00:00+00:00",
            end_date="2026-03-31T18:00:00+00:00",
        )
        assert q["timestamp"]["$gte"] == datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
        assert q["timestamp"]["$lte"] == datetime(2026, 3, 31, 18, 0, tzinfo=timezone.utc)
