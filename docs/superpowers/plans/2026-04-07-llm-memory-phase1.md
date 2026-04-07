# LLM Memory System — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent per-user memory to the LLM chat system — MCP tools for store/recall/forget, periodic dreaming consolidation, profile page management, admin config and consolidation logs.

**Architecture:** New `MemoryEntry` and `MemoryConsolidationLog` Beanie documents. Three MCP tools on the local server (`memory_store`, `memory_recall`, `memory_forget`). Memory instruction injected into system prompt for interactive chat contexts. APScheduler weekly dreaming job. User management in profile page, admin consolidation logs view.

**Tech Stack:** Python/FastAPI, Beanie/MongoDB, FastMCP, APScheduler, Angular 21 (standalone components, signals, Material)

**Spec:** `docs/superpowers/specs/2026-04-07-llm-memory-system-design.md`

---

### Task 1: MemoryEntry and MemoryConsolidationLog Models

**Files:**
- Modify: `backend/app/modules/llm/models.py` (add after line 170)
- Modify: `backend/app/modules/__init__.py:126-134` (register new models)
- Test: `backend/tests/unit/test_memory_models.py`

- [ ] **Step 1: Write failing tests for MemoryEntry CRUD**

```python
# backend/tests/unit/test_memory_models.py
"""Unit tests for LLM memory models."""

from datetime import datetime, timezone

import pytest

from app.modules.llm.models import MemoryEntry, MemoryConsolidationLog


@pytest.mark.unit
class TestMemoryEntry:
    """Test MemoryEntry document operations."""

    async def test_create_memory_entry(self, test_db, test_user):
        entry = MemoryEntry(
            user_id=test_user.id,
            key="site_paris_vlan200",
            value="DHCP relay misconfigured on VLAN 200",
            category="troubleshooting",
            source_thread_id="thread_abc",
        )
        await entry.insert()
        assert entry.id is not None
        assert entry.key == "site_paris_vlan200"
        assert entry.category == "troubleshooting"

    async def test_unique_key_per_user(self, test_db, test_user):
        await MemoryEntry(
            user_id=test_user.id,
            key="duplicate_key",
            value="first value",
        ).insert()
        with pytest.raises(Exception):  # DuplicateKeyError
            await MemoryEntry(
                user_id=test_user.id,
                key="duplicate_key",
                value="second value",
            ).insert()

    async def test_default_category(self, test_db, test_user):
        entry = MemoryEntry(
            user_id=test_user.id,
            key="some_key",
            value="some value",
        )
        await entry.insert()
        assert entry.category == "general"

    async def test_text_search(self, test_db, test_user):
        await MemoryEntry(
            user_id=test_user.id,
            key="dhcp_issue",
            value="DHCP relay broken on VLAN 200",
        ).insert()
        await MemoryEntry(
            user_id=test_user.id,
            key="ap_template",
            value="Prefer AP43 for offices",
        ).insert()
        # Text search for "DHCP"
        results = await MemoryEntry.find(
            {"user_id": test_user.id, "$text": {"$search": "DHCP"}},
        ).to_list()
        assert len(results) == 1
        assert results[0].key == "dhcp_issue"


@pytest.mark.unit
class TestMemoryConsolidationLog:
    """Test MemoryConsolidationLog document."""

    async def test_create_consolidation_log(self, test_db, test_user):
        log = MemoryConsolidationLog(
            user_id=test_user.id,
            run_at=datetime.now(timezone.utc),
            entries_before=15,
            entries_after=10,
            actions=[
                {
                    "action": "merge",
                    "keys": ["key1", "key2"],
                    "new_key": "merged_key",
                    "new_value": "merged value",
                    "reason": "Same topic",
                },
                {
                    "action": "delete",
                    "keys": ["old_key"],
                    "reason": "Resolved issue",
                },
            ],
            llm_model="gpt-4o",
            llm_tokens_used=850,
        )
        await log.insert()
        assert log.id is not None
        assert log.entries_before == 15
        assert len(log.actions) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/unit/test_memory_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'MemoryEntry'`

- [ ] **Step 3: Create the MemoryEntry model**

Add to `backend/app/modules/llm/models.py` after the `Skill` class (after line 170):

```python
class MemoryEntry(TimestampMixin, Document):
    """A single user memory entry, stored and managed by the LLM."""

    user_id: PydanticObjectId = Field(..., description="User who owns this memory")
    key: str = Field(..., max_length=100, description="Short unique label")
    value: str = Field(..., max_length=500, description="Memory content")
    category: str = Field(default="general", description="Category: general, network, preference, troubleshooting")
    source_thread_id: str | None = Field(default=None, description="Conversation that created this entry")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "memory_entries"
        indexes = [
            IndexModel([("user_id", 1), ("key", 1)], unique=True),
            IndexModel([("user_id", 1), ("category", 1)]),
            IndexModel([("updated_at", 1)], expireAfterSeconds=180 * 24 * 3600),
            IndexModel([("user_id", 1), ("key", "text"), ("value", "text")]),
        ]


class MemoryConsolidationLog(Document):
    """Audit log for periodic memory consolidation (dreaming)."""

    user_id: PydanticObjectId = Field(..., description="User whose memories were consolidated")
    run_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    entries_before: int = Field(..., description="Entry count before consolidation")
    entries_after: int = Field(..., description="Entry count after consolidation")
    actions: list[dict] = Field(default_factory=list, description="Consolidation actions with reasoning")
    llm_model: str = Field(default="", description="LLM model used for consolidation")
    llm_tokens_used: int = Field(default=0, description="Tokens consumed")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "memory_consolidation_logs"
        indexes = [
            IndexModel([("user_id", 1), ("run_at", -1)]),
            IndexModel([("created_at", 1)], expireAfterSeconds=365 * 24 * 3600),
        ]
```

- [ ] **Step 4: Register models in module registry**

In `backend/app/modules/__init__.py`, add to the `llm` module's `model_imports` list (around line 131):

```python
        ("app.modules.llm.models", "MemoryEntry"),
        ("app.modules.llm.models", "MemoryConsolidationLog"),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/unit/test_memory_models.py -v`
Expected: PASS — all 4 tests green

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/llm/models.py backend/app/modules/__init__.py backend/tests/unit/test_memory_models.py
git commit -m "feat(memory): add MemoryEntry and MemoryConsolidationLog models"
```

---

### Task 2: Memory MCP Tools

**Files:**
- Create: `backend/app/modules/mcp_server/tools/memory.py`
- Modify: `backend/app/modules/mcp_server/server.py:26` (import new tool module)
- Test: `backend/tests/unit/test_memory_mcp_tools.py`

- [ ] **Step 1: Write failing tests for memory tools**

```python
# backend/tests/unit/test_memory_mcp_tools.py
"""Unit tests for memory MCP tools."""

import pytest

from app.modules.llm.models import MemoryEntry


