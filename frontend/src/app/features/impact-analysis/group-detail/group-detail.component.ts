import {
  Component,
  DestroyRef,
  OnDestroy,
  OnInit,
  inject,
  signal,
  computed,
} from '@angular/core';
import { DecimalPipe, TitleCasePipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ImpactAnalysisService } from '../../../core/services/impact-analysis.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { WebSocketService } from '../../../core/services/websocket.service';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import {
  ChangeGroupDetailResponse,
  DeviceSummary,
  SLEDeltaSummary,
  SLE_METRIC_LABELS,
  VALIDATION_CHECK_LABELS,
} from '../models/impact-analysis.model';
import {
  deviceTypeIcon as _deviceTypeIcon,
  formatDeviceType as _formatDeviceType,
} from '../utils/device-type.utils';
import DOMPurify from 'dompurify';
import { marked } from 'marked';

function renderMarkdown(md: string): string {
  const raw = marked.parse(md, { async: false }) as string;
  return DOMPurify.sanitize(raw);
}

@Component({
  selector: 'app-group-detail',
  standalone: true,
  imports: [
    DecimalPipe,
    TitleCasePipe,
    MatIconModule,
    MatButtonModule,
    MatProgressBarModule,
    MatTableModule,
    MatTooltipModule,
    MatSnackBarModule,
    StatusBadgeComponent,
    DateTimePipe,
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

      <div class="detail-body">
        <!-- Summary cards -->
        <div class="summary-cards">
          <div class="summary-card">
            <div class="card-value">{{ g.summary.total_devices }}</div>
            <div class="card-label">Total Devices</div>
          </div>
          <div class="summary-card">
            <div class="card-value impacted">{{ impactedCount() }}</div>
            <div class="card-label">Impacted</div>
          </div>
          <div class="summary-card">
            <div class="card-value">
              <app-status-badge [status]="g.summary.status"></app-status-badge>
            </div>
            <div class="card-label">Group Status</div>
          </div>
        </div>

        <!-- Device breakdown table -->
        @if (g.summary.devices.length > 0) {
          <h3 class="section-title">Device Breakdown</h3>
          <div class="table-card">
            <table mat-table [dataSource]="g.summary.devices" class="mat-elevation-z0">
              <!-- Impact -->
              <ng-container matColumnDef="impact">
                <th mat-header-cell *matHeaderCellDef>Impact</th>
                <td mat-cell *matCellDef="let row">
                  @if (row.impact_severity && row.impact_severity !== 'none') {
                    <app-status-badge [status]="row.impact_severity"></app-status-badge>
                  } @else if (row.status === 'completed') {
                    <app-status-badge status="none"></app-status-badge>
                  }
                </td>
              </ng-container>

              <!-- Device -->
              <ng-container matColumnDef="device">
                <th mat-header-cell *matHeaderCellDef>Device</th>
                <td mat-cell *matCellDef="let row">
                  <div class="device-cell">
                    <mat-icon class="device-icon">{{
                      deviceTypeIcon(row.device_type)
                    }}</mat-icon>
                    <span>{{ row.device_name || row.device_mac }}</span>
                  </div>
                </td>
              </ng-container>

              <!-- Type -->
              <ng-container matColumnDef="type">
                <th mat-header-cell *matHeaderCellDef>Type</th>
                <td mat-cell *matCellDef="let row">{{
                  formatDeviceType(row.device_type)
                }}</td>
              </ng-container>

              <!-- Site -->
              <ng-container matColumnDef="site">
                <th mat-header-cell *matHeaderCellDef>Site</th>
                <td mat-cell *matCellDef="let row">{{ row.site_name }}</td>
              </ng-container>

              <!-- Status -->
              <ng-container matColumnDef="status">
                <th mat-header-cell *matHeaderCellDef>Status</th>
                <td mat-cell *matCellDef="let row">
                  <app-status-badge [status]="row.status"></app-status-badge>
                </td>
              </ng-container>

              <!-- Failed Checks -->
              <ng-container matColumnDef="failed_checks">
                <th mat-header-cell *matHeaderCellDef>Failed Checks</th>
                <td mat-cell *matCellDef="let row">
                  @if (row.failed_checks.length > 0) {
                    <span class="failed-checks">
                      {{ row.failed_checks.length }}
                    </span>
                  } @else {
                    <span class="no-failures">--</span>
                  }
                </td>
              </ng-container>

              <tr mat-header-row *matHeaderRowDef="deviceColumns"></tr>
              <tr
                mat-row
                *matRowDef="let row; columns: deviceColumns"
                class="clickable-row"
                (click)="viewSession(row)"
              ></tr>
            </table>
          </div>
        }

        <!-- Validation overview -->
        @if (g.summary.validation_summary.length > 0) {
          <h3 class="section-title">Validation Overview</h3>
          <div class="validation-grid">
            @for (check of g.summary.validation_summary; track check.check_name) {
              <div class="validation-item">
                <div class="check-name">{{ checkLabel(check.check_name) }}</div>
                <div class="check-counts">
                  @if (check.passed > 0) {
                    <span class="count-pass">
                      <mat-icon>check_circle</mat-icon>
                      {{ check.passed }}
                    </span>
                  }
                  @if (check.failed > 0) {
                    <span class="count-fail">
                      <mat-icon>cancel</mat-icon>
                      {{ check.failed }}
                    </span>
                  }
                  @if (check.skipped > 0) {
                    <span class="count-skip">
                      <mat-icon>remove_circle_outline</mat-icon>
                      {{ check.skipped }}
                    </span>
                  }
                </div>
              </div>
            }
          </div>
        }

        <!-- SLE overview -->
        @if (sleSummaryEntries().length > 0) {
          <h3 class="section-title">SLE Overview</h3>
          <div class="sle-grid">
            @for (entry of sleSummaryEntries(); track entry.metric) {
              <div class="sle-item" [class.degraded]="entry.delta_pct < -5">
                <div class="sle-metric">{{ sleLabel(entry.metric) }}</div>
                <div class="sle-values">
                  <span class="sle-baseline">{{ entry.baseline | number: '1.1-1' }}%</span>
                  <mat-icon class="sle-arrow">arrow_forward</mat-icon>
                  <span
                    class="sle-current"
                    [class.degraded]="entry.delta_pct < -5"
                    [class.improved]="entry.delta_pct > 5"
                  >
                    {{ entry.current | number: '1.1-1' }}%
                  </span>
                  <span
                    class="sle-delta"
                    [class.negative]="entry.delta_pct < 0"
                    [class.positive]="entry.delta_pct > 0"
                  >
                    {{ entry.delta_pct > 0 ? '+' : '' }}{{ entry.delta_pct | number: '1.1-1' }}%
                  </span>
                </div>
              </div>
            }
          </div>
        }

        <!-- AI assessment -->
        @if (aiAssessmentHtml()) {
          <h3 class="section-title">AI Assessment</h3>
          <div class="ai-assessment">
            <div class="ai-content" [innerHTML]="aiAssessmentHtml()"></div>
            @if (aiRecommendations().length > 0) {
              <div class="ai-recommendations">
                <h4>Recommendations</h4>
                <ul>
                  @for (rec of aiRecommendations(); track rec) {
                    <li>{{ rec }}</li>
                  }
                </ul>
              </div>
            }
          </div>
        }

        <!-- Timeline -->
        @if (g.timeline.length > 0) {
          <h3 class="section-title">Timeline</h3>
          <div class="timeline">
            @for (entry of g.timeline; track $index) {
              <div class="timeline-entry" [class]="'tl-' + (entry.severity || 'info')">
                <div class="tl-dot"></div>
                <div class="tl-content">
                  @if (entry.device_name) {
                    <span class="tl-device">{{ entry.device_name }}</span>
                  }
                  <div class="tl-title">{{ entry.title }}</div>
                  <div class="tl-time">{{ entry.timestamp | dateTime: 'short' }}</div>
                </div>
              </div>
            }
          </div>
        }
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

      /* ── Summary cards ────────────────────────────────────────────── */
      .summary-cards {
        display: flex;
        gap: 16px;
        margin-bottom: 24px;
      }

      .summary-card {
        flex: 1;
        padding: 16px;
        border: 1px solid var(--mat-sys-outline-variant, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        text-align: center;
      }

      .card-value {
        font-size: 28px;
        font-weight: 700;

        &.impacted {
          color: var(--app-warning);
        }
      }

      .card-label {
        font-size: 13px;
        color: var(--app-neutral);
        margin-top: 4px;
      }

      /* ── Section titles ───────────────────────────────────────────── */
      .section-title {
        font-size: 16px;
        font-weight: 600;
        margin: 24px 0 12px;
      }

      /* ── Device table ─────────────────────────────────────────────── */
      .device-cell {
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .device-icon {
        font-size: 18px;
        width: 18px;
        height: 18px;
        color: var(--app-neutral);
      }

      .failed-checks {
        color: var(--app-error);
        font-weight: 600;
      }

      .no-failures {
        color: var(--app-neutral);
      }

      /* ── Validation grid ──────────────────────────────────────────── */
      .validation-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 12px;
      }

      .validation-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 14px;
        border: 1px solid var(--mat-sys-outline-variant, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
      }

      .check-name {
        font-size: 13px;
        font-weight: 500;
      }

      .check-counts {
        display: flex;
        gap: 10px;
        font-size: 13px;

        span {
          display: flex;
          align-items: center;
          gap: 3px;
        }

        mat-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
        }
      }

      .count-pass {
        color: var(--app-success);
      }
      .count-fail {
        color: var(--app-error);
      }
      .count-skip {
        color: var(--app-neutral);
      }

      /* ── SLE grid ─────────────────────────────────────────────────── */
      .sle-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
        gap: 12px;
      }

      .sle-item {
        padding: 10px 14px;
        border: 1px solid var(--mat-sys-outline-variant, rgba(0, 0, 0, 0.12));
        border-radius: 8px;

        &.degraded {
          border-color: var(--app-warning);
          background: var(--app-warning-bg);
        }
      }

      .sle-metric {
        font-size: 13px;
        font-weight: 500;
        margin-bottom: 6px;
      }

      .sle-values {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 14px;
      }

      .sle-arrow {
        font-size: 16px;
        width: 16px;
        height: 16px;
        color: var(--app-neutral);
      }

      .sle-baseline {
        color: var(--app-neutral);
      }

      .sle-current {
        font-weight: 600;

        &.degraded {
          color: var(--app-error);
        }
        &.improved {
          color: var(--app-success);
        }
      }

      .sle-delta {
        font-size: 12px;
        font-weight: 600;

        &.negative {
          color: var(--app-error);
        }
        &.positive {
          color: var(--app-success);
        }
      }

      /* ── AI assessment ────────────────────────────────────────────── */
      .ai-assessment {
        padding: 16px;
        border: 1px solid var(--mat-sys-outline-variant, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
      }

      .ai-content {
        font-size: 14px;
        line-height: 1.6;

        ::ng-deep {
          p {
            margin: 0 0 8px;
          }
          ul,
          ol {
            margin: 4px 0 8px;
            padding-left: 20px;
          }
        }
      }

      .ai-recommendations {
        margin-top: 12px;
        padding-top: 12px;
        border-top: 1px solid var(--mat-sys-outline-variant, rgba(0, 0, 0, 0.12));

        h4 {
          margin: 0 0 8px;
          font-size: 14px;
          font-weight: 600;
        }

        ul {
          margin: 0;
          padding-left: 20px;
        }

        li {
          font-size: 13px;
          line-height: 1.5;
          margin-bottom: 4px;
        }
      }

      /* ── Timeline ─────────────────────────────────────────────────── */
      .timeline {
        position: relative;
        padding-left: 20px;
        border-left: 2px solid var(--mat-sys-outline-variant, rgba(0, 0, 0, 0.12));
      }

      .timeline-entry {
        position: relative;
        padding: 8px 0 16px 16px;
      }

      .tl-dot {
        position: absolute;
        left: -27px;
        top: 12px;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: var(--app-info);
        border: 2px solid var(--mat-sys-surface, #fff);
      }

      .tl-info .tl-dot {
        background: var(--app-info);
      }
      .tl-warning .tl-dot {
        background: var(--app-warning);
      }
      .tl-critical .tl-dot,
      .tl-error .tl-dot {
        background: var(--app-error);
      }
      .tl-success .tl-dot {
        background: var(--app-success);
      }

      .tl-device {
        font-size: 11px;
        font-weight: 500;
        color: var(--app-info);
        display: block;
        margin-bottom: 1px;
      }

      .tl-title {
        font-size: 13px;
        line-height: 1.4;
      }

      .tl-time {
        font-size: 12px;
        color: var(--app-neutral);
        margin-top: 2px;
      }

      /* ── Detail body ──────────────────────────────────────────────── */
      .detail-body {
        overflow-y: auto;
        padding-bottom: 32px;
      }

      /* ── Responsive ───────────────────────────────────────────────── */
      @media (max-width: 600px) {
        .summary-cards {
          flex-direction: column;
        }
      }
    `,
  ],
})
export class GroupDetailComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly service = inject(ImpactAnalysisService);
  private readonly topbarService = inject(TopbarService);
  private readonly wsService = inject(WebSocketService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);

  group = signal<ChangeGroupDetailResponse | null>(null);
  loading = signal(true);
  cancelling = signal(false);
  reanalyzing = signal(false);

  private groupId = '';

  isActive = computed(() => {
    const g = this.group();
    return g ? g.summary.status !== 'completed' && g.summary.status !== 'failed' : false;
  });

  worstSeverity = computed(() => this.group()?.summary.worst_severity ?? 'none');

  impactedCount = computed(() => {
    const g = this.group();
    if (!g) return 0;
    return g.summary.devices.filter(
      (d) => d.impact_severity && d.impact_severity !== 'none',
    ).length;
  });

  sleSummaryEntries = computed<SLEDeltaSummary[]>(() => {
    const g = this.group();
    if (!g) return [];
    return Object.values(g.summary.sle_summary);
  });

  aiAssessmentHtml = computed(() => {
    const ai = this.group()?.ai_assessment;
    if (!ai) return '';
    const summary = ai['summary'] as string | undefined;
    return summary ? renderMarkdown(summary) : '';
  });

  aiRecommendations = computed<string[]>(() => {
    const ai = this.group()?.ai_assessment;
    if (!ai) return [];
    return (ai['recommendations'] as string[]) ?? [];
  });

  deviceColumns = ['impact', 'device', 'type', 'site', 'status', 'failed_checks'];

  deviceTypeIcon = _deviceTypeIcon;
  formatDeviceType = _formatDeviceType;

  ngOnInit(): void {
    this.groupId = this.route.snapshot.paramMap.get('id') ?? '';
    this.topbarService.setTitle('Change Group');
    this.loadGroup();
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

  checkLabel(key: string): string {
    return VALIDATION_CHECK_LABELS[key] ?? key.replace(/_/g, ' ');
  }

  sleLabel(key: string): string {
    return SLE_METRIC_LABELS[key] ?? key;
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
