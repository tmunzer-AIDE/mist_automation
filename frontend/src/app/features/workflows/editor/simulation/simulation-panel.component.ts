import {
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  OnDestroy,
  OnInit,
  Output,
  inject,
  signal,
} from '@angular/core';
import { JsonPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatTabsModule } from '@angular/material/tabs';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription } from 'rxjs';
import {
  WorkflowExecution,
  NodeExecutionResult,
  SamplePayload,
  SimulationState,
  SimulationWsMessage,
  NodeSnapshot,
  SubflowParameter,
  WorkflowType,
} from '../../../../core/models/workflow.model';
import { WorkflowService } from '../../../../core/services/workflow.service';
import { LlmService } from '../../../../core/services/llm.service';
import { WebSocketService } from '../../../../core/services/websocket.service';
import { AiChatPanelComponent } from '../../../../shared/components/ai-chat-panel/ai-chat-panel.component';
import { AiIconComponent } from '../../../../shared/components/ai-icon/ai-icon.component';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';
import { DateTimePipe } from '../../../../shared/pipes/date-time.pipe';

@Component({
  selector: 'app-simulation-panel',
  standalone: true,
  imports: [
    JsonPipe,
    FormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatTabsModule,
    MatSlideToggleModule,
    MatProgressBarModule,
    MatTooltipModule,
    MatSnackBarModule,
    AiChatPanelComponent,
    AiIconComponent,
    DateTimePipe,
  ],
  template: `
    <div class="simulation-panel" [class.collapsed]="collapsed()">
      <div class="panel-header" (click)="collapsed.update(v => !v)">
        <mat-icon>{{ collapsed() ? 'expand_less' : 'expand_more' }}</mat-icon>
        <span class="panel-title">Simulation</span>
        @if (simulationState?.execution) {
          <span
            class="status-chip"
            [class.success]="simulationState!.execution!.status === 'success'"
            [class.failed]="simulationState!.execution!.status === 'failed'"
          >
            {{ simulationState!.execution!.status }}
          </span>
        }
      </div>

      @if (!collapsed()) {
        <div class="panel-body">
          <mat-tab-group animationDuration="0">
            <!-- Payload tab -->
            <mat-tab label="Payload">
              <div class="tab-content payload-tab">
                @if (workflowType === 'subflow' && inputParameters.length > 0) {
                  <!-- Structured form for subflow input parameters -->
                  <div class="subflow-params-form">
                    @for (param of inputParameters; track param.name) {
                      <mat-form-field appearance="outline" class="param-field">
                        <mat-label>{{ param.name }}{{ param.required ? ' *' : '' }} ({{ param.type }})</mat-label>
                        <input matInput
                          [value]="paramValues()[param.name] || ''"
                          (input)="setParamValue(param.name, $any($event.target).value)"
                          [placeholder]="param.description || param.type"
                        />
                      </mat-form-field>
                    }
                  </div>
                } @else {
                  <!-- JSON editor for standard workflows -->
                  <textarea
                    class="payload-editor"
                    [ngModel]="payloadJson()"
                    (ngModelChange)="payloadJson.set($event)"
                    placeholder='{"topic": "alarms", "events": [...]}'
                  ></textarea>

                  @if (samplePayloads().length > 0) {
                    <div class="samples-header">Recent Webhooks</div>
                    <div class="samples-list">
                      @for (sample of samplePayloads(); track sample.event_id) {
                        <div
                          class="sample-item"
                          [class.selected]="selectedSampleId() === sample.event_id"
                          (click)="selectSample(sample)"
                        >
                          <span class="sample-topic">{{ sample.webhook_type }}</span>
                          @if (sample.event_type) {
                            <span class="sample-event-type">{{ sample.event_type }}</span>
                          }
                          <span class="sample-time">{{ sample.timestamp | dateTime:'short' }}</span>
                        </div>
                      }
                    </div>
                  }
                }
              </div>
            </mat-tab>

            <!-- Results tab -->
            <mat-tab label="Results" [disabled]="!simulationState?.execution && liveNodeResults().length === 0">
              <div class="tab-content">
                @if (isRunning() && liveNodeResults().length > 0) {
                  <!-- Live results during execution -->
                  <div class="action-list">
                    @for (result of liveNodeResults(); track result.node_id) {
                      <div class="live-result-item">
                        <span class="snap-status" [class.success]="result.status === 'success'" [class.failed]="result.status === 'failed'">
                          {{ result.status }}
                        </span>
                        <span class="snap-name">{{ result.node_name }}</span>
                        @if (result.duration_ms) {
                          <span class="snap-duration">{{ result.duration_ms }}ms</span>
                        }
                        @if (getToolCallCount(result); as tcCount) {
                          <span class="tool-count-badge">
                            <mat-icon class="tool-count-icon">hub</mat-icon>{{ tcCount }} tool{{ tcCount > 1 ? 's' : '' }}
                          </span>
                        }
                        @if (result.error) {
                          <div class="snap-error">{{ result.error }}</div>
                        }
                      </div>
                    }
                  </div>
                } @else if (simulationState?.execution; as exec) {
                  <!-- Step-through controls (after completion) -->
                  <div class="step-controls">
                    <button
                      mat-icon-button
                      (click)="previousStep()"
                      [disabled]="simulationState!.currentStep <= 0"
                      matTooltip="Previous step"
                    >
                      <mat-icon>skip_previous</mat-icon>
                    </button>
                    <span class="step-label">
                      Step {{ simulationState!.currentStep + 1 }} / {{ simulationState!.totalSteps }}
                    </span>
                    <button
                      mat-icon-button
                      (click)="nextStep()"
                      [disabled]="simulationState!.currentStep >= simulationState!.totalSteps - 1"
                      matTooltip="Next step"
                    >
                      <mat-icon>skip_next</mat-icon>
                    </button>
                  </div>

                  <!-- Current step detail -->
                  @if (currentSnapshot; as snap) {
                    <div class="snapshot-detail">
                      <div class="snap-header">
                        <span class="snap-name">{{ snap.node_name || snap.node_id }}</span>
                        <span
                          class="snap-status"
                          [class.success]="snap.status === 'success'"
                          [class.failed]="snap.status === 'failed'"
                        >
                          {{ snap.status }}
                        </span>
                        @if (snap.duration_ms != null) {
                          <span class="snap-duration">{{ snap.duration_ms }}ms</span>
                        }
                      </div>

                      @if (snap.error) {
                        <div class="snap-error">{{ snap.error }}</div>
                      }

                      @if (snap.output_data) {
                        @if (getOutputToolCalls(snap.output_data); as toolCalls) {
                          @if (snap.output_data['result']) {
                            <div class="snap-section">
                              <div class="snap-section-title">Result</div>
                              <pre class="snap-json">{{ snap.output_data['result'] }}</pre>
                            </div>
                          }
                          <div class="snap-section">
                            <div class="snap-section-title">Tool Calls ({{ toolCalls.length }})</div>
                            <div class="tool-calls-list">
                              @for (tc of toolCalls; track $index) {
                                <div class="tool-call-item" (click)="toggleToolCall($index)">
                                  <mat-icon class="tool-call-icon">hub</mat-icon>
                                  <span class="tool-call-name">{{ tc['tool'] }}</span>
                                  <mat-icon class="tool-call-chevron">{{ expandedToolCalls().has($index) ? 'expand_less' : 'expand_more' }}</mat-icon>
                                </div>
                                @if (expandedToolCalls().has($index)) {
                                  <pre class="tool-call-detail">{{ formatToolCallDetail(tc) }}</pre>
                                }
                              }
                            </div>
                          </div>
                        } @else {
                          <div class="snap-section">
                            <div class="snap-section-title">Output</div>
                            <pre class="snap-json">{{ snap.output_data | json }}</pre>
                          </div>
                        }
                      }

                      @if (snap.input_variables && Object.keys(snap.input_variables).length) {
                        <div class="snap-section">
                          <div class="snap-section-title">Input Variables</div>
                          <pre class="snap-json">{{ snap.input_variables | json }}</pre>
                        </div>
                      }
                    </div>
                  }
                }
              </div>
            </mat-tab>

            <!-- Logs tab -->
            <mat-tab label="Logs" [disabled]="!simulationState?.execution && !isRunning()">
              <div class="tab-content">
                @if ((isRunning() ? liveLogs() : simulationState?.execution?.logs); as logs) {
                  <div class="log-viewer">
                    @for (line of logs; track $index) {
                      <div
                        class="log-line"
                        [class.error]="line.includes('[ERROR]')"
                        [class.warning]="line.includes('[WARNING]')"
                      >
                        {{ line }}
                      </div>
                    }
                  </div>
                }
              </div>
            </mat-tab>
          </mat-tab-group>

          @if (aiPanelOpen()) {
            <div class="ai-debug-section">
              <div class="ai-debug-header">
                <app-ai-icon [size]="18" [animated]="false"></app-ai-icon>
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

          <!-- Run controls -->
          <div class="run-controls">
            <mat-slide-toggle
              [ngModel]="dryRun()"
              (ngModelChange)="dryRun.set($event)"
              class="dry-run-toggle"
            >
              Dry Run
            </mat-slide-toggle>
            @if (hasFailedNodes() && llmAvailable()) {
              <button
                mat-stroked-button
                (click)="debugWithAI()"
                [disabled]="aiLoading()"
              >
                <app-ai-icon [size]="18" [animated]="false"></app-ai-icon> Debug
              </button>
            }
            <button
              mat-raised-button
              color="primary"
              (click)="runSimulation()"
              [disabled]="isRunning()"
            >
              @if (isRunning()) {
                <mat-icon>hourglass_top</mat-icon>
              } @else {
                <mat-icon>play_arrow</mat-icon>
              }
              {{ isRunning() ? 'Running...' : 'Simulate' }}
            </button>
            @if (isRunning()) {
              <button
                mat-stroked-button
                (click)="cancelSimulation()"
                class="cancel-button"
              >
                <mat-icon>stop</mat-icon> Stop
              </button>
            }
          </div>
        </div>

        @if (isRunning()) {
          <mat-progress-bar mode="indeterminate" />
        }
      }
    </div>
  `,
  styles: [
    `
      .simulation-panel {
        border-top: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
        background: var(--mat-sys-surface, #fff);
        display: flex;
        flex-direction: column;

        &.collapsed {
          .panel-body,
          mat-progress-bar {
            display: none;
          }
        }
      }

      .panel-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 12px;
        cursor: pointer;
        user-select: none;

        &:hover {
          background: var(--mat-sys-surface-variant, #f5f5f5);
        }
      }

      .panel-title {
        font-weight: 500;
        font-size: 13px;
        flex: 1;
      }

      .status-chip {
        font-size: 11px;
        padding: 2px 8px;
        border-radius: 10px;
        text-transform: uppercase;
        font-weight: 500;

        &.success {
          background: var(--app-success-bg);
          color: var(--app-success-text);
        }

        &.failed {
          background: var(--app-error-status-bg);
          color: var(--app-error);
        }
      }

      .panel-body {
        flex: 1;
        overflow: hidden;
        display: flex;
        flex-direction: column;
      }

      .tab-content {
        padding: 8px 12px;
        overflow-y: auto;
        height: 280px;
      }

      .payload-tab {
        display: flex;
        flex-direction: column;
      }

      .subflow-params-form {
        display: flex;
        flex-direction: column;
        gap: 4px;

        .param-field {
          width: 100%;
        }
      }

      .payload-editor {
        width: 100%;
        max-width: calc(100% - 20px);
        flex: 1;
        font-family: monospace;
        font-size: 12px;
        border: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
        border-radius: 4px;
        padding: 8px;
        resize: none;
        background: var(--mat-sys-surface, #fff);
        color: var(--mat-sys-on-surface, #212121);
      }

      .samples-header {
        font-size: 11px;
        font-weight: 500;
        text-transform: uppercase;
        color: var(--mat-sys-on-surface-variant, #666);
        margin-top: 8px;
        margin-bottom: 4px;
      }

      .samples-list {
        max-height: 120px;
        overflow-y: auto;
      }

      .sample-item {
        display: flex;
        justify-content: space-between;
        padding: 4px 8px;
        cursor: pointer;
        font-size: 12px;
        border-radius: 4px;

        &:hover {
          background: var(--mat-sys-surface-variant, #f5f5f5);
        }

        &.selected {
          background: var(--mat-sys-primary-container, #e3f2fd);
        }
      }

      .sample-topic {
        font-weight: 500;
      }

      .sample-event-type {
        font-size: 10px;
        font-family: var(--app-font-mono);
        padding: 1px 6px;
        border-radius: 4px;
        background: var(--mat-sys-surface-variant);
        color: var(--mat-sys-on-surface-variant);
      }

      .sample-time {
        color: var(--mat-sys-on-surface-variant, #999);
      }

      .step-controls {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        padding: 4px 0;
      }

      .step-label {
        font-size: 12px;
        min-width: 80px;
        text-align: center;
      }

      .snapshot-detail {
        padding: 8px 0;
      }

      .snap-header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
      }

      .snap-name {
        font-weight: 500;
        flex: 1;
      }

      .snap-status {
        font-size: 11px;
        padding: 1px 6px;
        border-radius: 4px;

        &.success {
          background: var(--app-success-bg);
          color: var(--app-success-text);
        }

        &.failed {
          background: var(--app-error-status-bg);
          color: var(--app-error);
        }
      }

      .snap-duration {
        font-size: 11px;
        color: var(--mat-sys-on-surface-variant, #999);
      }

      .snap-error {
        background: var(--app-error-status-bg);
        color: var(--app-error);
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 12px;
        margin-bottom: 8px;
      }

      .snap-section {
        margin-bottom: 8px;
      }

      .snap-section-title {
        font-size: 11px;
        font-weight: 500;
        text-transform: uppercase;
        color: var(--mat-sys-on-surface-variant, #666);
        margin-bottom: 2px;
      }

      .snap-json {
        font-size: 11px;
        background: var(--mat-sys-surface-variant, #f5f5f5);
        padding: 6px 8px;
        border-radius: 4px;
        max-height: 120px;
        overflow: auto;
        white-space: pre-wrap;
        word-break: break-all;
        margin: 0;
      }

      .log-viewer {
        font-family: monospace;
        font-size: 11px;
      }

      .log-line {
        padding: 1px 0;

        &.error {
          color: var(--app-error);
        }

        &.warning {
          color: var(--app-modified);
        }
      }

      .run-controls {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 12px;
        padding: 8px 12px;
        border-top: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
      }

      .dry-run-toggle {
        font-size: 13px;
      }
      .cancel-button {
        color: var(--app-error, #f44336);
      }
      .action-list { display: flex; flex-direction: column; gap: 6px; }
      .live-result-item {
        display: flex; align-items: center; gap: 8px;
        padding: 6px 10px; border-radius: 6px;
        border: 1px solid var(--mat-sys-outline-variant);
        font-size: 13px;
      }

      .tool-count-badge {
        display: inline-flex;
        align-items: center;
        gap: 3px;
        font-size: 11px;
        font-weight: 500;
        padding: 1px 6px;
        border-radius: 8px;
        background: var(--app-purple-bg);
        color: var(--app-purple);
      }

      .tool-count-icon {
        font-size: 11px;
        width: 11px;
        height: 11px;
      }

      .tool-calls-list {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }

      .tool-call-item {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 12px;
        cursor: pointer;
        transition: background 0.1s;

        &:hover {
          background: var(--mat-sys-surface-variant, #f0f0f0);
        }
      }

      .tool-call-icon {
        font-size: 13px;
        width: 13px;
        height: 13px;
        color: var(--app-purple);
      }

      .tool-call-name {
        font-family: var(--app-font-mono, monospace);
        font-weight: 500;
      }

      .tool-call-chevron {
        margin-left: auto;
        font-size: 16px;
        width: 16px;
        height: 16px;
        color: var(--mat-sys-on-surface-variant);
      }

      .tool-call-detail {
        font-size: 11px;
        font-family: var(--app-font-mono, monospace);
        background: var(--mat-sys-surface-variant, #f5f5f5);
        padding: 6px 8px;
        border-radius: 4px;
        max-height: 150px;
        overflow: auto;
        white-space: pre-wrap;
        word-break: break-all;
        margin: 0 0 4px 22px;
      }

      .ai-debug-section {
        border-top: 1px solid var(--mat-sys-outline-variant);
        border-bottom: 1px solid var(--mat-sys-outline-variant);
      }
      .ai-debug-header {
        display: flex; align-items: center; gap: 8px;
        padding: 6px 6px 6px 12px;
        font-size: 13px; font-weight: 600;
        mat-icon { color: var(--app-purple, #7c3aed); font-size: 18px; width: 18px; height: 18px; }
        button { margin-left: auto; }
      }
    `,
  ],
})
export class SimulationPanelComponent implements OnInit, OnDestroy {
  @Input() workflowId: string | null = null;
  @Input() workflowType: WorkflowType = 'standard';
  @Input() inputParameters: SubflowParameter[] = [];
  @Input() simulationState: SimulationState | null = null;
  @Output() simulationStarted = new EventEmitter<SimulationState>();
  @Output() simulationStepChanged = new EventEmitter<SimulationState>();
  @Output() simulationProgress = new EventEmitter<SimulationState>();