@pytest.mark.unit
class TestMemoryStore:
    """Test memory_store MCP tool logic."""

    async def test_store_new_entry(self, test_db, test_user):
        from app.modules.mcp_server.tools.memory import _store_memory

        result = await _store_memory(
            user_id=str(test_user.id),
            key="test_key",
            value="test value",
            category="general",
            thread_id="thread_1",
        )
        assert "Stored memory" in result
        entry = await MemoryEntry.find_one({"user_id": test_user.id, "key": "test_key"})
        assert entry is not None
        assert entry.value == "test value"

    async def test_store_upsert_existing(self, test_db, test_user):
        from app.modules.mcp_server.tools.memory import _store_memory

        await _store_memory(str(test_user.id), "upsert_key", "first", "general", None)
        await _store_memory(str(test_user.id), "upsert_key", "second", "general", None)
        entry = await MemoryEntry.find_one({"user_id": test_user.id, "key": "upsert_key"})
        assert entry.value == "second"

    async def test_store_rejects_over_cap(self, test_db, test_user):
        from app.modules.mcp_server.tools.memory import _store_memory

        # Insert 100 entries to fill cap (using default cap of 100)
        for i in range(100):
            await MemoryEntry(
                user_id=test_user.id, key=f"fill_{i}", value=f"value_{i}"
            ).insert()
        result = await _store_memory(str(test_user.id), "overflow", "val", "general", None)
        assert "limit" in result.lower() or "cap" in result.lower()

    async def test_store_validates_key_length(self, test_db, test_user):
        from app.modules.mcp_server.tools.memory import _store_memory

        result = await _store_memory(str(test_user.id), "k" * 101, "val", "general", None)
        assert "100 characters" in result

    async def test_store_validates_value_length(self, test_db, test_user):
        from app.modules.mcp_server.tools.memory import _store_memory

        result = await _store_memory(str(test_user.id), "key", "v" * 501, "general", None)
        assert "500 characters" in result


@pytest.mark.unit
class TestMemoryRecall:
    """Test memory_recall MCP tool logic."""

    async def test_recall_by_query(self, test_db, test_user):
        from app.modules.mcp_server.tools.memory import _recall_memory

        await MemoryEntry(user_id=test_user.id, key="vlan_issue", value="VLAN 200 DHCP broken").insert()
        await MemoryEntry(user_id=test_user.id, key="ap_pref", value="Use AP43 template").insert()
        result = await _recall_memory(str(test_user.id), query="DHCP", category=None)
        assert "vlan_issue" in result
        assert "ap_pref" not in result

    async def test_recall_by_category(self, test_db, test_user):
        from app.modules.mcp_server.tools.memory import _recall_memory

        await MemoryEntry(user_id=test_user.id, key="k1", value="v1", category="network").insert()
        await MemoryEntry(user_id=test_user.id, key="k2", value="v2", category="preference").insert()
        result = await _recall_memory(str(test_user.id), query=None, category="network")
        assert "k1" in result
        assert "k2" not in result

    async def test_recall_recent_no_args(self, test_db, test_user):
        from app.modules.mcp_server.tools.memory import _recall_memory

        await MemoryEntry(user_id=test_user.id, key="recent", value="recent val").insert()
        result = await _recall_memory(str(test_user.id), query=None, category=None)
        assert "recent" in result

    async def test_recall_empty(self, test_db, test_user):
        from app.modules.mcp_server.tools.memory import _recall_memory

        result = await _recall_memory(str(test_user.id), query=None, category=None)
        assert "No memories" in result


@pytest.mark.unit
class TestMemoryForget:
    """Test memory_forget MCP tool logic."""

    async def test_forget_existing(self, test_db, test_user):
        from app.modules.mcp_server.tools.memory import _forget_memory

        await MemoryEntry(user_id=test_user.id, key="to_delete", value="val").insert()
        result = await _forget_memory(str(test_user.id), "to_delete")
        assert "Deleted" in result or "Forgot" in result
        assert await MemoryEntry.find_one({"user_id": test_user.id, "key": "to_delete"}) is None

    async def test_forget_nonexistent(self, test_db, test_user):
        from app.modules.mcp_server.tools.memory import _forget_memory

        result = await _forget_memory(str(test_user.id), "no_such_key")
        assert "No memory found" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/unit/test_memory_mcp_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.mcp_server.tools.memory'`

- [ ] **Step 3: Implement the memory MCP tools**

Create `backend/app/modules/mcp_server/tools/memory.py`:

```python
"""
Memory tools — personal memory store/recall/forget for LLM conversations.
"""

from datetime import datetime, timezone
from typing import Annotated

import structlog
from beanie import PydanticObjectId
from pydantic import Field

from app.modules.mcp_server.server import mcp, mcp_user_id_var

logger = structlog.get_logger(__name__)

_MAX_ENTRIES_PER_USER = 100
_MAX_KEY_LENGTH = 100
_MAX_VALUE_LENGTH = 500
_MAX_RECALL_RESULTS = 30


async def _get_memory_config() -> tuple[int, int]:
    """Return (max_entries, max_value_length) from SystemConfig, with defaults."""
    try:
        from app.models.system import SystemConfig

        config = await SystemConfig.get_config()
        return (
            getattr(config, "memory_max_entries_per_user", _MAX_ENTRIES_PER_USER),
            getattr(config, "memory_entry_max_length", _MAX_VALUE_LENGTH),
        )
    except Exception:
        return _MAX_ENTRIES_PER_USER, _MAX_VALUE_LENGTH


async def _store_memory(
    user_id: str,
    key: str,
    value: str,
    category: str,
    thread_id: str | None,
) -> str:
    """Store or update a memory entry. Returns status message."""
    from app.modules.llm.models import MemoryEntry

    max_entries, max_value_len = await _get_memory_config()

    if len(key) > _MAX_KEY_LENGTH:
        return f"Error: key must be {_MAX_KEY_LENGTH} characters or fewer."
    if len(value) > max_value_len:
        return f"Error: value must be {max_value_len} characters or fewer."
    if category not in ("general", "network", "preference", "troubleshooting"):
        category = "general"

    uid = PydanticObjectId(user_id)
    now = datetime.now(timezone.utc)

    # Check if key already exists (upsert)
    existing = await MemoryEntry.find_one({"user_id": uid, "key": key})
    if existing:
        existing.value = value
        existing.category = category
        if thread_id:
            existing.source_thread_id = thread_id
        existing.updated_at = now
        await existing.save()
        logger.info("memory_updated", user_id=user_id, key=key)
        return f"Stored memory: {key} (updated existing)"

    # Check cap for new entries
    count = await MemoryEntry.find({"user_id": uid}).count()
    if count >= max_entries:
        return (
            f"Memory limit reached ({max_entries} entries). "
            "Delete old entries with memory_forget or wait for automatic consolidation."
        )

    entry = MemoryEntry(
        user_id=uid,
        key=key,
        value=value,
        category=category,
        source_thread_id=thread_id,
        created_at=now,
        updated_at=now,
    )
    await entry.insert()
    logger.info("memory_stored", user_id=user_id, key=key)
    return f"Stored memory: {key}"


async def _recall_memory(user_id: str, query: str | None, category: str | None) -> str:
    """Search or list memory entries. Returns formatted text."""
    from app.modules.llm.models import MemoryEntry

    uid = PydanticObjectId(user_id)
    filters: dict = {"user_id": uid}

    if query:
        filters["$text"] = {"$search": query}
    if category:
        filters["category"] = category

    entries = await MemoryEntry.find(filters).sort(-MemoryEntry.updated_at).limit(_MAX_RECALL_RESULTS).to_list()

    if not entries:
        return "No memories found." + (" Try a different search query." if query else "")

    lines = []
    for e in entries:
        updated = e.updated_at.strftime("%Y-%m-%d") if e.updated_at else "unknown"
        lines.append(f"- {e.key}: {e.value} ({e.category}, updated {updated})")
    return "\n".join(lines)


async def _forget_memory(user_id: str, key: str) -> str:
    """Delete a memory entry by exact key match."""
    from app.modules.llm.models import MemoryEntry

    uid = PydanticObjectId(user_id)
    entry = await MemoryEntry.find_one({"user_id": uid, "key": key})
    if not entry:
        return f"No memory found with key: {key}"
    await entry.delete()
    logger.info("memory_forgotten", user_id=user_id, key=key)
    return f"Forgot memory: {key}"


# ── MCP tool registrations ──────────────────────────────────────────────────


@mcp.tool()
async def memory_store(
    key: Annotated[
        str,
        Field(
            description=(
                "Short unique identifier for this memory (e.g. 'site_paris_dhcp'). "
                "Max 100 characters. WARNING: If this key already exists, the value "
                "will be OVERWRITTEN. Use memory_recall first to check existing keys if unsure."
            ),
        ),
    ],
    value: Annotated[
        str,
        Field(description="The information to remember. Max 500 characters."),
    ],
    category: Annotated[
        str,
        Field(
            description="Category for organization. One of: general, network, preference, troubleshooting.",
        ),
    ] = "general",
) -> str:
    """Save a fact to the user's personal memory store. Memories persist across conversations."""
    user_id = mcp_user_id_var.get()
    if not user_id:
        return "Error: user context not available."
    # Read thread context if available (set by _mcp_user_session in llm.py)
    from app.modules.mcp_server.server import mcp_thread_id_var
    thread_id = mcp_thread_id_var.get()
    return await _store_memory(user_id, key, value, category, thread_id=thread_id)


@mcp.tool()
async def memory_recall(
    query: Annotated[
        str,
        Field(description="Search text to find relevant memories (searches key and value fields)."),
    ] = "",
    category: Annotated[
        str,
        Field(description="Filter by category: general, network, preference, troubleshooting."),
    ] = "",
) -> str:
    """Search the user's personal memory store. Returns matching memories sorted by recency."""
    user_id = mcp_user_id_var.get()
    if not user_id:
        return "Error: user context not available."
    return await _recall_memory(user_id, query=query or None, category=category or None)


@mcp.tool()
async def memory_forget(
    key: Annotated[
        str,
        Field(description="Exact key of the memory to delete."),
    ],
) -> str:
    """Delete a specific memory by its exact key."""
    user_id = mcp_user_id_var.get()
    if not user_id:
        return "Error: user context not available."
    return await _forget_memory(user_id, key)
```

