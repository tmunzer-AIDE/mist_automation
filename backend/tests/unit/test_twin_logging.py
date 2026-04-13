from app.modules.digital_twin.services.twin_logging import (
    _MAX_ENTRIES_PER_SESSION,
    bind_twin_session,
    capture_twin_session_logs,
    drain_buffer,
)


def test_processor_ignored_when_no_session_bound():
    processor = capture_twin_session_logs
    event_dict = {"event": "anything", "level": "info"}
    result = processor(None, "info", dict(event_dict))
    assert result == event_dict
    assert drain_buffer("nonexistent") == []


def test_processor_captures_events_when_session_is_bound():
    with bind_twin_session("sess-A", phase="simulate"):
        capture_twin_session_logs(
            None, "info", {"event": "foo", "level": "info", "k": 1}
        )
        capture_twin_session_logs(
            None, "warning", {"event": "bar", "level": "warning", "k": 2}
        )

    entries = drain_buffer("sess-A")
    assert len(entries) == 2
    assert entries[0].event == "foo"
    assert entries[0].phase == "simulate"
    assert entries[0].context == {"k": 1}
    assert entries[1].level == "warning"


def test_buffer_is_bounded():
    with bind_twin_session("sess-B", phase="simulate"):
        total = _MAX_ENTRIES_PER_SESSION + 100
        for i in range(total):
            capture_twin_session_logs(
                None, "info", {"event": f"ev{i}", "level": "info"}
            )

    entries = drain_buffer("sess-B")
    assert len(entries) == _MAX_ENTRIES_PER_SESSION
    assert entries[0].event == "ev100"


def test_nested_session_bindings_use_latest():
    with bind_twin_session("outer", phase="simulate"):
        capture_twin_session_logs(None, "info", {"event": "outer1", "level": "info"})
        with bind_twin_session("outer", phase="remediate"):
            capture_twin_session_logs(None, "info", {"event": "inner", "level": "info"})
        capture_twin_session_logs(None, "info", {"event": "outer2", "level": "info"})

    entries = drain_buffer("outer")
    phases = [e.phase for e in entries]
    assert phases == ["simulate", "remediate", "simulate"]
