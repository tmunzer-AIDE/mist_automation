# Unified AI Summary Pattern

## Overview

Extend the inline "AI Summary" pattern (proven in webhook monitor) to dashboard, backup compare, audit logs, system logs, and backup list. Extract a shared component to eliminate duplication and ensure visual consistency.

## Goals

1. Every data-heavy page gets a contextual AI summary button in the topbar
2. Summaries open inline (not a separate chat), with follow-up capability
3. Shared component eliminates copy-paste markup across 6+ pages
4. Consistent visual treatment across all pages

## Non-Goals

- Proactive/auto-triggered summaries (all user-initiated)
- Streaming token output for summaries (simple completion is fine — summaries are short)
- MCP tool use in summaries (except dashboard, which needs live data queries)

## Constraints

- LLM cost sensitivity: one LLM call per button click, no background calls
- Local LLM latency: loading state must be clear, UI responsive during wait

---

## Shared Component: `AiSummaryPanelComponent`

**Location:** `frontend/src/app/shared/components/ai-summary-panel/ai-summary-panel.component.ts`

Encapsulates the container chrome around `AiChatPanel`. Pages just wire signals.

### Inputs/Outputs

```typescript
open = input(false);              // show/hide
summary = input<string | null>(null);  // initial LLM response
error = input<string | null>(null);    // error message
loading = input(false);           // loading state
threadId = input<string | null>(null); // for follow-ups
loadingLabel = input('Analyzing...');  // contextual loading text

closed = output<void>();          // emits when user clicks close
```

### Template

```html
@if (open()) {
  <div class="ai-summary-panel" [@slideDown]>
    <div class="panel-close">
      <button mat-icon-button (click)="closed.emit()" matTooltip="Close">
        <mat-icon>close</mat-icon>
      </button>
    </div>
    <app-ai-chat-panel
      [threadId]="threadId()"
      [initialSummary]="summary()"
      [errorMessage]="error()"
      [parentLoading]="loading()"
      [loadingLabel]="loadingLabel()"
    ></app-ai-chat-panel>
  </div>
}
```

### Styling

```scss
.ai-summary-panel {
  margin-bottom: 16px;
  border-radius: 12px;
  border: 1px solid var(--mat-sys-outline-variant);
  overflow: hidden;
  background: var(--mat-sys-surface);
  max-height: 50vh;
  display: flex;
  flex-direction: column;
}

.panel-close {
  display: flex;
  justify-content: flex-end;
  padding: 4px 4px 0 0;
  flex-shrink: 0;
}
```

### Animation

CSS slide-down via Angular `@trigger` animation:
- Enter: `max-height: 0; opacity: 0` → `max-height: 50vh; opacity: 1` over 200ms ease
- Leave: reverse

---

## Standardized Topbar Button

Global style in `styles.scss`:

```scss
.ai-summary-btn {
  margin-left: 8px;
  font-size: 13px;
}
```

Every page uses the same `ng-template` pattern:

```html
<ng-template #topbarActions>
  <!-- ...existing page actions... -->
  @if (llmAvailable()) {
    <button mat-stroked-button (click)="summarize()" [disabled]="aiLoading()" class="ai-summary-btn">
      <app-ai-icon [size]="16" [animated]="false"></app-ai-icon> AI Summary
    </button>
  }
</ng-template>
```

---

## Per-Page Integration

### Webhook Monitor (refactor existing)

**Frontend:** Replace inline `.ai-summary-container` markup with `<app-ai-summary-panel>`. Remove `.ai-summary-container`, `.ai-summary-topbar`, `.ai-summary-title` styles. Keep topbar button as-is (already correct pattern).

**Backend:** No change — existing `POST /llm/webhooks/summarize`.

### Dashboard (replace "Analyze Incidents")

**Frontend:** Remove "Analyze Incidents" button from hero card. Add topbar "AI Summary" button. Add `<app-ai-summary-panel>` at top of page (above welcome card). Add AI state signals + `summarize()` method. Remove `analyzeIncident()` method and `GlobalChatService.open()` call.

**Backend:** New `POST /llm/dashboard/summarize`.
- Gathers: dashboard stats (users, workflows, executions, webhooks, backups, reports, impact), highlights, recent failures, active incidents
- Uses MCP agent (needs to query live data via app MCP tools)
- Returns `{ summary, thread_id, usage }`

### Backup Object Detail — Compare Mode (improve visibility)

**Frontend:** Remove the tiny `mat-icon-button` from the compare header. Add topbar "AI Summary" button (only visible when `compareMode()` is true). Replace inline `.ai-chat-container` markup with `<app-ai-summary-panel>`. Remove `.ai-chat-container`, `.ai-chat-topbar`, `.ai-chat-title` styles.

**Backend:** No change — existing `POST /llm/backup/summarize`.

### Audit Logs (new)

