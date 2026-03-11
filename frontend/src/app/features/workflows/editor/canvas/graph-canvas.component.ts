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
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatButtonModule } from '@angular/material/button';
import {
  WorkflowNode,
  WorkflowEdge,
  SimulationState,
} from '../../../../core/models/workflow.model';
import { ACTION_META, DEFAULT_ACTION_META } from '../../../../core/models/workflow-meta';
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

@Component({
  selector: 'app-graph-canvas',
  standalone: true,
  imports: [CommonModule, MatIconModule, MatTooltipModule, MatButtonModule],
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

  // Computed edge paths
  edgePaths: {
    edge: WorkflowEdge;
    path: string;
    midX: number;
    midY: number;
  }[] = [];

  // Pending edge (being dragged from a port)
  pendingEdgePath: string | null = null;

  readonly NODE_WIDTH = NODE_WIDTH;
  readonly NODE_HEIGHT = NODE_HEIGHT;
  readonly PORT_RADIUS = PORT_RADIUS;
  readonly GRID_SIZE = GRID_SIZE;

  private el = inject(ElementRef);

  ngOnInit(): void {
    this.rebuildNodeMap();
    this.recalcEdgePaths();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['nodes'] || changes['edges']) {
      this.rebuildNodeMap();
      this.recalcEdgePaths();
    }
  }

  ngOnDestroy(): void {
    // cleanup
  }

  // ── Node rendering helpers ────────────────────────────────────────────

  getNodeMeta(type: string) {
    return ACTION_META[type as keyof typeof ACTION_META] || DEFAULT_ACTION_META;
  }

  getNodeLabel(node: WorkflowNode): string {
    if (node.name) return node.name;
    if (node.type === 'trigger') return 'Trigger';
    const meta = this.getNodeMeta(node.type);
    return meta.label;
  }

  getNodeIcon(node: WorkflowNode): string {
    if (node.type === 'trigger') {
      const tt = node.config?.['trigger_type'];
      if (tt === 'cron') return 'schedule';
      if (tt === 'manual') return 'play_circle';
      return 'webhook';
    }
    return this.getNodeMeta(node.type).icon;
  }

  getNodeColor(node: WorkflowNode): string {
    if (node.type === 'trigger') return '#6a1b9a';
    return this.getNodeMeta(node.type).color;
  }

  getSimulationStatus(nodeId: string): string | null {
    return this.simulationState?.nodeStatuses?.[nodeId] ?? null;
  }

  isEdgeActive(edgeId: string): boolean {
    return this.simulationState?.activeEdges?.has(edgeId) ?? false;
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

      const portIndex = sourceNode.output_ports.findIndex(
        (p) => p.id === edge.source_port_id
      );
      const from = getOutputPortPosition(
        sourceNode.position.x,
        sourceNode.position.y,
        Math.max(0, portIndex),
        sourceNode.output_ports.length || 1
      );
      const to = getInputPortPosition(targetNode.position.x, targetNode.position.y);

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

    // Left click on empty canvas = deselect
    if (event.button === 0 && (event.target as Element) === this.svgCanvas.nativeElement) {
      this.nodeDeselected.emit();
    }
  }

  onCanvasPointerMove(event: PointerEvent): void {
    if (this.drag.type === 'pan') {
      this.viewport.x = event.clientX - this.drag.startX;
      this.viewport.y = event.clientY - this.drag.startY;
      return;
    }

    if (this.drag.type === 'node' && this.drag.nodeId) {
      const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
      const pos = screenToCanvas(event.clientX, event.clientY, this.viewport, rect);
      const node = this.nodeMap.get(this.drag.nodeId);
      if (node) {
        node.position.x = snapToGrid(pos.x - this.drag.offsetX);
        node.position.y = snapToGrid(pos.y - this.drag.offsetY);
        this.recalcEdgePaths();
      }
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

    if (this.drag.type === 'node' && this.drag.nodeId) {
      const node = this.nodeMap.get(this.drag.nodeId);
      if (node) {
        this.nodeMoved.emit({
          nodeId: this.drag.nodeId,
          x: node.position.x,
          y: node.position.y,
        });
      }
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
      if (this.selectedNodeId) {
        const node = this.nodeMap.get(this.selectedNodeId);
        if (node && node.type !== 'trigger') {
          this.nodeRemoved.emit(this.selectedNodeId);
        }
      } else if (this.selectedEdgeId) {
        this.edgeRemoved.emit(this.selectedEdgeId);
      }
    }
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

  get viewTransform(): string {
    return `translate(${this.viewport.x}, ${this.viewport.y}) scale(${this.viewport.zoom})`;
  }

  getZoomPercent(): number {
    return Math.round(this.viewport.zoom * 100);
  }
}