- [ ] **Step 4: Add thread_id ContextVar and register the tool module**

In `backend/app/modules/mcp_server/server.py`, add a new ContextVar after `mcp_user_id_var` (line 13):

```python
mcp_thread_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_thread_id", default=None)
```

Then update line 26 to include the memory import:

```python
from app.modules.mcp_server.tools import backup, details, impact_analysis, memory, search, skills, workflow  # noqa: E402, F401
```

In `backend/app/api/v1/llm.py`, update `_mcp_user_session()` to also set `mcp_thread_id_var`:

```python
from app.modules.mcp_server.server import mcp_user_id_var, mcp_thread_id_var
# ... in the context manager, after setting user token:
token_thread = mcp_thread_id_var.set(thread_id)
# ... in finally: mcp_thread_id_var.reset(token_thread)
```

Pass `thread_id` as a new parameter to `_mcp_user_session()` from the global chat endpoint.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/unit/test_memory_mcp_tools.py -v`
Expected: PASS — all 10 tests green

- [ ] **Step 6: Run all existing tests to check for regressions**

Run: `cd backend && .venv/bin/pytest tests/ -v --timeout=30`
Expected: All existing tests still pass

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/mcp_server/tools/memory.py backend/app/modules/mcp_server/server.py backend/tests/unit/test_memory_mcp_tools.py
git commit -m "feat(memory): add memory_store, memory_recall, memory_forget MCP tools"
```

---

### Task 3: System Prompt Memory Instruction

**Files:**
- Modify: `backend/app/modules/llm/services/prompt_builders.py` (add memory instruction builder)
- Modify: `backend/app/api/v1/llm.py:1546-1557` (inject memory instruction in global chat)
- Test: `backend/tests/unit/test_prompt_builders.py` (add test for new function)

- [ ] **Step 1: Write failing test for memory instruction builder**

Add to `backend/tests/unit/test_prompt_builders.py`:

```python
@pytest.mark.unit
class TestBuildMemoryInstruction:
    """Test build_memory_instruction function."""

    def test_returns_instruction_text(self):
        from app.modules.llm.services.prompt_builders import build_memory_instruction

        result = build_memory_instruction()
        assert "memory_store" in result
        assert "memory_recall" in result
        assert "memory_forget" in result
        assert "OVERWRITTEN" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/test_prompt_builders.py::TestBuildMemoryInstruction -v`
Expected: FAIL — `ImportError: cannot import name 'build_memory_instruction'`

- [ ] **Step 3: Add build_memory_instruction to prompt_builders.py**

Add to `backend/app/modules/llm/services/prompt_builders.py`:

```python
def build_memory_instruction() -> str:
    """Return the system prompt instruction for memory tools."""
    return (
        "You have access to a personal memory store for this user. Use memory_store to save "
        "important facts, preferences, or context that would be useful in future conversations. "
        "Use memory_recall to search for relevant memories before answering questions where "
        "prior context might help. Use memory_forget to remove outdated information. "
        "Only store information that has long-term value — not transient conversation details. "
        "When storing memories, choose descriptive unique keys. Storing with an existing key "
        "replaces the previous value — check with memory_recall first if you want to update "
        "rather than overwrite. Storing with an existing key will OVERWRITE the previous value."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/test_prompt_builders.py::TestBuildMemoryInstruction -v`
Expected: PASS

- [ ] **Step 5: Inject memory instruction in global chat endpoint**

In `backend/app/api/v1/llm.py`, modify the global chat endpoint. After the skills catalog injection (around line 1551), add:

```python
    # Memory instruction (only when memory is enabled)
    from app.models.system import SystemConfig as SysConf
    sys_conf = await SysConf.get_config()
    if getattr(sys_conf, "memory_enabled", True):
        from app.modules.llm.services.prompt_builders import build_memory_instruction
        system_prompt += "\n\n" + build_memory_instruction()
```

Also apply the same pattern in the follow-up/continue endpoint (`_continue_with_mcp` or equivalent) where system prompts are rebuilt for existing threads. Search for other interactive chat endpoints (impact analysis chat, workflow debug) and add the same injection.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/llm/services/prompt_builders.py backend/app/api/v1/llm.py backend/tests/unit/test_prompt_builders.py
git commit -m "feat(memory): inject memory instruction into interactive chat system prompts"
```

---

### Task 4: SystemConfig Memory Settings

**Files:**
- Modify: `backend/app/models/system.py:82-83` (add memory fields after `llm_enabled`)
- Modify: `backend/app/schemas/admin.py` (add memory fields to SystemSettingsUpdate)
- Modify: `backend/app/api/v1/admin.py` (expose memory settings in GET/PUT)

- [ ] **Step 1: Add memory fields to SystemConfig**

In `backend/app/models/system.py`, after `llm_enabled` (line 83), add:

```python
    # LLM Memory Configuration
    memory_enabled: bool = Field(default=True, description="Enable LLM memory tools in chat")
    memory_max_entries_per_user: int = Field(default=100, ge=10, le=500, description="Max memory entries per user")
    memory_entry_max_length: int = Field(default=500, ge=100, le=2000, description="Max chars per memory value")
    memory_consolidation_enabled: bool = Field(default=True, description="Enable periodic memory consolidation")
    memory_consolidation_cron: str = Field(default="0 4 * * 0", description="Consolidation schedule (cron)")
```

- [ ] **Step 2: Add fields to SystemSettingsUpdate schema**

In `backend/app/schemas/admin.py`, add after the LLM section (after line 77):

```python
    # LLM Memory
    memory_enabled: bool | None = None
    memory_max_entries_per_user: int | None = Field(None, ge=10, le=500)
    memory_entry_max_length: int | None = Field(None, ge=100, le=2000)
    memory_consolidation_enabled: bool | None = None
    memory_consolidation_cron: str | None = None
