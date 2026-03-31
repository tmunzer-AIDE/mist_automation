# Group Detail Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the group detail page from a vertical-stacking layout to a split-view (chat + data panel) matching the session detail pattern.

**Architecture:** Extend `ImpactChatPanelComponent` with an optional `groupId` input so it can send group chat messages. Create a new `GroupDataPanelComponent` for the right-side scrollable dashboard. Rewrite `GroupDetailComponent` to use the split-view layout with timeline events narrated as chat messages.

**Tech Stack:** Angular 21, Angular Material, signals, standalone components, DOMPurify + marked

---

### Task 1: Extend ImpactChatPanelComponent with group support

**Files:**
- Modify: `frontend/src/app/features/impact-analysis/session-detail/impact-chat-panel.component.ts`

The chat panel currently has `sessionId` as `input.required<string>()`. We need to make it work for both sessions and groups by adding an optional `groupId` input. When `groupId` is set, `send()` calls `sendGroupChatMessage` instead.

- [ ] **Step 1: Change `sessionId` from required to optional and add `groupId` input**

In `frontend/src/app/features/impact-analysis/session-detail/impact-chat-panel.component.ts`, replace lines 363-367:

```typescript
  /** Chat messages mapped from timeline entries by the parent. */
  readonly messages = input.required<ChatMessage[]>();

  /** Session ID for sending chat messages. */
  readonly sessionId = input.required<string>();
```

with:

```typescript
  /** Chat messages mapped from timeline entries by the parent. */
  readonly messages = input.required<ChatMessage[]>();

  /** Session ID for sending chat messages (mutually exclusive with groupId). */
  readonly sessionId = input<string>('');

  /** Group ID for sending group chat messages (mutually exclusive with sessionId). */
  readonly groupId = input<string>('');
```

- [ ] **Step 2: Update `send()` to route to the correct service method**

Replace the `send()` method (lines 478-513) with:

```typescript
  /** Send a user message and stream the AI response. */
  send(): void {
    const text = this.userInput.trim();
    const sid = this.sessionId();
    const gid = this.groupId();
    if (!text || (!sid && !gid) || this.sending()) return;

    this.userInput = '';
    this.error.set(null);
    this.sending.set(true);

    // Generate stream ID and subscribe to WS before the HTTP call
    const streamId = crypto.randomUUID();
    this.subscribeToStream(`llm:${streamId}`);

    const mcpIds = this.selectedMcpIds().length > 0 ? this.selectedMcpIds() : undefined;
    const request$ = gid
      ? this.impactService.sendGroupChatMessage(gid, text, streamId, mcpIds)
      : this.impactService.sendChatMessage(sid, text, streamId, mcpIds);

    request$
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.streaming.set(false);
          this.streamingContent.set('');
          this.sending.set(false);
          this.messageSent.emit();
        },
        error: (err) => {
          this.streamSub?.unsubscribe();
          this.streamSub = null;
          this.streaming.set(false);
          this.streamingContent.set('');
          this.sending.set(false);
          this.error.set(extractErrorMessage(err));
        },
      });
  }
```

- [ ] **Step 3: Update the template placeholder text to be context-aware**

In the inline template, replace the placeholder text (line 98):

```html
            placeholder="Ask a question..."
```

with:

```html
            [placeholder]="groupId() ? 'Ask about this change group...' : 'Ask a question...'"
```

- [ ] **Step 4: Verify the session detail still compiles**

Run: `cd frontend && npx ng build --configuration=development 2>&1 | head -30`

The session detail template passes `[sessionId]="s.id"` which is a string, so it still works with the non-required input. Expected: BUILD SUCCESSFUL.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/features/impact-analysis/session-detail/impact-chat-panel.component.ts
git commit -m "feat(impact): extend chat panel with optional groupId input for group chat support"
```

---

### Task 2: Create GroupDataPanelComponent

**Files:**
- Create: `frontend/src/app/features/impact-analysis/group-detail/group-data-panel.component.ts`

New standalone component with inline template and styles. Mirrors `ImpactDataPanelComponent` but shows group-level aggregate data: status/counts, device list, validation overview, SLE metrics.

- [ ] **Step 1: Create the component file**

Create `frontend/src/app/features/impact-analysis/group-detail/group-data-panel.component.ts`:

```typescript
import { Component, computed, inject, input, output } from '@angular/core';
import { DecimalPipe, TitleCasePipe } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
  ChangeGroupDetailResponse,
  DeviceSummary,
  SLE_METRIC_LABELS,
  VALIDATION_CHECK_LABELS,
} from '../models/impact-analysis.model';
import { deviceTypeIcon } from '../utils/device-type.utils';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';

