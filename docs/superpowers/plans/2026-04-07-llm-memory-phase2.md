# Conversation Compaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed 20-turn sliding window in `ConversationThread` with token-budget-aware compaction that summarizes older messages via LLM, preserving full history in the DB while keeping LLM context efficient.

**Architecture:** A new `token_service` module handles token counting (via `litellm.token_counter()`) and context window detection (via `litellm.get_model_info()`). `LLMConfig` gains a `context_window_tokens` field (auto-detected or manual). `ConversationThread` stores a `compaction_summary` alongside its full messages array. After each chat response, a background task checks the token budget and compacts if >70% used. The compacted context structure is: `[system prompt] + [first user message] + [compaction summary] + [recent messages]`. If compaction fails, the existing sliding window is the fallback.

**Tech Stack:** Python 3.10+, litellm (token counting + model info), Beanie/MongoDB, FastAPI background tasks, Angular 21 signals + Material

**Spec:** `docs/superpowers/specs/2026-04-07-llm-memory-system-design.md` — Phase 2 section (lines 222-234)

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `backend/app/modules/llm/services/token_service.py` | Token counting and context window detection |
| Create | `backend/app/modules/llm/workers/compaction_worker.py` | Background compaction logic |
| Create | `backend/tests/unit/test_token_service.py` | Token service unit tests |
| Create | `backend/tests/unit/test_compaction.py` | Compaction logic unit tests |
| Modify | `backend/app/modules/llm/models.py` | Add `context_window_tokens` to `LLMConfig`, compaction fields to `ConversationThread` |
| Modify | `backend/app/modules/llm/schemas.py` | Add `context_window_tokens` to config schemas |
| Modify | `backend/app/api/v1/llm.py` | Wire config field through CRUD, trigger compaction after chat |
| Modify | `backend/app/modules/llm/services/llm_service_factory.py` | Expose context window from config |
| Modify | `frontend/src/app/core/models/llm.model.ts` | Add `context_window_tokens` to `LlmConfig` interface |
| Modify | `frontend/src/app/features/admin/settings/llm/llm-config-dialog.component.ts` | Add context window field + warning |
| Modify | `frontend/src/app/shared/components/ai-chat-panel/ai-chat-panel.component.ts` | Compaction indicator in timeline |

---

### Task 1: Token Counting Service

**Files:**
- Create: `backend/app/modules/llm/services/token_service.py`
- Test: `backend/tests/unit/test_token_service.py`

- [ ] **Step 1: Write failing tests for token counting**

```python
# backend/tests/unit/test_token_service.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/unit/test_token_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.llm.services.token_service'`

- [ ] **Step 3: Implement the token service**

```python
# backend/app/modules/llm/services/token_service.py
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
        total_chars = sum(len(m.get("content", "")) for m in messages)
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
        # litellm returns max_input_tokens or max_tokens
        return info.get("max_input_tokens") or info.get("max_tokens") or None
    except Exception:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/unit/test_token_service.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/modules/llm/services/token_service.py tests/unit/test_token_service.py
git commit -m "feat: add token counting service using litellm"
```

---

### Task 2: LLMConfig context_window_tokens Field

**Files:**
- Modify: `backend/app/modules/llm/models.py:15-37` (LLMConfig class)
- Modify: `backend/app/modules/llm/schemas.py:12-56` (Config schemas)
- Modify: `backend/app/api/v1/llm.py:231-247` (_config_to_response)
- Modify: `backend/app/api/v1/llm.py:259-285` (create_llm_config)
- Modify: `backend/app/api/v1/llm.py:288-320` (update_llm_config)
- Modify: `backend/app/api/v1/llm.py:478-517` (_fetch_models)

- [ ] **Step 1: Add field to LLMConfig model**

In `backend/app/modules/llm/models.py`, add after line 26 (`enabled` field):

```python
    context_window_tokens: int | None = Field(
        default=None, description="Context window size in tokens (auto-detected or manual override)"
    )
```

