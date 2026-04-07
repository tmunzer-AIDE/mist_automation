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
        # Determine cutoff: keep the last _MIN_RECENT_MESSAGES non-system messages
        non_system_indices = [i for i, m in enumerate(thread.messages) if m.role != "system"]
        if len(non_system_indices) <= _MIN_RECENT_MESSAGES:
            logger.info("compaction_too_few_messages", thread_id=thread_id)
            return

        # Cutoff: compact everything before the last _MIN_RECENT_MESSAGES non-system msgs
        cutoff_index = non_system_indices[-_MIN_RECENT_MESSAGES]

        # Gather messages to summarize (non-system messages from index 0 to cutoff)
        messages_to_summarize = []
        for m in thread.messages[1:cutoff_index]:  # Skip system prompt (index 0)
            if m.role != "system":
                messages_to_summarize.append(f"{m.role}: {_sanitize_for_prompt(m.content, max_len=500)}")

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
