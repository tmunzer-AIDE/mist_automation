"""
Conversation compaction worker.

Summarizes older messages in a ConversationThread via LLM, storing the summary
on the thread without modifying the original messages array.
"""

import structlog
from beanie import PydanticObjectId

from app.modules.llm.services.llm_service import LLMMessage
from app.modules.llm.services.prompt_builders import _sanitize_for_prompt
from app.modules.llm.services.token_service import DEFAULT_CONTEXT_WINDOW, count_message_tokens

logger = structlog.get_logger(__name__)

# Reserve 30% of context window for the response + new messages
_COMPACTION_THRESHOLD = 0.7

# Soft post-compaction usage target.
#
# Important: this is not enforced as a strict final token cap. The current
# algorithm uses it to derive the raw recent-turn budget kept unsummarized:
#   recent_budget ~= context_window * (_COMPACTION_THRESHOLD - _POST_COMPACTION_TARGET)
#
# With current defaults, compaction triggers above 70% usage and keeps roughly
# 15% of the window as recent raw user/assistant turns (plus a minimum floor).
_POST_COMPACTION_TARGET = 0.55

# Keep at least the last N non-system messages un-compacted
_MIN_RECENT_MESSAGES = 4

COMPACTION_PROMPT = """\
You are creating a continuity summary for an ongoing network automation chat.

Write a compact summary that preserves high-value context needed for future turns:
- Confirmed facts and current state
- Decisions made and why
- Open questions, unresolved issues, and pending action items
- Errors/failures, troubleshooting done, and outcomes
- Concrete identifiers and values (site names, AP names, SSIDs, VLAN IDs,
  IPs/subnets, object IDs, workflow/report names, tool outputs)

Requirements:
- Do not invent information.
- Keep specific names/IDs/numbers exactly when present.
- Prefer concise bullets over prose.
- Keep chronology only where it matters for understanding decisions/outcomes.
- Keep the result short but complete enough to continue the conversation safely.

Output only the summary text."""


def _estimate_message_tokens(role: str, content: str, model: str) -> int:
    """Estimate per-message tokens with a lightweight heuristic.

    We intentionally avoid calling the tokenizer per message here because
    cutoff selection may scan many messages. This budget estimate only guides
    recent-turn selection; final prompt/token accounting still uses real counts.
    """
    del model  # kept for call-site compatibility
    # Rough token approximation for English-like text: ~4 chars/token.
    # Add a small fixed overhead for role/wrapper metadata.
    return max(1, (len(content) // 4) + 4 + (1 if role == "assistant" else 0))


def _select_cutoff_index(thread, start_index: int, context_window: int, model: str) -> int | None:
    """Pick a cutoff index that keeps recent messages within a token budget.

    Keeps at least `_MIN_RECENT_MESSAGES` non-system turns, and then keeps more
    only while the recent-message token budget allows.

    The budget is derived from threshold-target delta, not a hard post-
    compaction token limit. This makes `_POST_COMPACTION_TARGET` a tuning knob
    for aggressiveness rather than a strict ratio guarantee.
    """
    non_system_indices = [i for i, m in enumerate(thread.messages) if m.role != "system" and i >= start_index]
    if len(non_system_indices) <= _MIN_RECENT_MESSAGES:
        return None

    recent_budget = int(round(context_window * (_COMPACTION_THRESHOLD - _POST_COMPACTION_TARGET)))
    recent_budget = max(recent_budget, 1)

    keep_indices: list[int] = []
    recent_tokens = 0
    for idx in reversed(non_system_indices):
        msg = thread.messages[idx]
        msg_tokens = _estimate_message_tokens(msg.role, msg.content, model)
        if len(keep_indices) < _MIN_RECENT_MESSAGES:
            keep_indices.append(idx)
            recent_tokens += msg_tokens
            continue
        if recent_tokens + msg_tokens <= recent_budget:
            keep_indices.append(idx)
            recent_tokens += msg_tokens
            continue
        break

    if not keep_indices:
        return None
    cutoff_index = min(keep_indices)
    if cutoff_index <= start_index:
        return None
    return cutoff_index


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
        oid = PydanticObjectId(thread_id)
    except Exception:
        logger.warning("compaction_invalid_thread_id", thread_id=thread_id)
        return

    # Atomic lock acquisition — prevents concurrent compaction on the same thread
    result = await ConversationThread.get_motor_collection().find_one_and_update(
        {"_id": oid, "compaction_in_progress": {"$ne": True}},
        {"$set": {"compaction_in_progress": True}},
    )
    if not result:
        logger.info("compaction_skipped", thread_id=thread_id)
        return

    thread = await ConversationThread.get(oid)
    if not thread:
        return

    # Check if compaction is actually needed
    all_messages = [{"role": m.role, "content": m.content} for m in thread.messages]
    token_count = count_message_tokens(all_messages, llm.model)
    threshold = int(context_window * _COMPACTION_THRESHOLD)

    if token_count <= threshold:
        logger.debug("compaction_not_needed", thread_id=thread_id, tokens=token_count, threshold=threshold)
        await _release_lock(oid)
        return

    summary = None
    cutoff_index = None
    try:
        # Incremental compaction: only summarize messages not already compacted.
        # On first compaction, skip the first user message because
        # ConversationThread._get_compacted_messages() preserves it raw.
        if thread.compacted_up_to_index is not None:
            start_index = thread.compacted_up_to_index
        else:
            first_user_idx = next((i for i, m in enumerate(thread.messages) if m.role == "user"), None)
            start_index = max(1, first_user_idx + 1) if first_user_idx is not None else 1

        cutoff_index = _select_cutoff_index(thread, start_index, context_window, llm.model)
        if cutoff_index is None:
            logger.info("compaction_too_few_messages", thread_id=thread_id, start_index=start_index)
            return

        # Gather messages to summarize (non-system messages from start_index to cutoff)
        messages_to_summarize = []
        for m in thread.messages[start_index:cutoff_index]:  # Skip system prompt (index 0)
            if m.role != "system":
                messages_to_summarize.append(f"{m.role}: {_sanitize_for_prompt(m.content, max_len=500)}")

        if not messages_to_summarize:
            return

        conversation_text = "\n".join(messages_to_summarize)

        existing_summary = (thread.compaction_summary or "").strip()
        if existing_summary:
            summary_input = (
                "Existing continuity summary (preserve still-valid context):\n"
                f"{existing_summary}\n\n"
                "New conversation messages to merge:\n"
                f"{conversation_text}"
            )
        else:
            summary_input = conversation_text

        # Call LLM to summarize
        summary_messages = [
            LLMMessage(role="system", content=COMPACTION_PROMPT),
            LLMMessage(role="user", content=summary_input),
        ]
        response = await llm.complete(summary_messages)
        summary = response.content.strip()

        if not summary:
            logger.warning("compaction_empty_summary", thread_id=thread_id)
            return

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
        # Atomic update — never overwrites messages added by concurrent chat requests
        update: dict = {"compaction_in_progress": False}
        if summary and cutoff_index is not None:
            update["compaction_summary"] = summary
            update["compacted_up_to_index"] = cutoff_index
        await ConversationThread.get_motor_collection().update_one(
            {"_id": oid}, {"$set": update}
        )


async def _release_lock(oid: PydanticObjectId) -> None:
    """Release the compaction lock via atomic $set."""
    from app.modules.llm.models import ConversationThread

    await ConversationThread.get_motor_collection().update_one(
        {"_id": oid}, {"$set": {"compaction_in_progress": False}}
    )