- [ ] **Step 2: Add field to config schemas**

In `backend/app/modules/llm/schemas.py`, add `context_window_tokens` to the three config schemas:

In `LLMConfigCreate` (after `max_tokens_per_request`):
```python
    context_window_tokens: int | None = Field(None, ge=1000, le=2_000_000)
```

In `LLMConfigUpdate` (after `max_tokens_per_request`):
```python
    context_window_tokens: int | None = Field(None, ge=1000, le=2_000_000)
```

In `LLMConfigResponse` (after `max_tokens_per_request`):
```python
    context_window_tokens: int | None
    context_window_effective: int
```

- [ ] **Step 3: Wire through _config_to_response**

In `backend/app/api/v1/llm.py`, update `_config_to_response` (~line 231) to include the new fields:

```python
def _config_to_response(cfg) -> LLMConfigResponse:
    from app.modules.llm.services.llm_service_factory import get_effective_canvas_tier
    from app.modules.llm.services.token_service import DEFAULT_CONTEXT_WINDOW, get_context_window

    # Effective context window: manual override > auto-detected > default
    effective_ctx = cfg.context_window_tokens
    if effective_ctx is None and cfg.model:
        detected = get_context_window(cfg.model)
        effective_ctx = detected if detected else DEFAULT_CONTEXT_WINDOW
    if effective_ctx is None:
        effective_ctx = DEFAULT_CONTEXT_WINDOW

    return LLMConfigResponse(
        id=str(cfg.id),
        name=cfg.name,
        provider=cfg.provider,
        api_key_set=bool(cfg.api_key),
        model=cfg.model,
        base_url=cfg.base_url,
        temperature=cfg.temperature,
        max_tokens_per_request=cfg.max_tokens_per_request,
        context_window_tokens=cfg.context_window_tokens,
        context_window_effective=effective_ctx,
        is_default=cfg.is_default,
        enabled=cfg.enabled,
        canvas_prompt_tier=cfg.canvas_prompt_tier,
        canvas_prompt_tier_effective=get_effective_canvas_tier(cfg),
    )
```

- [ ] **Step 4: Wire through create and update endpoints**

In `create_llm_config` (~line 272), add to the `LLMConfig(...)` constructor:
```python
        context_window_tokens=request.context_window_tokens,
```

In `update_llm_config`, no change needed — the generic `for field, value in updates.items()` loop already handles it.

- [ ] **Step 5: Enhance model discovery to return context window**

In `backend/app/api/v1/llm.py`, update `_fetch_models` (~line 478) to return context window info:

```python
async def _fetch_models(provider: str, api_key: str, base_url: str | None) -> list[dict]:
    """Fetch available models from a provider. Returns [{id, name, context_window}]."""
    import httpx

    from app.modules.llm.services.token_service import get_context_window

    try:
        if provider in ("openai", "azure_openai", "lm_studio", "ollama", "llama_cpp", "vllm"):
            from openai import AsyncOpenAI

            url = base_url
            if provider == "lm_studio" and not url:
                url = "http://localhost:1234/v1"
            if provider == "llama_cpp" and not url:
                url = "http://localhost:8080/v1"
            if url and not url.rstrip("/").endswith("/v1"):
                url = f"{url.rstrip('/')}/v1"

            client = AsyncOpenAI(api_key=api_key, base_url=url)
            try:
                result = await client.models.list()
                models = []
                for m in result.data:
                    ctx_win = get_context_window(m.id)
                    models.append({"id": m.id, "name": m.id, "context_window": ctx_win})
                return models
            finally:
                await client.close()

        elif provider == "anthropic":
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                )
                resp.raise_for_status()
                data = resp.json()
                models = []
                for m in data.get("data", []):
                    model_id = m["id"]
                    ctx_win = get_context_window(f"anthropic/{model_id}")
                    models.append({"id": model_id, "name": m.get("display_name", model_id), "context_window": ctx_win})
                return models

        else:
            return []

    except Exception as e:
        logger.warning("model_discovery_failed", provider=provider, error=str(e))
        return []
```

