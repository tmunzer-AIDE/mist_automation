"""
Node schema service — derives output schemas for workflow nodes.

Combines OAS data with node-type knowledge to produce variable trees
for the variable autocomplete feature.
"""

from collections import defaultdict, deque
from typing import Any

import structlog

from app.modules.automation.models.workflow import Workflow, WorkflowEdge, WorkflowNode
from app.modules.automation.services.oas_service import OASService

logger = structlog.get_logger(__name__)

# Hardcoded schemas for common Mist webhook topics
TRIGGER_SCHEMAS: dict[str, dict[str, Any]] = {
    "alarms": {
        "topic": "string",
        "events": [
            {
                "type": "string",
                "timestamp": "integer",
                "org_id": "string",
                "site_id": "string",
                "device_name": "string",
                "device_type": "string",
                "mac": "string",
                "severity": "string",
            }
        ],
    },
    "audits": {
        "topic": "string",
        "events": [
            {
                "admin_name": "string",
                "message": "string",
                "org_id": "string",
                "site_id": "string",
                "timestamp": "number",
            }
        ],
    },
    "device-updowns": {
        "topic": "string",
        "events": [
            {
                "type": "string",
                "device_name": "string",
                "device_type": "string",
                "mac": "string",
                "org_id": "string",
                "site_id": "string",
                "timestamp": "number",
            }
        ],
    },
    "device-events": {
        "topic": "string",
        "events": [
            {
                "type": "string",
                "device_name": "string",
                "device_type": "string",
                "mac": "string",
                "org_id": "string",
                "site_id": "string",
                "timestamp": "number",
                "text": "string",
            }
        ],
    },
}

# Utility variables always available
UTILITY_VARIABLES: dict[str, str] = {
    "now": "Current UTC datetime",
    "now_iso": "ISO format datetime",
    "now_timestamp": "Unix timestamp",
}


def get_node_output_schema(node: WorkflowNode) -> dict[str, Any]:
    """
    Derive the output schema for a node based on its type and config.

    Returns a dict representing the shape of the node's output data.
    """
    node_type = node.type

    if node_type == "trigger":
        # Use hardcoded webhook topic schema (support both new and legacy field names)
        webhook_topic = node.config.get("webhook_topic") or node.config.get("webhook_type", "")
        if webhook_topic in TRIGGER_SCHEMAS:
            return TRIGGER_SCHEMAS[webhook_topic]
        return {"topic": "string", "events": [{"type": "string"}]}

    if node_type in ("mist_api_get", "mist_api_post", "mist_api_put", "mist_api_delete"):
        # Try OAS lookup
        endpoint = node.config.get("api_endpoint", "")
        method_map = {
            "mist_api_get": "GET",
            "mist_api_post": "POST",
            "mist_api_put": "PUT",
            "mist_api_delete": "DELETE",
        }
        method = method_map.get(node_type, "GET")

        oas_endpoint = OASService.get_endpoint(method, endpoint)
        if oas_endpoint and oas_endpoint.response_schema:
            return {
                "status_code": "integer",
                "body": _schema_to_shape(oas_endpoint.response_schema),
            }

        return {"status_code": "integer", "body": {}}

    if node_type == "set_variable":
        var_name = node.config.get("variable_name", "value")
        return {var_name: "expression result"}

    if node_type == "webhook":
        return {"status_code": "integer", "response": "string"}

    if node_type == "delay":
        return {"delayed_seconds": "integer"}

    if node_type == "condition":
        return {"matched_branch": "string|integer|null"}

    if node_type == "for_each":
        # During iteration, the node output is the current item.
        # The actual item schema is resolved in get_available_variables
        # using the loop_over path; this is a fallback.
        return {"(current item)": "object"}

    if node_type in ("slack", "servicenow", "pagerduty"):
        return {"status": "string", "response": "string"}

    return {"status": "string", "result": "unknown"}


def _schema_to_shape(schema: dict) -> Any:
    """Convert a JSON Schema to a simple shape representation."""
    schema_type = schema.get("type", "object")

    if schema_type == "object":
        shape: dict[str, Any] = {}
        for prop_name, prop_schema in schema.get("properties", {}).items():
            shape[prop_name] = _schema_to_shape(prop_schema)
        return shape

    if schema_type == "array":
        items = schema.get("items", {})
        return [_schema_to_shape(items)]

    return schema_type