**Frontend:** Add topbar "AI Summary" button. Add `<app-ai-summary-panel>` above the table. Add AI state signals. `summarize()` sends current filter form values to backend.

**Backend:** New `POST /llm/audit-logs/summarize`.
- Request: `{ event_type?: string, user_id?: string, start_date?: string, end_date?: string }`
- Queries matching audit log entries from MongoDB (up to 500 most recent)
- Builds prompt: "Analyze these audit log entries. Identify patterns, anomalies, security concerns, and notable activity."
- Returns `{ summary, thread_id, usage }`

### System Logs (new)

**Frontend:** Add topbar "AI Summary" button. Add `<app-ai-summary-panel>` above the log list. Add AI state signals. `summarize()` sends current filter values to backend.

**Backend:** New `POST /llm/system-logs/summarize`.
- Request: `{ level?: string, logger?: string }`
- Queries matching log entries (up to 500 most recent)
- Builds prompt: "Analyze these system logs. Identify error patterns, recurring issues, performance concerns, and anything requiring attention."
- Returns `{ summary, thread_id, usage }`

### Backup List (new)

**Frontend:** Add topbar "AI Summary" button. Add `<app-ai-summary-panel>` above the table. Add AI state signals. `summarize()` sends current filter values to backend.

**Backend:** New `POST /llm/backups/summarize`.
- Request: `{ object_type?: string, site_id?: string, scope?: string }`
- Queries: backup object summaries (stale objects, version counts) + recent job stats (failures, success rates)
- Builds prompt: "Analyze backup health and change activity. Identify objects with stale backups, repeated failures, unusual change patterns, and overall backup coverage."
- Returns `{ summary, thread_id, usage }`

---

## Backend Architecture

### New Endpoints (3)

All in `backend/app/modules/llm/router.py`, following the `summarize_webhook_events` pattern:

1. `POST /llm/dashboard/summarize` — `require_automation_role`
2. `POST /llm/audit-logs/summarize` — `require_admin`
3. `POST /llm/system-logs/summarize` — `require_admin`
4. `POST /llm/backups/summarize` — `require_backup_role`

### New Context Functions

In `backend/app/modules/llm/services/context_service.py`:

- `get_dashboard_summary_context()` — aggregates stats from all modules
- `get_audit_log_summary_context(filters)` — queries audit logs with filters
- `get_system_log_summary_context(filters)` — queries system logs with filters
- `get_backup_summary_context(filters)` — queries backup objects + job stats

### New Prompt Builders

In `backend/app/modules/llm/services/prompt_builders.py`:

- `build_dashboard_summary_prompt(context)`
- `build_audit_log_summary_prompt(logs, filters)`
- `build_system_log_summary_prompt(logs, filters)`
- `build_backup_summary_prompt(objects, jobs, filters)`

### New Request/Response Schemas

In `backend/app/modules/llm/schemas.py`:

```python
class DashboardSummaryRequest(BaseModel):
    stream_id: str | None = None

class AuditLogSummaryRequest(BaseModel):
    event_type: str | None = None
    user_id: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    stream_id: str | None = None

class SystemLogSummaryRequest(BaseModel):
    level: str | None = None
    logger: str | None = None
    stream_id: str | None = None

class BackupSummaryRequest(BaseModel):
    object_type: str | None = None
    site_id: str | None = None
    scope: str | None = None
    stream_id: str | None = None
```

Response: all reuse existing `SummaryResponse` (`summary`, `thread_id`, `usage`) or `WebhookSummaryResponse` pattern.

### Frontend LlmService Additions

In `frontend/src/app/core/services/llm.service.ts`:

```typescript
summarizeDashboard(): Observable<SummaryResponse>
summarizeAuditLogs(filters: AuditLogFilters): Observable<SummaryResponse>
summarizeSystemLogs(filters: SystemLogFilters): Observable<SummaryResponse>
summarizeBackups(filters: BackupFilters): Observable<SummaryResponse>
```

---

## Migration: Existing Pages

The webhook monitor and backup detail already have working AI summaries. They get refactored to use the shared component:

1. **Webhook Monitor:** Delete `.ai-summary-container`/`.ai-summary-topbar`/`.ai-summary-title` markup and styles. Replace with `<app-ai-summary-panel>`. Keep button and `summarizeWithAI()` method.

2. **Backup Detail:** Delete `.ai-chat-container`/`.ai-chat-topbar`/`.ai-chat-title` markup and styles. Replace with `<app-ai-summary-panel>`. Move button from inline icon to topbar action. Keep `summarizeChanges()` method.

---

## Preserved

- Floating FAB chat (`GlobalChatComponent`) — unchanged, still available for general questions
- `/ai-chats` page — unchanged
- Impact Analysis inline chat — unchanged (it's a different pattern, page-specific)
- Workflow simulation "Debug with AI" — unchanged
- Execution detail dialog "Debug with AI" — unchanged