- [ ] **Step 6: Run existing tests + lint**

Run: `cd backend && .venv/bin/pytest tests/ -v --timeout=30 && .venv/bin/ruff check app/modules/llm/models.py app/modules/llm/schemas.py app/api/v1/llm.py app/modules/llm/services/token_service.py`
Expected: All pass, no lint errors

- [ ] **Step 7: Commit**

```bash
cd backend && git add app/modules/llm/models.py app/modules/llm/schemas.py app/api/v1/llm.py
git commit -m "feat: add context_window_tokens field to LLMConfig with auto-detection"
```

---

### Task 3: ConversationThread Compaction Fields

**Files:**
- Modify: `backend/app/modules/llm/models.py:86-125` (ConversationThread class)
- Create: `backend/tests/unit/test_compaction.py`

- [ ] **Step 1: Write failing tests for compaction-aware message retrieval**

```python
# backend/tests/unit/test_compaction.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/unit/test_compaction.py -v`
Expected: FAIL — `AttributeError: 'ConversationThread' object has no attribute 'compaction_summary'`

- [ ] **Step 3: Add compaction fields to ConversationThread**

In `backend/app/modules/llm/models.py`, add three fields to `ConversationThread` after `is_archived` (line 94):

```python
    compaction_summary: str | None = Field(default=None, description="LLM-generated summary of compacted older messages")
    compacted_up_to_index: int | None = Field(default=None, description="Messages[0..N] are covered by compaction_summary")
    compaction_in_progress: bool = Field(default=False, description="Lock to prevent concurrent compactions")
```

- [ ] **Step 4: Update get_messages_for_llm to use compaction**

Replace the existing `get_messages_for_llm` method (lines 111-119) with:

```python
    def get_messages_for_llm(self, max_turns: int = 20) -> list[dict[str, str]]:
        """Return messages for the LLM, using compaction summary when available.

        With compaction: [system prompt] + [first user message] + [compaction summary] + [recent messages]
        Without compaction: keeps all system messages + last ``max_turns`` non-system messages (sliding window).
        """
        if self.compaction_summary and self.compacted_up_to_index is not None:
            return self._get_compacted_messages(max_turns)

        # Fallback: original sliding window behavior
        system = [{"role": m.role, "content": m.content} for m in self.messages if m.role == "system"]
        non_system = [{"role": m.role, "content": m.content} for m in self.messages if m.role != "system"]
        return system + non_system[-max_turns:]

    def _get_compacted_messages(self, max_turns: int = 20) -> list[dict[str, str]]:
        """Build message list using compaction summary."""
        result: list[dict[str, str]] = []

        # 1. System prompt (first system message)
        for m in self.messages:
            if m.role == "system":
                result.append({"role": m.role, "content": m.content})
                break

        # 2. First user message
        for m in self.messages:
            if m.role == "user":
                result.append({"role": m.role, "content": m.content})
                break

        # 3. Compaction summary as a system message
        result.append({
            "role": "system",
            "content": f"Summary of prior conversation:\n{self.compaction_summary}",
        })

        # 4. Recent messages (after compacted_up_to_index), capped by max_turns
        recent = [
            {"role": m.role, "content": m.content}
            for m in self.messages[self.compacted_up_to_index:]
            if m.role != "system"
        ]
        result.extend(recent[-max_turns:])

        return result
```

- [ ] **Step 5: Update to_llm_messages to use compaction**

Replace `to_llm_messages` (lines 121-125) — no change needed to the method body since it delegates to `get_messages_for_llm`:

```python
    def to_llm_messages(self, max_turns: int = 20):
        """Return messages as LLMMessage objects ready for the LLM service."""
        from app.modules.llm.services.llm_service import LLMMessage

        return [LLMMessage(role=m["role"], content=m["content"]) for m in self.get_messages_for_llm(max_turns)]
```

(This is the same code — no change needed. The compaction is handled by `get_messages_for_llm`.)

