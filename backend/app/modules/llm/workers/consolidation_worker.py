"""
Memory consolidation worker — the "dreaming" feature.

Periodically reviews per-user memory entries via LLM and consolidates them:
merges duplicates, removes contradictions, and cleans up resolved entries.
"""

import json
from datetime import datetime, timezone

import structlog

from app.modules.llm.models import LLMUsageLog, MemoryConsolidationLog, MemoryEntry
from app.modules.llm.services.llm_service import LLMMessage

logger = structlog.get_logger(__name__)

CONSOLIDATION_PROMPT = """\
You are a memory manager. Below are stored facts for a user of a network automation platform.
Review and consolidate:
- Merge entries that describe the same topic into one (combine key + value)
- Delete entries that contradict newer ones (keep the newer fact)
- Delete entries that describe clearly resolved situations (e.g. "fixed on <date>", "workaround applied")
- Keep everything else unchanged

For each entry, return a JSON action:
{action: "keep"|"merge"|"delete", keys: [...], new_key: "...", new_value: "...", reason: "..."}

IMPORTANT: Every input key must appear in exactly one action. Return valid JSON only.
"""


async def run_consolidation() -> None:
    """Run memory consolidation for all users with enough entries."""
    from app.models.system import SystemConfig
    from app.modules.llm.services.llm_service_factory import create_llm_service

    # Check if LLM and consolidation are enabled
    config = await SystemConfig.get_config()
    if not config.llm_enabled:
        return
    if not getattr(config, "memory_consolidation_enabled", True):
        return

    # Try to create LLM service — skip silently if no default config
    try:
        llm = await create_llm_service()
    except Exception:
        return

    # Find all users with 10+ memory entries
    pipeline = [
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gte": 10}}},
    ]
    user_counts = await MemoryEntry.aggregate(pipeline).to_list()

    if not user_counts:
        logger.info("memory_consolidation_no_eligible_users")
        return

    logger.info("memory_consolidation_starting", user_count=len(user_counts))

    for entry in user_counts:
        user_id = entry["_id"]
        try:
            await _consolidate_user(user_id, llm, config.memory_entry_max_length)
        except Exception as e:
            logger.error("memory_consolidation_user_failed", user_id=str(user_id), error=str(e))

    logger.info("memory_consolidation_complete", user_count=len(user_counts))


async def _consolidate_user(user_id, llm, max_value_length: int = 500) -> None:
    """Consolidate memory entries for a single user."""
    # Load all entries sorted by updated_at
    entries = await MemoryEntry.find(MemoryEntry.user_id == user_id).sort("+updated_at").to_list()

    if not entries:
        return

    entries_before = len(entries)

    # Build a lookup by key for quick access
    entry_map: dict[str, MemoryEntry] = {e.key: e for e in entries}

    # Build the prompt with all entries
    entry_lines = []
    for e in entries:
        updated_str = e.updated_at.strftime("%Y-%m-%d") if e.updated_at else "unknown"
        entry_lines.append(f"- key={e.key}, value={e.value}, category={e.category}, updated={updated_str}")

    entries_text = "\n".join(entry_lines)

    messages = [
        LLMMessage(role="system", content=CONSOLIDATION_PROMPT),
        LLMMessage(role="user", content=f"Here are the memory entries:\n\n{entries_text}"),
    ]

    # Call LLM with JSON mode
    response = await llm.complete(messages, json_mode=True)

    # Parse response
    try:
        actions = json.loads(response.content)
    except json.JSONDecodeError:
        logger.error("memory_consolidation_invalid_json", user_id=str(user_id))
        return

    if not isinstance(actions, list):
        logger.error("memory_consolidation_unexpected_format", user_id=str(user_id))
        return

    # Apply actions
    applied_actions = []
    for action in actions:
        action_type = action.get("action")
        keys = action.get("keys", [])
        reason = action.get("reason", "")

        try:
            if action_type == "keep":
                # Touch updated_at to reset TTL
                for key in keys:
                    entry = entry_map.get(key)
                    if entry:
                        entry.updated_at = datetime.now(timezone.utc)
                        await entry.save()
                applied_actions.append({"action": "keep", "keys": keys, "reason": reason})

            elif action_type == "merge":
                new_key = action.get("new_key", "")
                new_value = action.get("new_value", "")[:max_value_length]
                if not new_key or not new_value:
                    logger.warning("memory_consolidation_merge_missing_fields", user_id=str(user_id), keys=keys)
                    continue

                # Upsert the merged entry
                existing = await MemoryEntry.find_one(
                    MemoryEntry.user_id == user_id,
                    MemoryEntry.key == new_key,
                )
                if existing:
                    existing.value = new_value
                    existing.updated_at = datetime.now(timezone.utc)
                    await existing.save()
                else:
                    # Use category from first original entry if available
                    category = "general"
                    for key in keys:
                        orig = entry_map.get(key)
                        if orig:
                            category = orig.category
                            break
                    new_entry = MemoryEntry(
                        user_id=user_id,
                        key=new_key,
                        value=new_value,
                        category=category,
                    )
                    await new_entry.insert()

                # Delete originals (except if one of them IS the new_key)
                for key in keys:
                    if key != new_key:
                        orig = entry_map.get(key)
                        if orig:
                            await orig.delete()

                applied_actions.append(
                    {"action": "merge", "keys": keys, "new_key": new_key, "new_value": new_value, "reason": reason}
                )

            elif action_type == "delete":
                for key in keys:
                    entry = entry_map.get(key)
                    if entry:
                        await entry.delete()
                applied_actions.append({"action": "delete", "keys": keys, "reason": reason})

        except Exception as e:
            logger.error(
                "memory_consolidation_action_failed",
                user_id=str(user_id),
                action=action_type,
                keys=keys,
                error=str(e),
            )

    # Count entries after consolidation
    entries_after = await MemoryEntry.find(MemoryEntry.user_id == user_id).count()

    # Save consolidation log
    await MemoryConsolidationLog(
        user_id=user_id,
        entries_before=entries_before,
        entries_after=entries_after,
        actions=applied_actions,
        llm_model=response.model,
        llm_tokens_used=response.usage.total_tokens,
    ).insert()

    # Log LLM usage
    await LLMUsageLog(
        user_id=user_id,
        feature="memory_dreaming",
        model=response.model,
        provider=llm.provider,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        total_tokens=response.usage.total_tokens,
        duration_ms=response.duration_ms,
    ).insert()

    logger.info(
        "memory_consolidation_user_done",
        user_id=str(user_id),
        entries_before=entries_before,
        entries_after=entries_after,
        actions_count=len(applied_actions),
    )
