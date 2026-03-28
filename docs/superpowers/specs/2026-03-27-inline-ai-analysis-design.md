# Inline AI Analysis Component

## Overview

Replace the current `AiSummaryPanelComponent` (separate block that pushes content down) with an integrated inline pattern. The AI trigger is a chip that sits alongside existing page chips, and the analysis expands in-place between the trigger row and the content below. The component feels native to each page — part of the data, not a separate layer.

## Goals

1. AI analysis is visually integrated into the page, not bolted on
2. Single reusable component works across all pages (backup compare, webhook monitor, dashboard, audit logs, system logs, backup list)
3. Trigger chip uses the same visual language as each page's existing chips
4. Expandable section has a max-height with internal scroll to prevent dominating the page

## Non-Goals

- Topbar "AI Summary" button (removed — trigger is inline)
- Side panel or drawer layout
- Auto-triggering analysis on page load

---

## Component: `AiInlineAnalysisComponent`

**Location:** `frontend/src/app/shared/components/ai-inline-analysis/ai-inline-analysis.component.ts`

Replaces `AiSummaryPanelComponent`. Two visual states: collapsed (just the trigger chip) and expanded (analysis card with AiChatPanel + follow-up input).

### Inputs/Outputs

```typescript
// State signals — wired by parent page
summary = input<string | null>(null);
error = input<string | null>(null);
loading = input(false);
threadId = input<string | null>(null);
loadingLabel = input('Analyzing...');

// Emits when user clicks the trigger chip (parent calls its LLM service method)
analyzeRequested = output<void>();
```

### Template — Collapsed State

When no summary/loading/error, render just the trigger chip:

```html
<button class="ai-trigger-chip" (click)="onTrigger()" [disabled]="loading()">
  <app-ai-icon [size]="14" [animated]="loading()"></app-ai-icon>
  @if (loading()) {
    <span>{{ loadingLabel() }}</span>
  } @else {
    <span>AI Analysis</span>
  }
</button>
```

### Template — Expanded State

When summary, error, or loading is active, render the trigger chip (now active-styled) + the expandable analysis section below:

```html
<button class="ai-trigger-chip active" (click)="toggle()">
  <app-ai-icon [size]="14" [animated]="loading()"></app-ai-icon>
  <span>AI Analysis</span>
  <mat-icon class="toggle-icon">{{ expanded() ? 'expand_less' : 'expand_more' }}</mat-icon>
</button>

@if (expanded()) {
  <div class="ai-analysis-section">
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

### Internal State

```typescript
expanded = signal(true);  // defaults to expanded when content arrives
hasContent = computed(() => !!this.summary() || !!this.error() || this.loading());
```

### Behavior

1. **First click** (no content yet): emits `analyzeRequested`, parent calls LLM service. Component shows loading state in the chip.
2. **Content arrives** (summary/error set by parent): analysis section expands with CSS animation.
3. **Subsequent clicks**: toggle expand/collapse. Don't re-trigger the LLM call.
4. **Re-analyze**: not needed. The follow-up input in AiChatPanel handles further questions.

### Styling

```scss
:host {
  display: contents;  // doesn't create a wrapper element, chip sits inline with siblings
}

.ai-trigger-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 14px;
  border-radius: 16px;
  border: 1px solid var(--mat-sys-outline-variant);
  background: transparent;
  color: var(--mat-sys-on-surface-variant);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease;

  &:hover, &.active {
    border-color: var(--mat-sys-primary);
    color: var(--mat-sys-primary);
    background: rgba(var(--mat-sys-primary-rgb, 100, 180, 255), 0.06);
  }

  &:disabled {
    cursor: wait;
    opacity: 0.7;
  }
}

.toggle-icon {
  font-size: 16px;
  width: 16px;
  height: 16px;
  opacity: 0.6;
}

.ai-analysis-section {
  margin: 10px 0;
  padding: 14px;
  background: rgba(var(--mat-sys-primary-rgb, 100, 180, 255), 0.04);
  border-radius: 10px;
  border: 1px solid rgba(var(--mat-sys-primary-rgb, 100, 180, 255), 0.15);
  max-height: 40vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  animation: analysis-expand 200ms ease;
}

@keyframes analysis-expand {
  from { max-height: 0; opacity: 0; }
  to { max-height: 40vh; opacity: 1; }
}
```

Key: `:host { display: contents }` means the component doesn't create a wrapper element — the trigger chip and analysis section sit directly in the parent's flex row, behaving like native siblings of the existing chips.

---

## Per-Page Integration

Each page places `<app-ai-inline-analysis>` in its template where the trigger chip should appear. The parent handles the LLM call on `(analyzeRequested)` and wires the result signals.

### Backup Compare

**Placement:** Inside the chips row (flex container), after the "modified N" chip, right-aligned via `margin-left: auto` on a wrapper or the chip itself.

```html
<div class="compare-chips">
  <span class="chip">added {{ addedCount() }}</span>
  <span class="chip">modified {{ modifiedCount() }}</span>
  <app-ai-inline-analysis
    [summary]="aiSummary()"
    [error]="aiError()"
    [loading]="aiLoading()"
    [threadId]="aiThreadId()"
    loadingLabel="Summarizing changes..."
    (analyzeRequested)="summarizeChanges()"
  />
</div>
<!-- analysis section expands here (between chips and diff entries) -->
```

The analysis section renders below the chips row, above the diff entries list, thanks to `display: contents`.

**Change:** Remove the topbar "AI Summary" button. The trigger is now the inline chip.

### Webhook Monitor

**Placement:** In the chart header row, after the "Webhook Volume" title and range selector, or as a separate row between chart and filters.

**Change:** Remove the topbar "AI Summary" button. Remove the old `AiSummaryPanelComponent` usage.

### Dashboard

**Placement:** In the welcome card, where the "Analyze Incidents" button used to be (now removed). Or in a stats summary row.

**Change:** Remove topbar "AI Summary" button.

### Audit Logs

**Placement:** In the filter row or above the table, inline with filter chips if present.

**Change:** Remove topbar "AI Summary" button.

### System Logs

**Placement:** In the filter row, inline with level/logger chips.

**Change:** Remove topbar "AI Summary" button.

### Backup List

**Placement:** In the filter row, inline with type/scope chips.

**Change:** Remove topbar "AI Summary" button.

---

## Migration from `AiSummaryPanelComponent`

The old `AiSummaryPanelComponent` is replaced entirely:
1. Delete `shared/components/ai-summary-panel/`
2. Remove the global `.ai-summary-btn` CSS from `styles.scss`
3. Each page that used `AiSummaryPanelComponent` switches to `AiInlineAnalysisComponent`
4. Remove topbar action buttons for AI Summary from all pages
5. Remove `ViewChild`/`setActions`/`clearActions` patterns that were added only for the AI Summary button

The parent's state management (signals, LLM service call, `summarize()` method) stays the same — only the template wiring changes.

---

## Preserved

- `AiChatPanel` — reused inside the analysis section (unchanged)
- Backend endpoints — all 6 summary endpoints remain
- `LlmService` methods — all summary methods remain
- Floating FAB chat — unchanged
- `/ai-chats` page — unchanged