- [ ] **Step 6: Run tests**

Run: `cd backend && .venv/bin/pytest tests/unit/test_compaction.py -v`
Expected: 4 PASSED

- [ ] **Step 7: Run full test suite**

Run: `cd backend && .venv/bin/pytest tests/ -v --timeout=30`
Expected: All pass (existing behavior preserved by the fallback path)

- [ ] **Step 8: Commit**

```bash
cd backend && git add app/modules/llm/models.py tests/unit/test_compaction.py
git commit -m "feat: add compaction fields to ConversationThread with compacted message retrieval"
```

---

### Task 4: Compaction Worker

**Files:**
- Create: `backend/app/modules/llm/workers/compaction_worker.py`
- Test: `backend/tests/unit/test_compaction.py` (append)

- [ ] **Step 1: Write failing tests for the compaction worker**

Append to `backend/tests/unit/test_compaction.py`:

```python
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

    await compact_thread(str(thread.id), mock_llm, context_window=20000)

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
    await compact_thread(str(thread.id), mock_llm, context_window=20000)

    updated = await ConversationThread.get(thread.id)
    assert updated.compaction_in_progress is False
    assert updated.compaction_summary is None  # No summary on failure
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/unit/test_compaction.py::test_compact_thread_basic -v`
Expected: FAIL — `ImportError: cannot import name 'compact_thread' from 'app.modules.llm.workers.compaction_worker'`

- [ ] **Step 3: Implement the compaction worker**

```python
# backend/app/modules/llm/workers/compaction_worker.py
"""
Conversation compaction worker.

Summarizes older messages in a ConversationThread via LLM, storing the summary
on the thread without modifying the original messages array.
"""

import structlog
from beanie import PydanticObjectId

from app.modules.llm.services.llm_service import LLMMessage
from app.modules.llm.services.token_service import DEFAULT_CONTEXT_WINDOW, count_message_tokens

logger = structlog.get_logger(__name__)

# Reserve 30% of context window for the response + new messages
_COMPACTION_THRESHOLD = 0.7

# Keep at least the last N non-system messages un-compacted
_MIN_RECENT_MESSAGES = 4

COMPACTION_PROMPT = """\
Summarize the following conversation between a user and an AI assistant on a \
network automation platform. Preserve:
- Key facts, decisions, and action items
- Names of specific network objects (sites, APs, SSIDs, VLANs, etc.)
- Any errors or issues discussed

Be concise but thorough. The summary will be used as context for continuing the \
conversation, so don't lose important details. Output only the summary text."""


async def compact_thread(
    thread_id: str,
    llm,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
) -> None:
    """Compact a conversation thread by summarizing older messages.

    - Checks if compaction is needed (token count > 70% of context window)
    - Skips if already in progress
    - On LLM failure, clears the lock and returns (fallback to sliding window)
    """
    from app.modules.llm.models import ConversationThread, LLMUsageLog

    try:
        thread = await ConversationThread.get(PydanticObjectId(thread_id))
    except Exception:
        logger.warning("compaction_invalid_thread_id", thread_id=thread_id)
        return

    if not thread:
        return

    # Skip if already in progress
    if thread.compaction_in_progress:
        logger.info("compaction_already_in_progress", thread_id=thread_id)
        return

    # Check if compaction is actually needed
    all_messages = [{"role": m.role, "content": m.content} for m in thread.messages]
    token_count = count_message_tokens(all_messages, llm.model)
    threshold = int(context_window * _COMPACTION_THRESHOLD)

    if token_count <= threshold:
        logger.debug("compaction_not_needed", thread_id=thread_id, tokens=token_count, threshold=threshold)
        return

    # Set lock
    thread.compaction_in_progress = True
    await thread.save()

    try:
        # Determine cutoff: keep the last _MIN_RECENT_MESSAGES non-system messages
        non_system_indices = [i for i, m in enumerate(thread.messages) if m.role != "system"]
        if len(non_system_indices) <= _MIN_RECENT_MESSAGES:
            # Not enough messages to compact
            logger.info("compaction_too_few_messages", thread_id=thread_id)
            return

        # Cutoff: compact everything before the last _MIN_RECENT_MESSAGES non-system msgs
        cutoff_index = non_system_indices[-_MIN_RECENT_MESSAGES]

        # Gather messages to summarize (non-system messages from index 0 to cutoff)
        messages_to_summarize = []
        for m in thread.messages[1:cutoff_index]:  # Skip system prompt (index 0)
            if m.role != "system":
                messages_to_summarize.append(f"{m.role}: {m.content}")

        if not messages_to_summarize:
            return

        conversation_text = "\n".join(messages_to_summarize)

        # Call LLM to summarize
        summary_messages = [
            LLMMessage(role="system", content=COMPACTION_PROMPT),
            LLMMessage(role="user", content=conversation_text),
        ]
        response = await llm.complete(summary_messages)
        summary = response.content.strip()

        if not summary:
            logger.warning("compaction_empty_summary", thread_id=thread_id)
            return

        # Store compaction result
        thread.compaction_summary = summary
        thread.compacted_up_to_index = cutoff_index

        # Log LLM usage
        await LLMUsageLog(
            user_id=thread.user_id,
            feature="conversation_compaction",
            model=response.model,
            provider=llm.provider,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            duration_ms=response.duration_ms,
        ).insert()

        logger.info(
            "compaction_complete",
            thread_id=thread_id,
            messages_compacted=cutoff_index,
            total_messages=len(thread.messages),
            summary_length=len(summary),
        )

    except Exception as e:
        logger.error("compaction_failed", thread_id=thread_id, error=str(e))

    finally:
        # Always release lock
        thread.compaction_in_progress = False
        await thread.save()


```

