import { Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTabsModule } from '@angular/material/tabs';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { WorkflowService } from '../../../core/services/workflow.service';
import { WorkflowExecution, NodeExecutionResult } from '../../../core/models/workflow.model';
import { DurationPipe } from '../../../shared/pipes/duration.pipe';

@Component({
  selector: 'app-execution-detail-dialog',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatIconModule,
    MatTabsModule,
    MatDialogModule,
    StatusBadgeComponent,
    DurationPipe,
  ],
  template: `
    <h2 mat-dialog-title>
      @if (execution()) {
        <div class="dialog-header">
          <app-status-badge [status]="execution()!.status"></app-status-badge>
          <span class="header-name">{{ execution()!.workflow_name }}</span>
          <span class="header-meta"
            >{{ execution()!.trigger_type }} &middot; {{ execution()!.duration_ms | duration }}</span
          >
        </div>
      } @else {
        Loading…
      }
    </h2>

    <mat-dialog-content>
      @if (loading()) {
        <div class="loading">Loading execution details…</div>
      } @else if (execution()) {
        @if (execution()!.error) {
          <div class="execution-error-banner">
            <mat-icon>error_outline</mat-icon>
            <span>{{ execution()!.error }}</span>
          </div>
        }
        <mat-tab-group>
          <!-- Nodes Tab -->
          <mat-tab label="Nodes">
            <div class="tab-content">
              @if (nodeResultsList().length === 0) {
                <div class="empty-tab">No node results recorded.</div>
              } @else {
                <div class="action-list">
                  @for (result of nodeResultsList(); track result.node_id) {
                    <div class="action-item">
                      <div class="action-header">
                        <app-status-badge [status]="result.status"></app-status-badge>
                        <span class="action-name">{{ result.node_name || result.node_id }}</span>
                        <span class="action-type">{{ result.node_type }}</span>
                        <span class="action-meta">
                          {{ result.duration_ms | duration }}
                          @if (result.retry_count > 0) {
                            &middot; {{ result.retry_count }} retries
                          }
                        </span>
                      </div>
                      @if (result.error) {
                        <div class="action-error">
                          <mat-icon>error_outline</mat-icon>
                          {{ result.error }}
                        </div>
                      }
                      @if (result.output_data) {
                        <details class="action-output">
                          <summary>Output</summary>
                          <pre class="json-pre">{{ result.output_data | json }}</pre>
                        </details>
                      }
                    </div>
                  }
                </div>
              }
            </div>
          </mat-tab>

          <!-- Logs Tab -->
          <mat-tab label="Logs">
            <div class="tab-content">
              @if (!execution()!.logs || execution()!.logs!.length === 0) {
                <div class="empty-tab">No log entries.</div>
              } @else {
                <div class="log-container">
                  @for (line of execution()!.logs; track line) {
                    <div class="log-line" [class]="getLogClass(line)">{{ line }}</div>
                  }
                </div>
              }
            </div>
          </mat-tab>

          <!-- Variables Tab -->
          <mat-tab label="Variables">
            <div class="tab-content">
              @if (!execution()!.variables || isEmptyObj(execution()!.variables!)) {
                <div class="empty-tab">No variables captured.</div>
              } @else {
                <pre class="json-pre">{{ execution()!.variables | json }}</pre>
              }
            </div>
          </mat-tab>

          <!-- Trigger Data Tab -->
          <mat-tab label="Trigger Data">
            <div class="tab-content">
              @if (!execution()!.trigger_data) {
                <div class="empty-tab">No trigger data.</div>
              } @else {
                <pre class="json-pre">{{ execution()!.trigger_data | json }}</pre>
              }
            </div>
          </mat-tab>
        </mat-tab-group>
      }
    </mat-dialog-content>

    <mat-dialog-actions align="end">
      <button mat-flat-button mat-dialog-close>Close</button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .dialog-header {
        display: flex;
        align-items: center;
        gap: 10px;
        flex-wrap: wrap;
      }
      .header-name {
        font-weight: 600;
      }
      .header-meta {
        font-size: 13px;
        color: var(--mat-sys-on-surface-variant);
      }
      .execution-error-banner {
        display: flex;
        align-items: flex-start;
        gap: 8px;
        padding: 12px 16px;
        margin-bottom: 16px;
        background: var(--app-error-status-bg);
        color: var(--app-error-status);
        border-radius: 8px;
        font-size: 14px;
        line-height: 1.5;

        mat-icon {
          flex-shrink: 0;
          margin-top: 1px;
        }
      }
      .loading,
      .empty-tab {
        padding: 24px;
        color: var(--mat-sys-on-surface-variant);
      }
      .tab-content {
        padding: 16px 0;
      }

      /* Nodes */
      .action-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .action-item {
        border: 1px solid var(--mat-sys-outline-variant);
        border-radius: 8px;
        padding: 12px;
      }
      .action-header {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .action-name {
        font-weight: 500;
      }
      .action-type {
        font-size: 11px;
        color: var(--mat-sys-on-surface-variant);
        background: var(--mat-sys-surface-variant);
        padding: 1px 6px;
        border-radius: 4px;
      }
      .action-meta {
        font-size: 12px;
        color: var(--mat-sys-on-surface-variant);
        margin-left: auto;
      }
      .action-error {
        display: flex;
        align-items: flex-start;
        gap: 6px;
        margin-top: 8px;
        padding: 8px 10px;
        background: var(--app-error-status-bg);
        color: var(--app-error-status);
        border-radius: 6px;
        font-size: 13px;

        mat-icon {
          font-size: 18px;
          width: 18px;
          height: 18px;
          flex-shrink: 0;
        }
      }
      .action-output {
        margin-top: 8px;

        summary {
          cursor: pointer;
          font-size: 13px;
          font-weight: 500;
          color: var(--mat-sys-primary);
        }
      }

      /* Logs */
      .log-container {
        background: var(--mat-sys-surface-container);
        border-radius: 8px;
        padding: 12px 16px;
        max-height: 400px;
        overflow: auto;
      }
      .log-line {
        font-family: monospace;
        font-size: 12px;
        line-height: 1.7;
        white-space: pre-wrap;
        word-break: break-all;
      }
      .log-warn {
        color: var(--app-warning-lvl);
      }
      .log-error {
        color: var(--app-error-status);
      }

      /* JSON */
      .json-pre {
        background: var(--mat-sys-surface-container);
        border-radius: 8px;
        padding: 16px;
        font-size: 12px;
        font-family: monospace;
        overflow: auto;
        max-height: 400px;
        white-space: pre-wrap;
        word-break: break-all;
      }
    `,
  ],
})
export class ExecutionDetailDialogComponent implements OnInit {
  private readonly data: { workflowId: string; execution: WorkflowExecution } =
    inject(MAT_DIALOG_DATA);
  private readonly dialogRef = inject(MatDialogRef<ExecutionDetailDialogComponent>);
  private readonly workflowService = inject(WorkflowService);

  execution = signal<WorkflowExecution | null>(null);
  loading = signal(true);
  nodeResultsList = signal<NodeExecutionResult[]>([]);

  ngOnInit(): void {
    this.workflowService.getExecution(this.data.workflowId, this.data.execution.id).subscribe({
      next: (ex) => {
        this.execution.set(ex);
        this.nodeResultsList.set(Object.values(ex.node_results || {}));
        this.loading.set(false);
      },
      error: () => {
        this.execution.set(this.data.execution);
        this.nodeResultsList.set(Object.values(this.data.execution.node_results || {}));
        this.loading.set(false);
      },
    });
  }

  getLogClass(line: string): string {
    if (line.includes('[WARN]') || line.includes('[WARNING]')) return 'log-warn';
    if (line.includes('[ERROR]')) return 'log-error';
    return '';
  }

  isEmptyObj(obj: Record<string, unknown>): boolean {
    return Object.keys(obj).length === 0;
  }
}
