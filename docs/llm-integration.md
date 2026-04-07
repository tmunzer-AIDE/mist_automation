# LLM Integration Architecture

Multi-provider AI integration enabling conversational assistants, automated summaries, workflow generation, and extensible tool-calling via MCP (Model Context Protocol).

## Contents

- [Features](#features)
- [Module Layout](#module-layout)
- [Architecture](#architecture)
- [LLM Providers](#llm-providers)
- [AI Agent Loop](#ai-agent-loop)
- [MCP Server (In-Process)](#mcp-server-in-process)
- [Conversational Threads](#conversational-threads)
- [Memory System](#memory-system)
- [Skills System](#skills-system)
- [Canvas Artifacts](#canvas-artifacts)
- [Elicitation (Tool Confirmations)](#elicitation-tool-confirmations)
- [WebSocket Streaming](#websocket-streaming)
- [Context-Aware Chat](#context-aware-chat)
- [Prompt Architecture](#prompt-architecture)
- [API Endpoints Reference](#api-endpoints-reference)
- [Data Flow: Full Global Chat Request](#data-flow-full-global-chat-request)
- [Key Design Decisions](#key-design-decisions)

---

## Features

- **Multi-provider support** — OpenAI, Anthropic, Azure OpenAI, Ollama, LM Studio, AWS Bedrock, Google Vertex, and any OpenAI-compatible endpoint
- **Conversational threads** — Per-user, per-feature conversation history with automatic token compaction
- **MCP tool-calling** — Bidirectional tool calling: the app exposes an in-process MCP server, and the agent can also connect to external MCP servers
- **Real-time streaming** — WebSocket-based token + tool event streaming to the frontend
- **Persistent memory** — Per-user key-value memory store with weekly LLM-driven consolidation ("dreaming")
- **Canvas artifacts** — LLM can emit sandboxed code, Mermaid diagrams, Chart.js charts, HTML, and SVG artifacts rendered inline in chat
- **Skills system** — Admin-managed library of SKILL.md instructions injected into chat contexts
- **Deep app integration** — Backup diffs, workflow generation, impact analysis, audit log summaries, etc.

## Module Layout

```
backend/app/
├── api/v1/
│   ├── llm.py              # All LLM REST endpoints (/llm/*, /mcp/*)
│   └── mcp.py              # MCP HTTP server gateway
├── modules/
│   ├── llm/
│   │   ├── models.py           # LLMConfig, ConversationThread, MemoryEntry, Skill, LLMUsageLog, ...
│   │   ├── schemas.py          # Request/response Pydantic schemas
│   │   └── services/
│   │       ├── llm_service.py          # Provider-agnostic LLM client (streaming + tools)
│   │       ├── llm_service_factory.py  # Factory: load config → LLMService instance
│   │       ├── agent_service.py        # AI Agent loop (LLM + MCP tools iteration)
│   │       ├── mcp_client.py           # Remote HTTP + in-process MCP client wrappers
│   │       ├── prompt_builders.py      # System/user prompt construction per feature
│   │       ├── context_service.py      # Data gathering from other modules for prompts
│   │       ├── skills_service.py       # Skill loading and catalog management
│   │       └── token_service.py        # Token counting and context window detection
│   │   └── workers/
│   │       ├── compaction_worker.py    # Background conversation summarization
│   │       └── consolidation_worker.py # Weekly memory consolidation job
│   └── mcp_server/
│       ├── server.py               # FastMCP instance + context variables
│       ├── auth_middleware.py      # JWT validation for HTTP MCP endpoint
│       ├── helpers.py              # Elicitation helpers
│       └── tools/
│           ├── backup.py           # Backup CRUD + restore with confirmation
│           ├── workflow.py         # Workflow CRUD + validation
│           ├── search.py           # Cross-module search
│           ├── details.py          # Object detail fetching
│           ├── impact_analysis.py  # Impact analysis queries
│           ├── memory.py           # memory_store / memory_recall / memory_forget
│           └── skills.py           # activate_skill tool

frontend/src/app/
├── core/
│   ├── services/
│   │   ├── llm.service.ts          # HTTP client for all LLM endpoints
│   │   └── global-chat.service.ts  # Page context + chat open/close events
│   └── models/
│       └── llm.model.ts            # TypeScript interfaces
├── shared/components/
│   ├── ai-chat-panel/              # Main chat timeline (messages, tools, artifacts)
│   │   ├── ai-chat-panel.component.ts
│   │   └── restore-diff-card.component.ts
│   ├── ai-summary-panel/           # Inline summary container used across pages
│   ├── ai-icon/                    # Animated SVG icon
│   ├── artifact-card/              # Sandboxed iframe artifact renderer
│   └── global-chat/                # Floating FAB + expandable chat panel
└── features/admin/settings/llm/
    ├── llm-admin.component.ts      # Provider config CRUD
    ├── skills-admin.component.ts   # Skill + git repo management
    └── memory-admin.component.ts   # Memory stats + consolidation logs
```

---

## Architecture

```
                     ┌────────────────────────────────────────┐
                     │             Frontend                   │
                     │                                        │
                     │  GlobalChatComponent                   │
                     │    └─ AiChatPanelComponent             │
                     │         ├─ Timeline (messages, tools)  │
                     │         ├─ ArtifactCards (iframes)     │
                     │         └─ RestoreDiffCard             │
                     └───────────┬──────────────┬─────────────┘
                                 │ REST         │ WebSocket
                                 ▼              ▼
                     ┌───────────────────────────────────────┐
                     │           API Layer                   │
                     │  POST /llm/chat                       │
                     │  POST /llm/chat/{id}                  │
                     │  POST /llm/*/summarize                │
                     │  POST /llm/workflow/assist            │
                     │  POST /mcp  (HTTP MCP gateway)        │
                     └───────────┬───────────────────────────┘
                                 │
               ┌─────────────────▼──────────────────────┐
               │           LLM Module                   │
               │                                        │
               │  AIAgentService                        │
               │    └─ Iteration loop:                  │
               │         LLMService (streaming + tools) │
               │         └─ OpenAI SDK  /  litellm      │
               │                                        │
               │  ConversationThread (Beanie/MongoDB)   │
               │  CompactionWorker (background)         │
               │  LLMUsageLog                           │
               └──────────┬──────┬──────────────────────┘
                          │      │
           ┌──────────────▼──┐  ┌▼─────────────────────────┐
           │  Local MCP      │  │  External MCP Servers    │
           │  (in-process)   │  │  (HTTP, user-configured) │
           │                 │  │                          │
           │  backup.py      │  │  Any MCP-compatible      │
           │  workflow.py    │  │  service with Bearer JWT │
           │  search.py      │  └──────────────────────────┘
           │  details.py     │
           │  memory.py      │
           │  skills.py      │
           │  impact_analysis│
           └─────────────────┘
```

---

## LLM Providers

### Dual-Path Architecture

Two execution paths exist to handle the heterogeneity of LLM providers:

| Path | Providers | When used |
|------|-----------|-----------|
| **OpenAI SDK** (native) | openai, lm_studio, azure_openai, llama_cpp, vllm | Always preferred; supports token-level streaming with tool calls |
| **litellm** | anthropic, ollama, bedrock, vertex | Universal wrapper; lacks token-level streaming |

The split exists because token-level streaming alongside tool calls is critical for real-time UX. OpenAI-compatible servers support it natively; litellm's abstraction layer doesn't expose it.

> **Constraint:** Thinking tokens (intermediate reasoning) are only captured on the OpenAI-compatible streaming path.

### Configuration (`LLMConfig` document)

```python
provider: str          # openai | anthropic | ollama | lm_studio | azure_openai | bedrock | vertex
api_key: str           # AES-256-GCM encrypted at rest (PBKDF2 from settings.secret_key)
model: str             # e.g., "gpt-4o", "claude-3-5-sonnet-20241022"
base_url: str | None   # Required for local providers; optional override for others
temperature: float     # Default 0.3
max_tokens_per_request: int  # Default 4096
context_window_tokens: int | None  # Override for auto-detection (default 20k)
canvas_prompt_tier: str | None     # "full" | "explicit" | "none" | None (auto-detect)
is_default: bool       # Singleton default config flag
```

**Factory pattern:** Always use `create_llm_service(config_id=None)` — never instantiate `LLMService` manually. The factory loads the config, decrypts the key, and applies provider-specific defaults.

### SSRF Protection

`validate_outbound_url()` blocks private/reserved/loopback IPs before any outbound HTTP. **Exception:** local providers (lm_studio, ollama, llama_cpp, vllm) explicitly bypass this check — they are expected to run on localhost.

---

## AI Agent Loop

The core intelligence is an iterative agentic loop in `agent_service.py`:

```
System prompt + user message
        │
        ▼
  ┌──────────────────────────────────────────────┐
  │  Iteration 1..N (max 25 server-side hard cap)│
  │                                              │
  │  1. Gather tools from all MCP clients        │
  │  2. Call LLM (stream + tools)                │
  │     └─ Each token → WS broadcast             │
  │  3. If tool_calls in response:               │
  │     a. WS broadcast: tool_start              │
  │     b. Call MCP tool → get result            │
  │     c. WS broadcast: tool_end                │
  │     d. Append tool result message            │
  │     e. Next iteration                        │
  │  4. If no tool_calls → break loop            │
  └──────────────────────────────────────────────┘
        │
        ▼
  AgentResult { status, result, tool_calls, thinking_texts }
```

**Iteration limit:** 10 per request (configurable, hard-capped at 25). If exceeded: `status = "max_iterations"`, partial result returned.

**Tool name routing:** The agent maintains a `tool_server_map` mapping each tool name to its MCP client. Duplicate names across servers are disambiguated by server prefix.

---

## MCP Server (In-Process)

The app runs a FastMCP server in-process. It is the default tool provider for every AI agent run, supplemented by any external MCP servers the user selects.

### Context Variables

Tool handlers need user/thread context without HTTP headers. This is solved via Python `contextvars`:

```python
mcp_user_id_var: ContextVar[str]   # Set before agent.run() for user-scoped tools
mcp_thread_id_var: ContextVar[str] # Set for thread-aware tools
elicitation_channel_var: ContextVar[str]  # WS channel for elicitation responses
```

> **Security:** All write tools must explicitly check `mcp_user_id_var` for ownership/role validation. The local path bypasses HTTP auth, so enforcement is at the tool level.

### HTTP MCP Endpoint

External clients (e.g., Claude Desktop) can connect to `POST /mcp`. This goes through `MCPAuthMiddleware` which validates the Bearer JWT before forwarding to FastMCP. The in-process path skips this entirely.

### Tools Reference

| Tool | Actions | Notes |
|------|---------|-------|
| `backup` | object_info, version_detail, compare, trigger, restore | Restore requires elicitation confirmation |
| `workflow` | list, get, create, update, delete, validate | Role + ownership enforced |
| `search` | backups, executions, webhook events | Paginated, date-filtered |
| `get_details` | backups, workflows, and more | Structured object info |
| `impact_analysis` | query sessions, get results | Read-only |
| `memory_store` | — | Upsert per-user key-value memory |
| `memory_recall` | — | Text search + category filter |
| `memory_forget` | — | Delete by key |
| `activate_skill` | — | Load skill content by name |

---

## Conversational Threads

### Data Model

```python
class ConversationThread(Document):
    user_id: PydanticObjectId
    feature: str          # "global_chat", "backup_summary", "workflow_assist", etc.
    context_ref: str | None  # ID of related object (backup version, workflow, etc.)
    messages: list[ConversationMessage]
    mcp_config_ids: list[str]  # External MCP servers active for this thread
    is_archived: bool

    # Compaction fields (original messages never modified)
    compaction_summary: str | None
    compacted_up_to_index: int | None
    compaction_in_progress: bool     # Optimistic lock

    created_at, updated_at: datetime  # 90-day TTL index
```

### Message Reconstruction

When building LLM context from a thread:
```
With compaction:    [system] + [first user msg] + [LLM compaction summary] + [last N messages]
Without compaction: [system] + sliding window of last N non-system messages
```

The original messages array is never altered. `compacted_up_to_index` tracks the boundary.

### Compaction Trigger

After each successful chat response, if `total_tokens > 70% of context_window`:
1. Acquire atomic lock (findOneAndUpdate)
2. Keep last 4+ non-system messages un-compacted
3. LLM summarizes the older messages
4. Store summary in `compaction_summary`
5. On failure: release lock, fall back to sliding window

---

## Memory System

### Storage

```python
class MemoryEntry(Document):
    user_id: PydanticObjectId
    key: str           # max 100 chars, unique per user
    value: str         # max 500 chars (configurable)
    category: str      # "general" | "network" | "preference" | "troubleshooting"
    source_thread_id: str | None

    created_at, updated_at: datetime  # 180-day TTL
```

**Per-user cap:** 100 entries (configurable via `SystemConfig.memory_max_entries_per_user`).

**TTL behavior:** `memory_recall` does NOT reset TTL. Entries age out regardless of access frequency. Consolidation can reset TTL by touching `updated_at` on "keep" actions.

### MCP Tools

The LLM can manage its own memory mid-conversation:

- **`memory_store(key, value, category)`** — upserts by `(user_id, key)`. Warns LLM if overwriting.
- **`memory_recall(query?, category?)`** — MongoDB text search on key+value. Returns max 30 entries.
- **`memory_forget(key)`** — deletes by exact key match.

The system prompt in global chat explicitly instructs the LLM when to store, recall, and forget. Users can view/edit/delete entries from their profile page.

### Consolidation ("Dreaming")

Weekly APScheduler job runs `consolidation_worker.run_consolidation()`:

```
For each user with 10+ memory entries:
  1. Load all entries
  2. Build prompt with key, value, category, age
  3. LLM returns JSON actions per entry:
     - "keep"   → touch updated_at (reset 180-day TTL)
     - "merge"  → combine related entries into one
     - "delete" → remove stale/contradictory entries
  4. Apply actions + log in MemoryConsolidationLog
```

The consolidation log is visible in the admin Memory panel, showing `entries_before / entries_after` and the LLM's reasoning for each action.

**Config:** `SystemConfig.memory_consolidation_enabled` + `SystemConfig.memory_consolidation_cron`.

---

## Skills System

Skills are markdown instruction files that get injected into the system prompt of the global chat.

### File Format (`SKILL.md`)

```markdown
---
name: network-troubleshooting
description: Helps troubleshoot Mist network issues with structured diagnostic steps
---

...skill instructions...
```

### Storage

```python
class Skill(Document):
    name: str             # From frontmatter (unique)
    description: str
    source: "direct" | "git"
    local_path: str       # Filesystem path to SKILL.md
    enabled: bool
    git_repo_id: PydanticObjectId | None
```

Skills are stored at `settings.skills_dir` (default `/data/skills`). Git-sourced skills are cloned/pulled via background jobs triggered from admin UI.

### Injection

`build_skills_catalog()` assembles a catalog string from all enabled skills. This is appended to the global chat system prompt. The LLM can call `activate_skill(name)` to load the full content of a skill on demand — the catalog lists name + description, the full body is loaded only when activated.

---

## Canvas Artifacts

The LLM can emit structured artifacts in responses using XML tags:

```xml
<artifact type="code" title="Switch config" language="json">
{
  "vlan_id": 100
}
</artifact>
```

Supported types: `code`, `markdown`, `html`, `mermaid`, `svg`, `chart`.

### Rendering Pipeline

1. `ArtifactParserService.parse()` extracts `<artifact>` tags, replaces them with `[artifact:{id}]` placeholders in prose
2. During streaming, `detectOpeningTag()` identifies artifact start, buffers content token-by-token
3. On closing tag, `ArtifactCardComponent` receives finalized content
4. Each artifact renders in a sandboxed `<iframe srcdoc>` with per-type templates and theme injection

**Auto-promotion:** Code blocks with 15+ lines that lack explicit `<artifact>` tags are automatically promoted to artifact cards.

### Canvas Prompt Tiers

Small/local models need more explicit instructions about when and how to emit artifacts. Three instruction tiers are applied automatically based on the provider+model:

| Tier | Instructions | Applied to |
|------|-------------|------------|
| `full` | Concise ruleset | Large cloud models (gpt-4, claude-opus, ...) |
| `explicit` | Verbose + examples | Small/local models |
| `none` | Disabled | Specific unsupported models |

Admins can override per-config via `LLMConfig.canvas_prompt_tier`.

---

## Elicitation (Tool Confirmations)

When an MCP tool needs user confirmation before proceeding (e.g., restore), it calls an elicitation helper:

```
MCP tool (e.g., backup.restore)
  └─ elicit_restore_confirmation(channel, description, diff_data)
       ├─ Generate request_id
       ├─ WS broadcast: {type: "elicitation", description, data: {diff, ...}}
       └─ Suspend until response

Frontend
  └─ pendingElicitation signal set
       ├─ Simple text card  (text confirmation)
       └─ RestoreDiffCard  (diff viewer)

User clicks Accept / Decline
  └─ POST /llm/elicitation/{requestId}/respond {accepted: bool}
       └─ MCP tool resumes or aborts
```

Two elicitation types are implemented:
- **Text confirmation** — generic yes/no prompt
- **Restore confirmation** — rich diff viewer showing exactly what config changes will be applied

---

## WebSocket Streaming

All streaming uses the existing `WebSocketService` on channel `llm:{stream_id}`.

### Event Types

| Event | Payload | Meaning |
|-------|---------|---------|
| `token` | `{content: str}` | Partial LLM response token |
| `thinking` | `{thinking: str}` | Intermediate reasoning (thinking mode) |
| `tool_start` | `{tool, server, arguments}` | Tool invocation starting |
| `tool_end` | `{tool, server, result_preview, is_error}` | Tool result received |
| `elicitation` | `{description, elicitation_type, data}` | Confirmation needed |
| `done` | `{content: str}` | Streaming complete, final text |

### Frontend Subscription

The `AiChatPanelComponent` calls `startStream(streamId)` **synchronously** (not via Angular effects). This is intentional — in zoneless mode, `effect()` can fire asynchronously and miss early WS events. The subscription is established before the HTTP request returns.

---

## Context-Aware Chat

The global chat is context-aware: when the user opens the panel from any page, the LLM automatically knows what they are looking at. This allows asking questions like "explain this workflow" or "what changed in this backup?" without copying anything manually.

### How It Works

```
Page Component (ngOnInit / data load)
  └─ GlobalChatService.setContext({ page, details })
       └─ Updates context signal

User opens global chat
  └─ GlobalChatComponent.sendFirst()
       └─ GlobalChatService.buildContextString()  → formatted text
            └─ Passed as page_context to POST /llm/chat

Backend (llm.py)
  └─ _sanitize_for_prompt(page_context, max_len=2000)
       └─ Appended to system prompt: "Current UI context:\n{safe_ctx}"
            └─ Special case: if "Workflow Editor" in context → also append
                             build_workflow_editor_context() (Jinja2 variable syntax reference)
```

**Context is only sent on the first message of a new thread.** Follow-up messages reuse the existing thread and don't re-inject context. The context is not persisted in the thread — it's ephemeral (set once at chat open).

### `PageContext` Interface

```typescript
interface PageContext {
  page: string;                           // e.g., "Workflow Editor", "Backup Object Detail"
  details?: Record<string, string | number | null>;  // Key facts about what the user sees
}
```

`buildContextString()` formats this as plain text:

```
The user is currently viewing: Workflow Editor
workflow_id: 64a1b2c3d4e5f6a7b8c9d0e1
workflow_name: AP Disconnect Alert
workflow_type: webhook
node_count: 5
trigger_topic: device-events
graph_summary: trigger [Webhook Trigger] → check_severity [Condition] → ...
selected_node: check_severity (condition)
selected_node_config: field: trigger.type, operator: equals, value: AP_DISCONNECTED
```

### Pages That Set Context

| Page | Context fields |
|------|----------------|
| **Dashboard** | `view: "System overview"` |
| **Workflow Editor** | `workflow_id`, `workflow_name`, `workflow_type`, `workflow_status`, `node_count`, `trigger_type`, `trigger_topic`, `graph_summary`; if a node is selected: `selected_node`, `selected_node_id`, `selected_node_config` |
| **Workflow List** | `view: "All workflows"` |
| **Webhook Monitor** | `view: "Live webhook events"` |
| **Backup Object Detail** | `object_type`, `object_name`, `object_id`, `versions` (version count) |
| **Impact Analysis — Session Detail** | `device`, `status` |
| **Impact Analysis — Session List** | `view: "Impact analysis sessions"` |

> Pages without `setContext()` calls leave the context signal `null`, so no context block is injected.

### Workflow Editor: Live Context Updates

The workflow editor updates context reactively — not just once on load. Two update triggers:

1. **Signal-based effect** — fires when `workflowId`, `workflowName`, or `selectedNode` signals change (e.g., user renames the workflow, clicks a different node)
2. **Debounced graph change subscriber** — fires 500ms after any graph edit (node add/remove/config change)

This means if the user edits a node config and then opens chat, the context already reflects the latest state — including the selected node's current config fields.

The `graph_summary` field is a compact human-readable representation of the entire graph:

```
trigger [Webhook Trigger] (device-events) → check_severity [Condition]
check_severity [Condition] → send_alert [Send Email], log_event [Audit Log]
```

### Backend Context Injection (`llm.py:1642-1646`)

```python
safe_ctx = _sanitize_for_prompt(request.page_context, max_len=2000) if request.page_context else None
if safe_ctx:
    system_prompt += f"\n\nCurrent UI context:\n{safe_ctx}"
    if "Workflow Editor" in safe_ctx:
        system_prompt += build_workflow_editor_context()
```

The 2000-char limit (vs the default 200 for other fields) is intentional — context strings can be long due to `graph_summary`. The sanitization still strips prompt injection markers.

The Workflow Editor special case appends the full Jinja2 variable syntax reference (trigger fields, node result paths, schedule fields). This prevents the LLM from inventing plausible-looking but wrong variable paths when helping with workflow configuration.

---

## Prompt Architecture

`prompt_builders.py` provides a function per feature context:

| Builder | Feature | Context injected |
|---------|---------|-----------------|
| `build_global_chat_system_prompt` | Global chat | User roles, workflow variable syntax, memory instructions, canvas rules, skills catalog |
| `build_backup_summary_prompt` | Backup diff | Diff entries, object type, version metadata |
| `build_workflow_assist_prompt` | Workflow generation | API categories, endpoint details (two-pass: select categories → generate workflow) |
| `build_field_assist_prompt` | Field suggestions | Field name + execution context |
| `build_debug_prompt` | Execution debug | Failed node details, input/output, error message |
| `build_webhook_summary_prompt` | Webhook monitor | Recent 24h events summary |
| `build_dashboard_summary_prompt` | Dashboard | Platform health metrics |
| `build_audit_log_summary_prompt` | Audit logs | Filtered log entries |
| `build_system_log_summary_prompt` | System logs | Filtered log entries |
| `build_backup_list_summary_prompt` | Backup list | Filtered backup objects |

**Prompt injection protection:** `_sanitize_for_prompt(value, max_len=200)` strips markdown control sequences (` ``` `, `---`, `***`) and truncates long values. Applied to all user-sourced fields before interpolation.

---

## API Endpoints Reference

### Global Chat
| Method | Path | Notes |
|--------|------|-------|
| POST | `/llm/chat` | New conversation (creates thread) |
| POST | `/llm/chat/{thread_id}` | Follow-up in existing thread |
| GET | `/llm/threads` | List user's threads |
| GET | `/llm/threads/{id}` | Thread detail + message history |
| DELETE | `/llm/threads/{id}` | Delete thread |
| POST | `/llm/elicitation/{id}/respond` | Respond to tool confirmation |

### Summarization (all POST)
`/llm/backup/summarize`, `/llm/webhooks/summarize`, `/llm/dashboard/summarize`, `/llm/audit-logs/summarize`, `/llm/system-logs/summarize`, `/llm/backups/summarize`

### Workflow Assistance
| Method | Path | Notes |
|--------|------|-------|
| POST | `/llm/workflow/select-categories` | Pass 1: category selection |
| POST | `/llm/workflow/assist` | Pass 2: workflow generation |
| POST | `/llm/workflow/field-assist` | Single field suggestion |
| POST | `/llm/workflow/debug` | Debug failed execution |

### LLM Config (admin only)
`GET/POST/PUT/DELETE /llm/configs`, `/llm/configs/{id}/set-default`, `/llm/configs/{id}/test`

### MCP Config (admin only)
`GET/POST/PUT/DELETE /mcp/configs`, `/mcp/configs/{id}/test`, `/mcp/local/tools`, `/mcp/local/tools/{name}/call`

### Skills (admin only)
`GET/POST /llm/skills`, `/llm/skills/{id}/toggle`, `/llm/skills/repos`

### Memory (user)
`GET /llm/memories`, `PUT /llm/memories/{id}`, `DELETE /llm/memories/{id}`, `DELETE /llm/memories`

### Rate Limiting
Per-user sliding window: 20 requests per 60 seconds. Applies to all `/llm/*` endpoints. Returns HTTP 429 when exceeded.

---

## Data Flow: Full Global Chat Request

```
1. User types message, selects MCP configs (optional)
2. Frontend generates stream_id (UUID), subscribes to WS channel llm:{stream_id}
3. POST /llm/chat {message, thread_id: null, page_context, stream_id, mcp_config_ids}

4. Handler:
   a. Rate limit check
   b. Load/create ConversationThread
   c. Load external MCP clients from mcp_config_ids
   d. Build system prompt (canvas rules, memory instructions, skills catalog, page context)
   e. Add user message to thread
   f. Create AIAgentService(llm, [local_mcp] + external_mcps)
   g. agent.run(task, system_prompt, callback=WS_broadcaster)

5. Agent loop (iterations):
   ├─ LLM streams response tokens → WS: {type: "token", content}
   ├─ LLM requests tool call:
   │   ├─ WS: {type: "tool_start", tool, arguments}
   │   ├─ MCP tool executes (may elicit confirmation via WS)
   │   └─ WS: {type: "tool_end", result_preview}
   └─ Loop until no tool_calls or iteration limit

6. WS: {type: "done", content: final_reply}

7. Handler post-processing:
   a. Save ConversationMessage (with tool_calls + thinking_texts in metadata)
   b. Log LLMUsageLog
   c. If tokens > 70% threshold: async compact_thread()
   d. Return {reply, thread_id, usage}

8. Frontend:
   a. Timeline renders messages, tool call cards, artifact cards
   b. User can reply → same flow with existing thread_id
```

---

## Key Design Decisions

### Why dual LLM paths (OpenAI SDK + litellm)?

Streaming with tool calls requires token-level events. The OpenAI SDK exposes this natively. litellm wraps providers but its streaming layer doesn't surface per-token events alongside tool call deltas. Maintaining two paths gives maximum provider compatibility without sacrificing UX quality on capable providers.

### Why in-process MCP instead of HTTP-only?

HTTP MCP requires the frontend to hold a connection open or the backend to poll. In-process execution uses Python contextvars to propagate user/thread context without any network overhead, enables synchronous elicitation (the tool can block waiting for user confirmation), and avoids auth complexity for same-process calls.

### Why compaction instead of truncation?

Simple truncation loses context — the LLM doesn't know what was discussed earlier. Compaction generates a rolling summary that preserves key facts. The original messages are never deleted, enabling audit and debugging. The lock mechanism prevents concurrent compaction races without adding a separate queue.

### Why 180-day TTL for memory with LLM consolidation?

Raw TTL-only would silently drop useful memories. LLM consolidation provides intentional curation: merging related entries, deleting stale/contradictory ones, and explicitly resetting TTL on entries worth keeping. The "dreaming" metaphor reflects how the system processes and organizes experiences after the fact.

### Why synchronous WS subscription in AiChatPanelComponent?

Angular's `effect()` runs asynchronously in zoneless mode. The HTTP request for the chat message and the first WS tokens can arrive before the effect fires, causing missed events. Calling `startStream()` synchronously before the HTTP call guarantees the subscription is established before any tokens arrive.