- [ ] **Step 4: Run tests**

Run: `cd backend && .venv/bin/pytest tests/unit/test_compaction.py -v`
Expected: 7 PASSED (4 from Task 3 + 3 new)

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/modules/llm/workers/compaction_worker.py tests/unit/test_compaction.py
git commit -m "feat: add conversation compaction worker"
```

---

### Task 5: Trigger Compaction from Chat Endpoints

**Files:**
- Modify: `backend/app/api/v1/llm.py:1642-1655` (global_chat, after saving assistant reply)
- Modify: `backend/app/api/v1/llm.py:922-931` (continue_conversation, after saving assistant reply)
- Modify: `backend/app/modules/llm/services/llm_service_factory.py:15-74` (expose context window)

- [ ] **Step 1: Add helper to get effective context window from default config**

In `backend/app/modules/llm/services/llm_service_factory.py`, add after `get_effective_canvas_tier` (line 149):

```python
async def get_effective_context_window(config_id: str | None = None) -> int:
    """Return the effective context window for the given or default LLM config.

    Priority: manual override > litellm auto-detect > DEFAULT_CONTEXT_WINDOW.
    """
    from app.modules.llm.models import LLMConfig
    from app.modules.llm.services.token_service import DEFAULT_CONTEXT_WINDOW, get_context_window

    if config_id:
        try:
            cfg = await LLMConfig.get(PydanticObjectId(config_id))
        except Exception:
            return DEFAULT_CONTEXT_WINDOW
    else:
        cfg = await LLMConfig.find_one(LLMConfig.is_default == True, LLMConfig.enabled == True)  # noqa: E712

    if not cfg:
        return DEFAULT_CONTEXT_WINDOW
    if cfg.context_window_tokens:
        return cfg.context_window_tokens
    if cfg.model:
        detected = get_context_window(cfg.model)
        if detected:
            return detected
    return DEFAULT_CONTEXT_WINDOW