@Component({
  selector: 'app-group-data-panel',
  standalone: true,
  imports: [DecimalPipe, TitleCasePipe, MatIconModule, MatTooltipModule, StatusBadgeComponent],
  template: `
    <div class="data-panel-content">
      @if (group(); as g) {
        <!-- Status section -->
        <div class="section">
          <div class="section-header">
            Status
            <app-status-badge [status]="g.summary.status"></app-status-badge>
          </div>
          <div class="stat-cards">
            <div class="stat-card">
              <div class="stat-value">{{ g.summary.total_devices }}</div>
              <div class="stat-label">Devices</div>
            </div>
            <div class="stat-card">
              <div class="stat-value" [class.impacted]="impactedCount() > 0">{{ impactedCount() }}</div>
              <div class="stat-label">Impacted</div>
            </div>
          </div>
          @for (entry of deviceTypeCounts(); track entry.type) {
            <div class="type-row">
              <span class="type-label">{{ entry.type | titlecase }}</span>
              <span class="type-detail">{{ entry.completed }}/{{ entry.total }} completed</span>
            </div>
          }
        </div>
        <div class="section-divider"></div>

        <!-- Devices section -->
        <div class="section">
          <div class="section-header">
            Devices
            <span class="count-badge">{{ g.summary.devices.length }}</span>
          </div>
          @for (device of g.summary.devices; track device.session_id) {
            <div class="device-row" (click)="deviceClicked.emit(device)" matTooltip="Open session detail">
              <mat-icon class="device-icon">{{ deviceTypeIcon(device.device_type) }}</mat-icon>
              <span class="device-name">{{ device.device_name || device.device_mac }}</span>
              @if (device.impact_severity && device.impact_severity !== 'none') {
                <span class="impact-dot" [class]="'dot-' + device.impact_severity"
                  [matTooltip]="(device.impact_severity | titlecase) + ' impact'"></span>
              }
              <app-status-badge [status]="device.status"></app-status-badge>
            </div>
          }
        </div>
        <div class="section-divider"></div>

        <!-- Validation section -->
        @if (g.summary.validation_summary.length > 0) {
          <div class="section">
            <div class="section-header">
              Validation
              <span class="status-pill" [class]="'pill-' + overallValidationStatus()">
                {{ overallValidationStatus() | titlecase }}
              </span>
            </div>
            @for (check of g.summary.validation_summary; track check.check_name) {
              <div
                class="check-row"
                [class.check-warn]="check.failed === 0 && check.skipped > 0"
                [class.check-fail]="check.failed > 0"
              >
                <span class="check-label">{{ checkLabel(check.check_name) }}</span>
                <span class="check-counts">
                  @if (check.passed > 0) {
                    <mat-icon class="check-pass">check_circle</mat-icon>
                    <span class="check-pass">{{ check.passed }}</span>
                  }
                  @if (check.failed > 0) {
                    <mat-icon class="check-fail">cancel</mat-icon>
                    <span class="check-fail">{{ check.failed }}</span>
                  }
                </span>
              </div>
            }
          </div>
          <div class="section-divider"></div>
        }

        <!-- SLE section -->
        @if (sleSummaryEntries().length > 0) {
          <div class="section">
            <div class="section-header">
              SLE Metrics
              @if (hasDegradedSle()) {
                <span class="status-pill pill-fail">Degraded</span>
              }
            </div>
            @for (entry of sleSummaryEntries(); track entry.metric) {
              <div class="sle-row" [class.sle-row-degraded]="entry.delta_pct < -5">
                <span class="sle-name">{{ sleLabel(entry.metric) }}</span>
                <span class="sle-values">
                  {{ entry.baseline | number: '1.1-1' }}%
                  <mat-icon class="sle-arrow">arrow_forward</mat-icon>
                  {{ entry.current | number: '1.1-1' }}%
                </span>
                <span [class]="deltaClass(entry.delta_pct)">
                  {{ entry.delta_pct > 0 ? '+' : '' }}{{ entry.delta_pct | number: '1.1-1' }}%
                </span>
              </div>
            }
          </div>
        }
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
      overflow-y: auto;
      padding: 16px;
      background: var(--app-canvas-bg, #fafafa);
    }

    .data-panel-content {
      display: flex;
      flex-direction: column;
    }

    .section {
      margin-bottom: 16px;
    }

    .section-header {
      font-size: 11px;
      font-weight: 600;
      color: var(--app-neutral, #757575);
      text-transform: uppercase;
      margin-bottom: 8px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .section-divider {
      border-top: 1px solid var(--mat-sys-outline-variant, rgba(128, 128, 128, 0.1));
      margin: 12px 0;
    }

    /* ── Status section ──────────────────────────────────────────────── */
    .stat-cards {
      display: flex;
      gap: 8px;
      margin-bottom: 8px;
    }

    .stat-card {
      flex: 1;
      text-align: center;
      padding: 10px 8px;
      border: 1px solid var(--mat-sys-outline-variant, rgba(0, 0, 0, 0.12));
      border-radius: 6px;
    }

    .stat-value {
      font-size: 20px;
      font-weight: 700;

      &.impacted {
        color: var(--app-warning);
      }
    }

    .stat-label {
      font-size: 10px;
      color: var(--app-neutral, #757575);
      margin-top: 2px;
    }

    .type-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 3px 0;
      font-size: 11px;
    }

    .type-label {
      color: var(--app-neutral, #757575);
    }

    .type-detail {
      font-weight: 500;
    }

    /* ── Devices section ─────────────────────────────────────────────── */
    .count-badge {
      font-size: 11px;
      font-weight: 600;
      min-width: 18px;
      height: 18px;
      line-height: 18px;
      text-align: center;
      border-radius: 9px;
      background: var(--mat-sys-outline-variant, rgba(128, 128, 128, 0.15));
      color: var(--app-neutral, #757575);
    }

    .device-row {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 6px 8px;
      border-radius: 6px;
      background: var(--app-neutral-bg, rgba(0, 0, 0, 0.03));
      margin-bottom: 3px;
      cursor: pointer;
      transition: background 0.15s ease;

      &:hover {
        background: var(--mat-sys-surface-container-low, rgba(0, 0, 0, 0.06));
      }
    }

    .device-icon {
      font-size: 16px;
      width: 16px;
      height: 16px;
      color: var(--app-neutral, #757575);
      flex-shrink: 0;
    }

    .device-name {
      flex: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 12px;
      font-weight: 500;
    }

    .impact-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;

      &.dot-warning { background: var(--app-warning); }
      &.dot-critical { background: var(--app-error); }
      &.dot-info { background: var(--app-info); }
    }

    /* ── Validation section ──────────────────────────────────────────── */
    .status-pill {
      font-size: 10px;
      font-weight: 600;
      padding: 2px 8px;
      border-radius: 4px;

      &.pill-pass {
        background: var(--app-success-bg);
        color: var(--app-success);
      }
      &.pill-warn {
        background: var(--app-warning-bg);
        color: var(--app-warning);
      }
      &.pill-fail {
        background: var(--app-error-bg);
        color: var(--app-error);
      }
      &.pill-unknown {
        background: var(--app-neutral-bg, rgba(0, 0, 0, 0.03));
        color: var(--app-neutral, #757575);
      }
    }

    .check-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 5px 8px;
      background: var(--app-neutral-bg, rgba(0, 0, 0, 0.03));
      border-radius: 6px;
      font-size: 12px;
      margin-bottom: 3px;

      &.check-warn {
        background: var(--app-warning-bg);
        border-left: 2px solid var(--app-warning);
      }
      &.check-fail {
        background: var(--app-error-bg);
        border-left: 2px solid var(--app-error);
      }
    }

    .check-label {
      flex: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .check-counts {
      display: flex;
      align-items: center;
      gap: 3px;
      flex-shrink: 0;

      mat-icon {
        font-size: 14px;
        width: 14px;
        height: 14px;
      }

      span {
        font-size: 11px;
        font-weight: 600;
      }
    }

    .check-pass { color: var(--app-success); }
    .check-fail { color: var(--app-error); }

    /* ── SLE section ─────────────────────────────────────────────────── */
    .sle-row {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 5px 8px;
      border-radius: 6px;
      font-size: 12px;
      margin-bottom: 3px;
      background: var(--app-neutral-bg, rgba(0, 0, 0, 0.03));

      &.sle-row-degraded {
        background: var(--app-error-bg);
        border-left: 2px solid var(--app-error);
      }
    }

    .sle-name {
      flex: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .sle-values {
      display: flex;
      align-items: center;
      gap: 2px;
      font-size: 11px;
      color: var(--app-neutral, #757575);
      flex-shrink: 0;
    }

    .sle-arrow {
      font-size: 12px;
      width: 12px;
      height: 12px;
      color: var(--app-neutral, #757575);
    }

    .delta-negative {
      color: var(--app-error);
      font-weight: 500;
      flex-shrink: 0;
      font-size: 11px;
    }

    .delta-positive {
      color: var(--app-success);
      font-weight: 500;
      flex-shrink: 0;
      font-size: 11px;
    }

    .delta-neutral {
      color: var(--app-neutral, #757575);
      flex-shrink: 0;
      font-size: 11px;
    }
  `,
})
export class GroupDataPanelComponent {
  readonly group = input<ChangeGroupDetailResponse | null>(null);

