import {
  Component,
  computed,
  inject,
  OnInit,
  OnDestroy,
  signal,
  TemplateRef,
  ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
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
  ActionType,
  SimulationState,
  VariableTree,
} from '../../../core/models/workflow.model';
import { ACTION_META, DEFAULT_ACTION_META } from '../../../core/models/workflow-meta';
import { GraphCanvasComponent } from './canvas/graph-canvas.component';
import { NodeConfigPanelComponent } from './config/node-config-panel.component';
import { BlockPaletteSidebarComponent } from './palette/block-palette-sidebar.component';
import { SimulationPanelComponent } from './simulation/simulation-panel.component';
import { DescriptionDialogComponent } from './description-dialog.component';
import { ExecutionsListDialogComponent } from './executions-list-dialog.component';
import { CanvasViewport } from './canvas/canvas-state';
import { Subject, takeUntil } from 'rxjs';

@Component({
  selector: 'app-workflow-editor',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
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
  private readonly destroy$ = new Subject<void>();

  @ViewChild('topbarActions', { static: true }) topbarActions!: TemplateRef<unknown>;

  // Workflow state
  workflowId = signal<string | null>(null);
  workflowName = signal('New Workflow');
  workflowDescription = signal<string | null>(null);
  workflowStatus = signal<WorkflowStatus>('draft');
  timeoutSeconds = signal(300);

  // Graph state
  graph = signal<WorkflowGraph>({ nodes: [], edges: [], viewport: null });
  selectedNodeId = signal<string | null>(null);
  selectedEdgeId = signal<string | null>(null);
  simulationState = signal<SimulationState | null>(null);
  variableTree = signal<VariableTree | null>(null);

  // UI state
  loading = signal(true);
  saving = signal(false);
  configPanelWidth = signal(320);
  isResizingPanel = signal(false);

  // Execution history
  lastExecution = signal<WorkflowExecution | null>(null);

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

  ngOnInit(): void {
    this.topbarService.setActions(this.topbarActions);

    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.workflowId.set(id);
      this.loadWorkflow(id);
    } else {
      this.createNewWorkflow();
      this.loading.set(false);
    }
  }

  ngOnDestroy(): void {
    this.topbarService.clearActions();
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
          this.workflowStatus.set(response.status);
          this.timeoutSeconds.set(response.timeout_seconds);
          this.graph.set(this.workflowService.toGraph(response));
          this.loading.set(false);
          this.loadLastExecution(id);
        },
        error: () => {
          this.loading.set(false);
          this.snackBar.open('Failed to load workflow', 'OK', { duration: 3000 });
          this.router.navigate(['/workflows']);
        },
      });
  }

  private createNewWorkflow(): void {
    const triggerNode = this.workflowService.createNode('trigger', { x: 400, y: 80 });
    this.graph.set({
      nodes: [triggerNode],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
    });
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
          timeout_seconds: this.timeoutSeconds(),
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
          timeout_seconds: this.timeoutSeconds(),
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
    const g = this.graph();
    const node = g.nodes.find((n) => n.id === event.nodeId);
    if (node) {
      node.position = { x: event.x, y: event.y };
    }
  }

  onNodeRemoved(nodeId: string): void {
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
  }

  onEdgeSelected(edgeId: string): void {
    this.selectedEdgeId.set(edgeId);
    this.selectedNodeId.set(null);
  }

  onEdgeRemoved(edgeId: string): void {
    this.graph.update((g) => ({
      ...g,
      edges: g.edges.filter((e) => e.id !== edgeId),
    }));
    if (this.selectedEdgeId() === edgeId) {
      this.selectedEdgeId.set(null);
    }
  }

  onCanvasDropped(event: { type: string; x: number; y: number }): void {
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
  }

  // ── Variable autocomplete ─────────────────────────────────────────

  private loadVariablesForNode(nodeId: string): void {
    if (!this.workflowId()) {
      this.variableTree.set(null);
      return;
    }

    this.workflowService
      .getAvailableVariables(this.workflowId()!, nodeId)
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

  // ── Palette ───────────────────────────────────────────────────────

  onPaletteBlockSelected(type: string): void {
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
      data: this.workflowDescription() || '',
    });
    ref.afterClosed().subscribe((result) => {
      if (result !== undefined) {
        this.workflowDescription.set(result);
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
}