```

- [ ] **Step 2: Add compaction trigger helper in llm.py**

In `backend/app/api/v1/llm.py`, add an async helper function after `_agent_result_metadata` (~line 1028).

The helper is self-contained — it loads the default config's model and context window internally, so callers just pass the thread. This avoids scoping issues in `continue_conversation` where the MCP path creates its LLM inside `_continue_with_mcp`.

```python
async def _maybe_trigger_compaction(thread) -> None:
    """Check token budget and schedule background compaction if needed.

    Reads the default LLM config to get model name and context window.
    Fires a background task if token count exceeds 70% of context window.
    """
    if len(thread.messages) < 6:
        return  # Too few messages to bother

    from app.modules.llm.models import LLMConfig
    from app.modules.llm.services.llm_service_factory import _default_model, get_effective_context_window
    from app.modules.llm.services.token_service import count_message_tokens
    from app.modules.llm.workers.compaction_worker import _COMPACTION_THRESHOLD

    ctx_window = await get_effective_context_window()
    default_cfg = await LLMConfig.find_one(LLMConfig.is_default == True, LLMConfig.enabled == True)  # noqa: E712
    model = (default_cfg.model or _default_model(default_cfg.provider)) if default_cfg else "gpt-4o"

    all_msgs = [{"role": m.role, "content": m.content} for m in thread.messages]
    token_count = count_message_tokens(all_msgs, model)
    if token_count <= int(ctx_window * _COMPACTION_THRESHOLD):
        return

    from app.core.tasks import create_background_task

    thread_id = str(thread.id)

    async def _run_compaction():
        from app.modules.llm.services.llm_service_factory import create_llm_service
        from app.modules.llm.workers.compaction_worker import compact_thread

        try:
            llm = await create_llm_service()
            await compact_thread(thread_id, llm, ctx_window)
        except Exception as e:
            logger.error("compaction_trigger_failed", thread_id=thread_id, error=str(e))

    create_background_task(_run_compaction(), name=f"compact-{thread_id}")
```

- [ ] **Step 3: Wire into global_chat endpoint**

In `backend/app/api/v1/llm.py`, inside the `global_chat` function, after storing the assistant reply and before the return statement (~line 1644), add:

```python
    # Check if compaction is needed (background task, non-blocking)
    await _maybe_trigger_compaction(thread)
```

- [ ] **Step 4: Wire into continue_conversation endpoint**

In `backend/app/api/v1/llm.py`, inside `continue_conversation`, after storing the assistant reply (~line 924) and before the return:

```python
    # Check if compaction is needed (background task, non-blocking)
    await _maybe_trigger_compaction(thread)
```

- [ ] **Step 5: Run full test suite + lint**

Run: `cd backend && .venv/bin/pytest tests/ -v --timeout=30 && .venv/bin/ruff check app/api/v1/llm.py app/modules/llm/services/llm_service_factory.py app/modules/llm/workers/compaction_worker.py`
Expected: All pass, no lint errors

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/api/v1/llm.py app/modules/llm/services/llm_service_factory.py
git commit -m "feat: trigger background compaction when token budget exceeds 70%"
```

---

### Task 6: Frontend — context_window_tokens in LLM Config

**Files:**
- Modify: `frontend/src/app/core/models/llm.model.ts`
- Modify: `frontend/src/app/features/admin/settings/llm/llm-config-dialog.component.ts`

- [ ] **Step 1: Add interface fields**

In `frontend/src/app/core/models/llm.model.ts`, add to the `LlmConfig` interface (after `max_tokens_per_request`):

```typescript
  context_window_tokens: number | null;
  context_window_effective: number;
```

- [ ] **Step 2: Add context window field to config dialog**

In `frontend/src/app/features/admin/settings/llm/llm-config-dialog.component.ts`:

Add form control in the `FormBuilder` group (after `max_tokens_per_request`):
```typescript
      context_window_tokens: [this.data.config?.context_window_tokens || null],
```

Add to the template, in the "Model Section" area after the `max_tokens_per_request` field:

```html
<mat-form-field>
  <mat-label>Context Window (tokens)</mat-label>
  <input matInput type="number" formControlName="context_window_tokens"
         placeholder="Auto-detected" min="1000" max="2000000">
  <mat-hint>
    @if (data.config?.context_window_effective; as effective) {
      Effective: {{ effective | number }} tokens
    } @else {
      Leave empty for auto-detection (default: 20,000)
    }
  </mat-hint>
</mat-form-field>
```