  private readonly workflowService = inject(WorkflowService);
  private readonly llmService = inject(LlmService);
  private readonly wsService = inject(WebSocketService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);

  private wsSub: Subscription | null = null;
  private liveNodeStatuses: Record<string, 'pending' | 'success' | 'failed' | 'active'> = {};

  collapsed = signal(true);
  payloadJson = signal('');
  paramValues = signal<Record<string, string>>({});
  dryRun = signal(true);
  isRunning = signal(false);
  executionId = signal<string | null>(null);
  liveLogs = signal<string[]>([]);
  liveNodeResults = signal<NodeExecutionResult[]>([]);

  // AI Debug
  llmAvailable = signal(false);
  hasFailedNodes = signal(false);
  aiPanelOpen = signal(false);
  aiLoading = signal(false);
  aiSummary = signal<string | null>(null);
  aiError = signal<string | null>(null);
  aiThreadId = signal<string | null>(null);
  samplePayloads = signal<SamplePayload[]>([]);
  selectedSampleId = signal<string | null>(null);

  protected readonly Object = Object;

  /** Track which tool call indices are expanded in the step-through view */
  expandedToolCalls = signal<Set<number>>(new Set());

  getToolCallCount(result: NodeExecutionResult): number {
    const tc = result.output_data?.['tool_calls'];
    return Array.isArray(tc) ? tc.length : 0;
  }

