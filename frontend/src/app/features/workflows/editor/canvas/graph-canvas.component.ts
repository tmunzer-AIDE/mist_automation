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
  computed,
  inject,
  signal,
} from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatButtonModule } from '@angular/material/button';
import {
  WorkflowNode,
  WorkflowEdge,
  WorkflowGraph,
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
  @Output() undoRequested = new EventEmitter<void>();
  @Output() redoRequested = new EventEmitter<void>();
  @Output() insertNodeOnEdge = new EventEmitter<{
    edgeId: string;
    actionType: string;
    position: { x: number; y: number };
  }>();
  @Output() nodesPasted = new EventEmitter<{
    nodes: WorkflowNode[];
    edges: WorkflowEdge[];
  }>();

  @ViewChild('svgCanvas', { static: true }) svgCanvas!: ElementRef<SVGSVGElement>;

  viewport = signal<CanvasViewport>({ x: 0, y: 0, zoom: 1 });
  drag = signal<DragState>(initialDragState());
  nodeMap: Map<string, WorkflowNode> = new Map();

  // Pre-computed per-node render data (rebuilt in ngOnChanges)
  nodeRenderData = signal(
    new Map<
      string,
      { color: string; icon: string; label: string; simStatus: string | null; simColor: string; hasErrors: boolean }
    >()
  );

  // Computed edge paths
  edgePaths = signal<
    {
      edge: WorkflowEdge;
      path: string;
      midX: number;
      midY: number;
    }[]
  >([]);

  // Pending edge (being dragged from a port)
  pendingEdgePath = signal<string | null>(null);

  // Multi-selection
  multiSelectedIds = signal(new Set<string>());
  selectionRect = signal<{ x: number; y: number; w: number; h: number } | null>(null);
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
    const newMap = new Map<
      string,
      { color: string; icon: string; label: string; simStatus: string | null; simColor: string; hasErrors: boolean }
    >();
    for (const node of this.nodes) {
      const simStatus = this.simulationState?.nodeStatuses?.[node.id] ?? null;
      newMap.set(node.id, {
        color: this.getNodeColor(node),
        icon: this.getNodeIcon(node),
        label: this.getNodeLabel(node),
        simStatus,
        simColor: this.getSimColor(simStatus),
        hasErrors: !isNodeConfigValid(node),
      });
    }
    this.nodeRenderData.set(newMap);
  }

  isEdgeActive(edgeId: string): boolean {
    return this.simulationState?.activeEdges?.has(edgeId) ?? false;
  }

  isNodeHighlighted(nodeId: string): boolean {
    return nodeId === this.selectedNodeId || this.multiSelectedIds().has(nodeId);
  }

  // ── Edge path computation ─────────────────────────────────────────────

  private rebuildNodeMap(): void {
    this.nodeMap.clear();
    for (const node of this.nodes) {
      this.nodeMap.set(node.id, node);
    }
  }

  recalcEdgePaths(): void {
    const paths: { edge: WorkflowEdge; path: string; midX: number; midY: number }[] = [];
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

      paths.push({
        edge,
        path: buildEdgePath(from, to),
        midX: (from.x + to.x) / 2,
        midY: (from.y + to.y) / 2,
      });
    }
    this.edgePaths.set(paths);
  }

  /** Recalculate edge paths only for edges connected to the given node IDs. */
  recalcEdgePathsForNodes(nodeIds: Set<string>): void {
    const current = this.edgePaths();
    const updated = current.map((ep) => {
      const edge = ep.edge;
      if (!nodeIds.has(edge.source_node_id) && !nodeIds.has(edge.target_node_id)) return ep;

      const sourceNode = this.nodeMap.get(edge.source_node_id);
      const targetNode = this.nodeMap.get(edge.target_node_id);
      if (!sourceNode || !targetNode) return ep;

      const sourcePos = this.getEffectivePosition(sourceNode);
      const targetPos = this.getEffectivePosition(targetNode);

      const portIndex = sourceNode.output_ports.findIndex((p) => p.id === edge.source_port_id);
      const from = getOutputPortPosition(
        sourcePos.x,
        sourcePos.y,
        Math.max(0, portIndex),
        sourceNode.output_ports.length || 1
      );
      const to = getInputPortPosition(targetPos.x, targetPos.y);

      return {
        edge,
        path: buildEdgePath(from, to),
        midX: (from.x + to.x) / 2,
        midY: (from.y + to.y) / 2,
      };
    });
    this.edgePaths.set(updated);
  }

  // ── Viewport controls ─────────────────────────────────────────────────

  onWheel(event: WheelEvent): void {
    event.preventDefault();

    const vp = this.viewport();
    if (event.ctrlKey || event.metaKey) {
      // Zoom (pinch-to-zoom OR Ctrl+scroll wheel)
      const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
      const mouseX = event.clientX - rect.left;
      const mouseY = event.clientY - rect.top;

      const oldZoom = vp.zoom;
      const zoomFactor = 1 - event.deltaY * 0.01;
      const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, oldZoom * zoomFactor));

      // Zoom toward cursor
      const newVp = {
        x: mouseX - ((mouseX - vp.x) / oldZoom) * newZoom,
        y: mouseY - ((mouseY - vp.y) / oldZoom) * newZoom,
        zoom: newZoom,
      };
      this.viewport.set(newVp);
      this.viewportChanged.emit({ ...newVp });
    } else {
      // Pan (two-finger scroll OR mouse wheel without Ctrl)
      const newVp = {
        x: vp.x - event.deltaX,
        y: vp.y - event.deltaY,
        zoom: vp.zoom,
      };
      this.viewport.set(newVp);
      this.viewportChanged.emit({ ...newVp });
    }
  }

  zoomIn(): void {
    const vp = this.viewport();
    const newVp = { ...vp, zoom: Math.min(MAX_ZOOM, vp.zoom + ZOOM_STEP) };
    this.viewport.set(newVp);
    this.viewportChanged.emit({ ...newVp });
  }

  zoomOut(): void {
    const vp = this.viewport();
    const newVp = { ...vp, zoom: Math.max(MIN_ZOOM, vp.zoom - ZOOM_STEP) };
    this.viewport.set(newVp);
    this.viewportChanged.emit({ ...newVp });
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

    const newVp = {
      zoom,
      x: (rect.width - graphW * zoom) / 2 - minX * zoom + 40 * zoom,
      y: (rect.height - graphH * zoom) / 2 - minY * zoom + 40 * zoom,
    };
    this.viewport.set(newVp);
    this.viewportChanged.emit({ ...newVp });
  }

  // ── Pointer handlers ──────────────────────────────────────────────────

  onCanvasPointerDown(event: PointerEvent): void {
    // Middle mouse or ctrl+left for pan
    if (event.button === 1 || (event.button === 0 && event.ctrlKey)) {
      event.preventDefault();
      const vp = this.viewport();
      this.drag.set({
        type: 'pan',
        startX: event.clientX - vp.x,
        startY: event.clientY - vp.y,
        offsetX: 0,
        offsetY: 0,
      });
      return;
    }

    // Left click on canvas → start rubber-band selection (or deselect if no drag)
    if (event.button === 0) {
      const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
      const pos = screenToCanvas(event.clientX, event.clientY, this.viewport(), rect);
      this.drag.set({
        type: 'select',
        startX: event.clientX,
        startY: event.clientY,
        offsetX: pos.x, // canvas-space start
        offsetY: pos.y,
      });
    }
  }

  onCanvasPointerMove(event: PointerEvent): void {
    const d = this.drag();

    if (d.type === 'pan') {
      const vp = this.viewport();
      this.viewport.set({
        x: event.clientX - d.startX,
        y: event.clientY - d.startY,
        zoom: vp.zoom,
      });
      return;
    }

    if (d.type === 'select') {
      const dx = event.clientX - d.startX;
      const dy = event.clientY - d.startY;
      if (Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD) return;

      const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
      const pos = screenToCanvas(event.clientX, event.clientY, this.viewport(), rect);
      const sx = d.offsetX;
      const sy = d.offsetY;

      const sr = {
        x: Math.min(sx, pos.x),
        y: Math.min(sy, pos.y),
        w: Math.abs(pos.x - sx),
        h: Math.abs(pos.y - sy),
      };
      this.selectionRect.set(sr);

      // Update multi-selection based on nodes intersecting the rect
      const newSelected = new Set<string>();
      for (const node of this.nodes) {
        if (this.nodeIntersectsRect(node, sr)) {
          newSelected.add(node.id);
        }
      }
      this.multiSelectedIds.set(newSelected);
      return;
    }

    if (d.type === 'node' && d.nodeId) {
      const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
      const pos = screenToCanvas(event.clientX, event.clientY, this.viewport(), rect);
      const msi = this.multiSelectedIds();

      if (msi.size > 1 && msi.has(d.nodeId)) {
        // Multi-drag: compute offsets for all selected nodes
        const primaryStart = this.multiDragStartPositions.get(d.nodeId);
        if (primaryStart) {
          const newX = snapToGrid(pos.x - d.offsetX);
          const newY = snapToGrid(pos.y - d.offsetY);
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
        const node = this.nodeMap.get(d.nodeId);
        if (node) {
          this.dragOffsets.set(d.nodeId, {
            dx: snapToGrid(pos.x - d.offsetX) - node.position.x,
            dy: snapToGrid(pos.y - d.offsetY) - node.position.y,
          });
        }
      }
      const draggedIds = new Set<string>(
        msi.size > 1 && msi.has(d.nodeId) ? msi : [d.nodeId]
      );
      this.recalcEdgePathsForNodes(draggedIds);
      return;
    }

    if (d.type === 'edge') {
      const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
      const pos = screenToCanvas(event.clientX, event.clientY, this.viewport(), rect);
      this.drag.set({ ...d, edgeEndX: pos.x, edgeEndY: pos.y });

      // Compute pending edge path
      const sourceNode = this.nodeMap.get(d.sourceNodeId!);
      if (sourceNode) {
        const portIndex = sourceNode.output_ports.findIndex(
          (p) => p.id === d.sourcePortId
        );
        const from = getOutputPortPosition(
          sourceNode.position.x,
          sourceNode.position.y,
          Math.max(0, portIndex),
          sourceNode.output_ports.length || 1
        );
        this.pendingEdgePath.set(buildEdgePath(from, { x: pos.x, y: pos.y }));
      }
    }
  }

  onCanvasPointerUp(event: PointerEvent): void {
    const d = this.drag();

    if (d.type === 'pan') {
      this.viewportChanged.emit({ ...this.viewport() });
    }

    if (d.type === 'select') {
      const dx = event.clientX - d.startX;
      const dy = event.clientY - d.startY;

      if (Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD) {
        // Click (no drag) → deselect all
        this.multiSelectedIds.set(new Set());
        this.nodeDeselected.emit();
      }
      // else: rubber-band completed, multiSelectedIds is already populated
      this.selectionRect.set(null);
    }

    if (d.type === 'node' && d.nodeId) {
      const msi = this.multiSelectedIds();
      if (msi.size > 1 && msi.has(d.nodeId)) {
        // Emit nodeMoved for each moved node using effective positions
        for (const id of msi) {
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
        const node = this.nodeMap.get(d.nodeId);
        if (node) {
          const offset = this.dragOffsets.get(d.nodeId);
          this.nodeMoved.emit({
            nodeId: d.nodeId,
            x: node.position.x + (offset?.dx ?? 0),
            y: node.position.y + (offset?.dy ?? 0),
          });
        }
      }
      this.dragOffsets.clear();
      this.multiDragStartPositions.clear();
    }

    if (d.type === 'edge' && d.sourceNodeId) {
      // Check if pointer is over an input port
      const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
      const pos = screenToCanvas(event.clientX, event.clientY, this.viewport(), rect);

      for (const node of this.nodes) {
        if (node.id === d.sourceNodeId) continue;
        const inputPos = getInputPortPosition(node.position.x, node.position.y);
        const dist = Math.sqrt(
          Math.pow(pos.x - inputPos.x, 2) + Math.pow(pos.y - inputPos.y, 2)
        );
        if (dist < 20) {
          this.edgeCreated.emit({
            sourceNodeId: d.sourceNodeId,
            sourcePortId: d.sourcePortId || 'default',
            targetNodeId: node.id,
          });
          break;
        }
      }
    }

    this.drag.set(initialDragState());
    this.pendingEdgePath.set(null);
  }

  // ── Node interaction ──────────────────────────────────────────────────

  onNodePointerDown(event: PointerEvent, node: WorkflowNode): void {
    event.stopPropagation();
    if (event.button !== 0) return;

    const rect = this.svgCanvas.nativeElement.getBoundingClientRect();
    const pos = screenToCanvas(event.clientX, event.clientY, this.viewport(), rect);

    if (event.shiftKey) {
      // Shift+click: toggle node in multi-selection
      const msi = new Set(this.multiSelectedIds());
      if (msi.has(node.id)) {
        msi.delete(node.id);
      } else {
        msi.add(node.id);
        // Also include the currently single-selected node if any
        if (this.selectedNodeId && !msi.has(this.selectedNodeId)) {
          msi.add(this.selectedNodeId);
        }
      }
      this.multiSelectedIds.set(msi);
      this.nodeSelected.emit(node.id);
      return;
    }

    // Not shift: check if this node is part of a multi-selection
    const currentMsi = this.multiSelectedIds();
    if (currentMsi.size > 1 && currentMsi.has(node.id)) {
      // Start multi-drag — keep selection, record start positions
      this.multiDragStartPositions.clear();
      for (const id of currentMsi) {
        const n = this.nodeMap.get(id);
        if (n) {
          this.multiDragStartPositions.set(id, { x: n.position.x, y: n.position.y });
        }
      }

      this.drag.set({
        type: 'node',
        nodeId: node.id,
        startX: event.clientX,
        startY: event.clientY,
        offsetX: pos.x - node.position.x,
        offsetY: pos.y - node.position.y,
      });
      this.nodeSelected.emit(node.id);
      return;
    }

    // Click on unselected node: clear multi-selection, single select + drag
    this.multiSelectedIds.set(new Set());

    this.drag.set({
      type: 'node',
      nodeId: node.id,
      startX: event.clientX,
      startY: event.clientY,
      offsetX: pos.x - node.position.x,
      offsetY: pos.y - node.position.y,
    });

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

    this.drag.set({
      type: 'edge',
      sourceNodeId: node.id,
      sourcePortId: port.id,
      startX: event.clientX,
      startY: event.clientY,
      offsetX: 0,
      offsetY: 0,
    });
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
    const pos = screenToCanvas(event.clientX, event.clientY, this.viewport(), rect);

    this.canvasDropped.emit({
      type: data,
      x: snapToGrid(pos.x - NODE_WIDTH / 2),
      y: snapToGrid(pos.y - NODE_HEIGHT / 2),
    });
  }

  // ── Keyboard ──────────────────────────────────────────────────────────

  onKeyDown(event: KeyboardEvent): void {
    const mod = event.ctrlKey || event.metaKey;

    if (event.key === 'Delete' || event.key === 'Backspace') {
      if (this.multiSelectedIds().size > 0) {
        // Delete all multi-selected nodes (except trigger)
        const toRemove = [...this.multiSelectedIds()].filter((id) => {
          const n = this.nodeMap.get(id);
          return n && n.type !== 'trigger';
        });
        this.multiSelectedIds.set(new Set());
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
    if (mod && event.key === 'a') {
      event.preventDefault();
      const allIds = new Set<string>();
      for (const node of this.nodes) {
        allIds.add(node.id);
      }
      this.multiSelectedIds.set(allIds);
    }

    // Ctrl/Cmd+Z: undo
    if (mod && event.key === 'z' && !event.shiftKey) {
      event.preventDefault();
      this.undoRequested.emit();
    }

    // Ctrl/Cmd+Shift+Z or Ctrl/Cmd+Y: redo
    if (mod && ((event.key === 'z' && event.shiftKey) || event.key === 'y')) {
      event.preventDefault();
      this.redoRequested.emit();
    }

    // Ctrl/Cmd+C: copy selected nodes
    if (mod && event.key === 'c') {
      event.preventDefault();
      this.copySelectedNodes();
    }

    // Ctrl/Cmd+V: paste nodes
    if (mod && event.key === 'v') {
      event.preventDefault();
      this.pasteNodes();
    }
  }

  // ── Copy / Paste ────────────────────────────────────────────────────────

  private copySelectedNodes(): void {
    const msi = this.multiSelectedIds();
    const ids =
      msi.size > 0
        ? [...msi]
        : this.selectedNodeId
          ? [this.selectedNodeId]
          : [];
    if (!ids.length) return;

    const idSet = new Set(ids);
    const nodesToCopy = this.nodes.filter((n) => idSet.has(n.id));
    const edgesToCopy = this.edges.filter(
      (e) => idSet.has(e.source_node_id) && idSet.has(e.target_node_id)
    );

    const payload = JSON.stringify({ _mist_wf_clipboard: true, nodes: nodesToCopy, edges: edgesToCopy });
    navigator.clipboard.writeText(payload).catch(() => {});
  }

  private async pasteNodes(): Promise<void> {
    let text: string;
    try {
      text = await navigator.clipboard.readText();
    } catch {
      return;
    }

    let data: { _mist_wf_clipboard?: boolean; nodes?: WorkflowNode[]; edges?: WorkflowEdge[] };
    try {
      data = JSON.parse(text);
    } catch {
      return;
    }
    if (!data._mist_wf_clipboard || !data.nodes?.length) return;

    // Validate pasted nodes: must have valid type, numeric position, not trigger/subflow_input
    const KNOWN_TYPES = new Set(Object.keys(ACTION_META));
    const BLOCKED_TYPES = new Set(['trigger', 'subflow_input']);
    const validNodes = data.nodes.filter(
      (n) =>
        n &&
        typeof n.id === 'string' &&
        typeof n.type === 'string' &&
        (KNOWN_TYPES.has(n.type) || n.type === 'subflow_output') &&
        !BLOCKED_TYPES.has(n.type) &&
        typeof n.position?.x === 'number' &&
        typeof n.position?.y === 'number' &&
        (!n.name || (typeof n.name === 'string' && n.name.length <= 200)) &&
        (!n.config || JSON.stringify(n.config).length < 100_000)
    );
    if (!validNodes.length) return;

    // Build old→new ID mapping
    const idMap = new Map<string, string>();
    const newNodes: WorkflowNode[] = validNodes.map((n) => {
      const newId = crypto.randomUUID();
      idMap.set(n.id, newId);
      return {
        ...n,
        id: newId,
        position: { x: n.position.x + 40, y: n.position.y + 40 },
      };
    });

    // Re-map edges
    const newEdges: WorkflowEdge[] = (data.edges || [])
      .filter((e) => idMap.has(e.source_node_id) && idMap.has(e.target_node_id))
      .map((e) => ({
        ...e,
        id: crypto.randomUUID(),
        source_node_id: idMap.get(e.source_node_id)!,
        target_node_id: idMap.get(e.target_node_id)!,
      }));

    this.nodesPasted.emit({ nodes: newNodes, edges: newEdges });
  }

  // ── "+" button on edge ──────────────────────────────────────────────────

  onEdgeInsertClick(event: MouseEvent, edgeId: string, midX: number, midY: number): void {
    event.stopPropagation();
    this.insertNodeOnEdge.emit({
      edgeId,
      actionType: '', // editor will open palette dialog
      position: { x: midX - NODE_WIDTH / 2, y: midY - NODE_HEIGHT / 2 },
    });
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

  getSourcePortCount(edge: WorkflowEdge): number {
    const node = this.nodes.find((n) => n.id === edge.source_node_id);
    return node?.output_ports?.length ?? 1;
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

  viewTransform = computed(() => {
    const vp = this.viewport();
    return `translate(${vp.x}, ${vp.y}) scale(${vp.zoom})`;
  });

  zoomPercent = computed(() => Math.round(this.viewport().zoom * 100));

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