Add a warning when context window could not be auto-detected. After the context window field:

```html
@if (data.config && !data.config.context_window_tokens && data.config.context_window_effective === 20000) {
  <div class="context-window-warning">
    Context window could not be auto-detected for this model. Using default (20,000 tokens).
    Set a manual value if your model supports a larger context.
  </div>
}
```

Add CSS for the warning:

```css
.context-window-warning {
  color: var(--app-warn);
  font-size: 12px;
  margin: -8px 0 8px 0;
  padding: 4px 8px;
}
```

Include `context_window_tokens` in the save payload (in the `save()` method, alongside other fields). Ensure `null` is sent when the field is empty (not `0`):

```typescript
const val = this.form.value.context_window_tokens;
payload.context_window_tokens = val ? Number(val) : null;
```

- [ ] **Step 3: Add context window info to model discovery response**

In the config dialog, when models are fetched and user selects one, auto-populate the context window if available:

In the `fetchModels()` method or wherever the model selection happens, when a model is selected from the autocomplete:

```typescript
// When model selection changes and a model from the discovered list is selected
const selected = this.availableModels().find(m => m.id === selectedModelId);
if (selected?.context_window && !this.form.value.context_window_tokens) {
  this.form.patchValue({ context_window_tokens: selected.context_window });
}
```

Update the `LlmModel` interface to include:
```typescript
export interface LlmModel {
  id: string;
  name: string;
  context_window?: number | null;
}
```

- [ ] **Step 4: Build frontend**

Run: `cd frontend && npx ng build`
Expected: Build succeeds with no errors

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/app/core/models/llm.model.ts src/app/features/admin/settings/llm/llm-config-dialog.component.ts
git commit -m "feat: add context window field to LLM config dialog with auto-detection warning"
```

---

### Task 7: Frontend — Compaction UI Indicator

**Files:**
- Modify: `frontend/src/app/shared/components/ai-chat-panel/ai-chat-panel.component.ts`

- [ ] **Step 1: Add compaction indicator to the timeline**

The compaction indicator appears as a small system message in the chat timeline when the thread has been compacted. This is driven by thread metadata, not a WS event.

In `frontend/src/app/shared/components/ai-chat-panel/ai-chat-panel.component.ts`:

Add a new `TimelineItem` kind for the compaction notice:

```typescript
type TimelineItem =
  | { kind: 'message'; role: 'user' | 'assistant'; content: string; html: string; sections?: MessageSection[]; timestamp?: string }
  | { kind: 'tool'; tool: string; server: string; status: 'running' | 'success' | 'error'; arguments?: Record<string, unknown>; resultPreview?: string; expanded: boolean; timestamp?: string }
  | { kind: 'compaction'; timestamp?: string };
```

Add a signal to track compaction status:

```typescript
readonly isCompacted = signal(false);
```

Add a public method to set compaction state (called by parent components when thread metadata indicates compaction):

```typescript
setCompacted(compacted: boolean): void {
  if (compacted && !this.isCompacted()) {
    this.isCompacted.set(true);
    // Insert compaction notice at the beginning of the timeline (after any system messages)
    this.timeline.update(items => {
      const notice: TimelineItem = { kind: 'compaction' };
      return [notice, ...items];
    });
  }
}
```

In the template, add rendering for the compaction notice:

```html
@case ('compaction') {
  <div class="compaction-notice">
    <mat-icon>compress</mat-icon>
    <span>Earlier messages have been summarized to save context</span>
  </div>
}
```

Add CSS:

```css
.compaction-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  margin: 4px 0;
  border-radius: 12px;
  background: var(--app-surface-variant, rgba(0,0,0,0.04));
  color: var(--app-text-secondary, rgba(0,0,0,0.6));
  font-size: 12px;

  mat-icon {
    font-size: 16px;
    width: 16px;
    height: 16px;
  }
}
```

- [ ] **Step 2: Wire compaction state in global chat component**

In `frontend/src/app/shared/components/global-chat/global-chat.component.ts` (or wherever the chat panel is instantiated for global chat), when loading a thread's messages, check for compaction:

The backend's `ConversationThreadDetail` response should include a `compacted` boolean. Add to the existing `ConversationThreadDetail` interface in `llm.model.ts`:

```typescript
  compacted: boolean;
