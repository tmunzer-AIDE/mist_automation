# Impact Analysis UI Redesign — Chat-Style Session Detail

## Context

The current impact analysis session detail page uses a vertical stack of independent sections (progress, event timeline, SLE metrics table, validation expansion panels, AI assessment panel). This layout forces users to scroll between disconnected sections and doesn't convey the monitoring process as a coherent story. The AI assessment is a static block at the bottom rather than an interactive participant.

The goal: transform the detail page into a **split-view with a chat-like AI narrative** that tells the monitoring story in real-time, alongside a compact **data panel** for structured at-a-glance results. Users can ask the AI follow-up questions about the analysis.

## Design Decisions

| Question | Decision |
|----------|----------|
| Layout approach | Split view: chat panel (left) + data panel (right) |
| AI narrative style | Detailed conversational messages (not terse one-liners) |
| User interaction | Input bar at bottom of chat — questions go to LLM with full session context |
| No-LLM fallback | Same split layout, timeline entries as system messages, no input bar |
| Data panel sections | Progress, Config Changes, Validation Checks, SLE Metrics, Incidents |
| Completion display | Colored verdict banner between header and split view |
| Progress bar | Time-based (smooth, computed from `monitoring_started_at` → `monitoring_ends_at`), not step-based |

## Layout

```
┌─────────────────────────────────────────────────────────────┐
│ Header: [icon] device-name  [Status Badge] [Impact Badge]   │
│         Type • Site • Detected time              [Cancel]    │
├─────────────────────────────────────────────────────────────┤
│ ⚠ Verdict Banner (only when completed): summary + Re-analyze│
├────────────────────────────────┬────────────────────────────┤
│  CHAT PANEL (flex: 1)         │  DATA PANEL (340px)        │
│                                │                            │
│  [AI] Starting impact analysis │  PROGRESS                  │
│  for switch-lobby-01...        │  ████████░░ 65% (time)     │
│                                │  Ends ~3:35 PM             │
│  [AI] Baseline captured.       │                            │
│  6 SLE metrics recorded.       │  CONFIG CHANGES (1)        │
│                                │  SW_CONFIG_CHANGED_BY_USER │
│  ── 2:35 PM Config applied ── │  2:33 PM • admin@co.com    │
│                                │                            │
│  [AI] Validation complete —    │  VALIDATION CHECKS         │
│  2 warnings detected...        │  ✓ Connectivity            │
│                                │  ✓ Stability               │
│  [AI] Root cause identified... │  ⚠ Port Flapping           │
│                                │  ⚠ DHCP Health             │
│  [User] Are other APs          │                            │
│         affected?              │  SLE METRICS (3/6)         │
│                                │  Throughput 98%→95% ↓3%    │
│  [AI] Checking LLDP...         │  Health     100%→100% —    │
│  Only ge-0/0/3 has an AP.      │                            │
│                                │  INCIDENTS (0)             │
│  ── 2:45 PM SLE check 1/6 ── │  No incidents detected     │
│                                │                            │
├────────────────────────────────┤                            │
│ [Ask about this analysis... ↑] │                            │
└────────────────────────────────┴────────────────────────────┘
```

## Chat Panel

### Message Types

| Source | Type | Rendering |
|--------|------|-----------|
| AI narration | `ai_narration` timeline entry | AI avatar + bubble (left-aligned), timestamp above, markdown content |
| System event | `config_change`, `sle_check`, `webhook_event`, `status_change` | Centered inline divider: `── timestamp — event text ──` |
| Validation result | `validation` | AI avatar + bubble with amber/red left border, severity-colored timestamp |
| AI analysis result | `ai_analysis` | AI avatar + bubble with severity border, full markdown |
| User question | `chat_message` (role: user) | User avatar + bubble (right-aligned) |
| AI response to user | `chat_message` (role: assistant) | AI avatar + bubble (left-aligned), may include streaming tokens |

### Severity Styling

- **Warning**: Amber left border on bubble, amber timestamp color
- **Critical**: Red left border on bubble, red timestamp color
- **Info/None**: Default style (no colored border)

### User Input

- Text input with rounded border + send button
- Enter to send, Shift+Enter for newline
- Hidden when LLM is disabled
- Hidden when session is cancelled/failed
- Visible on completed sessions (user can still ask questions about the analysis)
- On send: generates `streamId`, subscribes to WS `llm:{streamId}`, calls `POST /impact-analysis/sessions/{id}/chat`
- Streaming tokens update the last AI bubble in real-time
- HTTP response finalizes the content

### No-LLM Mode

Same split layout. All timeline entries render as system messages (no AI avatar, no conversational tone). No input bar. Backend uses template strings instead of LLM-generated narration.

## Data Panel

Fixed 340px width. Scrollable. Sections appear progressively as data becomes available.

### Progress Section

