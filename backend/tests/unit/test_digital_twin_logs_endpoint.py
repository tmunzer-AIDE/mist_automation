from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.digital_twin.models import SimulationLogEntry


@pytest.fixture
def sample_entries():
    return [
        SimulationLogEntry(
            timestamp=datetime(2026, 4, 12, 18, 50, 40, tzinfo=timezone.utc),
            level="info",
            event="simulate_start",
            phase="simulate",
            context={"org_id": "org"},
        ),
        SimulationLogEntry(
            timestamp=datetime(2026, 4, 12, 18, 50, 41, tzinfo=timezone.utc),
            level="warning",
            event="twin_write_parse_error",
            phase="simulate",
            context={"sequence": 0},
        ),
        SimulationLogEntry(
            timestamp=datetime(2026, 4, 12, 18, 50, 42, tzinfo=timezone.utc),
            level="error",
            event="resolved_failed",
            phase="remediate",
            context={},
        ),
    ]


def test_filter_by_level(sample_entries):
    from app.api.v1.digital_twin import _filter_logs

    result = _filter_logs(sample_entries, level="warning", phase=None, search=None)
    assert len(result) == 1
    assert result[0].event == "twin_write_parse_error"


def test_filter_by_phase(sample_entries):
    from app.api.v1.digital_twin import _filter_logs

    result = _filter_logs(sample_entries, level=None, phase="remediate", search=None)
    assert len(result) == 1
    assert result[0].phase == "remediate"


def test_filter_by_search(sample_entries):
    from app.api.v1.digital_twin import _filter_logs

    result = _filter_logs(sample_entries, level=None, phase=None, search="parse")
    assert len(result) == 1
    assert "parse" in result[0].event


def test_combined_filters(sample_entries):
    from app.api.v1.digital_twin import _filter_logs

    result = _filter_logs(sample_entries, level="info", phase="simulate", search="start")
    assert len(result) == 1
    assert result[0].event == "simulate_start"


def test_filter_with_no_filters_returns_all(sample_entries):
    from app.api.v1.digital_twin import _filter_logs

    result = _filter_logs(sample_entries, level=None, phase=None, search=None)
    assert len(result) == 3


def test_filter_search_matches_context_values(sample_entries):
    from app.api.v1.digital_twin import _filter_logs

    result = _filter_logs(sample_entries, level=None, phase=None, search="org")
    # Should match the first entry because its context contains org_id="org"
    assert len(result) == 1
    assert result[0].event == "simulate_start"


@pytest.mark.asyncio
async def test_get_session_logs_returns_404_for_foreign_session(monkeypatch):
    from app.api.v1 import digital_twin as api

    session = SimpleNamespace(
        user_id="owner-id",
        simulation_logs=[],
    )

    async def _fake_get_session(_session_id: str):
        return session

    monkeypatch.setattr(api.twin_service, "get_session", _fake_get_session)

    with pytest.raises(HTTPException) as exc:
        await api.get_session_logs(
            session_id="507f1f77bcf86cd799439011",
            level=None,
            phase=None,
            search=None,
            _current_user=SimpleNamespace(id="different-user"),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Session not found"


@pytest.mark.asyncio
async def test_get_session_logs_allows_owner(monkeypatch, sample_entries):
    from app.api.v1 import digital_twin as api

    session = SimpleNamespace(
        user_id="owner-id",
        simulation_logs=sample_entries,
    )

    async def _fake_get_session(_session_id: str):
        return session

    monkeypatch.setattr(api.twin_service, "get_session", _fake_get_session)

    result = await api.get_session_logs(
        session_id="507f1f77bcf86cd799439011",
        level=None,
        phase=None,
        search=None,
        _current_user=SimpleNamespace(id="owner-id"),
    )

    assert len(result) == len(sample_entries)