  getOutputToolCalls(output: Record<string, unknown>): Record<string, unknown>[] | null {
    const tc = output['tool_calls'];
    return Array.isArray(tc) && tc.length > 0 ? tc : null;
  }

  toggleToolCall(index: number): void {
    this.expandedToolCalls.update((set) => {
      const next = new Set(set);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }

  formatToolCallDetail(tc: Record<string, unknown>): string {
    const parts: string[] = [];
    if (tc['arguments']) {
      parts.push('Arguments: ' + JSON.stringify(tc['arguments'], null, 2));
    }
    if (tc['result']) {
      const result = String(tc['result']);
      parts.push('Result: ' + (result.length > 500 ? result.slice(0, 500) + '...' : result));
    }
    return parts.join('\n\n');
  }

  get currentSnapshot(): NodeSnapshot | null {
    if (!this.simulationState?.execution?.node_snapshots) return null;
    return (
      this.simulationState.execution.node_snapshots[
        this.simulationState.currentStep
      ] || null
    );
  }

  ngOnInit(): void {
    this.loadSamplePayloads();
    this.llmService.getStatus().subscribe({
      next: (s) => this.llmAvailable.set(s.enabled),
      error: () => this.llmAvailable.set(false),
    });
  }

  ngOnDestroy(): void {
    this.cleanupWs();
  }

  private cleanupWs(): void {
    if (this.wsSub) {
      this.wsSub.unsubscribe();
      this.wsSub = null;
    }
  }

  private loadSamplePayloads(): void {
    if (!this.workflowId) return;
    this.workflowService
      .getSamplePayloads(this.workflowId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => this.samplePayloads.set(res.payloads),
        error: () => {},
      });
  }

  selectSample(sample: SamplePayload): void {
    this.selectedSampleId.set(sample.event_id);
    this.payloadJson.set(JSON.stringify(sample.payload, null, 2));
  }

  setParamValue(name: string, value: string): void {
    this.paramValues.update((v) => ({ ...v, [name]: value }));
  }

  runSimulation(): void {
    if (!this.workflowId || this.isRunning()) return;

    this.isRunning.set(true);
    this.liveNodeStatuses = {};
    this.liveLogs.set([]);
    this.liveNodeResults.set([]);
    this.executionId.set(null);
    let payload: Record<string, unknown> | undefined;

    if (this.workflowType === 'subflow' && this.inputParameters.length > 0) {
      // Build payload from structured form fields
      payload = {};
      for (const param of this.inputParameters) {
        const raw = this.paramValues()[param.name] ?? param.default_value ?? '';
        payload[param.name] = param.type === 'number' ? Number(raw) || 0
          : param.type === 'boolean' ? raw === 'true'
          : raw;
      }
    } else {
      try {
        if (this.payloadJson().trim()) {
          payload = JSON.parse(this.payloadJson());
        }
      } catch {
        this.snackBar.open('Invalid JSON payload', 'OK', { duration: 3000 });
        this.isRunning.set(false);
        return;
      }
    }

    // Generate stream_id and subscribe to WS channel before HTTP call
    const streamId = crypto.randomUUID();
    const channel = `simulation:${streamId}`;

    this.cleanupWs();
    this.wsSub = this.wsService
      .subscribe<SimulationWsMessage>(channel)
      .subscribe({
        next: (msg) => this.handleWsMessage(msg),
        error: () => {},
      });

    this.workflowService
      .simulate(this.workflowId, {
        payload,
        webhook_event_id: this.selectedSampleId() || undefined,
        dry_run: this.dryRun(),
        stream_id: streamId,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.executionId.set(res.execution_id);
        },
        error: (err) => {
          this.isRunning.set(false);
          this.cleanupWs();
          this.snackBar.open(
            'Simulation failed: ' + (err?.error?.detail || err.message),
            'OK',
            { duration: 5000 }
          );
        },
      });
  }

