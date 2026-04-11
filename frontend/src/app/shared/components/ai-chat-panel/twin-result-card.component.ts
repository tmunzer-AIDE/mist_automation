import { Component, computed, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

export interface TwinResultData {
  session_id: string;
  status: string;
  overall_severity: string;
  remediation_count: number;
  summary?: string;
  execution_safe?: boolean;
  counts?: { total: number; passed: number; warnings: number; errors: number; critical: number };
  issues?: TwinIssue[];
}

interface TwinIssue {
  check: string;
  name: string;
  status: string;
  summary: string;
  details?: string[];
  remediation_hint?: string;
}

@Component({
  selector: 'app-twin-result-card',
  standalone: true,
  imports: [MatIconModule, MatButtonModule],
  template: `
    <div class="twin-card" [class]="'twin-card-' + severityClass()">
      <!-- Header -->
      <div class="twin-header">
        <div class="twin-icon" [class]="'twin-icon-' + severityClass()">
          <mat-icon>{{ severityIcon() }}</mat-icon>
        </div>
        <div class="twin-title">
          <div class="twin-label" [class]="'twin-label-' + severityClass()">
            Digital Twin Simulation
          </div>
          <div class="twin-severity">
            <span class="severity-badge" [class]="'severity-' + severityClass()">
              {{ data().overall_severity }}
            </span>
            @if (data().execution_safe === false) {
              <span class="severity-badge severity-unsafe">not safe</span>
            }
          </div>
        </div>
      </div>

      <!-- Counts bar -->
      @if (data().counts; as counts) {
        <div class="twin-counts">
          <div class="counts-text">
            {{ counts.total }} checks:
            <span class="count-passed">{{ counts.passed }} passed</span>
            @if (counts.warnings > 0) {
              ,
              <span class="count-warning"
                >{{ counts.warnings }} warning{{ counts.warnings > 1 ? 's' : '' }}</span
              >
            }
            @if (counts.errors > 0) {
              ,
              <span class="count-error"
                >{{ counts.errors }} error{{ counts.errors > 1 ? 's' : '' }}</span
              >
            }
            @if (counts.critical > 0) {
              , <span class="count-critical">{{ counts.critical }} critical</span>
            }
          </div>
          <div class="progress-bar">
            @if (counts.passed > 0) {
              <div
                class="bar-segment bar-passed"
                [style.width.%]="(counts.passed / counts.total) * 100"
              ></div>
            }
            @if (counts.warnings > 0) {
              <div
                class="bar-segment bar-warning"
                [style.width.%]="(counts.warnings / counts.total) * 100"
              ></div>
            }
            @if (counts.errors > 0) {
              <div
                class="bar-segment bar-error"
                [style.width.%]="(counts.errors / counts.total) * 100"
              ></div>
            }
            @if (counts.critical > 0) {
              <div
                class="bar-segment bar-critical"
                [style.width.%]="(counts.critical / counts.total) * 100"
              ></div>
            }
          </div>
        </div>
      }

      <!-- Issues -->
      @if (issues().length > 0) {
        <div class="twin-issues-toggle" (click)="issuesExpanded.set(!issuesExpanded())">
          <mat-icon class="chevron">{{
            issuesExpanded() ? 'expand_more' : 'chevron_right'
          }}</mat-icon>
          <span>{{ issues().length }} issue{{ issues().length > 1 ? 's' : '' }}</span>
        </div>
        @if (issuesExpanded()) {
          <div class="twin-issues">
            @for (issue of issues(); track issue.check) {
              <div class="issue-row">
                <div class="issue-header">
                  <span class="issue-dot" [class]="'dot-' + issue.status"></span>
                  <span class="issue-name">{{ issue.name }}</span>
                  <span class="issue-check">{{ issue.check }}</span>
                </div>
                <div class="issue-summary">{{ issue.summary }}</div>
                @if (issue.details?.length) {
                  <div class="issue-details">
                    @for (d of issue.details; track $index) {
                      <div class="issue-detail-line">{{ d }}</div>
                    }
                  </div>
                }
                @if (issue.remediation_hint) {
                  <div class="issue-remediation">
                    <mat-icon>lightbulb</mat-icon>
                    <span>{{ issue.remediation_hint }}</span>
                  </div>
                }
              </div>
            }
          </div>
        }
      } @else if (data().counts) {
        <div class="twin-clean">
          <mat-icon>check_circle</mat-icon>
          <span>All checks passed</span>
        </div>
      }
    </div>
  `,
  styles: [
    `
      .twin-card {
        margin: 0 4px;
        border-radius: 12px;
        border: 1px solid var(--mat-sys-outline-variant);
        background: var(--mat-sys-surface-container, #f5f5f5);
        overflow: hidden;
        animation: twin-in 200ms ease-out;
      }

      .twin-card-success {
        border-left: 3px solid var(--app-success);
      }
      .twin-card-warning {
        border-left: 3px solid var(--app-warning);
      }
      .twin-card-error {
        border-left: 3px solid var(--app-error);
      }
      .twin-card-critical {
        border-left: 3px solid var(--app-error);
      }

      @keyframes twin-in {
        from {
          opacity: 0;
          transform: translateY(8px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }

      .twin-header {
        display: flex;
        gap: 10px;
        padding: 12px 14px;
        align-items: flex-start;
      }

      .twin-icon {
        flex-shrink: 0;
        width: 32px;
        height: 32px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        mat-icon {
          font-size: 18px;
          width: 18px;
          height: 18px;
        }
      }

      .twin-icon-success {
        background: var(--app-success-bg, #e8f5e9);
        color: var(--app-success, #2e7d32);
      }
      .twin-icon-warning {
        background: var(--app-warning-bg, #fff3cd);
        color: var(--app-warning, #e65100);
      }
      .twin-icon-error,
      .twin-icon-critical {
        background: var(--app-error-bg, #fbe9e7);
        color: var(--app-error, #c62828);
      }

      .twin-title {
        flex: 1;
        min-width: 0;
      }

      .twin-label {
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }

      .twin-label-success {
        color: var(--app-success, #2e7d32);
      }
      .twin-label-warning {
        color: var(--app-warning, #e65100);
      }
      .twin-label-error,
      .twin-label-critical {
        color: var(--app-error, #c62828);
      }

      .twin-severity {
        display: flex;
        gap: 6px;
        margin-top: 4px;
      }

      .severity-badge {
        font-size: 11px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 10px;
        text-transform: capitalize;
      }

      .severity-success {
        background: var(--app-success-bg, #e8f5e9);
        color: var(--app-success, #2e7d32);
      }
      .severity-warning {
        background: var(--app-warning-bg, #fff3cd);
        color: var(--app-warning, #e65100);
      }
      .severity-error {
        background: var(--app-error-bg, #fbe9e7);
        color: var(--app-error, #c62828);
      }
      .severity-critical {
        background: var(--app-error-bg, #fbe9e7);
        color: var(--app-error, #c62828);
      }
      .severity-unsafe {
        background: var(--app-error-bg, #fbe9e7);
        color: var(--app-error, #c62828);
      }

      .twin-counts {
        padding: 0 14px 10px;
      }

      .counts-text {
        font-size: 12px;
        color: var(--mat-sys-on-surface-variant);
        margin-bottom: 6px;
      }

      .count-passed {
        color: var(--app-success, #2e7d32);
      }
      .count-warning {
        color: var(--app-warning, #e65100);
      }
      .count-error {
        color: var(--app-error, #c62828);
      }
      .count-critical {
        color: var(--app-error, #c62828);
        font-weight: 600;
      }

      .progress-bar {
        display: flex;
        height: 6px;
        border-radius: 3px;
        overflow: hidden;
        background: rgba(128, 128, 128, 0.12);
      }

      .bar-segment {
        height: 100%;
        min-width: 2px;
      }

      .bar-passed {
        background: var(--app-success, #2e7d32);
      }
      .bar-warning {
        background: var(--app-warning, #e65100);
      }
      .bar-error {
        background: var(--app-error, #c62828);
      }
      .bar-critical {
        background: #b71c1c;
      }

      .twin-issues-toggle {
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 6px 14px;
        cursor: pointer;
        font-size: 13px;
        font-weight: 500;
        border-top: 1px solid rgba(128, 128, 128, 0.15);

        &:hover {
          background: rgba(128, 128, 128, 0.06);
        }

        .chevron {
          font-size: 18px;
          width: 18px;
          height: 18px;
          color: var(--app-neutral);
        }
      }

      .twin-issues {
        max-height: 250px;
        overflow-y: auto;
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.3) transparent;
      }

      .issue-row {
        padding: 8px 14px;
        border-top: 1px solid rgba(128, 128, 128, 0.1);
      }

      .issue-header {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 13px;
      }

      .issue-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
      }

      .dot-warning {
        background: var(--app-warning, #e65100);
      }
      .dot-error {
        background: var(--app-error, #c62828);
      }
      .dot-critical {
        background: #b71c1c;
      }

      .issue-name {
        font-weight: 500;
        flex: 1;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .issue-check {
        font-size: 11px;
        font-family: var(--app-font-mono, monospace);
        color: var(--mat-sys-on-surface-variant);
        flex-shrink: 0;
      }

      .issue-summary {
        font-size: 12px;
        color: var(--mat-sys-on-surface-variant);
        margin-top: 2px;
        padding-left: 14px;
      }

      .issue-details {
        margin-top: 4px;
        padding-left: 14px;
      }

      .issue-detail-line {
        font-size: 11px;
        font-family: var(--app-font-mono, monospace);
        color: var(--mat-sys-on-surface-variant);
        padding: 2px 6px;
        background: var(--mat-sys-surface-variant, #f0f0f0);
        border-radius: 4px;
        margin-bottom: 2px;
        word-break: break-all;
      }

      .issue-remediation {
        display: flex;
        align-items: flex-start;
        gap: 4px;
        margin-top: 4px;
        padding-left: 14px;
        font-size: 12px;
        color: var(--app-info, #1976d2);

        mat-icon {
          font-size: 14px;
          width: 14px;
          height: 14px;
          flex-shrink: 0;
          margin-top: 1px;
        }
      }

      .twin-clean {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 8px 14px;
        font-size: 13px;
        color: var(--app-success, #2e7d32);

        mat-icon {
          font-size: 18px;
          width: 18px;
          height: 18px;
        }
      }
    `,
  ],
})
export class TwinResultCardComponent {
  data = input.required<TwinResultData>();

  issuesExpanded = signal(false);

  issues = computed<TwinIssue[]>(() => this.data().issues ?? []);

  severityClass = computed(() => {
    const s = this.data().overall_severity;
    if (s === 'critical' || s === 'error') return 'error';
    if (s === 'warning') return 'warning';
    return 'success';
  });

  severityIcon = computed(() => {
    const s = this.data().overall_severity;
    if (s === 'critical' || s === 'error') return 'error';
    if (s === 'warning') return 'warning';
    return 'check_circle';
  });
}
