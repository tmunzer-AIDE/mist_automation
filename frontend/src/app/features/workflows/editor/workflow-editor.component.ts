import {
  Component,
  computed,
  effect,
  inject,
  OnInit,
  OnDestroy,
  signal,
  TemplateRef,
  untracked,
  ViewChild,
} from '@angular/core';
import { NgClass } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { TopbarService } from '../../../core/services/topbar.service';
import { WorkflowService } from '../../../core/services/workflow.service';
import {
  WorkflowNode,
  WorkflowEdge,
  WorkflowGraph,
  WorkflowResponse,
  WorkflowExecution,
  WorkflowStatus,
  WorkflowType,
  SubflowParameter,
  ActionType,
  SimulationState,
  VariableTree,
  AggregationWindowSummary,
  AggregationWsMessage,
} from '../../../core/models/workflow.model';
import { ACTION_META, DEFAULT_ACTION_META } from '../../../core/models/workflow-meta';
import { GraphCanvasComponent } from './canvas/graph-canvas.component';
import { NodeConfigPanelComponent } from './config/node-config-panel.component';
import { BlockPaletteSidebarComponent } from './palette/block-palette-sidebar.component';
import { BlockPaletteDialogComponent } from './palette/block-palette-dialog.component';
import { PlaceholderWizardComponent } from './placeholder-wizard.component';
import { RecipePlaceholder } from '../../../core/services/recipe.service';
import { SimulationPanelComponent } from './simulation/simulation-panel.component';
import { DescriptionDialogComponent } from './description-dialog.component';
import { ExecutionsListDialogComponent } from './executions-list-dialog.component';
import { CanvasViewport } from './canvas/canvas-state';
import { NODE_WIDTH, NODE_HEIGHT } from './canvas/edge-utils';
import { Subject, debounceTime, takeUntil } from 'rxjs';
import { WebSocketService } from '../../../core/services/websocket.service';
import { GlobalChatService } from '../../../core/services/global-chat.service';

