/**
 * Edge path utilities for SVG Bezier curves between node ports.
 */

export interface Point {
  x: number;
  y: number;
}

/** Height/width of a node card on the canvas. */
export const NODE_WIDTH = 240;
export const NODE_HEIGHT = 72;
export const PORT_RADIUS = 6;

/**
 * Calculate the position of an output port on a node.
 * Output ports are evenly distributed along the bottom edge.
 */
export function getOutputPortPosition(
  nodeX: number,
  nodeY: number,
  portIndex: number,
  totalPorts: number
): Point {
  const spacing = NODE_WIDTH / (totalPorts + 1);
  return {
    x: nodeX + spacing * (portIndex + 1),
    y: nodeY + NODE_HEIGHT,
  };
}

/**
 * Calculate the position of the input port (top center of node).
 */
export function getInputPortPosition(nodeX: number, nodeY: number): Point {
  return {
    x: nodeX + NODE_WIDTH / 2,
    y: nodeY,
  };
}

/**
 * Build a cubic Bezier SVG path between two points.
 * The curve drops down from the source and curves up to the target.
 */
export function buildEdgePath(from: Point, to: Point): string {
  const dy = Math.abs(to.y - from.y);
  const controlOffset = Math.max(40, dy * 0.5);

  const c1x = from.x;
  const c1y = from.y + controlOffset;
  const c2x = to.x;
  const c2y = to.y - controlOffset;

  return `M ${from.x} ${from.y} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${to.x} ${to.y}`;
}

/**
 * Calculate the midpoint of a Bezier curve for label placement.
 */
export function getEdgeMidpoint(from: Point, to: Point): Point {
  return {
    x: (from.x + to.x) / 2,
    y: (from.y + to.y) / 2,
  };
}

/**
 * Check if a point is near an edge path (for click detection).
 */
export function isPointNearEdge(
  point: Point,
  from: Point,
  to: Point,
  threshold = 10
): boolean {
  // Sample points along the Bezier and check distance
  for (let t = 0; t <= 1; t += 0.05) {
    const dy = Math.abs(to.y - from.y);
    const controlOffset = Math.max(40, dy * 0.5);

    const c1 = { x: from.x, y: from.y + controlOffset };
    const c2 = { x: to.x, y: to.y - controlOffset };

    const x =
      Math.pow(1 - t, 3) * from.x +
      3 * Math.pow(1 - t, 2) * t * c1.x +
      3 * (1 - t) * Math.pow(t, 2) * c2.x +
      Math.pow(t, 3) * to.x;
    const y =
      Math.pow(1 - t, 3) * from.y +
      3 * Math.pow(1 - t, 2) * t * c1.y +
      3 * (1 - t) * Math.pow(t, 2) * c2.y +
      Math.pow(t, 3) * to.y;

    const dist = Math.sqrt(Math.pow(point.x - x, 2) + Math.pow(point.y - y, 2));
    if (dist < threshold) return true;
  }
  return false;
}