```

Add a validator for the consolidation cron field. Extend the existing `validate_cron` validator to also cover `memory_consolidation_cron`:

```python
    @field_validator("backup_full_schedule_cron", "memory_consolidation_cron")
```

- [ ] **Step 3: Expose memory settings in admin GET/PUT endpoints**

In `backend/app/api/v1/admin.py`, add the memory fields to the `get_system_settings` response dict and to the `update_system_settings` handler. Follow the same pattern used for `impact_analysis_*` fields — straightforward field mapping, no encryption.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/system.py backend/app/schemas/admin.py backend/app/api/v1/admin.py
git commit -m "feat(memory): add memory settings to SystemConfig and admin API"
```

---

### Task 5: Memory User API Endpoints

**Files:**
- Modify: `backend/app/api/v1/llm.py` (add memory CRUD endpoints)
- Test: `backend/tests/unit/test_memory_endpoints.py`

- [ ] **Step 1: Write failing tests for memory endpoints**

```python
# backend/tests/unit/test_memory_endpoints.py
"""Unit tests for user memory API endpoints."""

import pytest


@pytest.mark.unit
class TestMemoryEndpoints:
    """Test /llm/memories endpoints."""

    async def test_list_memories_empty(self, client):
        resp = await client.get("/api/v1/llm/memories")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entries"] == []
        assert data["total"] == 0

    async def test_list_memories_with_entries(self, client, test_user):
        from app.modules.llm.models import MemoryEntry

        await MemoryEntry(user_id=test_user.id, key="k1", value="v1").insert()
        await MemoryEntry(user_id=test_user.id, key="k2", value="v2", category="network").insert()
        resp = await client.get("/api/v1/llm/memories")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["entries"]) == 2

    async def test_list_filter_by_category(self, client, test_user):
        from app.modules.llm.models import MemoryEntry

        await MemoryEntry(user_id=test_user.id, key="k1", value="v1", category="network").insert()
        await MemoryEntry(user_id=test_user.id, key="k2", value="v2", category="preference").insert()
        resp = await client.get("/api/v1/llm/memories?category=network")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_update_memory(self, client, test_user):
        from app.modules.llm.models import MemoryEntry

        entry = MemoryEntry(user_id=test_user.id, key="k1", value="old")
        await entry.insert()
        resp = await client.put(f"/api/v1/llm/memories/{entry.id}", json={"value": "new", "category": "network"})
        assert resp.status_code == 200
        assert resp.json()["value"] == "new"

    async def test_delete_memory(self, client, test_user):
        from app.modules.llm.models import MemoryEntry

        entry = MemoryEntry(user_id=test_user.id, key="k1", value="v1")
        await entry.insert()
        resp = await client.delete(f"/api/v1/llm/memories/{entry.id}")
        assert resp.status_code == 200
        assert await MemoryEntry.get(entry.id) is None

    async def test_delete_all_memories(self, client, test_user):
        from app.modules.llm.models import MemoryEntry

        await MemoryEntry(user_id=test_user.id, key="k1", value="v1").insert()
        await MemoryEntry(user_id=test_user.id, key="k2", value="v2").insert()
        resp = await client.delete("/api/v1/llm/memories?confirm=true")
        assert resp.status_code == 200
        count = await MemoryEntry.find({"user_id": test_user.id}).count()
        assert count == 0

    async def test_delete_all_requires_confirm(self, client):
        resp = await client.delete("/api/v1/llm/memories")
        assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/unit/test_memory_endpoints.py -v`