```

In `backend/app/api/v1/llm.py`, where thread details are returned (the `get_conversation_thread` endpoint), add:

```python
compacted=bool(thread.compaction_summary),
```

In `backend/app/modules/llm/schemas.py`, add to `ConversationThreadDetail`:

```python
    compacted: bool = False
```

When the global chat loads a thread (existing thread), call:

```typescript
if (threadDetail.compacted) {
  this.chatPanel.setCompacted(true);
}
```

- [ ] **Step 3: Build frontend**

Run: `cd frontend && npx ng build`
Expected: Build succeeds with no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/shared/components/ai-chat-panel/ai-chat-panel.component.ts \
  frontend/src/app/core/models/llm.model.ts \
  frontend/src/app/shared/components/global-chat/global-chat.component.ts \
  backend/app/api/v1/llm.py \
  backend/app/modules/llm/schemas.py
git commit -m "feat: add compaction indicator in chat panel"
```

---

### Task 8: Update Documentation

**Files:**
- Modify: `backend/app/modules/llm/CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-04-07-llm-memory-system-design.md`

- [ ] **Step 1: Update LLM module CLAUDE.md**

In `backend/app/modules/llm/CLAUDE.md`, add to the Backend section (after the "Dreaming consolidation" entry):

```markdown
- **Conversation compaction**: Token-budget-aware background summarization of older messages. `token_service.py` provides `count_message_tokens()` (via `litellm.token_counter()`) and `get_context_window()` (via `litellm.get_model_info()`). `LLMConfig.context_window_tokens` stores manual override (auto-detected otherwise, default 20,000). When messages exceed 70% of context window after a chat response, `compaction_worker.compact_thread()` fires as a background task. `ConversationThread.compaction_summary` stores the result — `messages` array is never modified. `get_messages_for_llm()` builds: `[system prompt] + [first user message] + [compaction summary] + [recent messages]`. Falls back to sliding window (`max_turns=20`) when no compaction exists.
```

Update the conversation threads entry to mention compaction:

```markdown
- **Conversation threads**: `ConversationThread` with `to_llm_messages(max_turns=20)` — uses compaction summary when available, falls back to sliding window. TTL index (90 days). Compaction fields: `compaction_summary`, `compacted_up_to_index`, `compaction_in_progress`.
```

- [ ] **Step 2: Mark Phase 2 as implemented in spec**

In `docs/superpowers/specs/2026-04-07-llm-memory-system-design.md`, change the Phase 2 heading from:

```markdown
## Phase 2: Conversation Compaction (Deferred)
```

to:

```markdown
## Phase 2: Conversation Compaction (Implemented)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/modules/llm/CLAUDE.md docs/superpowers/specs/2026-04-07-llm-memory-system-design.md
git commit -m "docs: update CLAUDE.md and spec for Phase 2 conversation compaction"
```

---

## Verification

1. Run token service tests: `cd backend && .venv/bin/pytest tests/unit/test_token_service.py -v`
2. Run compaction tests: `cd backend && .venv/bin/pytest tests/unit/test_compaction.py -v`
3. Run full backend tests: `cd backend && .venv/bin/pytest tests/ -v`
4. Build frontend: `cd frontend && npx ng build`
5. Lint backend: `cd backend && .venv/bin/ruff check app/modules/llm/services/token_service.py app/modules/llm/workers/compaction_worker.py app/modules/llm/models.py app/modules/llm/schemas.py app/api/v1/llm.py app/modules/llm/services/llm_service_factory.py`
