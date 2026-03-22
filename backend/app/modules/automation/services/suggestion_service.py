"""
Smart suggestions service — rules-based graph analysis for contextual workflow improvement hints.
No LLM calls; designed for instant response.
"""

from pydantic import BaseModel, Field

from app.modules.automation.models.workflow import Workflow, WorkflowNode


class Suggestion(BaseModel):
    """A contextual suggestion for improving a workflow."""
    id: str = Field(..., description="Unique suggestion ID")
    message: str = Field(..., description="Human-readable suggestion text")
    action_type: str | None = Field(default=None, description="Suggested action type to add")
    target_node_id: str | None = Field(default=None, description="Node this suggestion relates to")
    priority: int = Field(default=0, description="Priority (higher = more important)")


def _build_node_map(workflow: Workflow) -> dict[str, WorkflowNode]:
    return {n.id: n for n in workflow.nodes}


def _get_downstream_types(workflow: Workflow, node_id: str) -> set[str]:
    """Get the set of node types directly downstream of a given node."""
    downstream_ids = {e.target_node_id for e in workflow.edges if e.source_node_id == node_id}
    node_map = _build_node_map(workflow)
    return {node_map[nid].type for nid in downstream_ids if nid in node_map}


def _has_template_vars(config: dict, keys: list[str]) -> bool:
    """Check if any of the given config keys contain {{ }} template expressions."""
    for key in keys:
        val = config.get(key, "")
        if isinstance(val, str) and "{{" in val:
            return True
    return False


def analyze_workflow(workflow: Workflow) -> list[Suggestion]:
    """Analyze a workflow graph and return contextual suggestions."""
    suggestions: list[Suggestion] = []
    node_map = _build_node_map(workflow)
    action_nodes = [n for n in workflow.nodes if n.type != "trigger" and n.type != "subflow_input"]
    entry_nodes = [n for n in workflow.nodes if n.type in ("trigger", "subflow_input")]

    # Rule 1: Trigger-only workflow → "Add your first action"
    if entry_nodes and not action_nodes:
        suggestions.append(Suggestion(
            id="add-first-action",
            message="Add your first action node to start building your workflow.",
            priority=100,
        ))

    # Rule 2: API call without downstream condition → "Add error handling"
    api_types = {"mist_api_get", "mist_api_post", "mist_api_put", "mist_api_delete"}
    for node in workflow.nodes:
        if node.type in api_types:
            downstream = _get_downstream_types(workflow, node.id)
            if "condition" not in downstream:
                suggestions.append(Suggestion(
                    id=f"error-handling-{node.id}",
                    message=f'Add a condition after "{node.name}" to handle API errors.',
                    action_type="condition",
                    target_node_id=node.id,
                    priority=60,
                ))

    # Rule 3: Notification without template variables → "Use dynamic content"
    notification_types = {"slack", "pagerduty", "email"}
    for node in workflow.nodes:
        if node.type in notification_types:
            if not _has_template_vars(node.config, ["notification_template", "email_subject"]):
                suggestions.append(Suggestion(
                    id=f"dynamic-content-{node.id}",
                    message=f'"{node.name}" has a static message. Use {{{{ }}}} variables for dynamic content.',
                    target_node_id=node.id,
                    priority=30,
                ))

    # Rule 4: No notification in workflow → "Add a notification"
    has_notification = any(n.type in notification_types | {"webhook"} for n in workflow.nodes)
    if action_nodes and not has_notification:
        suggestions.append(Suggestion(
            id="add-notification",
            message="Add a Slack or email notification so you know when this workflow runs.",
            action_type="slack",
            priority=40,
        ))

    # Rule 5: for_each without explicit max_iterations → "Set iteration limit"
    for node in workflow.nodes:
        if node.type == "for_each":
            max_iter = node.config.get("max_iterations", 100)
            if max_iter >= 100:
                suggestions.append(Suggestion(
                    id=f"loop-limit-{node.id}",
                    message=f'"{node.name}" has max_iterations={max_iter}. Consider lowering to prevent runaway loops.',
                    target_node_id=node.id,
                    priority=50,
                ))

    # Rule 6: Webhook trigger without condition → "Add trigger filter"
    for node in entry_nodes:
        if node.type == "trigger" and node.config.get("trigger_type") == "webhook":
            if not node.config.get("condition"):
                suggestions.append(Suggestion(
                    id="trigger-condition",
                    message="Add a trigger condition to filter out unwanted webhook events.",
                    target_node_id=node.id,
                    priority=20,
                ))

    # Sort by priority descending
    suggestions.sort(key=lambda s: s.priority, reverse=True)
    return suggestions