  readonly deviceClicked = output<DeviceSummary>();

  readonly deviceTypeIcon = deviceTypeIcon;

  readonly impactedCount = computed(() => {
    const g = this.group();
    if (!g) return 0;
    return g.summary.devices.filter(
      (d) => d.impact_severity && d.impact_severity !== 'none',
    ).length;
  });

  readonly deviceTypeCounts = computed(() => {
    const g = this.group();
    if (!g) return [];
    return Object.entries(g.summary.by_type).map(([type, counts]) => ({
      type,
      total: counts.total,
      completed: counts.completed,
      monitoring: counts.monitoring,
      impacted: counts.impacted,
    }));
  });

  readonly sleSummaryEntries = computed(() => {
    const g = this.group();
    if (!g) return [];
    return Object.values(g.summary.sle_summary);
  });

  readonly hasDegradedSle = computed(() => {
    return this.sleSummaryEntries().some((e) => e.delta_pct < -5);
  });

  readonly overallValidationStatus = computed(() => {
    const g = this.group();
    if (!g) return 'unknown';
    const checks = g.summary.validation_summary;
    if (checks.length === 0) return 'unknown';
    if (checks.some((c) => c.failed > 0)) return 'fail';
    if (checks.every((c) => c.passed > 0 && c.failed === 0)) return 'pass';
    return 'warn';
  });

