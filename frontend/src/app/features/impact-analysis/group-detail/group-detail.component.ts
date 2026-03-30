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
  private wsSubscribed = false;

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
    type Tagged = ChatMessage & { _baseContent: string; _devices: string[] };
    const messages = timeline
      .map((entry, idx) => this._timelineToChat(entry, idx, lastAnalysisIdx))
      .filter((msg): msg is Tagged => msg !== null);

    // Aggregate consecutive messages with the same base content
    const aggregated: Tagged[] = [];
    for (const msg of messages) {
      const prev = aggregated[aggregated.length - 1];
      if (
        prev &&
        msg.role === prev.role &&
        msg.type === prev.type &&
        msg._baseContent === prev._baseContent
      ) {
        prev._devices.push(...msg._devices);
        continue;
      }
      aggregated.push(msg);
    }

    // Render final messages with device info
    for (const msg of aggregated) {
      if (msg._devices.length === 0) continue;
      if (msg.role === 'system') {
        msg.content = msg._devices.length > 1
          ? `${msg._baseContent} (${msg._devices.length} devices)`
          : `${msg._baseContent} — ${msg._devices[0]}`;
      } else if (msg.role === 'ai' && msg.type === 'narration') {
        const prefix = msg._devices.join(', ');
        msg.content = `**${prefix}:** ${msg._baseContent}`;
        msg.html = renderMarkdown(msg.content);
      }
    }
    return aggregated;
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
  ): (ChatMessage & { _baseContent: string; _devices: string[] }) | null {
    if (entry.type === 'status_change') return null;
    if (entry.type === 'ai_analysis' && idx !== lastAnalysisIdx) return null;

    const id = `tl-${chatMsgCounter++}`;
    const timestamp = entry.timestamp;
    const devices = entry.device_name ? [entry.device_name] : [];

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
          _baseContent: entry.title,
          _devices: devices,
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
          _baseContent: fullSummary,
          _devices: devices,
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
          _baseContent: content,
          _devices: [],
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
          _baseContent: entry.title,
          _devices: devices,
        };
    }
  }

  private subscribeToUpdates(): void {
    if (this.wsSubscribed) return;
    this.wsSubscribed = true;
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