Expected: FAIL — 404 (endpoints don't exist yet)

- [ ] **Step 3: Implement memory endpoints in llm.py**

Add to `backend/app/api/v1/llm.py`:

```python
# ── User Memory Management ──────────────────────────────────────────────────


@router.get("/llm/memories", tags=["LLM"])
async def list_user_memories(
    category: str | None = None,
    search: str | None = None,
    current_user: User = Depends(get_current_user_from_token),
):
    """List the current user's memory entries."""
    from app.modules.llm.models import MemoryEntry

    filters: dict = {"user_id": current_user.id}
    if category:
        filters["category"] = category
    if search:
        filters["$text"] = {"$search": search}

    entries = await MemoryEntry.find(filters).sort(-MemoryEntry.updated_at).to_list()
    total = len(entries)

    return {
        "entries": [
            {
                "id": str(e.id),
                "key": e.key,
                "value": e.value,
                "category": e.category,
                "source_thread_id": e.source_thread_id,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "updated_at": e.updated_at.isoformat() if e.updated_at else None,
            }
            for e in entries
        ],
        "total": total,
    }


@router.get("/llm/memories/{memory_id}", tags=["LLM"])
async def get_user_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user_from_token),
):
    """Get a single memory entry."""
    from beanie import PydanticObjectId
    from app.modules.llm.models import MemoryEntry

    try:
        entry = await MemoryEntry.get(PydanticObjectId(memory_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid memory ID") from None
    if not entry or entry.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {
        "id": str(entry.id),
        "key": entry.key,
        "value": entry.value,
        "category": entry.category,
        "source_thread_id": entry.source_thread_id,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }


@router.put("/llm/memories/{memory_id}", tags=["LLM"])
async def update_user_memory(
    memory_id: str,
    body: dict,
    current_user: User = Depends(get_current_user_from_token),
):
    """Update a memory entry's value or category."""
    from beanie import PydanticObjectId
    from app.modules.llm.models import MemoryEntry

    try:
        entry = await MemoryEntry.get(PydanticObjectId(memory_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid memory ID") from None
    if not entry or entry.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Memory not found")

    if "value" in body:
        if len(body["value"]) > 500:
            raise HTTPException(status_code=400, detail="Value must be 500 characters or fewer")
        entry.value = body["value"]
    if "category" in body:
        if body["category"] not in ("general", "network", "preference", "troubleshooting"):
            raise HTTPException(status_code=400, detail="Invalid category")
        entry.category = body["category"]
    entry.updated_at = datetime.now(timezone.utc)
    await entry.save()
    return {
        "id": str(entry.id),
        "key": entry.key,
        "value": entry.value,
        "category": entry.category,
        "updated_at": entry.updated_at.isoformat(),
    }


@router.delete("/llm/memories/{memory_id}", tags=["LLM"])
async def delete_user_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user_from_token),
):
    """Delete a single memory entry."""
    from beanie import PydanticObjectId
    from app.modules.llm.models import MemoryEntry

    try:
        entry = await MemoryEntry.get(PydanticObjectId(memory_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid memory ID") from None
    if not entry or entry.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Memory not found")
    await entry.delete()
    return {"status": "deleted", "key": entry.key}


@router.delete("/llm/memories", tags=["LLM"])
async def delete_all_user_memories(
    confirm: bool = False,
    current_user: User = Depends(get_current_user_from_token),
):
    """Delete all memory entries for the current user. Requires confirm=true."""
    from app.modules.llm.models import MemoryEntry

    if not confirm:
        raise HTTPException(status_code=400, detail="Pass confirm=true to delete all memories")
    result = await MemoryEntry.find({"user_id": current_user.id}).delete()
    deleted = result.deleted_count if result else 0
    return {"status": "deleted", "count": deleted}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/unit/test_memory_endpoints.py -v`
Expected: PASS — all 8 tests green

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/llm.py backend/tests/unit/test_memory_endpoints.py
git commit -m "feat(memory): add user memory CRUD endpoints (GET/PUT/DELETE /llm/memories)"
```

---

### Task 6: Dreaming Consolidation Worker

**Files:**
- Create: `backend/app/modules/llm/workers/consolidation_worker.py`
- Modify: `backend/app/modules/automation/workers/scheduler.py:51-77` (register dreaming job)

- [ ] **Step 1: Create the consolidation worker**

Create `backend/app/modules/llm/workers/__init__.py` (empty).

Create `backend/app/modules/llm/workers/consolidation_worker.py`:

```python
"""
Memory consolidation worker — periodic 'dreaming' that merges, deduplicates,
and cleans up per-user memory entries via LLM.
"""

import json
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger(__name__)

_CONSOLIDATION_PROMPT = """\
You are a memory manager. Below are stored facts for a user of a network automation platform.
Review and consolidate:
- Merge entries that describe the same topic into one (combine key + value)
- Delete entries that contradict newer ones (keep the newer fact)
- Delete entries that describe clearly resolved situations (e.g. "fixed on <date>", "workaround applied")
- Keep everything else unchanged

Return a JSON array of actions. Each action:
{"action": "keep" | "merge" | "delete", "keys": ["key1", ...], "new_key": "...", "new_value": "...", "reason": "..."}

For "keep": keys is a single-element list, no new_key/new_value needed.
For "merge": keys lists all entries being merged, new_key and new_value are the consolidated result.
For "delete": keys lists entries to remove, reason explains why.

IMPORTANT: Every input key must appear in exactly one action. Return valid JSON only.

Current memories:
"""


async def run_consolidation() -> None:
    """Run memory consolidation for all eligible users."""
    from beanie import PydanticObjectId

    from app.models.system import SystemConfig
    from app.modules.llm.models import LLMUsageLog, MemoryConsolidationLog, MemoryEntry
    from app.modules.llm.services.llm_service import LLMMessage
    from app.modules.llm.services.llm_service_factory import create_llm_service

    config = await SystemConfig.get_config()
    if not config.llm_enabled or not getattr(config, "memory_consolidation_enabled", True):
        logger.info("memory_consolidation_skipped", reason="disabled")
        return

    try:
        llm = await create_llm_service()
    except Exception as e:
        logger.error("memory_consolidation_no_llm", error=str(e))
        return

    # Find users with 10+ entries
    pipeline = [
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gte": 10}}},
    ]
    user_counts = await MemoryEntry.aggregate(pipeline).to_list()

    for uc in user_counts:
        user_id = uc["_id"]
        try:
            await _consolidate_user(user_id, llm)
        except Exception as e:
            logger.error("memory_consolidation_user_failed", user_id=str(user_id), error=str(e))


async def _consolidate_user(user_id, llm) -> None:
    """Consolidate memories for a single user."""
    from app.modules.llm.models import LLMUsageLog, MemoryConsolidationLog, MemoryEntry
    from app.modules.llm.services.llm_service import LLMMessage

    entries = await MemoryEntry.find({"user_id": user_id}).sort(MemoryEntry.updated_at).to_list()
    if len(entries) < 10:
        return

    entries_before = len(entries)
    entries_text = "\n".join(f"- key={e.key}, value={e.value}, category={e.category}, updated={e.updated_at.isoformat()}" for e in entries)

    messages = [
        LLMMessage(role="system", content=_CONSOLIDATION_PROMPT + entries_text),
        LLMMessage(role="user", content="Consolidate the memories above. Return JSON only."),
    ]

    response = await llm.complete(messages, json_mode=True)

    # Parse LLM response
    try:
        actions = json.loads(response.content)
        if not isinstance(actions, list):
            actions = actions.get("actions", [])
    except (json.JSONDecodeError, AttributeError):
        logger.warning("memory_consolidation_parse_failed", user_id=str(user_id))
        return

    # Build key→entry lookup
    entry_map = {e.key: e for e in entries}
    now = datetime.now(timezone.utc)
    applied_actions = []

    for action in actions:
        act_type = action.get("action")
        keys = action.get("keys", [])
        reason = action.get("reason", "")

        if act_type == "keep":
            for key in keys:
                entry = entry_map.get(key)
                if entry:
                    entry.updated_at = now
                    await entry.save()
            applied_actions.append({"action": "keep", "keys": keys, "reason": reason})

        elif act_type == "merge":
            new_key = action.get("new_key", keys[0] if keys else "merged")
            new_value = action.get("new_value", "")
            before_values = {k: entry_map[k].value for k in keys if k in entry_map}

            # Delete originals
            for key in keys:
                entry = entry_map.get(key)
                if entry:
                    await entry.delete()

            # Upsert merged entry
            existing = await MemoryEntry.find_one({"user_id": user_id, "key": new_key})
            if existing:
                existing.value = new_value[:500]
                existing.updated_at = now
                await existing.save()
            else:
                await MemoryEntry(
                    user_id=user_id,
                    key=new_key,
                    value=new_value[:500],
                    category=action.get("category", "general"),
                    created_at=now,
                    updated_at=now,
                ).insert()

            applied_actions.append({
                "action": "merge",
                "keys": keys,
                "new_key": new_key,
                "new_value": new_value[:500],
                "before": before_values,
                "reason": reason,
            })

        elif act_type == "delete":
            before_values = {k: entry_map[k].value for k in keys if k in entry_map}
            for key in keys:
                entry = entry_map.get(key)
                if entry:
                    await entry.delete()
            applied_actions.append({
                "action": "delete",
                "keys": keys,
                "before": before_values,
                "reason": reason,
            })

    # Count remaining entries
    entries_after = await MemoryEntry.find({"user_id": user_id}).count()

    # Log consolidation
    await MemoryConsolidationLog(
        user_id=user_id,
        run_at=now,
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
        "memory_consolidation_complete",
        user_id=str(user_id),
        before=entries_before,
        after=entries_after,
        actions=len(applied_actions),
    )
```

- [ ] **Step 2: Register the dreaming job in the scheduler**

In `backend/app/modules/automation/workers/scheduler.py`, add to the `start()` method after `_load_impact_cleanup_schedule()` (around line 72):

```python
        # Load memory consolidation schedule
        await self._load_memory_consolidation_schedule()
```

Then add these methods after the impact cleanup methods (after line 288):

```python
    async def _load_memory_consolidation_schedule(self):
        """Register the weekly memory consolidation job."""
        try:
            from app.models.system import SystemConfig

            config = await SystemConfig.get_config()
            if not getattr(config, "memory_consolidation_enabled", True):
                logger.info("memory_consolidation_disabled")
                return
            cron_expr = getattr(config, "memory_consolidation_cron", "0 4 * * 0")
            await self.schedule_memory_consolidation(cron_expr)
        except Exception as e:
            logger.error("failed_to_load_memory_consolidation_schedule", error=str(e))

    async def schedule_memory_consolidation(self, cron_expression: str):
        """Add or update the memory consolidation job."""
        if not self.scheduler:
            return
        job_id = "memory_consolidation_weekly"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        parts = cron_expression.split()
        if len(parts) != 5:
            logger.error("invalid_memory_consolidation_cron", cron=cron_expression)
            return

        trigger = CronTrigger(
            minute=parts[0], hour=parts[1], day=parts[2],
            month=parts[3], day_of_week=parts[4], timezone="UTC",
        )
        self.scheduler.add_job(
            self._run_memory_consolidation, trigger=trigger,
            id=job_id, name="Weekly Memory Consolidation", replace_existing=True,
        )
        logger.info("memory_consolidation_scheduled", cron=cron_expression)

    async def unschedule_memory_consolidation(self):
        """Remove the memory consolidation job."""
        if not self.scheduler:
            return
        job_id = "memory_consolidation_weekly"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            logger.info("memory_consolidation_unscheduled")

    async def _run_memory_consolidation(self):
        """Execute the memory consolidation."""
        from app.modules.llm.workers.consolidation_worker import run_consolidation

        try:
            await run_consolidation()
        except Exception as e:
            logger.error("memory_consolidation_failed", error=str(e))
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/modules/llm/workers/__init__.py backend/app/modules/llm/workers/consolidation_worker.py backend/app/modules/automation/workers/scheduler.py
git commit -m "feat(memory): add dreaming consolidation worker and scheduler job"
```

---

### Task 7: Admin Consolidation Logs Endpoints

**Files:**
- Modify: `backend/app/api/v1/admin.py` (add consolidation log + stats endpoints)

- [ ] **Step 1: Add admin endpoints for consolidation logs**

In `backend/app/api/v1/admin.py`, add:

```python
# ── Memory Consolidation Admin ───────────────────────────────────────────────


@router.get("/admin/memory/consolidation-logs", tags=["Admin"])
async def list_consolidation_logs(
    page: int = 1,
    page_size: int = 25,
    user_id: str | None = None,
    _current_user: User = Depends(require_admin),
):
    """List memory consolidation logs (admin only)."""
    from beanie import PydanticObjectId
    from app.modules.llm.models import MemoryConsolidationLog
    from app.models.user import User as UserModel

    filters: dict = {}
    if user_id:
        filters["user_id"] = PydanticObjectId(user_id)

    total = await MemoryConsolidationLog.find(filters).count()
    logs = (
        await MemoryConsolidationLog.find(filters)
        .sort(-MemoryConsolidationLog.run_at)
        .skip((page - 1) * page_size)
        .limit(page_size)
        .to_list()
    )

    # Resolve user emails
    user_ids = list({log.user_id for log in logs})
    users = await UserModel.find({"_id": {"$in": user_ids}}).to_list()
    email_map = {u.id: u.email for u in users}

    return {
        "logs": [
            {
                "id": str(log.id),
                "user_id": str(log.user_id),
                "user_email": email_map.get(log.user_id, "unknown"),
                "run_at": log.run_at.isoformat(),
                "entries_before": log.entries_before,
                "entries_after": log.entries_after,
                "actions_summary": {
                    "merged": sum(1 for a in log.actions if a.get("action") == "merge"),
                    "deleted": sum(1 for a in log.actions if a.get("action") == "delete"),
                    "kept": sum(1 for a in log.actions if a.get("action") == "keep"),
                },
                "llm_model": log.llm_model,
                "llm_tokens_used": log.llm_tokens_used,
            }
            for log in logs
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/admin/memory/consolidation-logs/{log_id}", tags=["Admin"])
async def get_consolidation_log_detail(
    log_id: str,
    _current_user: User = Depends(require_admin),
):
    """Get a single consolidation log with full action details."""
    from beanie import PydanticObjectId
    from app.modules.llm.models import MemoryConsolidationLog

    try:
        log = await MemoryConsolidationLog.get(PydanticObjectId(log_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid log ID") from None
    if not log:
        raise HTTPException(status_code=404, detail="Consolidation log not found")

    return {
        "id": str(log.id),
        "user_id": str(log.user_id),
        "run_at": log.run_at.isoformat(),
        "entries_before": log.entries_before,
        "entries_after": log.entries_after,
        "actions": log.actions,
        "llm_model": log.llm_model,
        "llm_tokens_used": log.llm_tokens_used,
    }


@router.get("/admin/memory/stats", tags=["Admin"])
async def get_memory_stats(_current_user: User = Depends(require_admin)):
    """Aggregate memory stats for admin dashboard."""
    from app.modules.llm.models import MemoryEntry

    pipeline = [
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
    ]
    user_counts = await MemoryEntry.aggregate(pipeline).to_list()
    total_entries = sum(uc["count"] for uc in user_counts)
    user_count = len(user_counts)
    avg_per_user = total_entries / user_count if user_count > 0 else 0

    # Top users by entry count
    top_users = sorted(user_counts, key=lambda x: x["count"], reverse=True)[:10]

    return {
        "total_entries": total_entries,
        "users_with_memories": user_count,
        "avg_entries_per_user": round(avg_per_user, 1),
        "top_users": [{"user_id": str(u["_id"]), "count": u["count"]} for u in top_users],
    }
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/v1/admin.py
git commit -m "feat(memory): add admin consolidation logs and memory stats endpoints"
```

---

### Task 8: Frontend — Memory Model and LlmService Methods

**Files:**
- Modify: `frontend/src/app/core/models/llm.model.ts` (add memory interfaces)
- Modify: `frontend/src/app/core/services/llm.service.ts` (add memory methods)

- [ ] **Step 1: Add memory interfaces to llm.model.ts**

In `frontend/src/app/core/models/llm.model.ts`, add:

```typescript
export interface MemoryEntry {
  id: string;
  key: string;
  value: string;
  category: string;
  source_thread_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface MemoryListResponse {
  entries: MemoryEntry[];
  total: number;
}

export interface ConsolidationLogSummary {
  id: string;
  user_id: string;
  user_email: string;
  run_at: string;
  entries_before: number;
  entries_after: number;
  actions_summary: { merged: number; deleted: number; kept: number };
  llm_model: string;
  llm_tokens_used: number;
}

export interface ConsolidationLogDetail {
  id: string;
  user_id: string;
  run_at: string;
  entries_before: number;
  entries_after: number;
  actions: Record<string, unknown>[];
  llm_model: string;
  llm_tokens_used: number;
}

export interface MemoryStats {
  total_entries: number;
  users_with_memories: number;
  avg_entries_per_user: number;
  top_users: { user_id: string; count: number }[];
}
```

- [ ] **Step 2: Add memory methods to LlmService**

In `frontend/src/app/core/services/llm.service.ts`, add methods:

```typescript
  // ── User Memory ────────────────────────────────────────────────────────────

  listMemories(category?: string, search?: string): Observable<MemoryListResponse> {
    const params: Record<string, string> = {};
    if (category) params['category'] = category;
    if (search) params['search'] = search;
    return this.api.get<MemoryListResponse>('/llm/memories', { params });
  }

  updateMemory(id: string, data: { value?: string; category?: string }): Observable<MemoryEntry> {
    return this.api.put<MemoryEntry>(`/llm/memories/${id}`, data);
  }

  deleteMemory(id: string): Observable<{ status: string; key: string }> {
    return this.api.delete<{ status: string; key: string }>(`/llm/memories/${id}`);
  }

  deleteAllMemories(): Observable<{ status: string; count: number }> {
    return this.api.delete<{ status: string; count: number }>('/llm/memories?confirm=true');
  }

  // ── Admin Memory ───────────────────────────────────────────────────────────

  listConsolidationLogs(
    page = 1,
    pageSize = 25,
  ): Observable<{ logs: ConsolidationLogSummary[]; total: number }> {
    return this.api.get<{ logs: ConsolidationLogSummary[]; total: number }>(
      `/admin/memory/consolidation-logs?page=${page}&page_size=${pageSize}`,
    );
  }

  getConsolidationLog(id: string): Observable<ConsolidationLogDetail> {
    return this.api.get<ConsolidationLogDetail>(`/admin/memory/consolidation-logs/${id}`);
  }

  getMemoryStats(): Observable<MemoryStats> {
    return this.api.get<MemoryStats>('/admin/memory/stats');
  }
```

Add the new types to the import block at the top of the file.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/core/models/llm.model.ts frontend/src/app/core/services/llm.service.ts
git commit -m "feat(memory): add memory models and LlmService methods"
```

---

### Task 9: Frontend — Profile Memory Page

**Files:**
- Create: `frontend/src/app/features/profile/memory/memory.component.ts`
- Modify: `frontend/src/app/features/profile/profile.routes.ts:25-28`
- Modify: `frontend/src/app/features/profile/profile.component.ts:36-43`

- [ ] **Step 1: Create the memory component**

Create `frontend/src/app/features/profile/memory/memory.component.ts`:

```typescript
import { Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { LlmService } from '../../../core/services/llm.service';
import { MemoryEntry } from '../../../core/models/llm.model';
import { ConfirmDialogComponent } from '../../../shared/components/confirm-dialog/confirm-dialog.component';

@Component({
  selector: 'app-profile-memory',
  standalone: true,
  imports: [
    FormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatSelectModule,
    MatTableModule,
    MatTooltipModule,
  ],
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    }
    <div class="memory-header">
      <h3>My Memories ({{ total() }} / 100)</h3>
      <div class="memory-actions">
        <mat-form-field appearance="outline" class="search-field">
          <mat-label>Search</mat-label>
          <input matInput [ngModel]="searchQuery()" (ngModelChange)="onSearch($event)" />
        </mat-form-field>
        <mat-form-field appearance="outline" class="category-field">
          <mat-label>Category</mat-label>
          <mat-select [ngModel]="categoryFilter()" (ngModelChange)="onCategoryChange($event)">
            <mat-option value="">All</mat-option>
            <mat-option value="general">General</mat-option>
            <mat-option value="network">Network</mat-option>
            <mat-option value="preference">Preference</mat-option>
            <mat-option value="troubleshooting">Troubleshooting</mat-option>
          </mat-select>
        </mat-form-field>
        @if (total() > 0) {
          <button mat-stroked-button color="warn" (click)="deleteAll()">
            <mat-icon>delete_sweep</mat-icon> Delete All
          </button>
        }
      </div>
    </div>

    @if (entries().length > 0) {
      <div class="table-card">
        <table mat-table [dataSource]="entries()">
          <ng-container matColumnDef="key">
            <th mat-header-cell *matHeaderCellDef>Key</th>
            <td mat-cell *matCellDef="let e">{{ e.key }}</td>
          </ng-container>
          <ng-container matColumnDef="value">
            <th mat-header-cell *matHeaderCellDef>Value</th>
            <td mat-cell *matCellDef="let e" class="value-cell">{{ e.value }}</td>
          </ng-container>
          <ng-container matColumnDef="category">
            <th mat-header-cell *matHeaderCellDef>Category</th>
            <td mat-cell *matCellDef="let e">{{ e.category }}</td>
          </ng-container>
          <ng-container matColumnDef="updated_at">
            <th mat-header-cell *matHeaderCellDef>Updated</th>
            <td mat-cell *matCellDef="let e">{{ e.updated_at | date: 'short' }}</td>
          </ng-container>
          <ng-container matColumnDef="actions">
            <th mat-header-cell *matHeaderCellDef></th>
            <td mat-cell *matCellDef="let e">
              <button mat-icon-button color="warn" matTooltip="Delete" (click)="deleteEntry(e)">
                <mat-icon>delete</mat-icon>
              </button>
            </td>
          </ng-container>
          <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
          <tr mat-row *matRowDef="let row; columns: displayedColumns"></tr>
        </table>
      </div>
    } @else if (!loading()) {
      <p class="empty-state">No memories stored yet. The AI will create memories during conversations.</p>
    }
  `,
  styles: [
    `
      .memory-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 16px;
        margin-bottom: 16px;
      }
      .memory-actions {
        display: flex;
        gap: 12px;
        align-items: center;
      }
      .search-field {
        width: 200px;
      }
      .category-field {
        width: 160px;
      }
      .value-cell {
        max-width: 400px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .empty-state {
        text-align: center;
        padding: 48px;
        color: var(--app-neutral);
      }
    `,
  ],
})
export class MemoryComponent implements OnInit {
  private readonly llm = inject(LlmService);
  private readonly dialog = inject(MatDialog);
  private readonly destroyRef = inject(DestroyRef);

  readonly loading = signal(false);
  readonly entries = signal<MemoryEntry[]>([]);
  readonly total = signal(0);
  readonly searchQuery = signal('');
  readonly categoryFilter = signal('');
  readonly displayedColumns = ['key', 'value', 'category', 'updated_at', 'actions'];

  ngOnInit(): void {
    this.loadMemories();
  }

  loadMemories(): void {
    this.loading.set(true);
    this.llm
      .listMemories(this.categoryFilter() || undefined, this.searchQuery() || undefined)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.entries.set(res.entries);
          this.total.set(res.total);
          this.loading.set(false);
        },
        error: () => this.loading.set(false),
      });
  }

  onSearch(query: string): void {
    this.searchQuery.set(query);
    this.loadMemories();
  }

  onCategoryChange(category: string): void {
    this.categoryFilter.set(category);
    this.loadMemories();
  }

  deleteEntry(entry: MemoryEntry): void {
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: { title: 'Delete Memory', message: `Delete memory "${entry.key}"?` },
    });
    ref
      .afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((confirmed) => {
        if (confirmed) {
          this.llm.deleteMemory(entry.id).subscribe(() => this.loadMemories());
        }
      });
  }

  deleteAll(): void {
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: 'Delete All Memories',
        message: 'This will permanently delete all your stored memories. Continue?',
      },
    });
    ref
      .afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((confirmed) => {
        if (confirmed) {
          this.llm.deleteAllMemories().subscribe(() => this.loadMemories());
        }
      });
  }
}
```

- [ ] **Step 2: Add route and tab**

In `frontend/src/app/features/profile/profile.routes.ts`, add after the passkeys route (line 27):

```typescript
      {
        path: 'memory',
        loadComponent: () =>
          import('./memory/memory.component').then((m) => m.MemoryComponent),
      },
