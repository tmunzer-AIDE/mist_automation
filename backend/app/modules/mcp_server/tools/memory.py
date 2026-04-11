"""
Memory tools — store, recall, and forget user memories via MCP.

Internal helper functions are designed to be testable without MCP.
"""

from datetime import datetime, timezone
from typing import Annotated

import structlog
from beanie import PydanticObjectId
from fastmcp.exceptions import ToolError
from pydantic import Field

from app.modules.mcp_server.server import mcp, mcp_thread_id_var, mcp_user_id_var
from app.modules.mcp_server.tools.utils import is_placeholder

logger = structlog.get_logger(__name__)

VALID_CATEGORIES = {"general", "network", "preference", "troubleshooting"}

# Defaults — overridden by SystemConfig when memory settings exist (Task 4)
_DEFAULT_MAX_KEY_LENGTH = 100
_DEFAULT_MAX_VALUE_LENGTH = 500
_DEFAULT_MAX_ENTRIES_PER_USER = 100


async def _get_memory_config() -> tuple[int, int]:
    """Return (max_entries_per_user, max_value_length) from SystemConfig with defaults."""
    try:
        from app.models.system import SystemConfig

        config = await SystemConfig.get_config()
        return (
            getattr(config, "memory_max_entries_per_user", _DEFAULT_MAX_ENTRIES_PER_USER)
            or _DEFAULT_MAX_ENTRIES_PER_USER,
            getattr(config, "memory_entry_max_length", _DEFAULT_MAX_VALUE_LENGTH) or _DEFAULT_MAX_VALUE_LENGTH,
        )
    except Exception:
        return _DEFAULT_MAX_ENTRIES_PER_USER, _DEFAULT_MAX_VALUE_LENGTH


async def _store_memory(
    user_id: str,
    key: str,
    value: str,
    category: str,
    thread_id: str | None,
) -> str:
    """Store or update a memory entry for the user."""
    from app.modules.llm.models import MemoryEntry

    max_entries, max_value_len = await _get_memory_config()

    normalized_key = key.strip()
    normalized_value = value.strip()
    normalized_category = category.strip().lower()

    if not normalized_key:
        raise ToolError("key is required")
    if is_placeholder(normalized_key):
        raise ToolError("key must not contain unresolved placeholders")
    if not normalized_value:
        raise ToolError("value is required")
    if normalized_category not in VALID_CATEGORIES:
        raise ToolError(
            f"Invalid category '{category}'. Use: {', '.join(sorted(VALID_CATEGORIES))}"
        )

    # Validate key length (not admin-configurable, fixed at 100)
    if len(normalized_key) > _DEFAULT_MAX_KEY_LENGTH:
        raise ToolError(
            f"Key too long: maximum {_DEFAULT_MAX_KEY_LENGTH} characters, got {len(normalized_key)}"
        )

    # Validate value length
    if len(normalized_value) > max_value_len:
        raise ToolError(
            f"Value too long: maximum {max_value_len} characters, got {len(normalized_value)}"
        )

    try:
        uid = PydanticObjectId(user_id)
    except Exception as exc:
        raise ToolError("Invalid user context") from exc

    # Check if key already exists for this user → upsert
    existing = await MemoryEntry.find_one(
        MemoryEntry.user_id == uid,
        MemoryEntry.key == normalized_key,
    )

    if existing:
        existing.value = normalized_value
        existing.category = normalized_category
        existing.source_thread_id = thread_id
        existing.updated_at = datetime.now(timezone.utc)
        await existing.save()
        return f"Memory '{normalized_key}' updated."

    # New entry — check per-user cap
    count = await MemoryEntry.find(MemoryEntry.user_id == uid).count()
    if count >= max_entries:
        raise ToolError(
            f"Memory limit reached ({max_entries} entries). Delete old memories before storing new ones."
        )

    entry = MemoryEntry(
        user_id=uid,
        key=normalized_key,
        value=normalized_value,
        category=normalized_category,
        source_thread_id=thread_id,
    )
    await entry.insert()
    return f"Memory '{normalized_key}' stored."


