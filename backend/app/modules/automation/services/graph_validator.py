"""
Graph validator — ensures workflow graphs are structurally valid.
"""

from collections import defaultdict, deque

from app.core.exceptions import ValidationError
from app.modules.automation.models.workflow import WorkflowEdge, WorkflowNode


def validate_graph(nodes: list[WorkflowNode], edges: list[WorkflowEdge]) -> None:
    """
    Validate a workflow graph structure.

    Checks:
    - Exactly one trigger node
    - All edge references point to existing nodes/ports
    - No orphan non-trigger nodes (every non-trigger node must be reachable from the trigger)
    - No cycles (except for_each loops are allowed to have back-edges)

    Raises:
        ValidationError: If graph is invalid
    """
    if not nodes:
        raise ValidationError("Workflow must have at least one node")

    node_ids = {n.id for n in nodes}
    node_map = {n.id: n for n in nodes}

    # ── Check exactly one trigger ────────────────────────────────────────
    trigger_nodes = [n for n in nodes if n.type == "trigger"]
    if len(trigger_nodes) == 0:
        raise ValidationError("Workflow must have exactly one trigger node")
    if len(trigger_nodes) > 1:
        raise ValidationError("Workflow must have exactly one trigger node, found multiple")

    trigger_id = trigger_nodes[0].id

    # ── Validate edges reference existing nodes ──────────────────────────
    edge_ids = set()
    for edge in edges:
        if edge.id in edge_ids:
            raise ValidationError(f"Duplicate edge ID: {edge.id}")
        edge_ids.add(edge.id)

        if edge.source_node_id not in node_ids:
            raise ValidationError(f"Edge {edge.id} references non-existent source node {edge.source_node_id}")
        if edge.target_node_id not in node_ids:
            raise ValidationError(f"Edge {edge.id} references non-existent target node {edge.target_node_id}")

        # Validate port IDs exist on source node
        source_node = node_map[edge.source_node_id]
        valid_source_ports = {p.id for p in source_node.output_ports}
        if valid_source_ports and edge.source_port_id not in valid_source_ports:
            raise ValidationError(
                f"Edge {edge.id}: source port '{edge.source_port_id}' "
                f"not found on node {source_node.id} (available: {valid_source_ports})"
            )

    # ── Build adjacency map and check reachability ───────────────────────
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        adjacency[edge.source_node_id].append(edge.target_node_id)

    # BFS from trigger
    visited: set[str] = set()
    queue: deque[str] = deque([trigger_id])
    while queue:
        nid = queue.popleft()
        if nid in visited:
            continue
        visited.add(nid)
        for neighbor in adjacency.get(nid, []):
            if neighbor not in visited:
                queue.append(neighbor)

    # Check for orphan nodes
    for node in nodes:
        if node.id not in visited and node.type != "trigger":
            raise ValidationError(f"Node '{node.name or node.id}' is not reachable from the trigger")

    # ── Cycle detection (Kahn's algorithm — topological sort) ────────────
    # Skip for_each back-edges for cycle detection
    in_degree: dict[str, int] = defaultdict(int)
    forward_adj: dict[str, list[str]] = defaultdict(list)

    for nid in node_ids:
        in_degree[nid] = 0

    for edge in edges:
        # Allow for_each loop body → for_each node back-edges
        source_node = node_map[edge.source_node_id]
        target_node = node_map[edge.target_node_id]
        if target_node.type == "for_each" and edge.target_port_id == "loop_back":
            continue

        forward_adj[edge.source_node_id].append(edge.target_node_id)
        in_degree[edge.target_node_id] += 1

    topo_queue: deque[str] = deque()
    for nid in node_ids:
        if in_degree[nid] == 0:
            topo_queue.append(nid)

    topo_count = 0
    while topo_queue:
        nid = topo_queue.popleft()
        topo_count += 1
        for neighbor in forward_adj.get(nid, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                topo_queue.append(neighbor)

    if topo_count != len(node_ids):
        raise ValidationError("Workflow graph contains a cycle")
