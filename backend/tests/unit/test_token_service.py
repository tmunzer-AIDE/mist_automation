"""Tests for the token counting and context window service."""

from unittest.mock import patch

import pytest


async def test_count_message_tokens_returns_int():
    """count_message_tokens returns a positive integer for valid messages."""
    from app.modules.llm.services.token_service import count_message_tokens

    messages = [
        {"role": "system", "content": "You are an assistant."},
        {"role": "user", "content": "Hello, how are you?"},
    ]
    result = count_message_tokens(messages, "gpt-4o")
    assert isinstance(result, int)
    assert result > 0


async def test_count_message_tokens_empty_messages():
    """Empty message list returns 0."""
    from app.modules.llm.services.token_service import count_message_tokens

    result = count_message_tokens([], "gpt-4o")
    assert result == 0


async def test_count_message_tokens_fallback_on_error():
    """Falls back to character-based estimation when litellm fails."""
    from app.modules.llm.services.token_service import count_message_tokens

    with patch("app.modules.llm.services.token_service._litellm_token_count", side_effect=Exception("model not found")):
        messages = [{"role": "user", "content": "Hello world"}]
        result = count_message_tokens(messages, "unknown-model-xyz")
        assert isinstance(result, int)
        assert result > 0


async def test_get_context_window_known_model():
    """get_context_window returns a positive int for known models."""
    from app.modules.llm.services.token_service import get_context_window

    result = get_context_window("gpt-4o")
    assert result is not None
    assert result > 0


async def test_get_context_window_unknown_model():
    """get_context_window returns None for unknown models."""
    from app.modules.llm.services.token_service import get_context_window

    result = get_context_window("totally-fake-model-12345")
    assert result is None
