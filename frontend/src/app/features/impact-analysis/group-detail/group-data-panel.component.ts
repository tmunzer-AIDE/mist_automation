import { Component, computed, input, output } from '@angular/core';
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
