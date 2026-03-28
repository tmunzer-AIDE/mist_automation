# Unified AI Summary Pattern Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add contextual "AI Summary" buttons to 4 new pages (dashboard, audit logs, system logs, backup list), improve the backup compare button visibility, and extract a shared component to eliminate duplication across all 6 AI summary integrations.

**Architecture:** Extract `AiSummaryPanelComponent` (shared container with close button, max-height, slide animation). Each page adds a topbar "AI Summary" button that calls a dedicated backend endpoint, then displays the result in the shared panel. Backend endpoints follow the webhook summary pattern: gather context → build prompt → LLM call → return summary + thread_id.

**Tech Stack:** Angular 21 (standalone components, signals), Angular Material, FastAPI, Beanie/MongoDB, structlog ring buffer (system logs).

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `frontend/src/app/shared/components/ai-summary-panel/ai-summary-panel.component.ts` | Shared container: close button, max-height, slide animation, wraps AiChatPanel |
| Modify | `frontend/src/app/features/monitoring/webhook-monitor/webhook-monitor.component.ts` | Refactor to use shared panel |
| Modify | `frontend/src/app/features/monitoring/webhook-monitor/webhook-monitor.component.html` | Replace inline markup |
| Modify | `frontend/src/app/features/monitoring/webhook-monitor/webhook-monitor.component.scss` | Remove old AI styles |
| Modify | `frontend/src/app/features/backup/detail/backup-object-detail.component.ts` | Refactor to use shared panel, move button to topbar |
| Modify | `frontend/src/app/features/backup/detail/backup-object-detail.component.html` | Replace inline markup |
| Modify | `frontend/src/app/features/backup/detail/backup-object-detail.component.scss` | Remove old AI styles |
| Modify | `frontend/src/app/features/dashboard/dashboard.component.ts` | Add AI Summary (replace Analyze Incidents) |
| Modify | `frontend/src/app/features/dashboard/dashboard.component.html` | Add panel + topbar button |
| Modify | `frontend/src/app/features/admin/logs/audit-logs.component.ts` | Add AI Summary |
| Modify | `frontend/src/app/features/admin/system-logs/system-logs.component.ts` | Add AI Summary |
| Modify | `frontend/src/app/features/backup/list/backup-object-list.component.ts` | Add AI Summary |
| Modify | `frontend/src/app/core/services/llm.service.ts` | Add 4 new summary methods |
| Modify | `frontend/src/styles.scss` | Add global `.ai-summary-btn` style |
| Modify | `backend/app/modules/llm/router.py` | Add 4 new summary endpoints |
| Modify | `backend/app/modules/llm/schemas.py` | Add 4 new request schemas |
| Modify | `backend/app/modules/llm/services/context_service.py` | Add 4 new context functions |
| Modify | `backend/app/modules/llm/services/prompt_builders.py` | Add 4 new prompt builders |

---

### Task 1: Shared AiSummaryPanelComponent

**Files:**
- Create: `frontend/src/app/shared/components/ai-summary-panel/ai-summary-panel.component.ts`

- [ ] **Step 1: Create the component**

