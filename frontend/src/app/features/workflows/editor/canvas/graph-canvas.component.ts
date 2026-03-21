import {
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  OnInit,
  Output,
  SimpleChanges,
  ViewChild,
  inject,
} from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatButtonModule } from '@angular/material/button';
import {
  WorkflowNode,
  WorkflowEdge,
  SimulationState,
} from '../../../../core/models/workflow.model';
import { ACTION_META, DEFAULT_ACTION_META } from '../../../../core/models/workflow-meta';
import { isNodeConfigValid } from '../utils/node-validation';
import {
  buildEdgePath,
  getInputPortPosition,
  getOutputPortPosition,
  NODE_HEIGHT,
  NODE_WIDTH,
  PORT_RADIUS,
} from './edge-utils';
import {
  CanvasViewport,
  DragState,
  GRID_SIZE,
  MAX_ZOOM,
  MIN_ZOOM,
  ZOOM_STEP,
  initialDragState,
  screenToCanvas,
  snapToGrid,
} from './canvas-state';

const DRAG_THRESHOLD = 4; // pixels before rubber-band starts

@Component({
  selector: 'app-graph-canvas',
  standalone: true,
  imports: [MatIconModule, MatTooltipModule, MatButtonModule],
  templateUrl: './graph-canvas.component.html',
  styleUrl: './graph-canvas.component.scss',
})
export class GraphCanvasComponent implements OnInit, OnChanges, OnDestroy {
  @Input() nodes: WorkflowNode[] = [];
  @Input() edges: WorkflowEdge[] = [];
  @Input() selectedNodeId: string | null = null;
  @Input() selectedEdgeId: string | null = null;
  @Input() simulationState: SimulationState | null = null;

  @Output() nodeSelected = new EventEmitter<string>();
  @Output() nodeDeselected = new EventEmitter<void>();
  @Output() nodeMoved = new EventEmitter<{ nodeId: string; x: number; y: number }>();
  @Output() nodeRemoved = new EventEmitter<string>();
  @Output() edgeCreated = new EventEmitter<{
    sourceNodeId: string;
    sourcePortId: string;
    targetNodeId: string;
  }>();
  @Output() edgeSelected = new EventEmitter<string>();
  @Output() edgeRemoved = new EventEmitter<string>();
  @Output() canvasDropped = new EventEmitter<{ type: string; x: number; y: number }>();
  @Output() viewportChanged = new EventEmitter<CanvasViewport>();

  @ViewChild('svgCanvas', { static: true }) svgCanvas!: ElementRef<SVGSVGElement>;

  viewport: CanvasViewport = { x: 0, y: 0, zoom: 1 };
  drag: DragState = initialDragState();
  nodeMap: Map<string, WorkflowNode> = new Map();

  // Pre-computed per-node render data (rebuilt in ngOnChanges)
  nodeRenderData = new Map<
    string,
    { color: string; icon: string; label: string; simStatus: string | null; simColor: string; hasErrors: boolean }
  >();

  // Computed edge paths
  edgePaths: {
    edge: WorkflowEdge;
    path: string;
    midX: number;
    midY: number;
  }[] = [];

  // Pending edge (being dragged from a port)
  pendingEdgePath: string | null = null;

  // Multi-selection
  multiSelectedIds = new Set<string>();
  selectionRect: { x: number; y: number; w: number; h: number } | null = null;
  private multiDragStartPositions = new Map<string, { x: number; y: number }>();

  // Immutable drag offsets (applied during drag without mutating node.position)
  dragOffsets = new Map<string, { dx: number; dy: number }>();

  readonly NODE_WIDTH = NODE_WIDTH;
  readonly NODE_HEIGHT = NODE_HEIGHT;
  readonly PORT_RADIUS = PORT_RADIUS;
  readonly GRID_SIZE = GRID_SIZE;

  private el = inject(ElementRef);