- Phase label + percentage
- **Time-based progress bar**: Computed client-side from `monitoring_started_at` and `monitoring_ends_at` via `setInterval` (1s). Smooth linear interpolation.
- Before monitoring starts (PENDING, BASELINE_CAPTURE, AWAITING_CONFIG): indeterminate mode
- After monitoring starts: determinate, time-based
- "Started [time]" and "Ends ~[time]" labels
- "X min remaining" countdown

### Config Changes Section

Compact list of `config_changes[]` entries. Each shows: event type, timestamp, commit user.

### Validation Checks Section

Compact list (no expansion panels). Each check: name + pass/warn/fail icon. Overall status badge in section header. Details appear in the chat narration instead.

### SLE Metrics Section

Compact rows: Metric | Baseline → Current | Delta (colored). Poll count in header. Before first SLE poll: show baseline info with metric count.

### Incidents Section

List of incidents with severity icon, type, timestamp, resolved status. "No incidents" placeholder when empty.

## Header

Compact single-line header (unchanged from current except layout tweaks):
- Device type icon + device name (or MAC)
- Device type + site name + detected timestamp
- Status badge + impact severity badge
- Cancel button (when active)

## Verdict Banner

Appears between header and split view only when session is completed:
- Background color by severity (green/blue/amber/red)
- Icon + one-line summary text (first ~200 chars of AI assessment summary)
- Re-analyze button on the right

## Backend Changes

### New Timeline Entry Types

Add to `TimelineEntryType` enum:
- `AI_NARRATION` — AI-generated phase narration messages
- `CHAT_MESSAGE` — User questions and AI responses

### New Field on MonitoringSession

`conversation_thread_id: str | None` — Links to a `ConversationThread` for the session chat.

### New Endpoint: `POST /impact-analysis/sessions/{id}/chat`

Request: `{ message: str, stream_id: str | None }`
Response: `{ reply: str, thread_id: str, usage: dict }`

Behavior:
1. Load session (404 if not found)
2. Get or create `ConversationThread` (feature: `impact_analysis_chat`, stored in `session.conversation_thread_id`)
3. Build system prompt with current session data (device info, timeline, validation, SLE, config changes, incidents)
4. Add user message to thread
5. Run AI agent with MCP tools (uses in-process MCP client for app data access)
6. Store assistant response in thread
7. Append two `CHAT_MESSAGE` timeline entries (user + assistant) so other WS clients see them
8. Return response

Thread reuse: Subsequent messages reuse the same thread. System prompt is refreshed with latest session data on each call.

### AI Narration in Monitoring Pipeline

Add `_narrate_phase()` calls at each major phase transition in `monitoring_worker.py`:
1. Baseline capture starting
2. Baseline captured (with metric count)
3. Awaiting config
4. Config applied / monitoring started
5. Each SLE snapshot (with degradation status)
6. Validation complete (with overall status + issues found)
7. AI analysis complete (with brief finding)
8. Session complete (with final verdict)

When LLM available: Generate 1-2 sentence conversational text (low token limit: max_tokens=150).
When LLM unavailable: Use template strings.

### Thread Service Extraction

Extract `_load_or_create_thread` from LLM router into `backend/app/modules/llm/services/thread_service.py` so both LLM router and impact analysis router can reuse it.

## Files to Create

| File | Description |
|------|-------------|
| `frontend/.../session-detail/impact-chat-panel.component.ts` | Chat panel component (template + styles inline or separate) |
| `frontend/.../session-detail/impact-data-panel.component.ts` | Data panel component |
| `backend/.../llm/services/thread_service.py` | Extracted thread management helpers |

## Files to Modify

| File | Changes |
|------|---------|
| `backend/.../impact_analysis/models.py` | Add `AI_NARRATION`, `CHAT_MESSAGE` types; add `conversation_thread_id` field |
| `backend/.../impact_analysis/schemas.py` | Add `SessionChatRequest`, `SessionChatResponse` |
| `backend/.../impact_analysis/router.py` | Add `POST /sessions/{id}/chat` endpoint |
| `backend/.../impact_analysis/workers/monitoring_worker.py` | Add `_narrate_phase()` calls at each transition |
| `backend/.../llm/router.py` | Refactor to use extracted thread service |
| `frontend/.../impact-analysis/models/impact-analysis.model.ts` | Add `ChatMessage` interface |
| `frontend/.../core/services/impact-analysis.service.ts` | Add `sendChatMessage()` method |
| `frontend/.../session-detail/session-detail.component.ts` | Rewrite: split layout, chat message mapping, time-based progress |
| `frontend/.../session-detail/session-detail.component.html` | Rewrite: header + verdict + split view |
| `frontend/.../session-detail/session-detail.component.scss` | Rewrite: split layout styles, remove old section styles |

## Verification

1. Create a monitoring session and observe narration entries appearing in real-time in the chat panel
2. Send a user question during active monitoring and verify streaming AI response
3. Verify data panel sections update live via WebSocket
4. Verify time-based progress bar moves smoothly between WS updates
5. Verify verdict banner appears on completion with correct severity color
6. Test with LLM disabled: template narration, no input bar, same layout
7. Test responsive stacking below 900px viewport width
8. Verify dark theme compatibility
