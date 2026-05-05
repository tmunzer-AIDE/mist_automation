"""Tests for ConversationThread compaction fields and message retrieval."""

from datetime import datetime, timezone

import pytest

from app.modules.llm.models import ConversationThread


async def test_get_messages_for_llm_no_compaction(test_db, test_user):
    """Without compaction, get_messages_for_llm uses the sliding window."""
    thread = ConversationThread(user_id=test_user.id, feature="global_chat")
    thread.add_message("system", "You are an assistant.")
    thread.add_message("user", "First question")
    thread.add_message("assistant", "First answer")
    thread.add_message("user", "Second question")
    thread.add_message("assistant", "Second answer")
    await thread.insert()

    messages = thread.get_messages_for_llm(max_turns=20)
    assert len(messages) == 5
    assert messages[0]["role"] == "system"


async def test_get_messages_for_llm_with_compaction(test_db, test_user):
    """With compaction, messages include the summary and skip compacted messages."""
    thread = ConversationThread(user_id=test_user.id, feature="global_chat")
    thread.add_message("system", "You are an assistant.")
    thread.add_message("user", "First question")
    thread.add_message("assistant", "First answer")
    thread.add_message("user", "Second question")
    thread.add_message("assistant", "Second answer")
    thread.add_message("user", "Third question")
    thread.add_message("assistant", "Third answer")

    # Compact up to index 5 (covers messages 0-4: system + 2 Q&A pairs)
    thread.compaction_summary = "User asked two questions and received answers."
    thread.compacted_up_to_index = 5
    await thread.insert()

    messages = thread.get_messages_for_llm(max_turns=20)

    # Expected: [system] + [first user msg] + [summary as system] + [recent after index 5]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "You are an assistant."
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "First question"
    assert messages[2]["role"] == "system"
    assert "User asked two questions" in messages[2]["content"]
    # Messages after index 5: "Third question", "Third answer"
    assert messages[3]["role"] == "user"
    assert messages[3]["content"] == "Third question"
    assert messages[4]["role"] == "assistant"
    assert messages[4]["content"] == "Third answer"
    assert len(messages) == 5


async def test_get_messages_for_llm_compaction_with_sliding_window(test_db, test_user):
    """Compaction + sliding window: recent messages still capped by max_turns."""
    thread = ConversationThread(user_id=test_user.id, feature="global_chat")
    thread.add_message("system", "You are an assistant.")
    thread.add_message("user", "First question")
    thread.add_message("assistant", "First answer")
    # Add many messages after compaction point
    for i in range(20):
        thread.add_message("user", f"Q{i}")
        thread.add_message("assistant", f"A{i}")

    thread.compaction_summary = "User asked one question."
    thread.compacted_up_to_index = 3
    await thread.insert()

    messages = thread.get_messages_for_llm(max_turns=6)

    # [system] + [first user] + [summary] + last 6 non-system messages from recent
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "First question"
    assert messages[2]["role"] == "system"
    assert "User asked one question" in messages[2]["content"]
    # 6 recent turns (3 Q&A pairs)
    assert len(messages) == 3 + 6  # system + first_user + summary + 6 recent


async def test_compaction_defaults(test_db, test_user):
    """New threads have no compaction fields set."""
    thread = ConversationThread(user_id=test_user.id, feature="global_chat")
    await thread.insert()

    found = await ConversationThread.get(thread.id)
    assert found.compaction_summary is None
    assert found.compacted_up_to_index is None
    assert found.compaction_in_progress is False


from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.llm.models import ConversationThread, LLMUsageLog


async def test_compact_thread_basic(test_db, test_user):
    """compact_thread summarizes old messages and stores the summary."""
    from app.modules.llm.workers.compaction_worker import compact_thread

    thread = ConversationThread(user_id=test_user.id, feature="global_chat")
    thread.add_message("system", "You are an assistant.")
    thread.add_message("user", "What is an AP?")
    thread.add_message("assistant", "An AP is an access point.")
    thread.add_message("user", "How many APs do I have?")
    thread.add_message("assistant", "You have 42 APs.")
    thread.add_message("user", "Where are they deployed?")
    thread.add_message("assistant", "Across 5 sites in EMEA.")
    thread.add_message("user", "Tell me more about AP45")
    await thread.insert()

    mock_response = MagicMock()
    mock_response.content = "User asked about access points and has 42 APs."
    mock_response.model = "gpt-4o"
    mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    mock_response.duration_ms = 500

    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=mock_response)
    mock_llm.provider = "openai"
    mock_llm.model = "gpt-4o"

    await compact_thread(str(thread.id), mock_llm, context_window=10)

    updated = await ConversationThread.get(thread.id)
    assert updated.compaction_summary is not None
    assert "access points" in updated.compaction_summary
    assert updated.compacted_up_to_index is not None
    assert updated.compacted_up_to_index > 0
    assert updated.compaction_in_progress is False


