/**
 * Canvas state management for pan, zoom, and interaction modes.
 */

export interface CanvasViewport {
  x: number;
  y: number;
  zoom: number;
}

export interface DragState {
  type: 'none' | 'pan' | 'node' | 'edge';
  nodeId?: string;
  startX: number;
  startY: number;
  offsetX: number;
  offsetY: number;
  sourceNodeId?: string;
  sourcePortId?: string;
  edgeEndX?: number;
  edgeEndY?: number;
}

export const MIN_ZOOM = 0.25;
export const MAX_ZOOM = 2.0;
export const ZOOM_STEP = 0.1;
export const GRID_SIZE = 20;

export function snapToGrid(value: number): number {
  return Math.round(value / GRID_SIZE) * GRID_SIZE;
}

export function screenToCanvas(
  screenX: number,
  screenY: number,
  viewport: CanvasViewport,
  canvasRect: DOMRect
): { x: number; y: number } {
  return {
    x: (screenX - canvasRect.left - viewport.x) / viewport.zoom,
    y: (screenY - canvasRect.top - viewport.y) / viewport.zoom,
  };
}

export function canvasToScreen(
  canvasX: number,
  canvasY: number,
  viewport: CanvasViewport,
  canvasRect: DOMRect
): { x: number; y: number } {
  return {
    x: canvasX * viewport.zoom + viewport.x + canvasRect.left,
    y: canvasY * viewport.zoom + viewport.y + canvasRect.top,
  };
}

export function initialDragState(): DragState {
  return { type: 'none', startX: 0, startY: 0, offsetX: 0, offsetY: 0 };
}