```typescript
// frontend/src/app/shared/components/ai-summary-panel/ai-summary-panel.component.ts
import { Component, input, output } from '@angular/core';
import { trigger, transition, style, animate } from '@angular/animations';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AiChatPanelComponent } from '../ai-chat-panel/ai-chat-panel.component';

@Component({
  selector: 'app-ai-summary-panel',
  standalone: true,
  imports: [MatButtonModule, MatIconModule, MatTooltipModule, AiChatPanelComponent],
  animations: [
    trigger('slideDown', [
      transition(':enter', [
        style({ maxHeight: '0', opacity: 0 }),
        animate('200ms ease', style({ maxHeight: '50vh', opacity: 1 })),
      ]),
      transition(':leave', [
        animate('150ms ease', style({ maxHeight: '0', opacity: 0 })),
      ]),
    ]),
  ],
  template: `
    @if (open()) {
      <div class="ai-summary-panel" @slideDown>
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
  `,
  styles: [`
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
  `],
})
export class AiSummaryPanelComponent {
  open = input(false);
  summary = input<string | null>(null);
  error = input<string | null>(null);
  loading = input(false);
  threadId = input<string | null>(null);
  loadingLabel = input('Analyzing...');

  closed = output<void>();
}
```

- [ ] **Step 2: Add global `.ai-summary-btn` style to `frontend/src/styles.scss`**

Add at the end of the file:

```scss
// ── AI Summary topbar button (shared across all pages) ──
.ai-summary-btn {
  margin-left: 8px;
  font-size: 13px;
}
```

- [ ] **Step 3: Verify build**

Run: `cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng build --configuration production 2>&1 | tail -5`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/shared/components/ai-summary-panel/ai-summary-panel.component.ts frontend/src/styles.scss
git commit -m "feat(frontend): add shared AiSummaryPanelComponent with slide animation"
```

---

### Task 2: Refactor Webhook Monitor to Use Shared Panel

**Files:**
- Modify: `frontend/src/app/features/monitoring/webhook-monitor/webhook-monitor.component.html`
- Modify: `frontend/src/app/features/monitoring/webhook-monitor/webhook-monitor.component.ts`
- Modify: `frontend/src/app/features/monitoring/webhook-monitor/webhook-monitor.component.scss`

- [ ] **Step 1: Update the component TS — add AiSummaryPanelComponent to imports**

Add `AiSummaryPanelComponent` to the `imports` array. Import it from `'../../../shared/components/ai-summary-panel/ai-summary-panel.component'`.

- [ ] **Step 2: Update the HTML template — replace inline markup with shared component**

Replace lines 33-49 (the `@if (aiPanelOpen())` block with `.ai-summary-container`) with:

```html
<app-ai-summary-panel
  [open]="aiPanelOpen()"
  [summary]="aiSummary()"
  [error]="aiError()"
  [loading]="aiLoading()"
  [threadId]="aiThreadId()"
  loadingLabel="Summarizing events..."
  (closed)="aiPanelOpen.set(false)"
></app-ai-summary-panel>
```

- [ ] **Step 3: Remove old styles from SCSS**

Delete these CSS rules from the SCSS file:
- `.ai-summary-container`
- `.ai-summary-topbar`
- `.ai-summary-title`

Keep `.ai-summary-btn` (or it can be removed since it's now global).

- [ ] **Step 4: Verify build + visual check**

Run: `cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng build --configuration production 2>&1 | tail -5`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/features/monitoring/webhook-monitor/
git commit -m "refactor(frontend): webhook monitor uses shared AiSummaryPanelComponent"
```

---

### Task 3: Refactor Backup Detail to Use Shared Panel + Move Button to Topbar

**Files:**
- Modify: `frontend/src/app/features/backup/detail/backup-object-detail.component.ts`
- Modify: `frontend/src/app/features/backup/detail/backup-object-detail.component.html`
- Modify: `frontend/src/app/features/backup/detail/backup-object-detail.component.scss`

- [ ] **Step 1: Update the component TS**

Add `AiSummaryPanelComponent` to imports. Import from `'../../../shared/components/ai-summary-panel/ai-summary-panel.component'`.

- [ ] **Step 2: Move the AI button from inline compare header to topbar actions**

In the `ng-template #topbarActions` section of the HTML, add the AI Summary button (only visible during compare mode):

```html
@if (llmAvailable() && compareMode() && diffEntries().length > 0) {
  <button mat-stroked-button (click)="summarizeChanges()" [disabled]="aiLoading()" class="ai-summary-btn">
    <app-ai-icon [size]="16" [animated]="false"></app-ai-icon> AI Summary
  </button>
}
```

Remove the old inline `mat-icon-button` from the compare header.

- [ ] **Step 3: Replace inline AI chat markup with shared component**

Replace the `@if (aiPanelOpen())` block (`.ai-chat-container` with `.ai-chat-topbar`) with:

```html
<app-ai-summary-panel
  [open]="aiPanelOpen()"
  [summary]="aiSummary()"
  [error]="aiError()"
  [loading]="aiLoading()"
  [threadId]="aiThreadId()"
  loadingLabel="Summarizing changes..."
  (closed)="aiPanelOpen.set(false)"
></app-ai-summary-panel>
```

- [ ] **Step 4: Remove old AI styles from SCSS**

Delete: `.ai-chat-container`, `.ai-chat-topbar`, `.ai-chat-title`, `.ai-chat-title-icon`.

- [ ] **Step 5: Verify build**

Run: `cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng build --configuration production 2>&1 | tail -5`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/features/backup/detail/
git commit -m "refactor(frontend): backup detail uses shared AiSummaryPanel, AI button moved to topbar"
```

---

### Task 4: Backend — Dashboard Summary Endpoint

**Files:**
- Modify: `backend/app/modules/llm/schemas.py`
- Modify: `backend/app/modules/llm/services/context_service.py`
- Modify: `backend/app/modules/llm/services/prompt_builders.py`
- Modify: `backend/app/modules/llm/router.py`

- [ ] **Step 1: Add request schema to `schemas.py`**

```python
class DashboardSummaryRequest(BaseModel):
    """Request to summarize dashboard state."""

    stream_id: str | None = Field(None, description="WebSocket stream ID for token streaming")
```

- [ ] **Step 2: Add context function to `context_service.py`**

```python
async def get_dashboard_summary_context() -> str:
    """Gather dashboard stats for LLM summarization."""
    from datetime import datetime, timedelta, timezone

    from app.models.system import AuditLog
    from app.modules.automation.models.webhook import WebhookEvent
    from app.modules.automation.models.workflow import Workflow, WorkflowExecution
    from app.modules.backup.models import BackupJob
    from app.modules.impact_analysis.models import MonitoringSession

    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    # Parallel counts
    import asyncio

    workflow_count, execution_count, failed_execs, webhook_count, backup_count, active_impact, impacted_sessions = (
        await asyncio.gather(
            Workflow.find(Workflow.is_active == True).count(),
            WorkflowExecution.find(WorkflowExecution.started_at >= cutoff_7d).count(),
            WorkflowExecution.find(
                {"started_at": {"$gte": cutoff_7d}, "status": {"$in": ["failed", "timeout"]}}
            ).to_list(),
            WebhookEvent.find(WebhookEvent.received_at >= cutoff_7d).count(),
            BackupJob.find(BackupJob.created_at >= cutoff_7d).count(),
            MonitoringSession.find({"status": {"$in": ["MONITORING", "VALIDATING", "BASELINE_CAPTURE"]}}).count(),
            MonitoringSession.find(
                {"impact_severity": {"$in": ["warning", "critical"]}, "created_at": {"$gte": cutoff_7d}}
            ).count(),
        )
    )

    lines = [
        f"Dashboard overview (last 7 days, as of {now.strftime('%Y-%m-%d %H:%M UTC')}):",
        f"- Active workflows: {workflow_count}",
        f"- Executions: {execution_count} total, {len(failed_execs)} failed/timeout",
        f"- Webhook events: {webhook_count}",
        f"- Backup jobs: {backup_count}",
        f"- Impact analysis: {active_impact} active sessions, {impacted_sessions} with impact",
    ]

    if failed_execs:
        lines.append("\nFailed/timeout executions:")
        for ex in failed_execs[:10]:
            lines.append(f"  - Workflow: {ex.workflow_name or 'unknown'}, status: {ex.status}, "
                         f"started: {ex.started_at.strftime('%Y-%m-%d %H:%M')}")

    return "\n".join(lines)
```

- [ ] **Step 3: Add prompt builder to `prompt_builders.py`**

```python
def build_dashboard_summary_prompt(context: str) -> list[dict[str, str]]:
    """Build prompt for dashboard state summarization."""
    system = (
        "You are a Juniper Mist network operations analyst. "
        "Summarize the current system state: highlight failures, anomalies, "
        "active incidents, and anything that needs attention. "
        "Be concise — use bullet points grouped by priority."
    )

    user = f"Summarize this system dashboard state:\n\n{context}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
```

- [ ] **Step 4: Add endpoint to `router.py`**

```python
@router.post("/llm/dashboard/summarize", response_model=WebhookSummaryResponse, tags=["LLM"])
async def summarize_dashboard(
    request: DashboardSummaryRequest,
    current_user: User = Depends(require_automation_role),
):
    """Summarize dashboard state using LLM."""
    _check_llm_rate_limit(str(current_user.id))
    from app.modules.llm.services.context_service import get_dashboard_summary_context
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import build_dashboard_summary_prompt

    llm = await create_llm_service()
    context = await get_dashboard_summary_context()

    prompt_messages = build_dashboard_summary_prompt(context)
    thread = await _load_or_create_thread(None, current_user.id, "dashboard_summary", prompt_messages)

    llm_messages = thread.to_llm_messages()
    response = await _stream_or_complete(llm, llm_messages, stream_id=request.stream_id)

    thread.add_message("assistant", response.content)
    await thread.save()

    await _log_llm_usage(current_user.id, "dashboard_summary", llm, response)

    return WebhookSummaryResponse(
        summary=response.content,
        event_count=0,
        thread_id=str(thread.id),
        usage=_usage_dict(response),
    )
```

- [ ] **Step 5: Verify backend starts**

Run: `cd /Users/tmunzer/4_dev/mist_automation/backend && .venv/bin/python -c "from app.modules.llm.router import router; print('OK')"`

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/llm/
git commit -m "feat(backend): add POST /llm/dashboard/summarize endpoint"
```

---

### Task 5: Backend — Audit Logs Summary Endpoint

**Files:** Same as Task 4 (schemas, context_service, prompt_builders, router)

- [ ] **Step 1: Add request schema**

```python
class AuditLogSummaryRequest(BaseModel):
    """Request to summarize audit logs."""

    event_type: str | None = Field(None, description="Filter by event type")
    user_id: str | None = Field(None, description="Filter by user ID")
    start_date: str | None = Field(None, description="Start date (ISO 8601)")
    end_date: str | None = Field(None, description="End date (ISO 8601)")
    stream_id: str | None = Field(None, description="WebSocket stream ID")
```

- [ ] **Step 2: Add context function**

```python
async def get_audit_log_summary_context(
    event_type: str | None = None,
    user_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 500,
) -> tuple[str, int]:
    """Fetch audit logs matching filters for LLM summarization."""
    from datetime import datetime, timezone

    from app.models.system import AuditLog

    query: dict = {}
    if event_type:
        query["event_type"] = event_type
    if user_id:
        query["user_id"] = user_id
    if start_date:
        query.setdefault("timestamp", {})["$gte"] = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    if end_date:
        query.setdefault("timestamp", {})["$lte"] = datetime.fromisoformat(end_date.replace("Z", "+00:00"))

    if not query:
        # Default: last 24 hours
        from datetime import timedelta

        query["timestamp"] = {"$gte": datetime.now(timezone.utc) - timedelta(hours=24)}

    logs = await AuditLog.find(query).sort("-timestamp").limit(limit).to_list()

    if not logs:
        return "No audit log entries matching the specified filters.", 0

    lines = [f"Total: {len(logs)} audit log entries\n"]
    for log in logs:
        ts = log.timestamp.strftime("%Y-%m-%d %H:%M:%S") if log.timestamp else "?"
        success = "OK" if log.success else "FAILED"
        lines.append(
            f"- [{ts}] {log.event_type} ({success}) "
            f"user={log.user_email or '?'} target={log.target_type or ''}:{log.target_name or ''} "
            f"— {log.description[:100]}"
        )

    return "\n".join(lines), len(logs)
```

- [ ] **Step 3: Add prompt builder**

```python
def build_audit_log_summary_prompt(context: str, filters: dict) -> list[dict[str, str]]:
    """Build prompt for audit log summarization."""
    filter_desc = ", ".join(f"{k}={v}" for k, v in filters.items() if v) or "last 24 hours"
    system = (
        "You are a security and operations analyst for a Juniper Mist automation platform. "
        "Analyze these audit logs. Identify patterns, anomalies, security concerns, "
        "suspicious activity, and notable operational events. "
        "Be concise — use bullet points grouped by category."
    )
    user = f"Analyze these audit logs (filter: {filter_desc}):\n\n{context}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
```

- [ ] **Step 4: Add endpoint**

```python
@router.post("/llm/audit-logs/summarize", response_model=WebhookSummaryResponse, tags=["LLM"])
async def summarize_audit_logs(
    request: AuditLogSummaryRequest,
    current_user: User = Depends(require_admin),
):
    """Summarize audit logs using LLM."""
    _check_llm_rate_limit(str(current_user.id))
    from app.modules.llm.services.context_service import get_audit_log_summary_context
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import build_audit_log_summary_prompt

    llm = await create_llm_service()
    context, count = await get_audit_log_summary_context(
        event_type=request.event_type,
        user_id=request.user_id,
        start_date=request.start_date,
        end_date=request.end_date,
    )

    filters = {
        "event_type": request.event_type,
        "user_id": request.user_id,
        "start_date": request.start_date,
        "end_date": request.end_date,
    }
    prompt_messages = build_audit_log_summary_prompt(context, filters)
    thread = await _load_or_create_thread(None, current_user.id, "audit_log_summary", prompt_messages)

    llm_messages = thread.to_llm_messages()
    response = await _stream_or_complete(llm, llm_messages, stream_id=request.stream_id)

    thread.add_message("assistant", response.content)
    await thread.save()

    await _log_llm_usage(current_user.id, "audit_log_summary", llm, response)

    return WebhookSummaryResponse(
        summary=response.content,
        event_count=count,
        thread_id=str(thread.id),
        usage=_usage_dict(response),
    )
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/llm/
git commit -m "feat(backend): add POST /llm/audit-logs/summarize endpoint"
```

---

### Task 6: Backend — System Logs Summary Endpoint

**Files:** Same backend LLM files

- [ ] **Step 1: Add request schema**

```python
class SystemLogSummaryRequest(BaseModel):
    """Request to summarize system logs."""

    level: str | None = Field(None, description="Filter by log level")
    logger: str | None = Field(None, description="Filter by logger name")
    stream_id: str | None = Field(None, description="WebSocket stream ID")
```

- [ ] **Step 2: Add context function**

```python
async def get_system_log_summary_context(
    level: str | None = None,
    logger: str | None = None,
    limit: int = 500,
) -> tuple[str, int]:
    """Fetch system logs from ring buffer for LLM summarization."""
    from app.core.log_broadcaster import get_recent_logs

    all_logs = get_recent_logs(limit)

    # Apply filters
    logs = all_logs
    if level:
        logs = [l for l in logs if l.get("level", "").lower() == level.lower()]
    if logger:
        logs = [l for l in logs if l.get("logger", "") == logger]

    if not logs:
        return "No system log entries matching the specified filters.", 0

    lines = [f"Total: {len(logs)} system log entries\n"]
    for log in logs[:200]:  # Limit for token budget
        ts = log.get("timestamp", "?")
        lvl = log.get("level", "?")
        event = log.get("event", "?")[:120]
        lgr = log.get("logger", "?")
        lines.append(f"- [{ts}] [{lvl}] {lgr}: {event}")

    if len(logs) > 200:
        lines.append(f"... and {len(logs) - 200} more entries")

    return "\n".join(lines), len(logs)
```

- [ ] **Step 3: Add prompt builder**

```python
def build_system_log_summary_prompt(context: str, filters: dict) -> list[dict[str, str]]:
    """Build prompt for system log summarization."""
    filter_desc = ", ".join(f"{k}={v}" for k, v in filters.items() if v) or "all recent logs"
    system = (
        "You are a systems engineer analyzing application logs for a Juniper Mist automation platform. "
        "Identify error patterns, recurring issues, performance concerns, and anything requiring attention. "
        "Be concise — use bullet points grouped by severity."
    )
    user = f"Analyze these system logs (filter: {filter_desc}):\n\n{context}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
```

- [ ] **Step 4: Add endpoint**

```python
@router.post("/llm/system-logs/summarize", response_model=WebhookSummaryResponse, tags=["LLM"])
async def summarize_system_logs(
    request: SystemLogSummaryRequest,
    current_user: User = Depends(require_admin),
):
    """Summarize system logs using LLM."""
    _check_llm_rate_limit(str(current_user.id))
    from app.modules.llm.services.context_service import get_system_log_summary_context
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import build_system_log_summary_prompt

    llm = await create_llm_service()
    context, count = await get_system_log_summary_context(
        level=request.level,
        logger=request.logger,
    )

    filters = {"level": request.level, "logger": request.logger}
    prompt_messages = build_system_log_summary_prompt(context, filters)
    thread = await _load_or_create_thread(None, current_user.id, "system_log_summary", prompt_messages)

    llm_messages = thread.to_llm_messages()
    response = await _stream_or_complete(llm, llm_messages, stream_id=request.stream_id)

    thread.add_message("assistant", response.content)
    await thread.save()

    await _log_llm_usage(current_user.id, "system_log_summary", llm, response)

    return WebhookSummaryResponse(
        summary=response.content,
        event_count=count,
        thread_id=str(thread.id),
        usage=_usage_dict(response),
    )
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/llm/
git commit -m "feat(backend): add POST /llm/system-logs/summarize endpoint"
```

---

### Task 7: Backend — Backup List Summary Endpoint

**Files:** Same backend LLM files

- [ ] **Step 1: Add request schema**

```python
class BackupListSummaryRequest(BaseModel):
    """Request to summarize backup health and changes."""

    object_type: str | None = Field(None, description="Filter by object type")
    site_id: str | None = Field(None, description="Filter by site ID")
    scope: str | None = Field(None, description="Filter by scope (org/site)")
    stream_id: str | None = Field(None, description="WebSocket stream ID")
```

- [ ] **Step 2: Add context function**

```python
async def get_backup_summary_context(
    object_type: str | None = None,
    site_id: str | None = None,
    scope: str | None = None,
) -> tuple[str, int]:
    """Gather backup health and change activity for LLM summarization."""
    import asyncio
    from datetime import datetime, timedelta, timezone

    from app.modules.backup.models import BackupJob, BackupObject

    now = datetime.now(timezone.utc)
    cutoff_7d = now - timedelta(days=7)

    # Build object query
    obj_query: dict = {}
    if object_type:
        obj_query["object_type"] = object_type
    if site_id:
        obj_query["site_id"] = site_id
    if scope == "org":
        obj_query["site_id"] = None
    elif scope == "site":
        obj_query["site_id"] = {"$ne": None}

    # Build job query
    job_query: dict = {"created_at": {"$gte": cutoff_7d}}

    objects, recent_jobs, failed_jobs = await asyncio.gather(
        BackupObject.find(obj_query).sort("-backed_up_at").limit(500).to_list(),
        BackupJob.find(job_query).count(),
        BackupJob.find({**job_query, "status": "failed"}).count(),
    )

    if not objects:
        return "No backup objects matching the specified filters.", 0

    # Find stale objects (not backed up in 7+ days)
    stale = [o for o in objects if o.backed_up_at and o.backed_up_at < cutoff_7d]

    # Group by object type
    by_type: dict[str, int] = {}
    for o in objects:
        by_type[o.object_type] = by_type.get(o.object_type, 0) + 1

    lines = [
        f"Backup overview (as of {now.strftime('%Y-%m-%d %H:%M UTC')}):",
        f"- Total objects: {len(objects)}",
        f"- By type: {', '.join(f'{t}: {c}' for t, c in sorted(by_type.items()))}",
        f"- Stale (>7 days since last backup): {len(stale)}",
        f"- Recent jobs (7d): {recent_jobs} total, {failed_jobs} failed",
    ]

    if stale:
        lines.append("\nStale objects:")
        for o in stale[:20]:
            age = (now - o.backed_up_at).days if o.backed_up_at else "never"
            lines.append(f"  - {o.object_type}/{o.object_name or o.object_id} — {age} days old")

    # Recent changes
    changed = [o for o in objects if o.backed_up_at and o.backed_up_at >= cutoff_7d and o.version > 1]
    if changed:
        lines.append(f"\nRecently changed objects ({len(changed)}):")
        for o in changed[:20]:
            fields = ", ".join(o.changed_fields[:5]) if o.changed_fields else "N/A"
            lines.append(f"  - {o.object_type}/{o.object_name or o.object_id} v{o.version} — fields: {fields}")

    return "\n".join(lines), len(objects)
```

- [ ] **Step 3: Add prompt builder**

```python
def build_backup_list_summary_prompt(context: str, filters: dict) -> list[dict[str, str]]:
    """Build prompt for backup health and change activity summarization."""
    filter_desc = ", ".join(f"{k}={v}" for k, v in filters.items() if v) or "all objects"
    system = (
        "You are a network configuration analyst for a Juniper Mist automation platform. "
        "Analyze backup health and change activity. Identify objects with stale backups, "
        "repeated job failures, unusual change patterns, and overall backup coverage gaps. "
        "Be concise — use bullet points grouped by concern."
    )
    user = f"Analyze this backup health data (filter: {filter_desc}):\n\n{context}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
```

- [ ] **Step 4: Add endpoint**

```python
@router.post("/llm/backups/summarize", response_model=WebhookSummaryResponse, tags=["LLM"])
async def summarize_backups(
    request: BackupListSummaryRequest,
    current_user: User = Depends(require_backup_role),
):
    """Summarize backup health and change activity using LLM."""
    _check_llm_rate_limit(str(current_user.id))
    from app.modules.llm.services.context_service import get_backup_summary_context
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import build_backup_list_summary_prompt

    llm = await create_llm_service()
    context, count = await get_backup_summary_context(
        object_type=request.object_type,
        site_id=request.site_id,
        scope=request.scope,
    )

    filters = {"object_type": request.object_type, "site_id": request.site_id, "scope": request.scope}
    prompt_messages = build_backup_list_summary_prompt(context, filters)
    thread = await _load_or_create_thread(None, current_user.id, "backup_summary_list", prompt_messages)

    llm_messages = thread.to_llm_messages()
    response = await _stream_or_complete(llm, llm_messages, stream_id=request.stream_id)

    thread.add_message("assistant", response.content)
    await thread.save()

    await _log_llm_usage(current_user.id, "backup_summary_list", llm, response)

    return WebhookSummaryResponse(
        summary=response.content,
        event_count=count,
        thread_id=str(thread.id),
        usage=_usage_dict(response),
    )
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/llm/
git commit -m "feat(backend): add POST /llm/backups/summarize endpoint"
```

---

### Task 8: Frontend LlmService — Add Summary Methods

**Files:**
- Modify: `frontend/src/app/core/services/llm.service.ts`

- [ ] **Step 1: Add 4 new methods and interfaces**

Add these interfaces (if not already present):

```typescript
interface SummaryResponse {
  summary: string;
  thread_id: string;
  event_count?: number;
  usage: Record<string, number>;
}
```

Add these methods to `LlmService`:

```typescript
/** Summarize dashboard state */
summarizeDashboard(): Observable<SummaryResponse> {
  return this.api.post<SummaryResponse>('/llm/dashboard/summarize', {});
}

/** Summarize audit logs with current filters */
summarizeAuditLogs(filters: {
  event_type?: string;
  user_id?: string;
  start_date?: string;
  end_date?: string;
}): Observable<SummaryResponse> {
  return this.api.post<SummaryResponse>('/llm/audit-logs/summarize', filters);
}

/** Summarize system logs with current filters */
summarizeSystemLogs(filters: {
  level?: string;
  logger?: string;
}): Observable<SummaryResponse> {
  return this.api.post<SummaryResponse>('/llm/system-logs/summarize', filters);
}

/** Summarize backup health and changes */
summarizeBackups(filters: {
  object_type?: string;
  site_id?: string;
  scope?: string;
}): Observable<SummaryResponse> {
  return this.api.post<SummaryResponse>('/llm/backups/summarize', filters);
}
```

- [ ] **Step 2: Verify build**

Run: `cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng build --configuration production 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/core/services/llm.service.ts
git commit -m "feat(frontend): add summarizeDashboard/AuditLogs/SystemLogs/Backups to LlmService"
```

---

### Task 9: Dashboard — Replace "Analyze Incidents" with AI Summary

**Files:**
- Modify: `frontend/src/app/features/dashboard/dashboard.component.ts`
- Modify: `frontend/src/app/features/dashboard/dashboard.component.html`

- [ ] **Step 1: Update component TS**

Add imports for `AiSummaryPanelComponent`, `AiIconComponent`, `LlmService`, `extractErrorMessage`. Add to `imports` array.

Add AI state signals:

```typescript
llmAvailable = signal(false);
aiPanelOpen = signal(false);
aiLoading = signal(false);
aiSummary = signal<string | null>(null);
aiError = signal<string | null>(null);
aiThreadId = signal<string | null>(null);
```

In `ngOnInit`, add LLM status check:

```typescript
this.llmService.getStatus().subscribe({
  next: (s) => this.llmAvailable.set(s.enabled),
  error: () => {},
});
```

Replace `analyzeIncident()` method with:

```typescript
summarize(): void {
  this.aiPanelOpen.set(true);
  this.aiLoading.set(true);
  this.aiSummary.set(null);
  this.aiError.set(null);

  this.llmService.summarizeDashboard().subscribe({
    next: (res) => {
      this.aiThreadId.set(res.thread_id);
      this.aiSummary.set(res.summary);
      this.aiLoading.set(false);
    },
    error: (err) => {
      this.aiError.set(extractErrorMessage(err));
      this.aiLoading.set(false);
    },
  });
}
```

Remove the `GlobalChatService` injection and `analyzeIncident()` method if no longer used elsewhere.

- [ ] **Step 2: Update HTML template**

Add topbar actions `ng-template` (if not already present) with AI Summary button:

```html
<ng-template #topbarActions>
  @if (llmAvailable()) {
    <button mat-stroked-button (click)="summarize()" [disabled]="aiLoading()" class="ai-summary-btn">
      <app-ai-icon [size]="16" [animated]="false"></app-ai-icon> AI Summary
    </button>
  }
</ng-template>
```

Add the summary panel at the top of the page content (before the welcome card):

```html
<app-ai-summary-panel
  [open]="aiPanelOpen()"
  [summary]="aiSummary()"
  [error]="aiError()"
  [loading]="aiLoading()"
  [threadId]="aiThreadId()"
  loadingLabel="Analyzing dashboard..."
  (closed)="aiPanelOpen.set(false)"
></app-ai-summary-panel>
```

Remove the old "Analyze Incidents" button from the hero card.

Set topbar actions in `ngOnInit` and clear in `ngOnDestroy`:

```typescript
@ViewChild('topbarActions', { static: true }) topbarActions!: TemplateRef<unknown>;

ngOnInit(): void {
  this.topbarService.setTitle('Dashboard');
  this.topbarService.setActions(this.topbarActions);
  // ... rest of init
}

ngOnDestroy(): void {
  this.topbarService.clearActions();
}
```

- [ ] **Step 3: Verify build**

Run: `cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng build --configuration production 2>&1 | tail -5`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/features/dashboard/
git commit -m "feat(frontend): dashboard AI Summary replaces Analyze Incidents button"
```

---

### Task 10: Audit Logs — Add AI Summary

**Files:**
- Modify: `frontend/src/app/features/admin/logs/audit-logs.component.ts`

- [ ] **Step 1: Add imports and AI state**

Add imports: `AiSummaryPanelComponent`, `AiIconComponent`, `LlmService`. Add to `imports` array.

Add signals: `llmAvailable`, `aiPanelOpen`, `aiLoading`, `aiSummary`, `aiError`, `aiThreadId` (same pattern as Task 9).

Add LLM status check in constructor/ngOnInit.

- [ ] **Step 2: Add summarize method**

```typescript
summarize(): void {
  this.aiPanelOpen.set(true);
  this.aiLoading.set(true);
  this.aiSummary.set(null);
  this.aiError.set(null);

  const filters = {
    event_type: this.filterForm.get('event_type')?.value || undefined,
    user_id: this.filterForm.get('user_id')?.value || undefined,
    start_date: this.filterForm.get('start_date')?.value || undefined,
    end_date: this.filterForm.get('end_date')?.value || undefined,
  };

  this.llmService.summarizeAuditLogs(filters).subscribe({
    next: (res) => {
      this.aiThreadId.set(res.thread_id);
      this.aiSummary.set(res.summary);
      this.aiLoading.set(false);
    },
    error: (err) => {
      this.aiError.set(extractErrorMessage(err));
      this.aiLoading.set(false);
    },
  });
}
```

- [ ] **Step 3: Add AI Summary button to existing topbar actions template**

In the existing `ng-template #actions` (which already has export button), add:

```html
@if (llmAvailable()) {
  <button mat-stroked-button (click)="summarize()" [disabled]="aiLoading()" class="ai-summary-btn">
    <app-ai-icon [size]="16" [animated]="false"></app-ai-icon> AI Summary
  </button>
}
```

- [ ] **Step 4: Add summary panel to template**

Add `<app-ai-summary-panel>` at the top of the component template (before filters/table), same pattern as Task 9.

- [ ] **Step 5: Verify build and commit**

```bash
git add frontend/src/app/features/admin/logs/
git commit -m "feat(frontend): add AI Summary to audit logs page"
```

---

### Task 11: System Logs — Add AI Summary

**Files:**
- Modify: `frontend/src/app/features/admin/system-logs/system-logs.component.ts`
- Modify: `frontend/src/app/features/admin/system-logs/system-logs.component.html`

Same pattern as Task 10 but with system log filters (`level`, `logger`):

- [ ] **Step 1: Add imports, signals, LLM status check**
- [ ] **Step 2: Add summarize method**

```typescript
summarize(): void {
  this.aiPanelOpen.set(true);
  this.aiLoading.set(true);
  this.aiSummary.set(null);
  this.aiError.set(null);

  const filters = {
    level: this.levelFilter.value || undefined,
    logger: this.loggerFilter.value || undefined,
  };

  this.llmService.summarizeSystemLogs(filters).subscribe({
    next: (res) => {
      this.aiThreadId.set(res.thread_id);
      this.aiSummary.set(res.summary);
      this.aiLoading.set(false);
    },
    error: (err) => {
      this.aiError.set(extractErrorMessage(err));
      this.aiLoading.set(false);
    },
  });
}
```

- [ ] **Step 3: Add button to existing topbar actions + panel to template**
- [ ] **Step 4: Verify build and commit**

```bash
git add frontend/src/app/features/admin/system-logs/
git commit -m "feat(frontend): add AI Summary to system logs page"
```

---

### Task 12: Backup List — Add AI Summary

**Files:**
- Modify: `frontend/src/app/features/backup/list/backup-object-list.component.ts`

- [ ] **Step 1: Add imports, signals, LLM status check**
- [ ] **Step 2: Add summarize method**

```typescript
summarize(): void {
  this.aiPanelOpen.set(true);
  this.aiLoading.set(true);
  this.aiSummary.set(null);
  this.aiError.set(null);

  const filters = {
    object_type: this.typeFilter.value || undefined,
    site_id: this.siteFilter.value || undefined,
    scope: this.scopeFilter.value || undefined,
  };

  this.llmService.summarizeBackups(filters).subscribe({
    next: (res) => {
      this.aiThreadId.set(res.thread_id);
      this.aiSummary.set(res.summary);
      this.aiLoading.set(false);
    },
    error: (err) => {
      this.aiError.set(extractErrorMessage(err));
      this.aiLoading.set(false);
    },
  });
}
```

- [ ] **Step 3: Add topbar actions template + panel**

This component doesn't have topbar actions yet, so add the full pattern (ViewChild, ngOnInit setActions, ngOnDestroy clearActions).

- [ ] **Step 4: Verify build and commit**

```bash
git add frontend/src/app/features/backup/list/
git commit -m "feat(frontend): add AI Summary to backup list page"
```

---

### Task 13: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add AI Summary pattern documentation**

In the LLM Module Frontend section, add after the AiChatPanel description:

```
- **AI Summary Panel** (`shared/components/ai-summary-panel/`): Shared container for inline AI summaries — wraps `AiChatPanel` with close button, `max-height: 50vh`, and slide-down animation. Used by webhook monitor, dashboard, backup detail (compare mode), backup list, audit logs, and system logs. Each page adds a topbar "AI Summary" button (`.ai-summary-btn` global class) and wires signals to the shared panel.
```

In the backend LLM section, add the new endpoints:

```
- **Summary endpoints**: `POST /llm/dashboard/summarize`, `/llm/audit-logs/summarize`, `/llm/system-logs/summarize`, `/llm/backups/summarize` — each gathers context from its domain, builds a prompt, calls the LLM, and returns `{ summary, thread_id, event_count, usage }`. Follow-ups use the standard `/llm/chat/{thread_id}` endpoint via the chat panel.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document AI Summary pattern in CLAUDE.md"
```