async def test_compact_thread_skips_if_in_progress(test_db, test_user):
    """compact_thread skips if compaction_in_progress is already True."""
    from app.modules.llm.workers.compaction_worker import compact_thread

    thread = ConversationThread(user_id=test_user.id, feature="global_chat")
    thread.compaction_in_progress = True
    thread.add_message("system", "sys")
    thread.add_message("user", "q")
    thread.add_message("assistant", "a")
    await thread.insert()

    mock_llm = AsyncMock()
    await compact_thread(str(thread.id), mock_llm, context_window=20000)

    # LLM should not have been called
    mock_llm.complete.assert_not_called()


async def test_compact_thread_fallback_on_llm_error(test_db, test_user):
    """compact_thread clears in_progress flag even if LLM call fails."""
    from app.modules.llm.workers.compaction_worker import compact_thread

    thread = ConversationThread(user_id=test_user.id, feature="global_chat")
    thread.add_message("system", "You are an assistant.")
    for i in range(10):
        thread.add_message("user", f"Question {i}")
        thread.add_message("assistant", f"Answer {i}")
    await thread.insert()

    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(side_effect=Exception("LLM unavailable"))
    mock_llm.provider = "openai"
    mock_llm.model = "gpt-4o"

    # Should not raise — errors are caught
    await compact_thread(str(thread.id), mock_llm, context_window=10)

    updated = await ConversationThread.get(thread.id)
    assert updated.compaction_in_progress is False
    assert updated.compaction_summary is None  # No summary on failure


async def test_compact_thread_incremental_merge_uses_new_range_only(test_db, test_user, monkeypatch):
    """Incremental compaction merges existing summary and only summarizes new message range."""
    import app.modules.llm.workers.compaction_worker as compaction_worker
    from app.modules.llm.workers.compaction_worker import compact_thread

    thread = ConversationThread(user_id=test_user.id, feature="global_chat")
    thread.add_message("system", "You are an assistant.")
    thread.add_message("user", "old question")
    thread.add_message("assistant", "old answer")
    thread.add_message("user", "new question 1")
    thread.add_message("assistant", "new answer 1")
    thread.add_message("user", "new question 2")
    thread.add_message("assistant", "new answer 2")
    thread.compaction_summary = "Prior continuity summary"
    thread.compacted_up_to_index = 3
    await thread.insert()

    mock_response = MagicMock()
    mock_response.content = "Merged continuity summary"
    mock_response.model = "gpt-4o"
    mock_response.usage = MagicMock(prompt_tokens=80, completion_tokens=40, total_tokens=120)
    mock_response.duration_ms = 300

    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=mock_response)
    mock_llm.provider = "openai"
    mock_llm.model = "gpt-4o"

    # Force compaction path and deterministic cutoff for this test.
    monkeypatch.setattr(compaction_worker, "count_message_tokens", lambda *_args, **_kwargs: 9999)
    monkeypatch.setattr(compaction_worker, "_select_cutoff_index", lambda *_args, **_kwargs: 5)

    await compact_thread(str(thread.id), mock_llm, context_window=100)

    sent_messages = mock_llm.complete.await_args.args[0]
    user_payload = sent_messages[1].content

    assert "Existing continuity summary" in user_payload
    assert "Prior continuity summary" in user_payload
    assert "new question 1" in user_payload
    assert "new answer 1" in user_payload
    assert "old question" not in user_payload
    assert "new question 2" not in user_payload

    updated = await ConversationThread.get(thread.id)
    assert updated.compaction_summary == "Merged continuity summary"
    assert updated.compacted_up_to_index == 5
    assert updated.compaction_in_progress is False


async def test_compact_thread_first_run_skips_first_user_message(test_user, monkeypatch):
    """First compaction run should not summarize the first user turn (kept raw in prompt)."""
    import app.modules.llm.workers.compaction_worker as compaction_worker
    from app.modules.llm.workers.compaction_worker import compact_thread

    thread = ConversationThread(user_id=test_user.id, feature="global_chat")
    thread.add_message("system", "You are an assistant.")
    thread.add_message("user", "first user question")
    thread.add_message("assistant", "first assistant reply")
    thread.add_message("user", "second user question")
    thread.add_message("assistant", "second assistant reply")
    thread.add_message("user", "third user question")
    await thread.insert()

    mock_response = MagicMock()
    mock_response.content = "Compacted summary"
    mock_response.model = "gpt-4o"
    mock_response.usage = MagicMock(prompt_tokens=50, completion_tokens=25, total_tokens=75)
    mock_response.duration_ms = 200

    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=mock_response)
    mock_llm.provider = "openai"
    mock_llm.model = "gpt-4o"

    # Force compaction path and deterministic cutoff.
    monkeypatch.setattr(compaction_worker, "count_message_tokens", lambda *_args, **_kwargs: 9999)
    monkeypatch.setattr(compaction_worker, "_select_cutoff_index", lambda *_args, **_kwargs: 4)

    await compact_thread(str(thread.id), mock_llm, context_window=100)

    sent_messages = mock_llm.complete.await_args.args[0]
    user_payload = sent_messages[1].content

    # first user turn is intentionally preserved outside summary context
    assert "first user question" not in user_payload
    assert "first assistant reply" in user_payload
    assert "second user question" in user_payload

    updated = await ConversationThread.get(thread.id)
    assert updated.compaction_summary == "Compacted summary"
    assert updated.compacted_up_to_index == 4