  private handleWsMessage(msg: SimulationWsMessage): void {
    const data = msg.data || {};

    if (msg.type === 'node_started') {
      const nodeId = data['node_id'] as string;
      this.liveNodeStatuses[nodeId] = 'active';
      this.emitProgress();
    } else if (msg.type === 'node_completed') {
      const nodeId = data['node_id'] as string;
      const nodeStatus = data['status'] as string;
      this.liveNodeStatuses[nodeId] = nodeStatus === 'success' ? 'success' : 'failed';
      this.emitProgress();

      // Update live node results
      this.liveNodeResults.update((results) => [
        ...results,
        {
          node_id: nodeId,
          node_name: (data['node_name'] as string) || nodeId,
          node_type: '',
          status: nodeStatus,
          duration_ms: (data['duration_ms'] as number) || 0,
          error: (data['error'] as string) || null,
          output_data: data['output_data'] as Record<string, unknown> | null,
          retry_count: 0,
        } as NodeExecutionResult,
      ]);

      // Update live logs from the full logs array sent with each node_completed
      if (data['logs']) {
        this.liveLogs.set(data['logs'] as string[]);
      }
    } else if (msg.type === 'simulation_completed') {
      this.isRunning.set(false);
      this.cleanupWs();

      // Build final state from full execution data
      const execution = data as unknown as WorkflowExecution;
      const snapshots = execution.node_snapshots || [];
      const nodeStatuses: Record<string, 'pending' | 'success' | 'failed' | 'active'> = {};
      for (const snap of snapshots) {
        nodeStatuses[snap.node_id] = snap.status as 'success' | 'failed';
      }

      const state: SimulationState = {
        execution,
        currentStep: 0,
        totalSteps: snapshots.length,
        isRunning: false,
        nodeStatuses,
        activeEdges: new Set(),
      };

      this.hasFailedNodes.set(snapshots.some((s) => s.status === 'failed'));
      this.aiPanelOpen.set(false);
      this.simulationStarted.emit(state);
    }
  }