  ngOnInit(): void {
    this.rebuildNodeMap();
    this.recalcEdgePaths();
    this.rebuildRenderData();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['nodes'] || changes['edges']) {
      this.rebuildNodeMap();
      this.recalcEdgePaths();
    }
    if (changes['nodes'] || changes['simulationState']) {
      this.rebuildRenderData();
    }
  }

  ngOnDestroy(): void {
    // cleanup
  }

  // ── Node rendering helpers ────────────────────────────────────────────

  private getNodeMeta(type: string) {
    return ACTION_META[type as keyof typeof ACTION_META] || DEFAULT_ACTION_META;
  }

  private getNodeLabel(node: WorkflowNode): string {
    if (node.name) return node.name;
    if (node.type === 'trigger') return 'Trigger';
    if (node.type === 'subflow_input') return 'Sub-Flow Input';
    if (node.type === 'subflow_output') return 'Return Output';
    return this.getNodeMeta(node.type).label;
  }

  private getNodeIcon(node: WorkflowNode): string {
    if (node.type === 'trigger') {
      const tt = node.config?.['trigger_type'];
      if (tt === 'cron') return 'schedule';
      if (tt === 'manual') return 'play_circle';
      if (tt === 'aggregated_webhook') return 'layers';
      return 'webhook';
    }
    if (node.type === 'subflow_input') return 'input';
    if (node.type === 'subflow_output') return 'output';
    return this.getNodeMeta(node.type).icon;
  }

  private getNodeColor(node: WorkflowNode): string {
    if (node.type === 'trigger') return 'var(--app-trigger)';
    if (node.type === 'subflow_input') return '#00695c';
    if (node.type === 'subflow_output') return '#00695c';
    return this.getNodeMeta(node.type).color;
  }

  private rebuildRenderData(): void {
    this.nodeRenderData.clear();
    for (const node of this.nodes) {
      const simStatus = this.simulationState?.nodeStatuses?.[node.id] ?? null;
      this.nodeRenderData.set(node.id, {
        color: this.getNodeColor(node),
        icon: this.getNodeIcon(node),
        label: this.getNodeLabel(node),
        simStatus,
        simColor: this.getSimColor(simStatus),
        hasErrors: !isNodeConfigValid(node),
      });
    }
  }

  isEdgeActive(edgeId: string): boolean {
    return this.simulationState?.activeEdges?.has(edgeId) ?? false;
  }

  isNodeHighlighted(nodeId: string): boolean {
    return nodeId === this.selectedNodeId || this.multiSelectedIds.has(nodeId);
  }

  // ── Edge path computation ─────────────────────────────────────────────

  private rebuildNodeMap(): void {
    this.nodeMap.clear();
    for (const node of this.nodes) {
      this.nodeMap.set(node.id, node);
    }
  }

  recalcEdgePaths(): void {
    this.edgePaths = [];
    for (const edge of this.edges) {
      const sourceNode = this.nodeMap.get(edge.source_node_id);
      const targetNode = this.nodeMap.get(edge.target_node_id);
      if (!sourceNode || !targetNode) continue;

      const sourcePos = this.getEffectivePosition(sourceNode);
      const targetPos = this.getEffectivePosition(targetNode);

      const portIndex = sourceNode.output_ports.findIndex(
        (p) => p.id === edge.source_port_id
      );
      const from = getOutputPortPosition(
        sourcePos.x,
        sourcePos.y,
        Math.max(0, portIndex),
        sourceNode.output_ports.length || 1
      );
      const to = getInputPortPosition(targetPos.x, targetPos.y);

      this.edgePaths.push({
        edge,
        path: buildEdgePath(from, to),
        midX: (from.x + to.x) / 2,
        midY: (from.y + to.y) / 2,
      });
    }
  }

  // ── Viewport controls ─────────────────────────────────────────────────

  onWheel(event: WheelEvent): void {
    event.preventDefault();

    if (event.ctrlKey || event.metaKey) {
      // Zoom (pinch-to-zoom OR Ctrl+scroll wheel)
      const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
      const mouseX = event.clientX - rect.left;
      const mouseY = event.clientY - rect.top;

      const oldZoom = this.viewport.zoom;
      const zoomFactor = 1 - event.deltaY * 0.01;
      const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, oldZoom * zoomFactor));

      // Zoom toward cursor
      this.viewport.x = mouseX - ((mouseX - this.viewport.x) / oldZoom) * newZoom;
      this.viewport.y = mouseY - ((mouseY - this.viewport.y) / oldZoom) * newZoom;
      this.viewport.zoom = newZoom;
    } else {
      // Pan (two-finger scroll OR mouse wheel without Ctrl)
      this.viewport.x -= event.deltaX;
      this.viewport.y -= event.deltaY;
    }

    this.viewportChanged.emit({ ...this.viewport });
  }

  zoomIn(): void {
    this.viewport.zoom = Math.min(MAX_ZOOM, this.viewport.zoom + ZOOM_STEP);
    this.viewportChanged.emit({ ...this.viewport });
  }

  zoomOut(): void {
    this.viewport.zoom = Math.max(MIN_ZOOM, this.viewport.zoom - ZOOM_STEP);
    this.viewportChanged.emit({ ...this.viewport });
  }

  fitToView(): void {
    if (!this.nodes.length) return;

    const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity;

    for (const n of this.nodes) {
      minX = Math.min(minX, n.position.x);
      minY = Math.min(minY, n.position.y);
      maxX = Math.max(maxX, n.position.x + NODE_WIDTH);
      maxY = Math.max(maxY, n.position.y + NODE_HEIGHT);
    }

    const graphW = maxX - minX + 80;
    const graphH = maxY - minY + 80;
    const zoom = Math.min(
      Math.min(rect.width / graphW, rect.height / graphH),
      MAX_ZOOM
    );

    this.viewport.zoom = zoom;
    this.viewport.x = (rect.width - graphW * zoom) / 2 - minX * zoom + 40 * zoom;
    this.viewport.y = (rect.height - graphH * zoom) / 2 - minY * zoom + 40 * zoom;
    this.viewportChanged.emit({ ...this.viewport });
  }

  // ── Pointer handlers ──────────────────────────────────────────────────

  onCanvasPointerDown(event: PointerEvent): void {
    // Middle mouse or ctrl+left for pan
    if (event.button === 1 || (event.button === 0 && event.ctrlKey)) {
      event.preventDefault();
      this.drag = {
        type: 'pan',
        startX: event.clientX - this.viewport.x,
        startY: event.clientY - this.viewport.y,
        offsetX: 0,
        offsetY: 0,
      };
      return;
    }

    // Left click on canvas → start rubber-band selection (or deselect if no drag)
    if (event.button === 0) {
      const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
      const pos = screenToCanvas(event.clientX, event.clientY, this.viewport, rect);
      this.drag = {
        type: 'select',
        startX: event.clientX,
        startY: event.clientY,
        offsetX: pos.x, // canvas-space start
        offsetY: pos.y,
      };
    }
  }

  onCanvasPointerMove(event: PointerEvent): void {
    if (this.drag.type === 'pan') {
      this.viewport.x = event.clientX - this.drag.startX;
      this.viewport.y = event.clientY - this.drag.startY;
      return;
    }

    if (this.drag.type === 'select') {
      const dx = event.clientX - this.drag.startX;
      const dy = event.clientY - this.drag.startY;
      if (Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD) return;

      const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
      const pos = screenToCanvas(event.clientX, event.clientY, this.viewport, rect);
      const sx = this.drag.offsetX;
      const sy = this.drag.offsetY;

      this.selectionRect = {
        x: Math.min(sx, pos.x),
        y: Math.min(sy, pos.y),
        w: Math.abs(pos.x - sx),
        h: Math.abs(pos.y - sy),
      };

      // Update multi-selection based on nodes intersecting the rect
      this.multiSelectedIds.clear();
      for (const node of this.nodes) {
        if (this.nodeIntersectsRect(node, this.selectionRect)) {
          this.multiSelectedIds.add(node.id);
        }
      }
      return;
    }

    if (this.drag.type === 'node' && this.drag.nodeId) {
      const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
      const pos = screenToCanvas(event.clientX, event.clientY, this.viewport, rect);

      if (this.multiSelectedIds.size > 1 && this.multiSelectedIds.has(this.drag.nodeId)) {
        // Multi-drag: compute offsets for all selected nodes
        const primaryStart = this.multiDragStartPositions.get(this.drag.nodeId);
        if (primaryStart) {
          const newX = snapToGrid(pos.x - this.drag.offsetX);
          const newY = snapToGrid(pos.y - this.drag.offsetY);
          const dx = newX - primaryStart.x;
          const dy = newY - primaryStart.y;

          for (const [id, startPos] of this.multiDragStartPositions) {
            this.dragOffsets.set(id, {
              dx: snapToGrid(startPos.x + dx) - startPos.x,
              dy: snapToGrid(startPos.y + dy) - startPos.y,
            });
          }
        }
      } else {
        // Single node drag
        const node = this.nodeMap.get(this.drag.nodeId);
        if (node) {
          this.dragOffsets.set(this.drag.nodeId, {
            dx: snapToGrid(pos.x - this.drag.offsetX) - node.position.x,
            dy: snapToGrid(pos.y - this.drag.offsetY) - node.position.y,
          });
        }
      }
      this.recalcEdgePaths();
      return;
    }

    if (this.drag.type === 'edge') {
      const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
      const pos = screenToCanvas(event.clientX, event.clientY, this.viewport, rect);
      this.drag.edgeEndX = pos.x;
      this.drag.edgeEndY = pos.y;

      // Compute pending edge path
      const sourceNode = this.nodeMap.get(this.drag.sourceNodeId!);
      if (sourceNode) {
        const portIndex = sourceNode.output_ports.findIndex(
          (p) => p.id === this.drag.sourcePortId
        );
        const from = getOutputPortPosition(
          sourceNode.position.x,
          sourceNode.position.y,
          Math.max(0, portIndex),
          sourceNode.output_ports.length || 1
        );
        this.pendingEdgePath = buildEdgePath(from, { x: pos.x, y: pos.y });
      }
    }
  }

  onCanvasPointerUp(event: PointerEvent): void {
    if (this.drag.type === 'pan') {
      this.viewportChanged.emit({ ...this.viewport });
    }

    if (this.drag.type === 'select') {
      const dx = event.clientX - this.drag.startX;
      const dy = event.clientY - this.drag.startY;

      if (Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD) {
        // Click (no drag) → deselect all
        this.multiSelectedIds.clear();
        this.nodeDeselected.emit();
      }
      // else: rubber-band completed, multiSelectedIds is already populated
      this.selectionRect = null;
    }

    if (this.drag.type === 'node' && this.drag.nodeId) {
      if (this.multiSelectedIds.size > 1 && this.multiSelectedIds.has(this.drag.nodeId)) {
        // Emit nodeMoved for each moved node using effective positions
        for (const id of this.multiSelectedIds) {
          const n = this.nodeMap.get(id);
          if (n) {
            const offset = this.dragOffsets.get(id);
            this.nodeMoved.emit({
              nodeId: id,
              x: n.position.x + (offset?.dx ?? 0),
              y: n.position.y + (offset?.dy ?? 0),
            });
          }
        }
      } else {
        const node = this.nodeMap.get(this.drag.nodeId);
        if (node) {
          const offset = this.dragOffsets.get(this.drag.nodeId);
          this.nodeMoved.emit({
            nodeId: this.drag.nodeId,
            x: node.position.x + (offset?.dx ?? 0),
            y: node.position.y + (offset?.dy ?? 0),
          });
        }
      }
      this.dragOffsets.clear();
      this.multiDragStartPositions.clear();
    }

    if (this.drag.type === 'edge' && this.drag.sourceNodeId) {
      // Check if pointer is over an input port
      const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
      const pos = screenToCanvas(event.clientX, event.clientY, this.viewport, rect);

      for (const node of this.nodes) {
        if (node.id === this.drag.sourceNodeId) continue;
        const inputPos = getInputPortPosition(node.position.x, node.position.y);
        const dist = Math.sqrt(
          Math.pow(pos.x - inputPos.x, 2) + Math.pow(pos.y - inputPos.y, 2)
        );
        if (dist < 20) {
          this.edgeCreated.emit({
            sourceNodeId: this.drag.sourceNodeId,
            sourcePortId: this.drag.sourcePortId || 'default',
            targetNodeId: node.id,
          });
          break;
        }
      }
    }

    this.drag = initialDragState();
    this.pendingEdgePath = null;
  }

  // ── Node interaction ──────────────────────────────────────────────────

  onNodePointerDown(event: PointerEvent, node: WorkflowNode): void {
    event.stopPropagation();
    if (event.button !== 0) return;

    const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
    const pos = screenToCanvas(event.clientX, event.clientY, this.viewport, rect);

    if (event.shiftKey) {
      // Shift+click: toggle node in multi-selection
      if (this.multiSelectedIds.has(node.id)) {
        this.multiSelectedIds.delete(node.id);
      } else {
        this.multiSelectedIds.add(node.id);
        // Also include the currently single-selected node if any
        if (this.selectedNodeId && !this.multiSelectedIds.has(this.selectedNodeId)) {
          this.multiSelectedIds.add(this.selectedNodeId);
        }
      }
      this.nodeSelected.emit(node.id);
      return;
    }

    // Not shift: check if this node is part of a multi-selection
    if (this.multiSelectedIds.size > 1 && this.multiSelectedIds.has(node.id)) {
      // Start multi-drag — keep selection, record start positions
      this.multiDragStartPositions.clear();
      for (const id of this.multiSelectedIds) {
        const n = this.nodeMap.get(id);
        if (n) {
          this.multiDragStartPositions.set(id, { x: n.position.x, y: n.position.y });
        }
      }

      this.drag = {
        type: 'node',
        nodeId: node.id,
        startX: event.clientX,
        startY: event.clientY,
        offsetX: pos.x - node.position.x,
        offsetY: pos.y - node.position.y,
      };
      this.nodeSelected.emit(node.id);
      return;
    }

    // Click on unselected node: clear multi-selection, single select + drag
    this.multiSelectedIds.clear();

    this.drag = {
      type: 'node',
      nodeId: node.id,
      startX: event.clientX,
      startY: event.clientY,
      offsetX: pos.x - node.position.x,
      offsetY: pos.y - node.position.y,
    };

    this.nodeSelected.emit(node.id);
  }

  // ── Port interaction ──────────────────────────────────────────────────

  onOutputPortPointerDown(
    event: PointerEvent,
    node: WorkflowNode,
    port: { id: string }
  ): void {
    event.stopPropagation();
    if (event.button !== 0) return;

    this.drag = {
      type: 'edge',
      sourceNodeId: node.id,
      sourcePortId: port.id,
      startX: event.clientX,
      startY: event.clientY,
      offsetX: 0,
      offsetY: 0,
    };
  }

  // ── Edge interaction ──────────────────────────────────────────────────

  onEdgeClick(event: MouseEvent, edgeId: string): void {
    event.stopPropagation();
    this.edgeSelected.emit(edgeId);
  }

  // ── Drag & drop from palette ──────────────────────────────────────────

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = 'copy';
    }
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    const data = event.dataTransfer?.getData('text/plain');
    if (!data) return;

    const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
    const pos = screenToCanvas(event.clientX, event.clientY, this.viewport, rect);

    this.canvasDropped.emit({
      type: data,
      x: snapToGrid(pos.x - NODE_WIDTH / 2),
      y: snapToGrid(pos.y - NODE_HEIGHT / 2),
    });
  }

  // ── Keyboard ──────────────────────────────────────────────────────────

  onKeyDown(event: KeyboardEvent): void {
    if (event.key === 'Delete' || event.key === 'Backspace') {
      if (this.multiSelectedIds.size > 0) {
        // Delete all multi-selected nodes (except trigger)
        const toRemove = [...this.multiSelectedIds].filter((id) => {
          const n = this.nodeMap.get(id);
          return n && n.type !== 'trigger';
        });
        this.multiSelectedIds.clear();
        for (const id of toRemove) {
          this.nodeRemoved.emit(id);
        }
      } else if (this.selectedNodeId) {
        const node = this.nodeMap.get(this.selectedNodeId);
        if (node && node.type !== 'trigger') {
          this.nodeRemoved.emit(this.selectedNodeId);
        }
      } else if (this.selectedEdgeId) {
        this.edgeRemoved.emit(this.selectedEdgeId);
      }
    }

    // Ctrl/Cmd+A: select all nodes
    if ((event.ctrlKey || event.metaKey) && event.key === 'a') {
      event.preventDefault();
      this.multiSelectedIds.clear();
      for (const node of this.nodes) {
        this.multiSelectedIds.add(node.id);
      }
    }
  }

  // ── Multi-selection helpers ───────────────────────────────────────────

  private nodeIntersectsRect(
    node: WorkflowNode,
    rect: { x: number; y: number; w: number; h: number }
  ): boolean {
    return (
      node.position.x < rect.x + rect.w &&
      node.position.x + NODE_WIDTH > rect.x &&
      node.position.y < rect.y + rect.h &&
      node.position.y + NODE_HEIGHT > rect.y
    );
  }

  // ── Port position helpers for template ────────────────────────────────

  getOutputPortX(node: WorkflowNode, portIndex: number): number {
    const spacing = NODE_WIDTH / (node.output_ports.length + 1);
    return spacing * (portIndex + 1);
  }

  getOutputPortY(): number {
    return NODE_HEIGHT;
  }

  getInputPortX(): number {
    return NODE_WIDTH / 2;
  }

  getInputPortY(): number {
    return 0;
  }

  /** Returns effective position accounting for drag offsets. */
  private getEffectivePosition(node: WorkflowNode): { x: number; y: number } {
    const offset = this.dragOffsets.get(node.id);
    return offset
      ? { x: node.position.x + offset.dx, y: node.position.y + offset.dy }
      : node.position;
  }

  /** Returns the SVG transform for a node, accounting for drag offsets. */
  nodeTransform(node: WorkflowNode): string {
    const pos = this.getEffectivePosition(node);
    return `translate(${pos.x}, ${pos.y})`;
  }

  get viewTransform(): string {
    return `translate(${this.viewport.x}, ${this.viewport.y}) scale(${this.viewport.zoom})`;
  }

  getZoomPercent(): number {
    return Math.round(this.viewport.zoom * 100);
  }

  getEdgeStroke(edgeId: string): string {
    if (this.isEdgeActive(edgeId)) return 'var(--app-canvas-active)';
    if (this.selectedEdgeId === edgeId) return 'var(--app-canvas-selected)';
    return 'var(--app-canvas-edge)';
  }

  getSimColor(status: string | null): string {
    switch (status) {
      case 'success':
        return 'var(--app-sim-success)';
      case 'failed':
        return 'var(--app-sim-failed)';
      case 'active':
        return 'var(--app-sim-active)';
      default:
        return 'var(--app-sim-pending)';
    }
  }
}
