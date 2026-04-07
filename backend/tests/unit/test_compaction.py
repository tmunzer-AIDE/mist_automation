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