  private emitProgress(): void {
    const state: SimulationState = {
      execution: null,
      currentStep: 0,
      totalSteps: 0,
      isRunning: true,
      nodeStatuses: { ...this.liveNodeStatuses },
      activeEdges: new Set(),
    };
    this.simulationProgress.emit(state);
  }

  nextStep(): void {
    if (!this.simulationState) return;
    if (this.simulationState.currentStep < this.simulationState.totalSteps - 1) {
      this.emitStepChange(this.simulationState.currentStep + 1);
    }
  }

  previousStep(): void {
    if (!this.simulationState) return;
    if (this.simulationState.currentStep > 0) {
      this.emitStepChange(this.simulationState.currentStep - 1);
    }
  }

  private emitStepChange(step: number): void {
    if (!this.simulationState?.execution) return;

    const snapshots = this.simulationState.execution.node_snapshots;
    const nodeStatuses: Record<string, 'pending' | 'success' | 'failed' | 'active'> = {};

    for (let i = 0; i < snapshots.length; i++) {
      const snap = snapshots[i];
      if (i < step) {
        nodeStatuses[snap.node_id] = snap.status as 'success' | 'failed';
      } else if (i === step) {
        nodeStatuses[snap.node_id] = 'active';
      } else {
        nodeStatuses[snap.node_id] = 'pending';
      }
    }

    this.simulationStepChanged.emit({
      ...this.simulationState,
      currentStep: step,
      nodeStatuses,
    });
  }

  cancelSimulation(): void {
    const execId = this.executionId();
    if (!execId || !this.workflowId) return;
    this.workflowService
      .cancelSimulation(this.workflowId, execId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe();
  }

  debugWithAI(): void {
    const executionId = this.simulationState?.execution?.id;
    if (!executionId) return;

    this.aiPanelOpen.set(true);
    this.aiLoading.set(true);
    this.aiSummary.set(null);
    this.aiError.set(null);

    this.llmService.debugExecution(executionId).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
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
