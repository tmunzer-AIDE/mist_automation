import { Component, input, computed } from '@angular/core';
import { TitleCasePipe } from '@angular/common';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import {
  SessionDetailResponse,
  SLE_METRIC_LABELS,
  VALIDATION_CHECK_LABELS,
} from '../models/impact-analysis.model';

@Component({
  selector: 'app-impact-data-panel',
  standalone: true,
  imports: [TitleCasePipe, MatProgressBarModule, MatIconModule, MatTooltipModule, DateTimePipe],
  template: `
    <div class="data-panel-content">
      <!-- Progress section -->
      @if (session(); as s) {
        <div class="section">
          <div class="section-header">Progress</div>
          <div class="phase-label">{{ s.progress.phase | titlecase }}</div>
          <mat-progress-bar
            [mode]="progressMode()"
            [value]="timeProgress()"
          ></mat-progress-bar>
          <div class="progress-meta">
            <span>{{ timeProgress() }}%</span>
            @if (timeRemaining()) {
              <span class="time-remaining">{{ timeRemaining() }}</span>
            }
          </div>
          <div class="timestamp-row">
            <span class="ts-label">Started</span>
            <span class="ts-value">
              @if (s.monitoring_started_at) {
                {{ s.monitoring_started_at | dateTime: 'short' }}
              } @else {
                {{ s.created_at | dateTime: 'short' }}
              }
            </span>
          </div>
          @if (s.monitoring_ends_at) {
            <div class="timestamp-row">
              <span class="ts-label">Ends</span>
              <span class="ts-value">{{ s.monitoring_ends_at | dateTime: 'short' }}</span>
            </div>
          }
          @if (s.completed_at) {
            <div class="timestamp-row">
              <span class="ts-label">Completed</span>
              <span class="ts-value">{{ s.completed_at | dateTime: 'short' }}</span>
            </div>
          }
        </div>
        <div class="section-divider"></div>
      }

      <!-- Config Changes section -->
      @if (session()?.config_changes?.length) {
        <div class="section">
          <div class="section-header">
            Config Changes
            <span class="count-badge">{{ session()!.config_changes.length }}</span>
          </div>
          @for (change of session()!.config_changes; track $index) {
            <div class="config-row">
              <div class="config-event-type">{{ change.event_type }}</div>
              <div class="config-meta">
                <span>{{ change.timestamp | dateTime: 'short' }}</span>
                @if (change.commit_user) {
                  <span class="commit-user">{{ change.commit_user }}</span>
                }
              </div>
            </div>
          }
        </div>
        <div class="section-divider"></div>
      }

      <!-- Incidents -->
      <div class="section">
        <div class="section-header">
          Incidents
          <span class="count-badge">{{ session()?.incident_count ?? 0 }}</span>
        </div>
        @if (session()?.incidents?.length) {
          @for (incident of session()!.incidents; track $index) {
            <div class="incident-row">
              <mat-icon [class]="'incident-icon severity-' + incident.severity">
                @switch (incident.severity) {
                  @case ('critical') { error }
                  @case ('warning') { warning }
                  @default { info }
                }
              </mat-icon>
              <div class="incident-info">
                <div class="incident-type">{{ incident.event_type }}</div>
                <div class="incident-meta">
                  {{ incident.timestamp | dateTime: 'short' }}
                  @if (incident.resolved) {
                    <span class="resolved-badge">Resolved</span>
                  }
                </div>
              </div>
            </div>
          }
        } @else {
          <div class="empty-hint">No incidents detected</div>
        }
      </div>
      <div class="section-divider"></div>

      <!-- Validation Checks -->
      @if (session()?.validation_results) {
        <div class="section">
          <div class="section-header">
            Validation
            <span
              class="status-pill"
              [class]="'pill-' + overallValidationStatus()"
            >{{ overallValidationStatus() | titlecase }}</span>
          </div>
          @for (check of validationChecks(); track check.name) {
            <div
              class="check-row"
              [class.check-warn]="check.status === 'warn'"
              [class.check-fail]="check.status === 'fail'"
              [matTooltip]="check.details.length ? check.details[0] : ''"
            >
              <span class="check-label">{{ check.label }}</span>
              <mat-icon [class]="'check-icon check-' + check.status">
                @switch (check.status) {
                  @case ('pass') { check_circle }
                  @case ('warn') { warning }
                  @case ('fail') { cancel }
                  @case ('error') { error_outline }
                  @default { help_outline }
                }
              </mat-icon>
            </div>
          }
        </div>
        <div class="section-divider"></div>
      }

      <!-- SLE Metrics -->
      @if (session()?.sle_data) {
        <div class="section">
          <div class="section-header">
            SLE Metrics
            @if (sleOverallDegraded()) {
              <span class="status-pill pill-fail">Degraded</span>
            }
          </div>
          @if (deltaMetrics().length > 0) {
            @for (m of deltaMetrics(); track m.name) {
              <div class="sle-row" [class.sle-row-degraded]="m.degraded">
                <span class="sle-name">{{ m.label }}</span>
                <span class="sle-values">
                  {{ m.baseline_value }}
                  <mat-icon class="sle-arrow">arrow_forward</mat-icon>
                  {{ m.current_value }}
                </span>
                <span
                  [class]="deltaClass(m.change_percent)"
                >
                  @if (m.change_percent != null) {
                    {{ m.change_percent > 0 ? '+' : '' }}{{ m.change_percent }}%
                  } @else {
                    —
                  }
                </span>
              </div>
            }
          } @else if (baselineMetrics().length > 0) {
            <div class="sle-baseline-hint">
              Baseline captured ({{ baselineMetrics().length }} metrics)
            </div>
            @for (m of baselineMetrics(); track m.name) {
              <div class="sle-row">
                <span class="sle-name">{{ m.name }}</span>
                <span class="sle-values baseline-only">
                  @if (m.value !== null) {
                    {{ m.value }}%
                  } @else {
                    no data
                  }
                </span>
              </div>
            }
          } @else {
            <div class="empty-hint">Awaiting SLE data</div>
          }
        </div>
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
      // height: calc(100% - 32px);
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

    // ── Progress ────────────────────────────────────────────────────────────
    .phase-label {
      font-size: 13px;
      font-weight: 500;
      margin-bottom: 6px;
    }

    .progress-meta {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 4px;
      font-size: 11px;
      color: var(--app-neutral, #757575);
    }

    .time-remaining {
      font-weight: 500;
    }

    .timestamp-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 3px 0;
      font-size: 11px;
    }

    .ts-label {
      color: var(--app-neutral, #757575);
    }

    .ts-value {
      font-weight: 500;
    }

    // ── Config Changes ──────────────────────────────────────────────────────
    .config-row {
      padding: 6px 8px;
      border-radius: 6px;
      background: var(--app-info-bg, rgba(37, 99, 235, 0.05));
      margin-bottom: 4px;
    }

    .config-event-type {
      font-size: 12px;
      font-weight: 500;
    }

    .config-meta {
      display: flex;
      justify-content: space-between;
      font-size: 11px;
      color: var(--app-neutral, #757575);
      margin-top: 2px;
    }

    .commit-user {
      font-style: italic;
    }

    // ── Count Badge ─────────────────────────────────────────────────────────
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

    // ── Validation Checks ───────────────────────────────────────────────────
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

      &.pill-error {
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

    .check-icon {
      font-size: 16px;
      width: 16px;
      height: 16px;
      flex-shrink: 0;

      &.check-pass {
        color: var(--app-success);
      }

      &.check-warn {
        color: var(--app-warning);
      }

      &.check-fail {
        color: var(--app-error);
      }

      &.check-error {
        color: var(--app-error);
      }

      &.check-unknown {
        color: var(--app-neutral, #757575);
      }
    }

    // ── SLE Metrics ─────────────────────────────────────────────────────────
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
      text-transform: capitalize;
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

      &.baseline-only {
        font-style: italic;
        font-size: 10px;
      }
    }

    .sle-arrow {
      font-size: 12px;
      width: 12px;
      height: 12px;
      color: var(--app-neutral, #757575);
    }

    .sle-baseline-hint {
      font-size: 11px;
      color: var(--app-neutral, #757575);
      margin-bottom: 6px;
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

    // ── Incidents ───────────────────────────────────────────────────────────
    .incident-row {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      padding: 6px 8px;
      border-radius: 6px;
      background: var(--app-neutral-bg, rgba(0, 0, 0, 0.03));
      margin-bottom: 4px;
    }

    .incident-icon {
      font-size: 16px;
      width: 16px;
      height: 16px;
      flex-shrink: 0;
      margin-top: 1px;

      &.severity-critical {
        color: var(--app-error);
      }

      &.severity-warning {
        color: var(--app-warning);
      }

      &.severity-info {
        color: var(--app-info);
      }
    }

    .incident-info {
      flex: 1;
      min-width: 0;
    }

    .incident-type {
      font-size: 12px;
      font-weight: 500;
    }

    .incident-meta {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11px;
      color: var(--app-neutral, #757575);
      margin-top: 2px;
    }

    .resolved-badge {
      font-size: 10px;
      font-weight: 600;
      padding: 1px 5px;
      border-radius: 3px;
      background: var(--app-success-bg);
      color: var(--app-success);
    }

    // ── Empty ───────────────────────────────────────────────────────────────
    .empty-hint {
      font-size: 12px;
      color: var(--app-neutral, #757575);
      text-align: center;
      padding: 12px 0;
    }
  `,
})
export class ImpactDataPanelComponent {
  session = input<SessionDetailResponse | null>(null);
  timeProgress = input<number>(0);

