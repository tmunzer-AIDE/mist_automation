import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { JsonPipe, SlicePipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatIconModule } from '@angular/material/icon';
import { MatTabsModule } from '@angular/material/tabs';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { AiChatPanelComponent } from '../../../shared/components/ai-chat-panel/ai-chat-panel.component';
import { AiIconComponent } from '../../../shared/components/ai-icon/ai-icon.component';
import { WorkflowService } from '../../../core/services/workflow.service';
import { LlmService } from '../../../core/services/llm.service';
import { WorkflowExecution, NodeExecutionResult } from '../../../core/models/workflow.model';
import { DurationPipe } from '../../../shared/pipes/duration.pipe';
import { extractErrorMessage } from '../../../shared/utils/error.utils';

interface AIAgentOutputData {
  result?: string;
  iterations?: number;
  tool_calls?: Array<Record<string, unknown>>;
  output_fields?: Record<string, unknown> | Array<{ label?: string; value?: unknown }>;
  status?: string;
  error?: string;
}

@Component({
  selector: 'app-execution-detail-dialog',
  standalone: true,
  imports: [
    JsonPipe,
    SlicePipe,
    MatButtonModule,
    MatChipsModule,
    MatExpansionModule,
    MatIconModule,
    MatTabsModule,
    MatDialogModule,
    StatusBadgeComponent,
    AiChatPanelComponent,
    AiIconComponent,
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
                      @if (result.node_type === 'ai_agent' && aiOutputData(result); as ai) {
                        <div class="ai-result-card">
                          <div class="ai-result-header">
                            <app-status-badge [status]="result.status"></app-status-badge>
                            <span class="ai-result-title">AI Agent Result</span>
                            @if (ai.iterations) {
                              <span class="ai-result-meta">{{ ai.iterations }} iterations</span>
                            }
                          </div>

                          @if (ai.result) {
                            <div class="ai-result-text">{{ ai.result }}</div>
                          } @else if (ai.status !== 'error') {
                            <div class="ai-result-text ai-result-empty">No result</div>
                          }

                          @let fields = outputFieldsEntries(ai);
                          @if (fields.length > 0) {
                            <div class="ai-result-fields">
                              @for (field of fields; track field.key) {
                                <mat-chip>{{ field.key }}: {{ field.value }}</mat-chip>
                              }
                            </div>
                          }

                          @if (ai.tool_calls && ai.tool_calls.length > 0) {
                            <mat-expansion-panel class="ai-tool-calls-panel">
                              <mat-expansion-panel-header>
                                <mat-panel-title>
                                  {{ ai.tool_calls.length }}
                                  {{ ai.tool_calls.length === 1 ? 'tool call' : 'tool calls' }}
                                </mat-panel-title>
                              </mat-expansion-panel-header>
                              @for (tc of ai.tool_calls; track $index) {
                                @let name = toolName(tc);
                                @let preview = toolPreview(tc);
                                <div class="ai-tool-call-row">
                                  <strong>{{ name || 'Tool call (format unrecognized)' }}</strong>
                                  <span class="ai-tool-preview">{{ preview | slice: 0 : 120 }}</span>
                                  @if (!name && !preview) {
                                    <details class="ai-tool-raw-json">
                                      <summary>Raw tool call JSON</summary>
                                      <pre>{{ tc | json }}</pre>
                                    </details>
                                  }
                                </div>
                              }
                            </mat-expansion-panel>
                          }

                          @if (ai.status === 'error') {
                            <div class="ai-result-error">
                              <mat-icon>error_outline</mat-icon>
                              {{ ai.error || 'No result' }}
                            </div>
                          }
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

        @if (aiPanelOpen()) {
          <div class="ai-debug-panel">
            <div class="ai-debug-header">
              <app-ai-icon [size]="20"></app-ai-icon>
              <span>AI Debug Analysis</span>
              <button mat-icon-button (click)="aiPanelOpen.set(false)"><mat-icon>close</mat-icon></button>
            </div>
            <app-ai-chat-panel
              [initialSummary]="aiSummary()"
              [errorMessage]="aiError()"
              [parentLoading]="aiLoading()"
              [threadId]="aiThreadId()"
              loadingLabel="Analyzing execution..."
            ></app-ai-chat-panel>
          </div>
        }
      }
    </mat-dialog-content>

    <mat-dialog-actions align="end">
      @if (hasFailedNodes() && llmAvailable()) {
        <button mat-stroked-button (click)="debugWithAI()" [disabled]="aiLoading()">
          <app-ai-icon [size]="18" [animated]="false"></app-ai-icon> Debug with AI
        </button>
      }
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

      /* AI Debug */
      .ai-debug-panel {
        margin-top: 16px;
        border: 1px solid var(--mat-sys-outline-variant);
        border-radius: 12px;
        overflow: hidden;
      }
      .ai-debug-header {
        display: flex; align-items: center; gap: 8px;
        padding: 8px 8px 8px 16px;
        border-bottom: 1px solid var(--mat-sys-outline-variant);
        font-size: 14px; font-weight: 600;
        mat-icon { color: var(--app-purple, #7c3aed); font-size: 20px; width: 20px; height: 20px; }
        button { margin-left: auto; }
      }

      /* AI Agent result card */
      .ai-result-card {
        border: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
        border-radius: 8px;
        padding: 12px;
        margin: 8px 0;
      }
      .ai-result-header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
      }
      .ai-result-title {
        font-weight: 500;
      }
      .ai-result-meta {
        margin-left: auto;
        color: var(--mat-sys-on-surface-variant, #666);
        font-size: 0.875rem;
      }
      .ai-result-text {
        white-space: pre-wrap;
        max-height: 320px;
        overflow-y: auto;
        padding: 8px;
        background: var(--mat-sys-surface-container, #f5f5f5);
        border-radius: 4px;
        margin-bottom: 8px;
      }
      .ai-result-empty {
        color: var(--mat-sys-on-surface-variant, #666);
        font-style: italic;
      }
      .ai-result-fields {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-bottom: 8px;
      }
      .ai-tool-calls-panel {
        margin-bottom: 8px;
      }
      .ai-tool-call-row {
        display: flex;
        flex-direction: column;
        gap: 4px;
        padding: 6px 0;
        border-bottom: 1px solid var(--mat-sys-outline-variant, #eee);
      }
      .ai-tool-call-row:last-child {
        border-bottom: none;
      }
      .ai-tool-preview {
        color: var(--mat-sys-on-surface-variant, #666);
        font-size: 0.875rem;
      }
      .ai-tool-raw-json {
        margin-top: 8px;
        font-size: 12px;
      }
      .ai-tool-raw-json summary {
        cursor: pointer;
        color: var(--mat-sys-primary);
        font-weight: 500;
      }
      .ai-tool-raw-json pre {
        margin: 8px 0 0 0;
        padding: 8px;
        background: var(--mat-sys-surface-container);
        border-radius: 4px;
        font-size: 11px;
        overflow-x: auto;
      }
      .ai-result-error {
        display: flex;
        align-items: center;
        gap: 6px;
        color: var(--mat-sys-error, #b3261e);
        font-size: 0.875rem;

        mat-icon {
          font-size: 18px;
          width: 18px;
          height: 18px;
          flex-shrink: 0;
        }
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
  private readonly llmService = inject(LlmService);
  private readonly destroyRef = inject(DestroyRef);

  execution = signal<WorkflowExecution | null>(null);
  loading = signal(true);
  nodeResultsList = signal<NodeExecutionResult[]>([]);

  // AI Debug
  llmAvailable = signal(false);
  aiPanelOpen = signal(false);
  aiLoading = signal(false);
  aiSummary = signal<string | null>(null);
  aiError = signal<string | null>(null);
  aiThreadId = signal<string | null>(null);

  hasFailedNodes = signal(false);

  ngOnInit(): void {
    this.llmService.getStatus().subscribe({
      next: (s) => this.llmAvailable.set(s.enabled),
      error: () => this.llmAvailable.set(false),
    });
    this.workflowService.getExecution(this.data.workflowId, this.data.execution.id).subscribe({
      next: (ex) => {
        this.execution.set(ex);
        const results = Object.values(ex.node_results || {});
        this.nodeResultsList.set(results);
        this.hasFailedNodes.set(results.some((r) => r.status === 'failed'));
        this.loading.set(false);
      },
      error: () => {
        this.execution.set(this.data.execution);
        const results = Object.values(this.data.execution.node_results || {});
        this.nodeResultsList.set(results);
        this.hasFailedNodes.set(results.some((r) => r.status === 'failed'));
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

  aiOutputData(result: NodeExecutionResult): AIAgentOutputData | null {
    const data = result.output_data;
    if (!data || typeof data !== 'object') return null;
    return data as AIAgentOutputData;
  }

  outputFieldsEntries(data: AIAgentOutputData): Array<{ key: string; value: unknown }> {
    if (!data.output_fields) return [];
    if (Array.isArray(data.output_fields)) {
      return data.output_fields
        .filter(
          (f): f is { label: string; value: unknown } => !!f.label && f.value !== undefined,
        )
        .map((f) => ({ key: f.label, value: f.value }));
    }
    if (typeof data.output_fields === 'object') {
      return Object.entries(data.output_fields).map(([key, value]) => ({ key, value }));
    }
    return [];
  }

  toolName(tc: Record<string, unknown>): string | null {
    const name = tc['name'] ?? tc['tool_name'];
    return typeof name === 'string' && name.length > 0 ? name : null;
  }

  toolPreview(tc: Record<string, unknown>): string {
    const value = tc['result'] ?? tc['output'] ?? tc['response'];
    if (value === undefined || value === null) return '';
    return typeof value === 'string' ? value : JSON.stringify(value);
  }

  debugWithAI(): void {
    const ex = this.execution();
    if (!ex) return;

    this.aiPanelOpen.set(true);
    this.aiLoading.set(true);
    this.aiSummary.set(null);
    this.aiError.set(null);

    this.llmService.debugExecution(ex.id).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (res) => {
        this.aiThreadId.set(res.thread_id);
        this.aiSummary.set(res.analysis);
        this.aiLoading.set(false);
      },
      error: (err) => {
        this.aiError.set(extractErrorMessage(err));
        this.aiLoading.set(false);
      },
    });
  }
}