async def _recall_memory(
    user_id: str,
    query: str | None,
    category: str | None,
) -> str:
    """Search or list user memories. Returns formatted text."""
    from app.modules.llm.models import MemoryEntry

    try:
        uid = PydanticObjectId(user_id)
    except Exception as exc:
        raise ToolError("Invalid user context") from exc

    normalized_query = (query or "").strip()
    normalized_category = (category or "").strip().lower()

    if normalized_category and normalized_category not in VALID_CATEGORIES:
        raise ToolError(
            f"Invalid category '{category}'. Use: {', '.join(sorted(VALID_CATEGORIES))}"
        )

    max_results = 30

    if normalized_query:
        # MongoDB text search on key+value, filtered by user_id
        filters: dict = {"user_id": uid, "$text": {"$search": normalized_query}}
        if normalized_category:
            filters["category"] = normalized_category
        entries = await MemoryEntry.find(filters).sort([("score", {"$meta": "textScore"})]).limit(max_results).to_list()
    elif normalized_category:
        entries = (
            await MemoryEntry.find(
                MemoryEntry.user_id == uid,
                MemoryEntry.category == normalized_category,
            )
            .sort(-MemoryEntry.updated_at)
            .limit(max_results)
            .to_list()
        )
    else:
        # Most recent 20 entries
        entries = await MemoryEntry.find(MemoryEntry.user_id == uid).sort(-MemoryEntry.updated_at).limit(20).to_list()

    if not entries:
        return "No memories found."

    lines = []
    for e in entries:
        updated = e.updated_at.strftime("%Y-%m-%d") if e.updated_at else "unknown"
        lines.append(f"- {e.key}: {e.value} ({e.category}, updated {updated})")

    return "\n".join(lines)


async def _forget_memory(user_id: str, key: str) -> str:
    """Delete a specific memory by exact key match."""
    from app.modules.llm.models import MemoryEntry

    try:
        uid = PydanticObjectId(user_id)
    except Exception as exc:
        raise ToolError("Invalid user context") from exc

    normalized_key = key.strip()
    if not normalized_key:
        raise ToolError("key is required")
    if is_placeholder(normalized_key):
        raise ToolError("key must not contain unresolved placeholders")

    entry = await MemoryEntry.find_one(
        MemoryEntry.user_id == uid,
        MemoryEntry.key == normalized_key,
    )

    if not entry:
        raise ToolError(f"No memory found with key: {normalized_key}")

    await entry.delete()
    return f"Memory '{normalized_key}' deleted."


# ---------------------------------------------------------------------------
# MCP tool registrations
# ---------------------------------------------------------------------------


@mcp.tool()
async def memory_store(
    key: Annotated[
        str,
        Field(
            description=(
                "Short unique label for this memory (max 100 chars). "
                "WARNING: if a memory with this key already exists, it will be overwritten."
            ),
        ),
    ],
    value: Annotated[
        str,
        Field(description="The fact or information to remember (max 500 chars)."),
    ],
    category: Annotated[
        str,
        Field(
            description=(
                "Category for this memory. Must be one of: general, network, preference, troubleshooting."
            ),
        ),
    ] = "general",
) -> str:
    """Save a fact to the user's personal memory store. Memories persist across conversations."""
    user_id = mcp_user_id_var.get()
    if not user_id:
        raise ToolError("User context not available")
    thread_id = mcp_thread_id_var.get()
    return await _store_memory(user_id, key, value, category, thread_id)


@mcp.tool()
async def memory_recall(
    query: Annotated[
        str,
        Field(description="Text to search for across memory keys and values. Leave empty to list recent memories."),
    ] = "",
    category: Annotated[
        str,
        Field(
            description=(
                "Filter by category: general, network, preference, troubleshooting. " "Leave empty for all categories."
            ),
        ),
    ] = "",
) -> str:
    """Search the user's personal memory store."""
    user_id = mcp_user_id_var.get()
    if not user_id:
        raise ToolError("User context not available")
    return await _recall_memory(user_id, query or None, category or None)


@mcp.tool()
async def memory_forget(
    key: Annotated[
        str,
        Field(description="The exact key of the memory to delete."),
    ],
) -> str:
    """Delete a specific memory by its exact key."""
    user_id = mcp_user_id_var.get()
    if not user_id:
        raise ToolError("User context not available")
    return await _forget_memory(user_id, key)
