# AI-Centered UI Design

## Overview

Transform the Mist Automation UI from a traditional dashboard-with-AI-sidebar into an AI-first interface where the LLM assistant is the primary interaction point. The AI panel is persistent, context-aware, and deeply integrated with every feature area.

## Goals

1. Make AI the first thing users see and interact with -- not a hidden FAB in the corner
2. Deep contextual integration: AI understands on-screen data and can drive page actions
3. Precompute insights at event time to minimize LLM cost (especially important for local LLM deployments)
4. Rework the workflow editor to leverage the new split layout

## Non-Goals

- Proactive auto-triggering of LLM across the board (cost concern)
- Actionable insight cards with embedded buttons (future evolution from uniform cards)
- Voice or multimodal interaction
- Multi-org context

## Constraints

- **LLM cost sensitivity**: The app is tested and used with local LLMs (e.g., LM Studio) which can be slow. Minimize on-the-fly LLM calls. Prefer precomputed insights stored at event time.
- **Local LLM latency**: UI must remain responsive even when LLM calls take several seconds. All LLM-dependent features need loading states and graceful degradation.

## Phasing

| Phase | Scope | Depends On |
|-------|-------|------------|
| Phase 1 -- Foundation | Persistent split layout, resizable panel, thread history, remove FAB + `/ai-chats` | Nothing |
| Phase 2 -- Intelligence | Action commands, LLM greeting, inline insight cards, precompute pipeline, LLM usage monitoring | Phase 1 |
| Phase 3 -- Editor Rework | Workflow editor redesign with config-in-panel, tabbed AI panel, inline AI generation | Phase 1 + 2 |

---

## Phase 1: Persistent Split Layout

### App Shell Structure

The layout changes from `sidebar + full-width content` to `sidebar + split(AI panel | resize handle | content)`.

```
+-------+------- resize --------+------------------------------+
| Side  | AI Panel    |  handle |  Page Content                |
| bar   |             |    ||   |  (router-outlet)             |
|       | [header]    |    ||   |                              |
| [D]   | [context]   |    ||   |                              |
| [W]   | [messages]  |    ||   |                              |
| [R]   | [input]     |    ||   |                              |
+-------+-------------+---------+------------------------------+
```

### AI Panel Component (`AiPanelComponent`)

Replaces `GlobalChatComponent` (FAB) and absorbs the `/ai-chats` page functionality.

