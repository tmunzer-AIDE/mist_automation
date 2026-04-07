# LLM Memory System Design

**Date**: 2026-04-07
**Status**: Approved
**Approach**: Hybrid — persistent memory store (Phase 1) + conversation compaction (Phase 2)

## Problem

The LLM chat has no memory across conversations. Each thread uses a sliding window of 10-20 messages — older context is dropped. Users must re-explain context every new conversation. Long conversations also lose early context within the same thread.

## Solution Overview

Two complementary features, delivered in phases:

- **Phase 1 — Persistent Memory Store**: Per-user key-value memory entries stored in MongoDB, exposed to the LLM via MCP tools. The LLM autonomously stores and recalls facts across conversations. A periodic "dreaming" job consolidates memories.
- **Phase 2 — Conversation Compaction**: Token-aware background summarization of older messages within a thread. Replaces the fixed-count sliding window with a token-budget approach.

---

## Phase 1: Persistent Memory Store

### Data Models

#### MemoryEntry

```python
class MemoryEntry(Document):
    user_id: PydanticObjectId          # FK to User — ownership
    key: str                           # Short unique label, max 100 chars
    value: str                         # Content, max 500 chars
    category: str = "general"          # LLM-assigned: general, network, preference, troubleshooting
    source_thread_id: str | None       # Which conversation created this entry
    created_at: datetime
    updated_at: datetime

    class Settings:
        name = "memory_entries"
        indexes = [
            IndexModel([("user_id", 1), ("key", 1)], unique=True),
            IndexModel([("user_id", 1), ("category", 1)]),
            IndexModel([("updated_at", 1)], expireAfterSeconds=180 * 86400),  # 180-day TTL
            IndexModel([("user_id", 1), ("key", "text"), ("value", "text")]),  # Text search
        ]
```

- **Unique index** on `(user_id, key)` — storing with an existing key upserts (replaces value).
- **180-day TTL** — MongoDB auto-deletes entries not updated within 180 days. Only store/upsert and dreaming "keep" actions refresh `updated_at` — recall does not extend TTL.
- **Text index** on `key` + `value` — enables MongoDB text search for `memory_recall`.
- **Per-user cap**: 100 entries. Enforced on `memory_store` — rejects with a message if at cap.

#### MemoryConsolidationLog

```python
class MemoryConsolidationLog(Document):
    user_id: PydanticObjectId
    run_at: datetime
    entries_before: int
    entries_after: int
    actions: list[dict]   # [{action, keys, new_key, new_value, reason, before, after}]
    llm_model: str
    llm_tokens_used: int
    created_at: datetime

    class Settings:
        name = "memory_consolidation_logs"
        indexes = [
            IndexModel([("created_at", 1)], expireAfterSeconds=365 * 86400),  # 1-year TTL
        ]
```

Stores the full before/after diff and LLM reasoning for each consolidation action.

### MCP Tools

Three new tools on the existing local in-process MCP server. Available in **user-interactive chat contexts only**: global chat, follow-up conversations, impact analysis chat, workflow debug chat. **Not** available in: AI Agent workflow nodes, background summarization, workflow assist.

#### memory_store(key, value, category?)

- **Tool description** (visible to LLM): "Save a fact to your personal memory. WARNING: If this key already exists, the value will be OVERWRITTEN. Use memory_recall first to check existing keys if unsure."
- Upserts by `(user_id, key)`
- Validates: `key` max 100 chars, `value` max 500 chars
- Checks per-user cap (100) before insert
- Sets `source_thread_id` from current conversation
- `category` optional, defaults to `"general"`
- Returns: `"Stored memory: {key}"`

#### memory_recall(query?, category?)

- If `query` provided: MongoDB text search on `key` + `value`, filtered by `user_id`
- If only `category`: returns all entries in that category
- If neither: returns 20 most recent entries
- Returns formatted list: `"- {key}: {value} (category, updated {date})"` per entry
- Capped at 30 results

#### memory_forget(key)

- Deletes by exact `(user_id, key)` match
- Returns confirmation or `"No memory found with key: {key}"`

### System Prompt Integration

No bulk memory injection. A short instruction appended to the system prompt in interactive chat contexts:

```
You have access to a personal memory store for this user. Use memory_store to save
important facts, preferences, or context that would be useful in future conversations.
Use memory_recall to search for relevant memories before answering questions where
prior context might help. Use memory_forget to remove outdated information.
Only store information that has long-term value — not transient conversation details.
When storing memories, choose descriptive unique keys. Storing with an existing key
replaces the previous value — check with memory_recall first if you want to update
rather than overwrite.
```

The LLM decides when to recall and what to store autonomously.

### Request Flow (with memory)

```
1. User sends message
2. Build system prompt (base + canvas + skills + memory instruction)
3. Connect MCP clients (local with memory tools + external)
4. Agent loop runs:
   - LLM may call memory_recall to fetch relevant context
   - LLM answers using recalled memories + tool results
   - LLM may call memory_store if it learns something worth remembering
5. Save assistant reply + tool call metadata to thread
```

### Dreaming — Periodic Memory Consolidation

#### Scheduler Job