```

In `frontend/src/app/features/profile/profile.component.ts`, add a new tab link after the Passkeys tab (after line 42):

```html
      <a
        mat-tab-link
        routerLink="memory"
        routerLinkActive
        #mem="routerLinkActive"
        [active]="mem.isActive"
        >Memory</a
      >
```

- [ ] **Step 3: Verify the frontend compiles**

Run: `cd frontend && npx ng build`
Expected: Build succeeds with no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/features/profile/memory/memory.component.ts frontend/src/app/features/profile/profile.routes.ts frontend/src/app/features/profile/profile.component.ts
git commit -m "feat(memory): add My Memories profile page with table, search, and delete"
```

---

### Task 10: Frontend — Admin Consolidation Logs Section

**Files:**
- Create: `frontend/src/app/features/admin/settings/llm/memory-admin.component.ts`
- Modify: `frontend/src/app/features/admin/settings/llm/settings-llm.component.ts` (embed memory admin)

- [ ] **Step 1: Create the memory admin component**

Create `frontend/src/app/features/admin/settings/llm/memory-admin.component.ts`:

```typescript
import { Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DatePipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { LlmService } from '../../../../core/services/llm.service';
import { ConsolidationLogSummary, MemoryStats, ConsolidationLogDetail } from '../../../../core/models/llm.model';

@Component({
  selector: 'app-memory-admin',
  standalone: true,
  imports: [
    DatePipe,
    MatButtonModule,
    MatCardModule,
    MatExpansionModule,
    MatIconModule,
    MatProgressBarModule,
    MatTableModule,
  ],
  template: `
    <mat-card>
      <mat-card-header>
        <mat-card-title>Memory Statistics</mat-card-title>
      </mat-card-header>
      <mat-card-content>
        @if (stats()) {
          <div class="stats-grid">
            <div class="stat">
              <span class="stat-value">{{ stats()!.total_entries }}</span>
              <span class="stat-label">Total Entries</span>
            </div>
            <div class="stat">
              <span class="stat-value">{{ stats()!.users_with_memories }}</span>
              <span class="stat-label">Users with Memories</span>
            </div>
            <div class="stat">
              <span class="stat-value">{{ stats()!.avg_entries_per_user }}</span>
              <span class="stat-label">Avg per User</span>
            </div>
          </div>
        }
      </mat-card-content>
    </mat-card>

    <mat-card class="logs-card">
      <mat-card-header>
        <mat-card-title>Consolidation Logs</mat-card-title>
      </mat-card-header>
      <mat-card-content>
        @if (logsLoading()) {
          <mat-progress-bar mode="indeterminate"></mat-progress-bar>
        }
        @if (logs().length > 0) {
          <mat-accordion>
            @for (log of logs(); track log.id) {
              <mat-expansion-panel (opened)="loadLogDetail(log.id)">
                <mat-expansion-panel-header>
                  <mat-panel-title>{{ log.run_at | date: 'medium' }} - {{ log.user_email }}</mat-panel-title>
                  <mat-panel-description>
                    {{ log.entries_before }} &rarr; {{ log.entries_after }} entries |
                    Merged: {{ log.actions_summary.merged }},
                    Deleted: {{ log.actions_summary.deleted }},
                    Kept: {{ log.actions_summary.kept }}
                  </mat-panel-description>
                </mat-expansion-panel-header>
                @if (expandedLog()?.id === log.id) {
                  <div class="log-detail">
                    <p><strong>Model:</strong> {{ expandedLog()!.llm_model }} ({{ expandedLog()!.llm_tokens_used }} tokens)</p>
                    @for (action of expandedLog()!.actions; track $index) {
                      <div class="action-item" [class]="'action-' + $any(action)['action']">
                        <strong>{{ $any(action)['action'] | uppercase }}:</strong>
                        {{ $any(action)['keys']?.join(', ') }}
                        @if ($any(action)['reason']) {
                          <br /><em>{{ $any(action)['reason'] }}</em>
                        }
                      </div>
                    }
                  </div>
                }
              </mat-expansion-panel>
            }
          </mat-accordion>
        } @else if (!logsLoading()) {
          <p>No consolidation logs yet.</p>
        }
      </mat-card-content>
    </mat-card>
  `,
  styles: [
    `
      mat-card {
        margin-bottom: 24px;
      }
      .stats-grid {
        display: flex;
        gap: 32px;
      }
      .stat {
        display: flex;
        flex-direction: column;
        align-items: center;
      }
      .stat-value {
        font-size: 24px;
        font-weight: 500;
      }
      .stat-label {
        color: var(--app-neutral);
        font-size: 13px;
      }
      .log-detail {
        padding: 12px 0;
      }
      .action-item {
        padding: 8px 12px;
        margin: 4px 0;
        border-radius: 4px;
        border-left: 3px solid var(--app-neutral);
      }
      .action-merge {
        border-left-color: var(--app-info);
      }
      .action-delete {
        border-left-color: var(--app-error);
      }
      .action-keep {
        border-left-color: var(--app-success);
      }
    `,
  ],
})
export class MemoryAdminComponent implements OnInit {
  private readonly llm = inject(LlmService);
  private readonly destroyRef = inject(DestroyRef);

  readonly stats = signal<MemoryStats | null>(null);
  readonly logs = signal<ConsolidationLogSummary[]>([]);
  readonly logsLoading = signal(false);
  readonly expandedLog = signal<ConsolidationLogDetail | null>(null);

  ngOnInit(): void {
    this.llm.getMemoryStats().pipe(takeUntilDestroyed(this.destroyRef)).subscribe((s) => this.stats.set(s));
    this.loadLogs();
  }

  loadLogs(): void {
    this.logsLoading.set(true);
    this.llm
      .listConsolidationLogs()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.logs.set(res.logs);
          this.logsLoading.set(false);
        },
        error: () => this.logsLoading.set(false),
      });
  }

  loadLogDetail(logId: string): void {
    this.llm
      .getConsolidationLog(logId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((detail) => this.expandedLog.set(detail));
  }
}
```