**Dimensions:**
- Default width: ~380px
- Resizable via drag handle: range 280px to 60% of viewport
- Collapse/expand: button in panel header + keyboard shortcut (`Ctrl+\`)
- Per-page width and collapsed state persisted in localStorage
- Smart defaults: open on dashboard, open on most pages, collapsed on workflow editor (until Phase 3)

**Sections (top to bottom):**

1. **Header**: AI icon + "Assistant" label + thread controls (new chat button, history toggle button)
2. **Context breadcrumb**: Subtle bar showing current page context (e.g., "Viewing: Backups > site-NYC > wlans"). Updated via existing `GlobalChatService.setContext()` calls.
3. **Thread history drawer**: Slides over chat content when history toggle is clicked. Threads grouped by date (Today / Yesterday / Previous 7 days / Older), filterable by feature tag. Click to resume thread, delete button per thread. Replaces the need for `/ai-chats` page.
4. **Chat area**: Reuses existing `AiChatPanel` component. Markdown rendering, tool call timeline, WebSocket streaming, elicitation cards -- all preserved.
5. **Input bar**: Text input + MCP server toggle + send button. Same as current global chat input.

### Thread Behavior

- **User-controlled**: Conversation persists across page navigation by default. The AI automatically picks up page context via `setContext()` but does not force thread switches.
- User can explicitly start a new thread (button) or resume a past thread (from history drawer).
- Thread history in the drawer replaces the `/ai-chats` page entirely.

### Removals

- `GlobalChatComponent` (FAB + popup panel) -- replaced by `AiPanelComponent`
- `/ai-chats` route and its navigation sidebar entry
- `AiChatsComponent` -- functionality absorbed into the panel's thread history drawer

### Preserved

- `AiChatPanel` component -- reused inside `AiPanelComponent`
- `GlobalChatService` -- context awareness, `setContext()` calls from all pages remain
- All LLM endpoints, thread management, MCP integration
- `AiIcon` component

### No-LLM Fallback

When LLM is disabled (`SystemConfig.llm_enabled = false`):
- The AI panel is hidden entirely
- Layout reverts to `sidebar + full-width content` (current behavior)
- No persistent split, no resize handle
- All existing feature pages work unchanged

---

## Phase 2: Intelligence Layer

### Action Command System

The AI can drive page state through a fixed vocabulary of structured commands returned alongside text responses.

**Backend changes:**
- Chat response schema gains an optional `commands: ActionCommand[]` field
- System prompt updated to teach the LLM available commands per page context
- Command set is context-dependent: backend includes only commands valid for the current page in the prompt

**Command vocabulary:**

| Command | Params | Effect |
|---------|--------|--------|
| `navigate` | `route: string`, `queryParams?: Record<string, string>` | Angular router navigation |
| `filter` | `field: string`, `value: string` | Apply filter on current list/table view |
| `highlight` | `nodeId?: string`, `elementId?: string` | Highlight element on current page |
| `select` | `itemId: string` | Select item in list or table |
| `expand` | `sectionId: string` | Expand collapsed section or panel |
| `open_dialog` | `dialogType: string`, `params?: Record<string, any>` | Open specific dialog |

**Frontend changes:**
- New `ActionCommandService` validates commands against a whitelist and dispatches to the current page
- Pages register supported commands via a `CommandHandler` interface
- Invalid or unsupported commands are silently ignored (no error to user)
- Commands render as subtle "action taken" indicators in the chat (e.g., "Navigated to backup detail")

**Safety:**
- Commands are validated against the fixed whitelist before execution
- Write operations (restore, delete, execute workflow) remain as MCP tool calls with elicitation prompts -- never as commands
- Command params validated (e.g., `navigate` route must match a known app route)

### LLM Dashboard Greeting

On login or new chat thread creation:

1. Backend gathers structured state data: failed workflows (24h), active impact sessions, backup drift count, pending reports, recent alerts
2. Data passed to LLM with a greeting prompt instructing it to summarize, prioritize, and suggest next actions
3. Response is the first message in the thread, with action commands rendered as clickable chips
4. Cached per session -- navigating away and back shows the same greeting
5. No-LLM fallback: static welcome message with structured data rendered as a formatted card

**New endpoint:** `GET /llm/greeting` -- gathers data + calls LLM, returns greeting text + commands. Called once per session by the frontend.

### Inline AI Insight Cards

**New component:** `AiInsightCardComponent`

Uniform style across all pages:
- Subtle gradient background (matching AI panel aesthetic)
- AI icon + insight type label + optional severity badge (info/warning/critical)
- Summary text (markdown)
- "Ask more" button: focuses chat panel, pre-fills context about this insight
- "Generated at" timestamp footer
- Loading skeleton state while fetching
- "Get AI insight" button state when no precomputed insight exists

**New model:** `AiInsight` Beanie Document

```python
class AiInsight(Document, TimestampMixin):
    entity_type: str          # "workflow_execution", "backup_version", "impact_session", "report"
    entity_id: str            # ID of the related entity
    insight_type: str         # "change_analysis", "execution_summary", "impact_assessment", "findings"
    content: str              # Markdown text
    severity: str | None      # "info", "warning", "critical", or None
    generated_at: datetime
    llm_config_id: str | None # Which LLM config was used
```

**Precompute pipeline -- insights generated at event time:**

| Event | Insight Type | Trigger Point |
|-------|-------------|---------------|
| Backup version created | `change_analysis` | After backup save, diff computed, LLM summarizes changes |
| Workflow execution completes | `execution_summary` | After execution finishes (success or failure), LLM summarizes outcome |
| Impact session completes | `impact_assessment` | Already exists as AI analysis -- stored as `AiInsight` too |
| Report job completes | `findings_summary` | After validation finishes, LLM summarizes findings |

**API:**
- `GET /insights?entity_type=&entity_id=` -- fetch stored insight for an entity
- `POST /insights/generate` -- on-demand generation for entities without precomputed insights
- Insights cleaned up on the same nightly schedule as executions/sessions

**Pages that display insight cards (Phase 2):**
- Backup object detail: change analysis between latest versions
- Execution detail: root cause / success summary
- Impact session detail: AI assessment (re-rendered as standard card)
- Report detail: findings summary

### Cost Control Strategy

- **Precompute at event time**: Insights generated when events naturally occur, stored in DB. Displaying them costs zero LLM calls.
- **On-demand fallback**: Old entities (pre-feature) show "Get AI insight" button. User clicks = one LLM call, result stored for future views.
- **Greeting cached per session**: One LLM call on login, not per dashboard visit.
- **Action commands are free**: Structured output from existing chat calls, no extra LLM invocation.
- **Admin-configurable**: Precompute can be disabled per insight type in admin settings if LLM costs need further reduction.

### LLM Token Usage Monitoring (Admin)

Admin dashboard panel for monitoring LLM cost and usage patterns. Built on the existing `LLMUsageLog` model (already tracks `user_id`, `feature`, `model`, `provider`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `duration_ms`).

**Enhanced `LLMUsageLog` fields:**
- `source: str` -- which feature triggered the call (e.g., `greeting`, `global_chat`, `insight_precompute`, `workflow_assist`, `backup_summary`, `impact_analysis`, `execution_debug`)
- `trigger: str` -- `user_initiated` or `automated` (precompute, impact analysis auto-trigger, etc.)
- `insight_type: str | None` -- links to `AiInsight.insight_type` when the call was for insight generation

**Admin UI (`features/admin/settings/llm-usage/`):**

Dashboard with:
- **Total token consumption** over time (line chart, configurable range: 24h / 7d / 30d)
- **Breakdown by source**: Which features consume the most tokens (bar chart or table)
- **Breakdown by trigger**: Automated vs. user-initiated ratio (pie or stacked bar)
- **Breakdown by user**: Per-user consumption (table, sortable)
- **Breakdown by LLM config/model**: Cost per model when using multiple providers
- **Average latency per source**: Helps identify slow local LLM calls
- **Token budget alerts**: Optional threshold setting -- warn admin when daily/monthly usage exceeds a configurable limit

**API:**
- `GET /admin/llm/usage/summary?range=24h|7d|30d` -- aggregated usage stats
- `GET /admin/llm/usage/breakdown?group_by=source|trigger|user|model&range=` -- grouped breakdown
- `GET /admin/llm/usage/timeseries?range=&interval=1h|1d` -- time-series data for charts

**Cost estimation**: For cloud providers with known pricing (OpenAI, Anthropic), display estimated cost alongside token counts. For local LLMs, show tokens + latency only.

---

## Phase 3: Workflow Editor Rework

### Layout Change

**Current:** `sidebar | canvas + right config panel + bottom simulation panel`
**New:** `sidebar | AI panel (tabbed) | canvas`

The right config panel and bottom simulation panel are removed. Their functionality moves into the AI panel's tabbed interface.

### AI Panel Tabs (Editor Mode)

When on the workflow editor route, the AI panel switches to a tabbed layout:

1. **Config tab**: Node configuration form. Activates automatically when a node is selected on canvas. Contains all current config fields, variable picker, advanced options (Save As, Error Handling). Same form fields as today, relocated.
2. **Chat tab**: Conversation with full workflow context. AI knows the graph structure, node types, execution history. Can suggest nodes, debug Jinja2 expressions, explain errors. Workflow AI generation (currently a modal dialog) becomes an inline flow here.
3. **Simulation tab**: Simulation controls, payload picker, step-by-step replay, per-node results and logs. Replaces the current bottom panel.

### Canvas Changes

- Takes all remaining width after sidebar + AI panel (no right config panel)
- Bottom simulation panel removed (moved to Simulation tab)
- Palette sidebar (node type drag-and-drop) remains as a thin overlay on the canvas left edge (unchanged from today)
- The AI panel defaults to open (not collapsed) since it now hosts essential editor functionality

### Interaction Patterns

| Action | Result |
|--------|--------|
| Click node on canvas | AI panel switches to Config tab, loads node form |
| Double-click node | Same + expands panel if collapsed |
| Right-click node | Context menu with "Ask AI about this node" (switches to Chat tab with node context) |
| Run simulation | AI panel switches to Simulation tab |
| Deselect node | Config tab shows workflow-level settings (name, description, tags) |

### Workflow AI Generation

The current `WorkflowAiDialogComponent` (modal with multi-step flow: description → categories → generation → refinement) is replaced by an inline conversation in the Chat tab:
- User describes the workflow in the chat
- AI generates nodes directly onto the canvas
- Refinement is natural follow-up messages in the same thread
- No modal needed

### Removals (Phase 3)

- `WorkflowAiDialogComponent` (modal) -- replaced by inline chat generation
- Right config panel component -- form moves into Config tab
- Bottom simulation panel -- moves into Simulation tab

---

## Technical Architecture

### New Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `AiPanelComponent` | `shared/components/ai-panel/` | Persistent split panel with chat, thread history, resize |
| `AiInsightCardComponent` | `shared/components/ai-insight-card/` | Uniform inline insight card |
| `ActionCommandService` | `core/services/` | Validates and dispatches AI action commands |
| `PanelStateService` | `core/services/` | Persists panel width/collapsed state per page |
| `LlmUsageDashboardComponent` | `features/admin/settings/llm-usage/` | Token usage monitoring admin panel |

### New Backend Models

| Model | Purpose |
|-------|---------|
| `AiInsight` | Stored precomputed LLM insights for entities |

### New Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /llm/greeting` | Generate situational greeting (cached per session) |
| `GET /insights` | Fetch stored insights by entity type + ID |
| `POST /insights/generate` | On-demand insight generation |
| `GET /admin/llm/usage/summary` | Aggregated LLM usage stats |
| `GET /admin/llm/usage/breakdown` | Grouped breakdown by source/trigger/user/model |
| `GET /admin/llm/usage/timeseries` | Time-series data for usage charts |

### Modified Components

| Component | Change |
|-----------|--------|
| `LayoutComponent` | Split layout with AI panel instead of full-width content |
| `AiChatPanel` | Reused inside `AiPanelComponent`, no changes needed |
| Chat response schema | Add optional `commands` field |
| System prompts | Add command vocabulary per page context |
| Feature pages (backup detail, execution detail, etc.) | Add `AiInsightCardComponent` + register `CommandHandler` |
| `LLMUsageLog` model | Add `source`, `trigger`, `insight_type` fields |
| All LLM call sites | Pass `source` and `trigger` to usage logging |

### WebSocket Channels

No new channels needed. Existing channels (`report:*`, `impact:*`, `workflow:*`) continue to work. The AI panel subscribes to the same streaming channels as the current global chat.
