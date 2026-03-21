"""
Graph validator — ensures workflow graphs are structurally valid.
"""

from collections import defaultdict, deque

from app.core.exceptions import ValidationError
from app.modules.automation.models.workflow import WorkflowEdge, WorkflowNode


def validate_graph(
    nodes: list[WorkflowNode],
    edges: list[WorkflowEdge],
    workflow_type: str = "standard",
) -> None:
    """
    Validate a workflow graph structure.

    Checks:
    - Entry node rules based on workflow_type
    - All edge references point to existing nodes/ports
    - No orphan nodes (every non-entry node must be reachable from entry)
    - No cycles (except for_each loops are allowed to have back-edges)

    Raises:
        ValidationError: If graph is invalid
    """
    if not nodes:
        raise ValidationError("Workflow must have at least one node")

    node_ids = {n.id for n in nodes}
    node_map = {n.id: n for n in nodes}

    # ── Validate entry node based on workflow_type ────────────────────────
    if workflow_type == "subflow":
        _validate_subflow_entry(nodes)
        entry = _require_single_node(nodes, "subflow_input", "subflow_input node")
    else:
        _validate_standard_entry(nodes)
        entry = _require_single_node(nodes, "trigger", "trigger node")
    entry_id = entry.id

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

    # BFS from entry node
    visited: set[str] = set()
    queue: deque[str] = deque([entry_id])
    while queue:
        nid = queue.popleft()
        if nid in visited:
            continue
        visited.add(nid)
        for neighbor in adjacency.get(nid, []):
            if neighbor not in visited:
                queue.append(neighbor)

    # Check for orphan nodes
    entry_type = "subflow_input" if workflow_type == "subflow" else "trigger"
    for node in nodes:
        if node.id not in visited and node.type != entry_type:
            raise ValidationError(f"Node '{node.name or node.id}' is not reachable from the entry node")

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


def _require_single_node(nodes: list[WorkflowNode], node_type: str, label: str) -> WorkflowNode:
    """Find exactly one node of the given type, or raise ValidationError."""
    matching = [n for n in nodes if n.type == node_type]
    if len(matching) != 1:
        raise ValidationError(f"Workflow must have exactly one {label}, found {len(matching)}")
    return matching[0]


def _validate_standard_entry(nodes: list[WorkflowNode]) -> None:
    """Validate entry node rules for standard workflows."""
    trigger = _require_single_node(nodes, "trigger", "trigger node")

    # Validate aggregated_webhook trigger config
    trigger_type = (trigger.config or {}).get("trigger_type", "")
    if trigger_type == "aggregated_webhook":
        _validate_aggregated_webhook_config(trigger)

    for node in nodes:
        if node.type in ("subflow_input", "subflow_output"):
            raise ValidationError(
                f"Standard workflows cannot contain '{node.type}' nodes. "
                "Use a sub-flow workflow instead."
            )


def _validate_subflow_entry(nodes: list[WorkflowNode]) -> None:
    """Validate entry node rules for sub-flow workflows."""
    _require_single_node(nodes, "subflow_input", "subflow_input node")

    output_nodes = [n for n in nodes if n.type == "subflow_output"]
    if len(output_nodes) == 0:
        raise ValidationError("Sub-flow must have at least one subflow_output node")

    for node in nodes:
        if node.type == "trigger":
            raise ValidationError("Sub-flow workflows cannot contain trigger nodes. Use subflow_input instead.")


def _validate_aggregated_webhook_config(trigger: WorkflowNode) -> None:
    """Validate config fields specific to aggregated_webhook triggers."""
    cfg = trigger.config or {}

    window_seconds = cfg.get("window_seconds")
    if not window_seconds or (isinstance(window_seconds, (int, float)) and window_seconds <= 0):
        raise ValidationError("Aggregated webhook trigger requires 'window_seconds' > 0")

    group_by = cfg.get("group_by")
    if not group_by:
        raise ValidationError("Aggregated webhook trigger requires a non-empty 'group_by' field")

    event_type_filter = cfg.get("event_type_filter")
    if not event_type_filter:
        raise ValidationError("Aggregated webhook trigger requires 'event_type_filter' (the opening event type)")

    # closing_event_type is optional
    # device_key is optional (defaults to device_mac)


async def validate_no_circular_subflow_references(
    workflow_id: str | None,
    nodes: list[WorkflowNode],
) -> None:
    """
    Detect circular references in invoke_subflow nodes.

    Walks the chain of sub-flow invocations and raises ValidationError
    if a cycle is found (e.g., A → B → A).
    """
    from app.modules.automation.models.workflow import Workflow

    # Extract target workflow IDs from invoke_subflow nodes
    target_ids = set()
    for node in nodes:
        if node.type == "invoke_subflow":
            target_wf_id = node.config.get("target_workflow_id")
            if target_wf_id:
                target_ids.add(target_wf_id)

    if not target_ids:
        return

    # BFS through sub-flow references
    visited: set[str] = set()
    if workflow_id:
        visited.add(workflow_id)

    queue = deque(target_ids)
    while queue:
        wf_id = queue.popleft()
        if wf_id in visited:
            raise ValidationError(f"Circular sub-flow reference detected involving workflow {wf_id}")
        visited.add(wf_id)

        try:
            from beanie import PydanticObjectId

            target_wf = await Workflow.get(PydanticObjectId(wf_id))
        except Exception:
            continue

        if not target_wf:
            continue

        for node in target_wf.nodes:
            if node.type == "invoke_subflow":
                child_id = node.config.get("target_workflow_id")
                if child_id and child_id not in visited:
                    queue.append(child_id)
