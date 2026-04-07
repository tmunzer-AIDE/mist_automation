"""
Token counting and context window detection.

Uses litellm.token_counter() universally (regardless of provider path)
and litellm.get_model_info() for context window detection.
"""

import structlog

logger = structlog.get_logger(__name__)

# Default context window when detection fails and no manual override
DEFAULT_CONTEXT_WINDOW = 20_000


def _litellm_token_count(messages: list[dict], model: str) -> int:
    """Call litellm.token_counter — isolated for easy mocking."""
    import litellm

    return litellm.token_counter(model=model, messages=messages)


def count_message_tokens(messages: list[dict[str, str]], model: str) -> int:
    """Count tokens in a list of chat messages.

    Uses litellm.token_counter() which supports all major model families.
    Falls back to a character-based estimate (1 token ≈ 4 chars) on failure.
    """
    if not messages:
        return 0
    try:
        return _litellm_token_count(messages, model)
    except Exception:
        # Fallback: rough estimate — 1 token ≈ 4 characters
        total_chars = sum(len(m.get("content") or "") + len(str(m.get("tool_calls") or "")) for m in messages)
        estimated = total_chars // 4
        logger.debug("token_count_fallback", model=model, estimated_tokens=estimated)
        return estimated


def get_context_window(model: str) -> int | None:
    """Detect the context window size for a model.

    Returns the max input tokens if available, None if the model is unknown.
    """
    try:
        import litellm

        info = litellm.get_model_info(model=model)
        return info.get("max_input_tokens") or info.get("max_tokens") or None
    except Exception:
        return None