  checkLabel(key: string): string {
    return VALIDATION_CHECK_LABELS[key] ?? key.replace(/_/g, ' ');
  }

  sleLabel(key: string): string {
    return SLE_METRIC_LABELS[key] ?? key;
  }

  deltaClass(changePercent: number): string {
    if (changePercent < 0) return 'delta-negative';
    if (changePercent > 0) return 'delta-positive';
    return 'delta-neutral';
  }
}
```

- [ ] **Step 2: Verify the component compiles**

Run: `cd frontend && npx ng build --configuration=development 2>&1 | head -30`
Expected: BUILD SUCCESSFUL (component is created but not yet used anywhere).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/features/impact-analysis/group-detail/group-data-panel.component.ts
git commit -m "feat(impact): create GroupDataPanelComponent for group detail right panel"
```

---

### Task 3: Rewrite GroupDetailComponent with split-view layout

**Files:**
- Modify: `frontend/src/app/features/impact-analysis/group-detail/group-detail.component.ts`

Replace the entire component with the split-view layout: header + verdict banner + chat panel (left) + data panel (right). Timeline entries converted to chat messages using the same `_timelineToChat()` pattern as `SessionDetailComponent`.

- [ ] **Step 1: Replace the entire component file**

Rewrite `frontend/src/app/features/impact-analysis/group-detail/group-detail.component.ts` with this complete file:

