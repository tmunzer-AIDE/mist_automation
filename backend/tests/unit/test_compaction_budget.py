"""Unit tests for compaction cutoff/budget selection logic.

These tests intentionally avoid DB fixtures so they can validate the
threshold/target math in isolation.
"""

from types import SimpleNamespace

from app.modules.llm.workers import compaction_worker


def _build_thread(non_system_count: int):
    """Create a minimal thread-like object for cutoff selection tests."""
    messages = [SimpleNamespace(role="system", content="sys")]
    for i in range(non_system_count):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append(SimpleNamespace(role=role, content=f"m{i}"))
    return SimpleNamespace(messages=messages)


def test_select_cutoff_keeps_min_recent_even_if_budget_tiny(monkeypatch):
    """Always keep at least _MIN_RECENT_MESSAGES non-system turns."""
    thread = _build_thread(non_system_count=6)  # indices 1..6

    monkeypatch.setattr(compaction_worker, "_estimate_message_tokens", lambda *_: 100)

    cutoff = compaction_worker._select_cutoff_index(
        thread,
        start_index=1,
        context_window=1000,  # recent_budget ~= 150 with default constants
        model="gpt-4o-mini",
    )

    # Keep last 4 turns => keep [3,4,5,6], compact [1,2]
    assert cutoff == 3


def test_select_cutoff_keeps_extra_recent_within_budget(monkeypatch):
    """After minimum recency floor, keep additional turns while budget allows."""
    thread = _build_thread(non_system_count=6)  # indices 1..6

    monkeypatch.setattr(compaction_worker, "_estimate_message_tokens", lambda *_: 30)

    cutoff = compaction_worker._select_cutoff_index(
        thread,
        start_index=1,
        context_window=1000,  # recent_budget ~= 150
        model="gpt-4o-mini",
    )

    # 5 turns fit in budget => keep [2,3,4,5,6], compact [1]
    assert cutoff == 2


def test_select_cutoff_returns_none_when_not_enough_messages():
    """No cutoff when there are not enough non-system turns after start_index."""
    thread = _build_thread(non_system_count=4)  # equals _MIN_RECENT_MESSAGES

    cutoff = compaction_worker._select_cutoff_index(
        thread,
        start_index=1,
        context_window=1000,
        model="gpt-4o-mini",
    )

    assert cutoff is None


def test_select_cutoff_honors_start_index(monkeypatch):
    """Only messages after the already-compacted boundary are considered."""
    thread = _build_thread(non_system_count=10)  # indices 1..10

    monkeypatch.setattr(compaction_worker, "_estimate_message_tokens", lambda *_: 30)

    cutoff = compaction_worker._select_cutoff_index(
        thread,
        start_index=5,
        context_window=1000,
        model="gpt-4o-mini",
    )

    # Consider only [5..10], keep [6..10], compact [5]
    assert cutoff == 6