@Component({
  selector: 'app-workflow-editor',
  standalone: true,
  imports: [
    NgClass,
    RouterModule,
    MatButtonModule,
    MatIconModule,
    MatSnackBarModule,
    MatDialogModule,
    MatMenuModule,
    MatTooltipModule,
    MatProgressBarModule,
    GraphCanvasComponent,
    NodeConfigPanelComponent,
    BlockPaletteSidebarComponent,
    SimulationPanelComponent,
    PlaceholderWizardComponent,
  ],
  templateUrl: './workflow-editor.component.html',
  styleUrl: './workflow-editor.component.scss',
})
export class WorkflowEditorComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly workflowService = inject(WorkflowService);
  private readonly topbarService = inject(TopbarService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);
  private readonly wsService = inject(WebSocketService);
  private readonly globalChatService = inject(GlobalChatService);
  private readonly destroy$ = new Subject<void>();
  private readonly graphChanged$ = new Subject<void>();

  @ViewChild('topbarActions', { static: true }) topbarActions!: TemplateRef<unknown>;

  // Workflow state
  workflowId = signal<string | null>(null);
  workflowName = signal('New Workflow');
  workflowDescription = signal<string | null>(null);
  workflowSharing = signal<string>('private');
  workflowStatus = signal<WorkflowStatus>('draft');
  workflowType = signal<WorkflowType>('standard');
  inputParameters = signal<SubflowParameter[]>([]);
  outputParameters = signal<SubflowParameter[]>([]);
  timeoutSeconds = signal(300);

  // Graph state
  graph = signal<WorkflowGraph>({ nodes: [], edges: [], viewport: null });
  selectedNodeId = signal<string | null>(null);
  selectedEdgeId = signal<string | null>(null);
  simulationState = signal<SimulationState | null>(null);
  variableTree = signal<VariableTree | null>(null);

  // UI state
  loading = signal(true);
  graphVersion = signal(0);
  pendingPlaceholders = signal<RecipePlaceholder[]>([]);
  saving = signal(false);
  configPanelWidth = signal(500);
  isResizingPanel = signal(false);

  // Aggregation tracking
  activeWindows = signal<AggregationWindowSummary[]>([]);
  totalBufferedEvents = computed(() =>
    this.activeWindows().reduce((sum, w) => sum + w.event_count, 0)
  );

  // Execution history
  lastExecution = signal<WorkflowExecution | null>(null);

  // Undo/Redo history
  private graphHistory: WorkflowGraph[] = [];
  private historyIndex = -1;
  private readonly MAX_HISTORY = 50;
  private lastHistoryPushTime = 0;
  private configDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingConfigSnapshot: WorkflowGraph | null = null;
  canUndo = signal(false);
  canRedo = signal(false);

  selectedNode = computed(() => {
    const id = this.selectedNodeId();
    if (!id) return null;
    return this.graph().nodes.find((n) => n.id === id) || null;
  });

  statusChipClass = computed(() => {
    switch (this.workflowStatus()) {
      case 'enabled': return 'status-enabled';
      case 'disabled': return 'status-disabled';
      default: return 'status-draft';
    }
  });

  // Update chat context when workflow ID, name, or selected node changes.
  // Graph changes are handled separately via the debounced graphChanged$ subscriber.
  private readonly _chatContextEffect = effect(() => {
    this.workflowId();
    this.workflowName();
    this.selectedNode();
    untracked(() => this._updateChatContext());
  });

  private _updateChatContext(): void {
    const id = this.workflowId();
    const g = this.graph();
    if (!id || g.nodes.length === 0) return;

    const selected = this.selectedNode();
    const triggerNode = g.nodes.find((n) => n.type === 'trigger');
    const details: Record<string, string | number | null> = {
      workflow_id: id,
      workflow_name: this.workflowName(),
      workflow_type: this.workflowType(),
      workflow_status: this.workflowStatus(),
      node_count: g.nodes.length,
      trigger_type: (triggerNode?.config['trigger_type'] as string) || null,
      trigger_topic: (triggerNode?.config['webhook_topic'] as string) || null,
      graph_summary: this._buildGraphSummary(g),
    };

    if (selected) {
      details['selected_node'] = `${selected.name} (${selected.type})`;
      details['selected_node_id'] = selected.id;
      const configKeys = Object.keys(selected.config).filter((k) => selected.config[k] != null);
      if (configKeys.length > 0) {
        details['selected_node_config'] = configKeys
          .map((k) => {
            const v = selected.config[k];
            const s = typeof v === 'string' ? v : JSON.stringify(v);
            return `${k}: ${s.length > 80 ? s.slice(0, 80) + '...' : s}`;
          })
          .join(', ');
      }
    }

    this.globalChatService.setContext({ page: 'Workflow Editor', details });
  }

  private _buildGraphSummary(g: WorkflowGraph): string {
    const lines: string[] = [];
    for (const node of g.nodes) {
      const meta = ACTION_META[node.type as ActionType] || DEFAULT_ACTION_META;
      let info = `${node.name} [${meta.label}]`;
      if (node.type === 'trigger') {
        const topic = node.config['webhook_topic'] || node.config['trigger_type'] || '';
        if (topic) info += ` (${topic})`;
      }
      const targets = g.edges
        .filter((e) => e.source_node_id === node.id)
        .map((e) => {
          const target = g.nodes.find((n) => n.id === e.target_node_id);
          const port = e.source_port_id !== 'default' ? `[${e.source_port_id}]` : '';
          return port + (target?.name || '?');
        });
      if (targets.length > 0) info += ` → ${targets.join(', ')}`;
      lines.push(info);
      if (lines.join('\n').length > 1200) {
        lines.push(`... and ${g.nodes.length - lines.length} more nodes`);
        break;
      }
    }
    return lines.join('\n');
  }

  ngOnInit(): void {
    this.topbarService.setActions(this.topbarActions);

    this.graphChanged$
      .pipe(debounceTime(500), takeUntil(this.destroy$))
      .subscribe(() => {
        const nodeId = this.selectedNodeId();
        if (nodeId) this.refreshVariables(nodeId);
        this.graphVersion.update((v) => v + 1);
        this._updateChatContext();
      });

    // Check for placeholders from recipe instantiation
    const placeholdersParam = this.route.snapshot.queryParamMap.get('placeholders');
    if (placeholdersParam) {
      try {
        const parsed = JSON.parse(placeholdersParam);
        if (Array.isArray(parsed)) {
          const validated = parsed.filter(
            (p: Record<string, unknown>) =>
              typeof p['node_id'] === 'string' &&
              typeof p['field_path'] === 'string' &&
              typeof p['label'] === 'string' &&
              /^[a-zA-Z_][a-zA-Z0-9_.]*$/.test(p['field_path'] as string)
          );
          this.pendingPlaceholders.set(validated);
        }
      } catch { /* ignore invalid JSON */ }
    }

    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.workflowId.set(id);
      this.loadWorkflow(id);
    } else {
      this.createNewWorkflow();
      this.initHistory();
      this.loading.set(false);
    }
  }

  ngOnDestroy(): void {
    this.topbarService.clearActions();
    if (this.configDebounceTimer) clearTimeout(this.configDebounceTimer);
    this.destroy$.next();
    this.destroy$.complete();
  }

  // ── Load / Create ─────────────────────────────────────────────────

  private loadWorkflow(id: string): void {
    this.workflowService
      .get(id)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (response) => {
          this.workflowName.set(response.name);
          this.workflowDescription.set(response.description);
          this.workflowSharing.set(response.sharing || 'private');
          this.workflowStatus.set(response.status);
          this.workflowType.set(response.workflow_type || 'standard');
          this.inputParameters.set(response.input_parameters || []);
          this.outputParameters.set(response.output_parameters || []);
          this.timeoutSeconds.set(response.timeout_seconds);
          this.graph.set(this.workflowService.toGraph(response));
          this.initHistory();
          this.loading.set(false);
          this.loadLastExecution(id);
          this.startAggregationTracking(id);
        },
        error: () => {
          this.loading.set(false);
          this.snackBar.open('Failed to load workflow', 'OK', { duration: 3000 });
          this.router.navigate(['/workflows']);
        },
      });
  }

  private createNewWorkflow(): void {
    const type = (this.route.snapshot.queryParamMap.get('type') as WorkflowType) || 'standard';
    this.workflowType.set(type);

    if (type === 'subflow') {
      this.workflowName.set('New Sub-Flow');
      const inputNode = this.workflowService.createNode('subflow_input', { x: 400, y: 80 });
      const outputNode = this.workflowService.createNode('subflow_output', { x: 400, y: 320 });
      this.graph.set({
        nodes: [inputNode, outputNode],
        edges: [],
        viewport: { x: 0, y: 0, zoom: 1 },
      });
    } else {
      const triggerNode = this.workflowService.createNode('trigger', { x: 400, y: 80 });
      this.graph.set({
        nodes: [triggerNode],
        edges: [],
        viewport: { x: 0, y: 0, zoom: 1 },
      });
    }
  }

  private loadLastExecution(id: string): void {
    this.workflowService
      .getExecutions(id, 0, 1)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (res) => {
          this.lastExecution.set(res.executions[0] || null);
        },
      });
  }

  // ── Save ──────────────────────────────────────────────────────────

  save(): void {
    this.saving.set(true);
    const graphData = this.workflowService.fromGraph(this.graph());

    if (this.workflowId()) {
      this.workflowService
        .update(this.workflowId()!, {
          name: this.workflowName(),
          description: this.workflowDescription() || undefined,
          sharing: this.workflowSharing(),
          timeout_seconds: this.timeoutSeconds(),
          input_parameters: this.inputParameters(),
          output_parameters: this.outputParameters(),
          ...graphData,
        })
        .pipe(takeUntil(this.destroy$))
        .subscribe({
          next: () => {
            this.saving.set(false);
            this.snackBar.open('Workflow saved', '', { duration: 2000 });
          },
          error: (err) => {
            this.saving.set(false);
            this.snackBar.open(
              'Save failed: ' + (err?.error?.detail || 'Unknown error'),
              'OK',
              { duration: 5000 }
            );
          },
        });
    } else {
      this.workflowService
        .create({
          name: this.workflowName(),
          description: this.workflowDescription() || undefined,
          sharing: this.workflowSharing(),
          workflow_type: this.workflowType(),
          timeout_seconds: this.timeoutSeconds(),
          input_parameters: this.inputParameters(),
          output_parameters: this.outputParameters(),
          ...graphData,
        })
        .pipe(takeUntil(this.destroy$))
        .subscribe({
          next: (response) => {
            this.saving.set(false);
            this.workflowId.set(response.id);
            this.workflowStatus.set(response.status);
            this.snackBar.open('Workflow created', '', { duration: 2000 });
            this.router.navigate(['/workflows', response.id], { replaceUrl: true });
          },
          error: (err) => {
            this.saving.set(false);
            this.snackBar.open(
              'Create failed: ' + (err?.error?.detail || 'Unknown error'),
              'OK',
              { duration: 5000 }
            );
          },
        });
    }
  }

  // ── Graph event handlers ──────────────────────────────────────────

  onNodeSelected(nodeId: string): void {
    this.selectedNodeId.set(nodeId);
    this.selectedEdgeId.set(null);
    this.loadVariablesForNode(nodeId);
  }

  onNodeDeselected(): void {
    this.selectedNodeId.set(null);
    this.selectedEdgeId.set(null);
    this.variableTree.set(null);
  }

  onNodeMoved(event: { nodeId: string; x: number; y: number }): void {
    const current = this.graph().nodes.find((n) => n.id === event.nodeId);
    if (current && current.position.x === event.x && current.position.y === event.y) return;

    this.pushHistory();
    this.graph.update((g) => {
      const nodes = g.nodes.map((n) =>
        n.id === event.nodeId ? { ...n, position: { x: event.x, y: event.y } } : n
      );
      return { ...g, nodes };
    });
  }

  onNodeRemoved(nodeId: string): void {
    this.pushHistory();
    this.graph.update((g) => ({
      ...g,
      nodes: g.nodes.filter((n) => n.id !== nodeId),
      edges: g.edges.filter(
        (e) => e.source_node_id !== nodeId && e.target_node_id !== nodeId
      ),
    }));
    if (this.selectedNodeId() === nodeId) {
      this.selectedNodeId.set(null);
      this.variableTree.set(null);
    }
    this.graphChanged$.next();
  }

  onEdgeCreated(event: {
    sourceNodeId: string;
    sourcePortId: string;
    targetNodeId: string;
  }): void {
    const g = this.graph();
    // Prevent duplicate edges
    const exists = g.edges.some(
      (e) =>
        e.source_node_id === event.sourceNodeId &&
        e.source_port_id === event.sourcePortId &&
        e.target_node_id === event.targetNodeId
    );
    if (exists) return;

    this.pushHistory();
    const edge = this.workflowService.createEdge(
      event.sourceNodeId,
      event.sourcePortId,
      event.targetNodeId
    );

    // Set label for condition branch edges
    const sourceNode = g.nodes.find((n) => n.id === event.sourceNodeId);
    if (sourceNode?.type === 'condition') {
      const port = sourceNode.output_ports.find((p) => p.id === event.sourcePortId);
      if (port) edge.label = port.label;
    }

    this.graph.update((g) => ({ ...g, edges: [...g.edges, edge] }));
    this.graphChanged$.next();
  }

  onEdgeSelected(edgeId: string): void {
    this.selectedEdgeId.set(edgeId);
    this.selectedNodeId.set(null);
  }

  onEdgeRemoved(edgeId: string): void {
    this.pushHistory();
    this.graph.update((g) => ({
      ...g,
      edges: g.edges.filter((e) => e.id !== edgeId),
    }));
    if (this.selectedEdgeId() === edgeId) {
      this.selectedEdgeId.set(null);
    }
    this.graphChanged$.next();
  }

  onCanvasDropped(event: { type: string; x: number; y: number }): void {
    this.pushHistory();
    const node = this.workflowService.createNode(event.type, {
      x: event.x,
      y: event.y,
    });
    node.name = this.getUniqueNodeName(node.name);
    this.graph.update((g) => ({ ...g, nodes: [...g.nodes, node] }));
    this.selectedNodeId.set(node.id);
    this.loadVariablesForNode(node.id);
  }

  onViewportChanged(viewport: CanvasViewport): void {
    this.graph.update((g) => ({ ...g, viewport }));
  }

  // ── Config panel ──────────────────────────────────────────────────

  onNodeConfigChanged(updatedNode: WorkflowNode): void {
    this.pushHistoryDebounced();
    // Update output ports for condition nodes when branches change
    if (updatedNode.type === 'condition') {
      const branches = (updatedNode.config['branches'] as { condition: string }[]) || [];
      updatedNode.output_ports = [
        ...branches.map((_, i) => ({
          id: `branch_${i}`,
          label: i === 0 ? 'If' : `Else If ${i}`,
          type: 'branch',
        })),
        { id: 'else', label: 'Else', type: 'branch' },
      ];
    }

    this.graph.update((g) => {
      const nodes = [...g.nodes];
      const index = nodes.findIndex((n) => n.id === updatedNode.id);
      if (index >= 0) {
        nodes[index] = updatedNode;
      }
      return { ...g, nodes };
    });
    this.graphChanged$.next();
  }

  // ── Variable autocomplete ─────────────────────────────────────────

  private loadVariablesForNode(nodeId: string): void {
    this.refreshVariables(nodeId);
  }

  private refreshVariables(nodeId: string): void {
    const g = this.graph();
    this.workflowService
      .computeAvailableVariables(nodeId, g.nodes, g.edges, this.inputParameters())
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (tree) => this.variableTree.set(tree),
        error: () => this.variableTree.set(null),
      });
  }

  // ── Simulation ────────────────────────────────────────────────────

  onSimulationStarted(state: SimulationState): void {
    this.simulationState.set(state);
  }

  onSimulationStepChanged(state: SimulationState): void {
    this.simulationState.set({ ...state });
  }

  onSimulationProgress(state: SimulationState): void {
    this.simulationState.set({ ...state });
  }

  // ── Palette ───────────────────────────────────────────────────────

  onPaletteBlockSelected(type: string): void {
    this.pushHistory();
    // Find good position — below the last node
    let maxY = 80;
    for (const node of this.graph().nodes) {
      maxY = Math.max(maxY, node.position.y);
    }

    const node = this.workflowService.createNode(type, { x: 400, y: maxY + 160 });
    node.name = this.getUniqueNodeName(node.name);
    this.graph.update((g) => ({ ...g, nodes: [...g.nodes, node] }));
    this.selectedNodeId.set(node.id);
    this.loadVariablesForNode(node.id);
  }

  private getUniqueNodeName(baseName: string): string {
    const existingNames = new Set(this.graph().nodes.map((n) => n.name));
    if (!existingNames.has(baseName)) return baseName;
    let i = 2;
    while (existingNames.has(`${baseName} ${i}`)) i++;
    return `${baseName} ${i}`;
  }

  // ── Resize ────────────────────────────────────────────────────────

  onResizeStart(event: MouseEvent): void {
    event.preventDefault();
    this.isResizingPanel.set(true);

    const startX = event.clientX;
    const startWidth = this.configPanelWidth();

    const onMove = (e: MouseEvent) => {
      const delta = startX - e.clientX;
      this.configPanelWidth.set(Math.max(280, Math.min(800, startWidth + delta)));
    };

    const onUp = () => {
      this.isResizingPanel.set(false);
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }

  // ── Topbar actions ────────────────────────────────────────────────

  openDescription(): void {
    const ref = this.dialog.open(DescriptionDialogComponent, {
      width: '500px',
      data: { description: this.workflowDescription() || '', sharing: this.workflowSharing() },
    });
    ref.afterClosed().subscribe((result) => {
      if (result !== undefined) {
        this.workflowDescription.set(result.description);
        this.workflowSharing.set(result.sharing);
      }
    });
  }

  toggleStatus(): void {
    if (!this.workflowId()) return;
    const newStatus: WorkflowStatus =
      this.workflowStatus() === 'enabled' ? 'disabled' : 'enabled';
    this.workflowService
      .update(this.workflowId()!, { status: newStatus })
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: () => {
          this.workflowStatus.set(newStatus);
          this.snackBar.open(
            `Workflow ${newStatus}`,
            '',
            { duration: 2000 }
          );
        },
      });
  }

  runWorkflow(): void {
    if (!this.workflowId()) return;
    this.workflowService
      .execute(this.workflowId()!)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: () => this.snackBar.open('Execution started', '', { duration: 2000 }),
        error: (err) =>
          this.snackBar.open(
            err?.error?.detail || 'Failed to start',
            'OK',
            { duration: 3000 }
          ),
      });
  }

  openExecutions(): void {
    if (!this.workflowId()) return;
    this.dialog.open(ExecutionsListDialogComponent, {
      width: '800px',
      maxHeight: '80vh',
      data: this.workflowId(),
    });
  }

  onInputParametersChanged(params: SubflowParameter[]): void {
    this.inputParameters.set(params);
  }

  onOutputParametersChanged(params: SubflowParameter[]): void {
    this.outputParameters.set(params);
  }

  exportWorkflow(): void {
    this.workflowService.exportWorkflow({
      ...this.graph(),
      name: this.workflowName(),
      description: this.workflowDescription(),
      timeout_seconds: this.timeoutSeconds(),
    } as any);
  }

  cancel(): void {
    this.router.navigate(['/workflows']);
  }

  // ── Placeholder wizard ──────────────────────────────────────────────

  onPlaceholderFilled(event: { nodeId: string; fieldPath: string; value: string }): void {
    // Validate node exists in graph
    if (!this.graph().nodes.some((n) => n.id === event.nodeId)) return;

    this.graph.update((g) => {
      const nodes = g.nodes.map((n) => {
        if (n.id === event.nodeId) {
          const config = JSON.parse(JSON.stringify(n.config));
          // Support dot-path notation (e.g., "variables.0.expression")
          const parts = event.fieldPath.split('.');
          let target: any = config;
          for (let i = 0; i < parts.length - 1; i++) {
            const key = /^\d+$/.test(parts[i]) ? parseInt(parts[i], 10) : parts[i];
            target = target[key];
            if (target === undefined || target === null) break;
          }
          if (target) {
            const lastKey = /^\d+$/.test(parts[parts.length - 1]) ? parseInt(parts[parts.length - 1], 10) : parts[parts.length - 1];
            target[lastKey] = event.value;
          }
          return { ...n, config };
        }
        return n;
      });
      return { ...g, nodes };
    });
  }

  onPlaceholderWizardCompleted(): void {
    this.pushHistory();
    this.pendingPlaceholders.set([]);
  }

  // ── Aggregation tracking ─────────────────────────────────────────────

  private startAggregationTracking(id: string): void {
    this.workflowService.getActiveWindows(id)
      .pipe(takeUntil(this.destroy$))
      .subscribe({ next: (r) => this.activeWindows.set(r.windows), error: () => {} });

    this.wsService.subscribe<AggregationWsMessage>(`workflow:${id}:aggregation`)
      .pipe(takeUntil(this.destroy$))
      .subscribe((msg) => {
        const d = msg.data;
        if (msg.type === 'aggregation_updated') {
          if (d.status === 'collecting') {
            this.activeWindows.update((windows) => {
              const idx = windows.findIndex((w) => w.window_id === d.window_id);
              const summary: AggregationWindowSummary = {
                window_id: d.window_id,
                group_key: d.group_key,
                event_count: d.event_count,
                site_id: d.site_id,
                site_name: d.site_name,
                window_end: d.window_end,
                window_seconds: d.window_seconds,
              };
              return idx >= 0
                ? windows.map((w, i) => (i === idx ? summary : w))
                : [...windows, summary];
            });
          } else {
            this.activeWindows.update((windows) =>
              windows.filter((w) => w.window_id !== d.window_id)
            );
          }
        } else if (msg.type === 'aggregation_fired') {
          this.activeWindows.update((windows) =>
            windows.filter((w) => w.window_id !== d.window_id)
          );
        }
      });
  }

  // ── Undo / Redo ─────────────────────────────────────────────────────

  private cloneGraph(g: WorkflowGraph): WorkflowGraph {
    return {
      nodes: g.nodes.map((n) => ({ ...n, position: { ...n.position }, config: { ...n.config }, output_ports: [...n.output_ports], save_as: n.save_as ? [...n.save_as] : undefined })),
      edges: g.edges.map((e) => ({ ...e })),
      viewport: null,
    };
  }

  /** Push a snapshot of the current graph onto the history stack. */
  private pushHistory(): void {
    // Flush any pending debounced config snapshot first
    if (this.pendingConfigSnapshot) {
      if (this.configDebounceTimer) {
        clearTimeout(this.configDebounceTimer);
        this.configDebounceTimer = null;
      }
      this.graphHistory = this.graphHistory.slice(0, this.historyIndex + 1);
      this.graphHistory.push(this.pendingConfigSnapshot);
      if (this.graphHistory.length > this.MAX_HISTORY) this.graphHistory.shift();
      this.historyIndex = this.graphHistory.length - 1;
      this.pendingConfigSnapshot = null;
    }

    const snapshot = this.cloneGraph(this.graph());

    // Truncate any redo states
    this.graphHistory = this.graphHistory.slice(0, this.historyIndex + 1);
    this.graphHistory.push(snapshot);

    // Cap history size
    if (this.graphHistory.length > this.MAX_HISTORY) {
      this.graphHistory.shift();
    }
    this.historyIndex = this.graphHistory.length - 1;
    this.lastHistoryPushTime = Date.now();
    this.updateUndoRedoState();
  }

  /** Push history for config changes with debouncing (batch rapid changes). */
  private pushHistoryDebounced(): void {
    if (!this.pendingConfigSnapshot) {
      // Capture the state *before* the first change in this batch
      this.pendingConfigSnapshot = this.cloneGraph(this.graph());
    }
    if (this.configDebounceTimer) clearTimeout(this.configDebounceTimer);
    this.configDebounceTimer = setTimeout(() => {
      if (this.pendingConfigSnapshot) {
        // Push the pre-change snapshot
        this.graphHistory = this.graphHistory.slice(0, this.historyIndex + 1);
        this.graphHistory.push(this.pendingConfigSnapshot);
        if (this.graphHistory.length > this.MAX_HISTORY) {
          this.graphHistory.shift();
        }
        this.historyIndex = this.graphHistory.length - 1;
        this.updateUndoRedoState();
        this.pendingConfigSnapshot = null;
      }
    }, 500);
  }

  private updateUndoRedoState(): void {
    this.canUndo.set(this.historyIndex > 0);
    this.canRedo.set(this.historyIndex < this.graphHistory.length - 1);
  }

  undo(): void {
    if (this.historyIndex <= 0 && !this.pendingConfigSnapshot) return;
    // If there's a pending debounced config snapshot, flush it first
    if (this.pendingConfigSnapshot) {
      if (this.configDebounceTimer) clearTimeout(this.configDebounceTimer);
      this.graphHistory = this.graphHistory.slice(0, this.historyIndex + 1);
      this.graphHistory.push(this.pendingConfigSnapshot);
      if (this.graphHistory.length > this.MAX_HISTORY) this.graphHistory.shift();
      this.historyIndex = this.graphHistory.length - 1;
      this.pendingConfigSnapshot = null;
    }

    this.historyIndex--;
    this.graph.set(this.cloneGraph(this.graphHistory[this.historyIndex]));
    this.updateUndoRedoState();
    this.selectedNodeId.set(null);
    this.selectedEdgeId.set(null);
    this.variableTree.set(null);
  }

  redo(): void {
    if (this.historyIndex >= this.graphHistory.length - 1) return;
    this.historyIndex++;
    this.graph.set(this.cloneGraph(this.graphHistory[this.historyIndex]));
    this.updateUndoRedoState();
    this.selectedNodeId.set(null);
    this.selectedEdgeId.set(null);
    this.variableTree.set(null);
  }

  /** Initialize history with the current graph state (called after load/create). */
  private initHistory(): void {
    this.graphHistory = [this.cloneGraph(this.graph())];
    this.historyIndex = 0;
    this.updateUndoRedoState();
  }

  // ── Insert node on edge ─────────────────────────────────────────────

  onInsertNodeOnEdge(event: { edgeId: string; actionType: string; position: { x: number; y: number } }): void {
    const ref = this.dialog.open(BlockPaletteDialogComponent, {
      width: '400px',
      data: { actionsOnly: true },
    });
    ref.afterClosed().pipe(takeUntil(this.destroy$)).subscribe((option: { actionType?: string } | undefined) => {
      if (!option?.actionType) return;

      this.pushHistory();

      const edge = this.graph().edges.find((e) => e.id === event.edgeId);
      if (!edge) return;

      const node = this.workflowService.createNode(option.actionType, {
        x: event.position.x,
        y: event.position.y,
      });
      node.name = this.getUniqueNodeName(node.name);

      // Remove old edge, add node, create two new edges
      const edge1 = this.workflowService.createEdge(
        edge.source_node_id,
        edge.source_port_id,
        node.id
      );
      const edge2 = this.workflowService.createEdge(
        node.id,
        'default',
        edge.target_node_id
      );

      this.graph.update((g) => ({
        ...g,
        nodes: [...g.nodes, node],
        edges: [...g.edges.filter((e) => e.id !== event.edgeId), edge1, edge2],
      }));

      this.selectedNodeId.set(node.id);
      this.loadVariablesForNode(node.id);
      this.graphChanged$.next();
    });
  }

  // ── Paste nodes ─────────────────────────────────────────────────────

  onNodesPasted(event: { nodes: WorkflowNode[]; edges: WorkflowEdge[] }): void {
    this.pushHistory();

    // Assign unique names
    for (const n of event.nodes) {
      n.name = this.getUniqueNodeName(n.name);
    }

    this.graph.update((g) => ({
      ...g,
      nodes: [...g.nodes, ...event.nodes],
      edges: [...g.edges, ...event.edges],
    }));

    this.graphChanged$.next();
  }
}