  progressMode = computed<'determinate' | 'indeterminate'>(() => {
    return this.timeProgress() > 0 ? 'determinate' : 'indeterminate';
  });

  timeRemaining = computed<string>(() => {
    const s = this.session();
    if (!s?.monitoring_ends_at) return '';

    const now = Date.now();
    const end = new Date(this.ensureUtc(s.monitoring_ends_at)).getTime();
    const diff = end - now;

    if (diff <= 0) return '';

    const totalMinutes = Math.ceil(diff / 60_000);
    if (totalMinutes < 1) return '< 1 min';
    if (totalMinutes < 60) return `${totalMinutes} min`;

    const hours = Math.floor(totalMinutes / 60);
    const mins = totalMinutes % 60;
    return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
  });

  validationChecks = computed(() => {
    const results = this.session()?.validation_results;
    if (!results || typeof results !== 'object') return [];
    return Object.entries(results)
      .filter(([key]) => key !== 'overall_status' && key !== 'error')
      .map(([key, value]: [string, unknown]) => {
        const v = value as Record<string, unknown> | null;
        return {
          name: key,
          label: VALIDATION_CHECK_LABELS[key] || key.replace(/_/g, ' '),
          status: (v?.['status'] as string) || 'unknown',
          details: Array.isArray(v?.['details']) ? (v!['details'] as string[]) : [],
        };
      });
  });