New APScheduler job in `WorkflowScheduler.start()`:
- **Schedule**: Weekly, Sunday 4:00 UTC (configurable via `SystemConfig.memory_consolidation_cron`)
- **Job ID**: `memory_consolidation_weekly`
- **Toggle**: `SystemConfig.memory_consolidation_enabled` (default: True)

#### Consolidation Flow (per user)

1. Find all users with 10+ memory entries (skip users with fewer)
2. For each user, load all `MemoryEntry` docs sorted by `updated_at`
3. Send to LLM with consolidation prompt:

```
You are a memory manager. Below are stored facts for a user of a network automation platform.
Review and consolidate:
- Merge entries that describe the same topic into one (combine key + value)
- Delete entries that contradict newer ones (keep the newer fact)
- Delete entries that describe clearly resolved situations (e.g. "fixed on <date>", "workaround applied")
- Keep everything else unchanged

For each entry, return a JSON action:
{action: "keep"|"merge"|"delete", keys: [...], new_key: "...", new_value: "...", reason: "..."}
```

4. Parse LLM response, apply actions:
   - `merge`: upsert combined entry, delete originals
   - `delete`: remove entry
   - `keep`: touch `updated_at` (resets TTL)
5. Save `MemoryConsolidationLog` with full before/after detail
6. Log to `LLMUsageLog(feature="memory_dreaming")`

#### LLM Config

Uses the default LLM config (same as global chat). If no default config or LLM disabled, skip silently.

### User-Facing Memory Management (Profile Page)

New "My Memories" section on the profile page:

- **Table view**: key, value (truncated), category, last updated
- **Search/filter**: text search + category dropdown
- **Actions per entry**: edit value, delete
- **Bulk action**: "Delete all" with confirmation
- **Stats**: entry count / 100 cap, oldest/newest entry dates
- **No manual create**: LLM is the sole creator — keeps format consistent

#### User API Endpoints

```
GET    /api/v1/llm/memories          — list current user's memories (paginated, filterable)
GET    /api/v1/llm/memories/:id      — get single entry
PUT    /api/v1/llm/memories/:id      — update value/category
DELETE /api/v1/llm/memories/:id      — delete single entry
DELETE /api/v1/llm/memories          — delete all (with confirmation param)
```

All scoped to `current_user.id`.

### Admin Features

#### Consolidation Logs View

New section under admin settings:
- **Table**: date, user email, entries before/after, action counts (merged/deleted/kept), model, tokens used
- **Expandable row**: full action list with before/after values and LLM reasoning
- **Filters**: date range, user

#### Admin Memory Settings (SystemConfig)

```python
memory_enabled: bool = True                          # Global kill switch for memory tools
memory_max_entries_per_user: int = 100               # Per-user cap
memory_entry_max_length: int = 500                   # Max chars per value
memory_consolidation_enabled: bool = True            # Dreaming on/off
memory_consolidation_cron: str = "0 4 * * 0"         # Weekly Sunday 4:00 UTC
```

#### Admin API Endpoints

```
GET /api/v1/admin/memory/consolidation-logs          — paginated consolidation runs
GET /api/v1/admin/memory/consolidation-logs/:id      — single run detail with full actions
GET /api/v1/admin/memory/stats                       — aggregate stats (total entries, per-user avg, top users)
```

All require `require_admin`.

---

## Phase 2: Conversation Compaction (Deferred)

Key decisions documented for future implementation:

- **Token counting**: `litellm.token_counter()` universally, regardless of provider path
- **Context window detection**: New `context_window_tokens` field on `LLMConfig`, auto-detected via `litellm.get_model_info()`, warning in config UI if detection fails, default 20,000 tokens
- **Compaction trigger**: Background task when token estimate > 70% of context window
- **Compaction output**: `CompactionSummary` stored separately — `ConversationThread.messages` array is never modified (UI shows full history)
- **LLM context structure**: `[system prompt] + [first user message] + [compaction summary] + [recent messages]`
- **UI indicator**: Visual cue in chat panel when compaction occurs
- **Fallback**: If compaction LLM call fails, fall back to current sliding window (`max_turns`) behavior
- **Fully transparent**: No user action needed

---

## Future Work

- **RAG/embedding-based semantic search**: Replace or supplement MongoDB text search with vector embeddings for semantic similarity recall. Requires embedding model + vector storage infrastructure. Deferred — keyword search sufficient for <100 entries per user.
- **Org-level shared memory**: Cross-user memory store with access controls. Deferred for security concerns (information leakage between users).

---

## Size Safeguards Summary

| Mechanism | Limit | Effect |
|-----------|-------|--------|
| Per-user entry cap | 100 entries | Store rejected when full |
| Per-value max length | 500 chars | Validated on store |
| Per-key max length | 100 chars | Validated on store |
| TTL index | 180 days | MongoDB auto-deletes unused entries |
| Consolidation log TTL | 1 year | MongoDB auto-deletes old logs |
| Recall result cap | 30 entries | Prevents large tool responses |
| Dedup on key | Unique index per (user, key) | Upsert prevents bloat |
| Dreaming consolidation | Weekly | Merges duplicates, removes obsolete |
