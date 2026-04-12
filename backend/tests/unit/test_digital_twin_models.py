from datetime import datetime, timezone
from typing import get_args

from app.modules.digital_twin.models import (
    SimulationLogEntry,
    TwinSession,
)


def test_twin_session_new_fields_defaults():
    # TwinSession is a Beanie Document; use model_construct to bypass the
    # Motor collection initialization that Document.__init__ performs.
    session = TwinSession.model_construct(
        user_id="507f1f77bcf86cd799439011",
        org_id="8aa21779-1178-4357-b3e0-42c02b93b870",
        source="mcp",
    )
    assert session.source == "mcp"
    assert session.source_ref is None
    assert session.affected_object_label is None
    assert session.affected_site_labels == []
    assert session.simulation_logs == []


def test_simulation_log_entry_roundtrip():
    entry = SimulationLogEntry(
        timestamp=datetime(2026, 4, 12, 18, 50, 40, tzinfo=timezone.utc),
        level="info",
        event="twin_write_parse_error",
        phase="simulate",
        context={"sequence": 0, "error": "bad endpoint"},
    )
    data = entry.model_dump()
    restored = SimulationLogEntry.model_validate(data)
    assert restored == entry
    assert restored.context["sequence"] == 0


def test_twin_session_source_literal_accepts_mcp():
    # Verify "mcp" is part of the Literal type for TwinSession.source.
    source_field = TwinSession.model_fields["source"]
    allowed_values = set(get_args(source_field.annotation))
    assert "mcp" in allowed_values
    assert "workflow" in allowed_values
    assert "backup_restore" in allowed_values
    assert "llm_chat" not in allowed_values