- [ ] **Step 2: Embed in the LLM settings page**

In `frontend/src/app/features/admin/settings/llm/settings-llm.component.ts`, import and add `MemoryAdminComponent` to the imports array and add it to the template after the existing LLM config and skills sections (inside the `llmEnabled` guard):

```html
<app-memory-admin />
```

- [ ] **Step 3: Verify the frontend compiles**

Run: `cd frontend && npx ng build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/features/admin/settings/llm/memory-admin.component.ts frontend/src/app/features/admin/settings/llm/settings-llm.component.ts
git commit -m "feat(memory): add admin consolidation logs and memory stats UI"
```

---

### Task 11: Update CLAUDE.md Files

**Files:**
- Modify: `backend/app/modules/llm/CLAUDE.md`
- Modify: `backend/app/modules/mcp_server/CLAUDE.md`
- Modify: `CLAUDE.md` (root)

- [ ] **Step 1: Update LLM module CLAUDE.md**

Add a "Memory System" section to `backend/app/modules/llm/CLAUDE.md`:

```markdown
- **Memory system**: Per-user persistent memory via `MemoryEntry` documents (key-value, 180-day TTL, 100 entries/user cap). Three MCP tools (`memory_store`, `memory_recall`, `memory_forget`) in `mcp_server/tools/memory.py`. Memory instruction injected into system prompt for interactive chat contexts only (global chat, follow-up, impact analysis chat, workflow debug). Recall uses MongoDB text search — does not extend TTL. `MemoryConsolidationLog` tracks periodic dreaming runs.
- **Dreaming consolidation**: Weekly APScheduler job (`memory_consolidation_weekly`). LLM reviews per-user entries and merges/deletes. Config: `SystemConfig.memory_consolidation_enabled` + `memory_consolidation_cron`. Worker: `app/modules/llm/workers/consolidation_worker.py`.
```

