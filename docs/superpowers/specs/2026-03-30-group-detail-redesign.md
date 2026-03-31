# Group Detail Page Redesign

## Problem

The current group detail page has three issues:
1. The timeline is overwhelmingly long — every event for every device appears as a flat list (e.g., "SLE check 1/6" x3 devices = 18 entries for one poll cycle)
2. Summary cards show only 3 basic numbers with no context
3. Everything stacks vertically with no information hierarchy

## Solution

Redesign the group detail page to match the session detail's split-view pattern: chat panel (left) + data panel (right). Timeline events become chat messages (narration), and the data panel becomes a compact scrollable dashboard.

## Architecture

### Layout

Same split-view as `SessionDetailComponent`:
- Header with breadcrumb, title, status/impact badges, meta info, action buttons
- Verdict banner (when completed, same pattern as session detail)
- Split-view:
  - **Left**: `ImpactChatPanelComponent` (reused, extended with `groupId` input)
  - **Right**: New `GroupDataPanelComponent` (340px, scrollable)

### Components

#### 1. `ImpactChatPanelComponent` — extend for group support

Add an optional `groupId` input alongside the existing `sessionId`. When `groupId` is set, the `send()` method calls `impactService.sendGroupChatMessage(groupId, ...)` instead of `sendChatMessage(sessionId, ...)`.

Both inputs remain `input.required` → change to `input<string>('')` (optional with empty default). The component checks which one is set and routes accordingly. At least one must be non-empty.

#### 2. `GroupDataPanelComponent` — new component

Mirrors `ImpactDataPanelComponent` but shows group-level aggregate data. Single-file standalone component with inline template and styles.

**Input**: `group: ChangeGroupDetailResponse`

**Sections** (same visual pattern as the session data panel — section headers with dividers):

1. **Status** — Group status pill, two mini stat cards (total devices / impacted count), per-device-type breakdown (e.g., "Switch: 3 completed")
2. **Devices** — Compact list with device icon, name, and impact/status badge. Clickable rows navigate to session detail via `Router`. Count badge in header.
3. **Validation** — Aggregate pass/fail/skip per check type. Overall status pill. Same `check-row` pattern as session data panel.
4. **SLE Metrics** — Aggregate SLE deltas. Same `sle-row` pattern as session data panel with baseline → current → delta display.

#### 3. `GroupDetailComponent` — rewrite template

Replace the vertical-stacking `detail-body` with the session detail's split-view layout.

**Header**: Keep current header (back button, layers icon, title, status/impact badges, triggered_by/timestamp/device-count meta, cancel/re-analyze actions).

**Verdict banner**: Add the same verdict banner as session detail, shown when completed. Severity-colored left border with icon + summary text + re-analyze button.

**Split-view**: Chat panel (left, flex: 1) + GroupDataPanel (right, 340px).

**Timeline → Chat messages**: Use the same `_timelineToChat()` conversion as `SessionDetailComponent`. The group timeline already contains aggregated events from all child sessions (with `device_name` field). The conversion maps:
- `ai_narration` → AI message (role: 'ai', type: 'narration')
- `ai_analysis` → AI message (role: 'ai', type: 'analysis'), uses full `ai_assessment.summary`
- `chat_message` → User or AI message (role from `data.role`)
- `status_change` → skipped (narrations cover these)
- Everything else → system event divider

**WebSocket**: Keep current subscription to `impact:group:{groupId}`. On any update event, call `loadGroup()` to refresh both panels and chat messages.

**LLM status**: Check `LlmService.getStatus()` on init and pass `llmEnabled` to chat panel (same as session detail).

### Verdict summary computation

New `verdictSummary` computed signal on `GroupDetailComponent`:
- Validation: count failed checks across all devices from `summary.validation_summary` (any check with `failed > 0`)
- Incidents: count from `summary.devices` active incidents
- SLE: check `summary.sle_summary` for any degraded metrics (delta_pct < -5)
- Combine into a summary string like session detail

### Files to modify

| File | Action |
|------|--------|
| `frontend/src/app/features/impact-analysis/group-detail/group-detail.component.ts` | Rewrite: split-view layout, chat integration, verdict banner |
| `frontend/src/app/features/impact-analysis/session-detail/impact-chat-panel.component.ts` | Modify: add optional `groupId` input, route send() accordingly |
| `frontend/src/app/features/impact-analysis/group-detail/group-data-panel.component.ts` | Create: new data panel component |

### No backend changes needed

The existing endpoints and WebSocket channels already support everything needed:
- `GET /groups/{id}` returns `ChangeGroupDetailResponse` with timeline, summary, ai_assessment
- `POST /groups/{id}/chat` handles group chat
- `impact:group:{groupId}` WebSocket channel broadcasts updates
- `llm:stream` WebSocket channel handles token streaming