  overallValidationStatus = computed(() => {
    const results = this.session()?.validation_results;
    return (results?.['overall_status'] as string) || 'unknown';
  });

  deltaMetrics = computed(() => {
    const delta = this.session()?.sle_data?.delta as Record<string, unknown> | undefined;
    const metrics = delta?.['metrics'] as
      | Array<{
          name: string;
          baseline_value: number;
          current_value: number;
          change_percent: number;
          degraded: boolean;
          status: string;
        }>
      | undefined;
    if (!metrics) return [];
    return metrics.map((m) => ({
      ...m,
      label: SLE_METRIC_LABELS[m.name] || m.name.replace(/-/g, ' '),
    }));
  });

  sleOverallDegraded = computed(() => {
    const delta = this.session()?.sle_data?.delta as Record<string, unknown> | undefined;
    return (delta?.['overall_degraded'] as boolean) ?? false;
  });

  baselineMetrics = computed(() => {
    const baseline = this.session()?.sle_data?.baseline as Record<string, unknown> | undefined;
    const metrics = baseline?.['metrics'] as Record<string, Record<string, unknown>> | undefined;
    if (!metrics) return [];
    return Object.entries(metrics)
      .filter(([, data]) => data && Object.keys(data).length > 0)
      .map(([name, data]) => ({
        name: SLE_METRIC_LABELS[name] || name.replace(/-/g, ' '),
        value: typeof data?.['baseline_value'] === 'number' ? (data['baseline_value'] as number) : null,
      }));
  });

  deltaClass(changePercent: number | null): string {
    if (changePercent == null) return 'delta-neutral';
    if (changePercent < 0) return 'delta-negative';
    if (changePercent > 0) return 'delta-positive';
    return 'delta-neutral';
  }

  private ensureUtc(value: string): string {
    if (/[Zz]$/.test(value) || /[+-]\d{2}:\d{2}$/.test(value)) return value;
    return value + 'Z';
  }
}