def get_available_variables(workflow: Workflow, target_node_id: str) -> dict[str, Any]:
    """
    Get all variables available to a target node by traversing edges backward.

    Returns a structured dict grouped by source:
    {
        "trigger": { ... schema ... },
        "nodes": {
            "node_name": { ... schema ... },
        },
        "utilities": { "now": "...", ... }
    }
    """
    # Build reverse adjacency map
    reverse_adj: dict[str, list[str]] = defaultdict(list)
    for edge in workflow.edges:
        reverse_adj[edge.target_node_id].append(edge.source_node_id)

    # BFS backward from target node to find all upstream nodes (in reverse flow order)
    upstream_ordered: list[str] = []
    visited: set[str] = set()
    queue: deque[str] = deque()

    for parent_id in reverse_adj.get(target_node_id, []):
        queue.append(parent_id)

    while queue:
        nid = queue.popleft()
        if nid in visited:
            continue
        visited.add(nid)
        upstream_ordered.append(nid)
        for parent_id in reverse_adj.get(nid, []):
            if parent_id not in visited:
                queue.append(parent_id)

    # Reverse to get trigger-first (flow) order
    upstream_ordered.reverse()

    # Build variable tree
    result: dict[str, Any] = {"trigger": {}, "nodes": {}, "utilities": UTILITY_VARIABLES}

    node_map = {n.id: n for n in workflow.nodes}
    # Map node_id → key used in the variable tree (for resolving loop_over paths)
    node_key_map: dict[str, str] = {}
    used_keys: dict[str, int] = {}
    for uid in upstream_ordered:
        node = node_map.get(uid)
        if not node:
            continue

        schema = get_node_output_schema(node)

        if node.type == "trigger":
            result["trigger"] = schema
        else:
            base_key = node.name or node.type.replace("_", " ").title()
            if base_key in used_keys:
                used_keys[base_key] += 1
                key = f"{base_key} {used_keys[base_key]}"
            else:
                used_keys[base_key] = 1
                key = base_key

            # For for_each nodes, resolve item schema from the loop_over path
            if node.type == "for_each":
                item_schema = _resolve_for_each_item_schema(node, result, node_key_map)
                if item_schema is not None:
                    schema = item_schema

            result["nodes"][key] = schema
            node_key_map[node.id] = key
            if node.name:
                node_key_map[node.name] = key

    return result


def _resolve_for_each_item_schema(
    node: WorkflowNode,
    current_tree: dict[str, Any],
    node_key_map: dict[str, str],
) -> dict[str, Any] | None:
    """
    Derive the item schema for a for_each node by tracing its loop_over path
    through the already-built variable tree.

    E.g. loop_over="trigger.events" → look up trigger schema, navigate to
    "events" field, return the array element type.
    """
    loop_over = (node.config.get("loop_over") or "").strip()
    if loop_over.startswith("{{") and loop_over.endswith("}}"):
        loop_over = loop_over[2:-2].strip()
    if not loop_over:
        return None

    parts = loop_over.split(".")
    if not parts:
        return None

    # Navigate the variable tree
    cursor: Any = None
    if parts[0] == "trigger":
        cursor = current_tree.get("trigger", {})
        parts = parts[1:]
    elif parts[0] == "nodes" and len(parts) >= 2:
        # Resolve node name which may contain spaces (e.g., "nodes.For Each Events.field")
        # Try progressively longer node name segments
        nodes_tree = current_tree.get("nodes", {})
        parts = parts[1:]  # remove "nodes"
        matched = False
        for end in range(1, len(parts) + 1):
            candidate = ".".join(parts[:end])
            if candidate in nodes_tree:
                cursor = nodes_tree[candidate]
                parts = parts[end:]
                matched = True
                break
        if not matched:
            return None
    else:
        return None

    # Navigate remaining path segments
    for part in parts:
        if isinstance(cursor, dict) and part in cursor:
            cursor = cursor[part]
        else:
            return None

    # cursor should now be a list (array schema) — extract item type
    if isinstance(cursor, list) and len(cursor) > 0:
        return cursor[0] if isinstance(cursor[0], dict) else None

    return None
