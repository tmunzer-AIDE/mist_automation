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
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTabsModule } from '@angular/material/tabs';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription } from 'rxjs';
import {
  WorkflowExecution,
  SamplePayload,
  SimulationState,
  SimulationWsMessage,
  NodeSnapshot,
} from '../../../../core/models/workflow.model';
import { WorkflowService } from '../../../../core/services/workflow.service';
import { WebSocketService } from '../../../../core/services/websocket.service';
import { DateTimePipe } from '../../../../shared/pipes/date-time.pipe';

@Component({
  selector: 'app-simulation-panel',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatButtonModule,
    MatIconModule,
    MatTabsModule,
    MatSlideToggleModule,
    MatProgressBarModule,
    MatTooltipModule,
    MatSnackBarModule,
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
              <div class="tab-content">
                <textarea
                  class="payload-editor"
                  [ngModel]="payloadJson()"
                  (ngModelChange)="payloadJson.set($event)"
                  placeholder='{"topic": "alarms", "events": [...]}'
                  rows="8"
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
                        <span class="sample-time">{{ sample.timestamp | dateTime:'short' }}</span>
                      </div>
                    }
                  </div>
                }
              </div>
            </mat-tab>

            <!-- Results tab -->
            <mat-tab label="Results" [disabled]="!simulationState?.execution">
              <div class="tab-content">
                @if (simulationState?.execution; as exec) {
                  <!-- Step-through controls -->
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
                        <div class="snap-section">
                          <div class="snap-section-title">Output</div>
                          <pre class="snap-json">{{ snap.output_data | json }}</pre>
                        </div>
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
            <mat-tab label="Logs" [disabled]="!simulationState?.execution">
              <div class="tab-content">
                @if (simulationState?.execution?.logs; as logs) {
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

          <!-- Run controls -->
          <div class="run-controls">
            <mat-slide-toggle
              [ngModel]="dryRun()"
              (ngModelChange)="dryRun.set($event)"
              class="dry-run-toggle"
            >
              Dry Run
            </mat-slide-toggle>
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
        max-height: 280px;
      }

      .payload-editor {
        width: 100%;
        font-family: monospace;
        font-size: 12px;
        border: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
        border-radius: 4px;
        padding: 8px;
        resize: vertical;
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
    `,
  ],
})
export class SimulationPanelComponent implements OnInit, OnDestroy {
  @Input() workflowId: string | null = null;
  @Input() simulationState: SimulationState | null = null;
  @Output() simulationStarted = new EventEmitter<SimulationState>();
  @Output() simulationStepChanged = new EventEmitter<SimulationState>();
  @Output() simulationProgress = new EventEmitter<SimulationState>();

  private readonly workflowService = inject(WorkflowService);
  private readonly wsService = inject(WebSocketService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);

  private wsSub: Subscription | null = null;
  private liveNodeStatuses: Record<string, 'pending' | 'success' | 'failed' | 'active'> = {};

  collapsed = signal(true);
  payloadJson = signal('');
  dryRun = signal(true);
  isRunning = signal(false);
  samplePayloads = signal<SamplePayload[]>([]);
  selectedSampleId = signal<string | null>(null);

  protected readonly Object = Object;

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

  runSimulation(): void {
    if (!this.workflowId || this.isRunning()) return;

    this.isRunning.set(true);
    this.liveNodeStatuses = {};
    let payload: Record<string, unknown> | undefined;

    try {
      if (this.payloadJson().trim()) {
        payload = JSON.parse(this.payloadJson());
      }
    } catch {
      this.snackBar.open('Invalid JSON payload', 'OK', { duration: 3000 });
      this.isRunning.set(false);
      return;
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
        next: () => {
          // Backend accepted; progress comes via WS
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
      const status = data['status'] as string;
      this.liveNodeStatuses[nodeId] = status === 'success' ? 'success' : 'failed';
      this.emitProgress();
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
}