```typescript
import {
  Component,
  DestroyRef,
  OnInit,
  OnDestroy,
  inject,
  signal,
  computed,
} from '@angular/core';
import { TitleCasePipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ImpactAnalysisService } from '../../../core/services/impact-analysis.service';
import { LlmService } from '../../../core/services/llm.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { WebSocketService } from '../../../core/services/websocket.service';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import {
  ChangeGroupDetailResponse,
  DeviceSummary,
  TimelineEntryResponse,
  ChatMessage,
} from '../models/impact-analysis.model';
import { ImpactChatPanelComponent } from '../session-detail/impact-chat-panel.component';
import { GroupDataPanelComponent } from './group-data-panel.component';
import DOMPurify from 'dompurify';
import { marked } from 'marked';

function renderMarkdown(md: string): string {
  const raw = marked.parse(md, { async: false }) as string;
  return DOMPurify.sanitize(raw);
}

let chatMsgCounter = 0;

@Component({
  selector: 'app-group-detail',
  standalone: true,
  imports: [
    TitleCasePipe,
    MatIconModule,
    MatButtonModule,
    MatProgressBarModule,
    MatTooltipModule,
    MatSnackBarModule,
    StatusBadgeComponent,
    DateTimePipe,
    ImpactChatPanelComponent,
    GroupDataPanelComponent,
  ],
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    }

    @if (group(); as g) {
      <!-- Header -->
      <div class="detail-header">
        <button mat-icon-button (click)="goBack()" matTooltip="Back to list">
          <mat-icon>arrow_back</mat-icon>
        </button>
        <div class="header-info">
          <div class="header-title">
            <mat-icon class="group-icon">layers</mat-icon>
            <h2>{{ g.change_description }}</h2>
            <app-status-badge [status]="g.summary.status"></app-status-badge>
            @if (worstSeverity() !== 'none') {
              <span class="impact-badge" [class]="'impact-' + worstSeverity()">
                {{ worstSeverity() | titlecase }} Impact
              </span>
            } @else if (!isActive()) {
              <span class="impact-badge ok">No Impact</span>
            }
          </div>
          <div class="header-meta">
            <span>
              <mat-icon>person</mat-icon>
              {{ g.triggered_by || 'Unknown' }}
            </span>
            <span>
              <mat-icon>schedule</mat-icon>
              Detected {{ g.triggered_at | dateTime: 'short' }}
            </span>
            <span>
              <mat-icon>devices</mat-icon>
              {{ g.summary.total_devices }}
              device{{ g.summary.total_devices !== 1 ? 's' : '' }}
            </span>
          </div>
        </div>
        <div class="header-actions">
          @if (isActive()) {
            <button
              mat-stroked-button
              color="warn"
              (click)="cancelGroup()"
              [disabled]="cancelling()"
            >
              <mat-icon>stop</mat-icon>
              Cancel
            </button>
          } @else {
            <button
              mat-stroked-button
              (click)="reanalyzeGroup()"
              [disabled]="reanalyzing()"
            >
              <mat-icon>refresh</mat-icon>
              Re-analyze
            </button>
          }
        </div>
      </div>

      <div class="detail-content">
        <!-- Verdict banner (only when completed) -->
        @if (!isActive()) {
          <div class="verdict-banner" [class]="'verdict-' + worstSeverity()">
            <div class="verdict-content">
              @if (worstSeverity() === 'none') {
                <mat-icon>check_circle</mat-icon>
              } @else {
                <mat-icon>warning</mat-icon>
              }
              <span class="verdict-text">{{ verdictSummary() }}</span>
            </div>
            <button mat-stroked-button (click)="reanalyzeGroup()" [disabled]="reanalyzing()">
              <mat-icon>refresh</mat-icon>
              Re-analyze
            </button>
          </div>
        }

        <!-- Split view -->
        <div class="split-view">
          <app-impact-chat-panel
            class="chat-panel"
            [messages]="chatMessages()"
            [groupId]="g.id"
            [isActive]="isActive()"
            [llmEnabled]="llmEnabled()"
            (messageSent)="onChatMessageSent()"
          />
          <app-group-data-panel
            class="data-panel"
            [group]="g"
            (deviceClicked)="viewSession($event)"
          />
        </div>
      </div>
    }
  `,
  styles: [
    `
      /* ── Header ───────────────────────────────────────────────────── */
      .detail-header {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        margin-bottom: 16px;
      }

      .header-info {
        flex: 1;
        min-width: 0;
      }

      .header-title {
        display: flex;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;

        h2 {
          margin: 0;
          font-size: 22px;
          font-weight: 600;
        }
      }

      .group-icon {
        font-size: 28px;
        width: 28px;
        height: 28px;
        color: var(--app-neutral);
      }

      .impact-badge {
        font-size: 12px;
        font-weight: 600;
        padding: 3px 10px;
        border-radius: 6px;

        &.ok {
          background: var(--app-success-bg);
          color: var(--app-success);
        }
        &.impact-warning {
          background: var(--app-warning-bg);
          color: var(--app-warning);
        }
        &.impact-critical {
          background: var(--app-error-bg);
          color: var(--app-error);
        }
        &.impact-info {
          background: var(--app-info-bg);
          color: var(--app-info);
        }
        &.impact-none {
          background: var(--app-success-bg);
          color: var(--app-success);
        }
      }

      .header-meta {
        display: flex;
        gap: 16px;
        flex-wrap: wrap;
        margin-top: 6px;
        color: var(--app-neutral);
        font-size: 13px;

        span {
          display: flex;
          align-items: center;
          gap: 4px;
        }

        mat-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
        }
      }

      .header-actions {
        flex-shrink: 0;
      }

      /* ── Verdict banner ────────────────────────────────────────────── */
      .verdict-banner {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        padding: 12px 16px;
        border-radius: 8px;
        margin-bottom: 16px;

        &.verdict-none {
          background: var(--app-success-bg);
          border-left: 4px solid var(--app-success);
          mat-icon { color: var(--app-success); }
        }
        &.verdict-info {
          background: var(--app-info-bg);
          border-left: 4px solid var(--app-info);
          mat-icon { color: var(--app-info); }
        }
        &.verdict-warning {
          background: var(--app-warning-bg);
          border-left: 4px solid var(--app-warning);
          mat-icon { color: var(--app-warning); }
        }
        &.verdict-critical {
          background: var(--app-error-bg);
          border-left: 4px solid var(--app-error);
          mat-icon { color: var(--app-error); }
        }
      }

      .verdict-content {
        display: flex;
        align-items: center;
        gap: 10px;
        flex: 1;
        min-width: 0;

        mat-icon {
          flex-shrink: 0;
          margin-top: 1px;
        }
      }

      .verdict-text {
        font-size: 13px;
        line-height: 1.5;
      }

      /* ── Split view layout ─────────────────────────────────────────── */
      .detail-content {
        display: flex;
        flex-direction: column;
        overflow: hidden;
        height: calc(100vh - 175px);
      }

      .split-view {
        display: flex;
        gap: 16px;
        min-height: 0;
        flex-grow: 1;
      }

      .chat-panel {
        flex: 1;
        min-width: 0;
        overflow: hidden;
        border: 1px solid var(--mat-sys-outline-variant, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
      }

      .data-panel {
        width: 340px;
        flex-shrink: 0;
        overflow-y: auto;
        border: 1px solid var(--mat-sys-outline-variant, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
      }

      /* ── Responsive ────────────────────────────────────────────────── */
      @media (max-width: 900px) {
        .split-view {
          flex-direction: column;
          height: auto;
        }

        .chat-panel {
          min-height: 400px;
        }

        .data-panel {
          width: 100%;
        }
      }
    `,
  ],
})
export class GroupDetailComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly service = inject(ImpactAnalysisService);
  private readonly llmService = inject(LlmService);
  private readonly topbarService = inject(TopbarService);
  private readonly wsService = inject(WebSocketService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);

  group = signal<ChangeGroupDetailResponse | null>(null);
  loading = signal(true);
  cancelling = signal(false);
  reanalyzing = signal(false);
  llmEnabled = signal(false);

  private groupId = '';

  isActive = computed(() => {
    const g = this.group();
    return g ? g.summary.status !== 'completed' && g.summary.status !== 'failed' : false;
  });

  worstSeverity = computed(() => this.group()?.summary.worst_severity ?? 'none');

  verdictSummary = computed(() => {
    const g = this.group();
    if (!g) return '';
    const parts: string[] = [];

    // Validation summary
    const checks = g.summary.validation_summary;
    const failedChecks = checks.filter((c) => c.failed > 0);
    if (failedChecks.length > 0) {
      const names = failedChecks.map((c) => c.check_name.replace(/_/g, ' ')).join(', ');
      parts.push(`${failedChecks.length} validation failure${failedChecks.length > 1 ? 's' : ''} (${names})`);
    } else if (checks.length > 0) {
      parts.push('all validation checks passed');
    }

    // Incidents
    const totalIncidents = g.summary.devices.reduce(
      (sum, d) => sum + d.active_incidents.length,
      0,
    );
    if (totalIncidents > 0) {
      const unresolved = g.summary.devices.reduce(
        (sum, d) => sum + d.active_incidents.filter((i) => !i.resolved).length,
        0,
      );
      const label = unresolved > 0 ? `${unresolved} unresolved` : 'all resolved';
      parts.push(`${totalIncidents} incident${totalIncidents > 1 ? 's' : ''} (${label})`);
    }

    // SLE
    const sleEntries = Object.values(g.summary.sle_summary);
    const degraded = sleEntries.filter((e) => e.delta_pct < -5);
    if (degraded.length > 0) {
      parts.push(`SLE degraded (${degraded.map((d) => d.metric).join(', ')})`);
    } else if (sleEntries.length > 0) {
      parts.push('SLE stable');
    }

    if (parts.length === 0) {
      return `Configuration change applied to ${g.summary.total_devices} device${g.summary.total_devices !== 1 ? 's' : ''} with no impact detected.`;
    }

    return parts.join(' \u2014 ');
  });

  chatMessages = computed<ChatMessage[]>(() => {
    const timeline = this.group()?.timeline ?? [];
    let lastAnalysisIdx = -1;
    for (let i = timeline.length - 1; i >= 0; i--) {
      if (timeline[i].type === 'ai_analysis') {
        lastAnalysisIdx = i;
        break;
      }
    }
    return timeline
      .map((entry, idx) => this._timelineToChat(entry, idx, lastAnalysisIdx))
      .filter((msg): msg is ChatMessage => msg !== null);
  });

  ngOnInit(): void {
    this.groupId = this.route.snapshot.paramMap.get('id') ?? '';
    this.topbarService.setTitle('Change Group');
    this.loadGroup();
    this.llmService.getStatus().subscribe({
      next: (status) => this.llmEnabled.set(status.enabled),
      error: () => this.llmEnabled.set(false),
    });
  }

  loadGroup(): void {
    this.loading.set(true);
    this.service.getGroup(this.groupId).subscribe({
      next: (group) => {
        this.group.set(group);
        this.loading.set(false);
        this.topbarService.setTitle(`Group: ${group.change_description}`);

        if (this.isActive()) {
          this.subscribeToUpdates();
        }
      },
      error: () => {
        this.loading.set(false);
        this.snackBar.open('Failed to load group', 'OK', { duration: 3000 });
      },
    });
  }

  cancelGroup(): void {
    this.cancelling.set(true);
    this.service.cancelGroup(this.groupId).subscribe({
      next: () => {
        this.snackBar.open('Group cancelled', 'OK', { duration: 3000 });
        this.loadGroup();
        this.cancelling.set(false);
      },
      error: () => {
        this.snackBar.open('Failed to cancel group', 'OK', { duration: 3000 });
        this.cancelling.set(false);
      },
    });
  }

  reanalyzeGroup(): void {
    this.reanalyzing.set(true);
    this.service.analyzeGroup(this.groupId).subscribe({
      next: () => {
        this.snackBar.open('Re-analysis started', 'OK', { duration: 3000 });
        this.loadGroup();
        this.reanalyzing.set(false);
      },
      error: () => {
        this.snackBar.open('Failed to start re-analysis', 'OK', { duration: 3000 });
        this.reanalyzing.set(false);
      },
    });
  }

  viewSession(device: DeviceSummary): void {
    this.router.navigate(['/impact-analysis', device.session_id]);
  }

  goBack(): void {
    this.router.navigate(['/impact-analysis']);
  }

  onChatMessageSent(): void {
    this.loadGroup();
  }

  private _timelineToChat(
    entry: TimelineEntryResponse,
    idx: number,
    lastAnalysisIdx: number,
  ): ChatMessage | null {
    if (entry.type === 'status_change') return null;
    if (entry.type === 'ai_analysis' && idx !== lastAnalysisIdx) return null;

    const id = `tl-${chatMsgCounter++}`;
    const timestamp = entry.timestamp;

    switch (entry.type) {
      case 'ai_narration':
        return {
          id,
          role: 'ai',
          type: 'narration',
          content: entry.title,
          html: renderMarkdown(entry.title),
          timestamp,
          severity: entry.severity || undefined,
        };

      case 'ai_analysis': {
        const fullSummary =
          (this.group()?.ai_assessment?.['summary'] as string) ||
          (entry.data['summary'] as string) ||
          entry.title;
        return {
          id,
          role: 'ai',
          type: 'analysis',
          content: fullSummary,
          html: renderMarkdown(fullSummary),
          timestamp,
          severity: entry.severity || undefined,
        };
      }

      case 'chat_message': {
        const role = entry.data['role'] as string;
        const content = (entry.data['content'] as string) || entry.title;
        return {
          id,
          role: role === 'user' ? 'user' : 'ai',
          type: 'chat',
          content,
          html: role === 'user' ? '' : renderMarkdown(content),
          timestamp,
        };
      }

      default:
        return {
          id,
          role: 'system',
          type: 'event',
          content: entry.title,
          html: '',
          timestamp,
          severity: entry.severity || undefined,
        };
    }
  }

  private subscribeToUpdates(): void {
    this.wsService
      .subscribe<{ type: string; data?: Record<string, unknown> }>(
        `impact:group:${this.groupId}`,
      )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((msg) => {
        switch (msg.type) {
          case 'group_update':
          case 'group_completed':
          case 'ai_analysis_completed':
          case 'timeline_entry':
            this.loadGroup();
            break;
        }
      });
  }

  ngOnDestroy(): void {
    this.topbarService.clearActions();
  }
}
```

- [ ] **Step 2: Verify the build compiles**

Run: `cd frontend && npx ng build --configuration=development 2>&1 | head -30`
Expected: BUILD SUCCESSFUL.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/features/impact-analysis/group-detail/group-detail.component.ts
git commit -m "feat(impact): redesign group detail page with split-view chat + data panel layout"
```

---

### Task 4: End-to-end verification

**Files:**
- No file changes — verification only

Verify the full flow works: group list → group detail → split-view renders → chat panel sends messages → data panel shows devices → clicking a device navigates to session detail.

- [ ] **Step 1: Full build check**

Run: `cd frontend && npx ng build 2>&1 | tail -10`
Expected: BUILD SUCCESSFUL with no warnings related to impact-analysis components.

- [ ] **Step 2: Verify session detail still works (regression check)**

The session detail template still passes `[sessionId]="s.id"` which is now an optional input with default `''`. The session detail does not pass `[groupId]`, so the chat panel will use `sessionId` path. No regression.

Run: `cd frontend && npx ng build 2>&1 | grep -i error`
Expected: No errors.

- [ ] **Step 3: Commit (no changes, just verification)**

No commit needed — this is a verification-only task.