- [ ] **Step 2: Update MCP server CLAUDE.md**

Add to `backend/app/modules/mcp_server/CLAUDE.md`:

```markdown
- **Memory tools** (`tools/memory.py`): `memory_store(key, value, category)`, `memory_recall(query, category)`, `memory_forget(key)`. Per-user scoped via `mcp_user_id_var`. Store upserts by `(user_id, key)` — warns LLM about overwrite. Recall uses MongoDB text index. Cap enforced from `SystemConfig.memory_max_entries_per_user`. Internal helpers `_store_memory`, `_recall_memory`, `_forget_memory` are exported for direct testing.
```

- [ ] **Step 3: Update root CLAUDE.md**

Add a brief mention in the LLM Module section of the root `CLAUDE.md`:

```markdown
### LLM Memory System

Per-user persistent memory (key-value store) exposed via MCP tools in interactive chat contexts. Weekly "dreaming" consolidation job merges/deduplicates entries via LLM. User management in profile page, admin consolidation logs in LLM settings. See `backend/app/modules/llm/CLAUDE.md` and `backend/app/modules/mcp_server/CLAUDE.md` for details.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md backend/app/modules/llm/CLAUDE.md backend/app/modules/mcp_server/CLAUDE.md
git commit -m "docs: update CLAUDE.md files with memory system documentation"
```

---

### Task 12: Final Integration Test

- [ ] **Step 1: Run full backend test suite**

Run: `cd backend && .venv/bin/pytest tests/ -v --timeout=60`
Expected: All tests pass

- [ ] **Step 2: Run frontend build**

Run: `cd frontend && npx ng build`
Expected: Build succeeds

- [ ] **Step 3: Run linting**

Run: `cd backend && .venv/bin/ruff check . && .venv/bin/black --check .`
Run: `cd frontend && npx ng lint` (if available) or `npx prettier --check 'src/**/*.ts'`
Expected: No lint errors

- [ ] **Step 4: Final commit (if any lint/format fixes needed)**

```bash
git add -A
git commit -m "fix: lint and format fixes for memory system"
```
