"""
Built-in seed recipes for common Mist automation workflows.
Seeded on startup if no built-in recipes exist.
"""

import structlog

from app.modules.automation.models.recipe import (
    RecipeCategory,
    RecipeDifficulty,
    RecipePlaceholder,
    WorkflowRecipe,
)
from app.modules.automation.models.workflow import (
    NodePort,
    NodePosition,
    VariableBinding,
    WorkflowEdge,
    WorkflowNode,
)

logger = structlog.get_logger(__name__)


def _node(
    node_id: str,
    node_type: str,
    name: str,
    x: float,
    y: float,
    config: dict,
    output_ports: list[NodePort] | None = None,
    save_as: list[VariableBinding] | None = None,
) -> WorkflowNode:
    if output_ports is None:
        output_ports = [NodePort(id="default", label="", type="default")]
    return WorkflowNode(
        id=node_id,
        type=node_type,
        name=name,
        position=NodePosition(x=x, y=y),
        config=config,
        output_ports=output_ports,
        save_as=save_as,
    )


def _edge(eid: str, src: str, tgt: str, src_port: str = "default", label: str = "") -> WorkflowEdge:
    return WorkflowEdge(id=eid, source_node_id=src, source_port_id=src_port, target_node_id=tgt, label=label)


def _build_ap_offline_alert() -> WorkflowRecipe:
    """AP Offline Alert: webhook → delay → check status → condition → Slack."""
    n1 = _node(
        "trigger-1", "trigger", "AP Offline Trigger", 400, 80,
        {"trigger_type": "webhook", "webhook_topic": "device-events"},
    )
    n2 = _node("delay-1", "delay", "Wait 5 min", 400, 220, {"delay_seconds": 300})
    n3 = _node(
        "api-1", "mist_api_get", "Check Device Status", 400, 360,
        {"api_endpoint": "/api/v1/sites/{{ trigger.site_id }}/stats/devices?type=ap&mac={{ trigger.mac }}"},
        save_as=[VariableBinding(name="device_status", expression="{{ output.body }}")],
    )
    n4 = _node(
        "cond-1", "condition", "Still Offline?", 400, 500,
        {"branches": [{"condition": "{{ device_status | length == 0 or device_status[0].status != 'connected' }}"}]},
        output_ports=[
            NodePort(id="branch_0", label="If", type="branch"),
            NodePort(id="else", label="Else", type="branch"),
        ],
    )
    n5 = _node(
        "slack-1", "slack", "Notify Slack", 300, 660,
        {
            "notification_channel": "PLACEHOLDER_SLACK_URL",
            "notification_template": "AP {{ trigger.device_name }} at site {{ trigger.site_name }} is still offline after 5 minutes.",
            "slack_header": "AP Offline Alert",
        },
    )

    edges = [
        _edge("e1", "trigger-1", "delay-1"),
        _edge("e2", "delay-1", "api-1"),
        _edge("e3", "api-1", "cond-1"),
        _edge("e4", "cond-1", "slack-1", "branch_0", "If"),
    ]

    return WorkflowRecipe(
        name="AP Offline Alert",
        description="When an AP goes offline, wait 5 minutes, recheck status, and send a Slack notification if still offline.",
        category=RecipeCategory.MONITORING,
        tags=["ap", "offline", "slack", "notification"],
        difficulty=RecipeDifficulty.BEGINNER,
        nodes=[n1, n2, n3, n4, n5],
        edges=edges,
        placeholders=[
            RecipePlaceholder(
                node_id="slack-1",
                field_path="notification_channel",
                label="Slack Webhook URL",
                description="The Slack incoming webhook URL for notifications",
                placeholder_type="url",
            ),
        ],
        built_in=True,
    )


def _build_config_change_notification() -> WorkflowRecipe:
    """Config Change Notification: webhook audit → data_transform → format_report → Slack."""
    n1 = _node(
        "trigger-1", "trigger", "Config Audit Trigger", 400, 80,
        {"trigger_type": "webhook", "webhook_topic": "audits"},
    )
    n2 = _node(
        "dt-1", "data_transform", "Extract Changes", 400, 240,
        {
            "source": "{{ trigger }}",
            "fields": [
                {"path": "admin_name", "label": "Admin"},
                {"path": "message", "label": "Change"},
                {"path": "timestamp", "label": "Time"},
            ],
        },
    )
    n3 = _node(
        "fr-1", "format_report", "Format Report", 400, 400,
        {
            "data_source": "{{ nodes.Extract_Changes.rows }}",
            "format": "slack",
            "title": "Configuration Change Report",
        },
    )
    n4 = _node(
        "slack-1", "slack", "Send Notification", 400, 560,
        {
            "notification_channel": "PLACEHOLDER_SLACK_URL",
            "notification_template": "{{ nodes.Format_Report.report }}",
            "slack_header": "Config Change Detected",
        },
    )

    edges = [
        _edge("e1", "trigger-1", "dt-1"),
        _edge("e2", "dt-1", "fr-1"),
        _edge("e3", "fr-1", "slack-1"),
    ]

    return WorkflowRecipe(
        name="Config Change Notification",
        description="When a configuration change is detected via audit webhook, format the details and send a Slack notification.",
        category=RecipeCategory.MONITORING,
        tags=["audit", "config", "slack", "notification"],
        difficulty=RecipeDifficulty.BEGINNER,
        nodes=[n1, n2, n3, n4],
        edges=edges,
        placeholders=[
            RecipePlaceholder(
                node_id="slack-1",
                field_path="notification_channel",
                label="Slack Webhook URL",
                description="The Slack incoming webhook URL for notifications",
                placeholder_type="url",
            ),
        ],
        built_in=True,
    )


def _build_device_health_check() -> WorkflowRecipe:
    """Device Health Check: cron → GET stats → data_transform → condition → email."""
    n1 = _node(
        "trigger-1", "trigger", "Scheduled Check", 400, 80,
        {"trigger_type": "cron", "cron_expression": "0 */6 * * *", "timezone": "UTC"},
    )
    n2 = _node(
        "api-1", "mist_api_get", "Get AP Stats", 400, 240,
        {"api_endpoint": "/api/v1/sites/PLACEHOLDER_SITE_ID/stats/devices?type=ap"},
        save_as=[VariableBinding(name="devices", expression="{{ output.body }}")],
    )
    n3 = _node(
        "dt-1", "data_transform", "Filter Unhealthy", 400, 400,
        {
            "source": "{{ devices }}",
            "fields": [
                {"path": "name", "label": "Device"},
                {"path": "status", "label": "Status"},
                {"path": "mac", "label": "MAC"},
            ],
            "filter": "{{ item.status != 'connected' }}",
        },
    )
    n4 = _node(
        "cond-1", "condition", "Any Unhealthy?", 400, 560,
        {"branches": [{"condition": "{{ nodes.Filter_Unhealthy.row_count > 0 }}"}]},
        output_ports=[
            NodePort(id="branch_0", label="If", type="branch"),
            NodePort(id="else", label="Else", type="branch"),
        ],
    )
    n5 = _node(
        "email-1", "email", "Send Email Alert", 300, 720,
        {
            "notification_channel": "PLACEHOLDER_EMAIL",
            "email_subject": "Device Health Alert - {{ nodes.Filter_Unhealthy.row_count }} unhealthy devices",
            "notification_template": "The following devices are not connected:\n\n{% for row in nodes.Filter_Unhealthy.rows %}{{ row.Device }} ({{ row.MAC }}): {{ row.Status }}\n{% endfor %}",
        },
    )

    edges = [
        _edge("e1", "trigger-1", "api-1"),
        _edge("e2", "api-1", "dt-1"),
        _edge("e3", "dt-1", "cond-1"),
        _edge("e4", "cond-1", "email-1", "branch_0", "If"),
    ]

    return WorkflowRecipe(
        name="Device Health Check",
        description="Run a scheduled check every 6 hours. List all unhealthy APs and email an alert if any are found.",
        category=RecipeCategory.MONITORING,
        tags=["cron", "health", "ap", "email"],
        difficulty=RecipeDifficulty.INTERMEDIATE,
        nodes=[n1, n2, n3, n4, n5],
        edges=edges,
        placeholders=[
            RecipePlaceholder(
                node_id="api-1",
                field_path="api_endpoint",
                label="Site ID",
                description="Replace PLACEHOLDER_SITE_ID with your Mist site ID",
                placeholder_type="site_id",
            ),
            RecipePlaceholder(
                node_id="email-1",
                field_path="notification_channel",
                label="Email Recipients",
                description="Comma-separated email addresses for alerts",
                placeholder_type="text",
            ),
        ],
        built_in=True,
    )


def _build_incident_escalation() -> WorkflowRecipe:
    """Incident Escalation: aggregated_webhook → delay → condition (severity) → PagerDuty + Slack."""
    n1 = _node(
        "trigger-1", "trigger", "AP Disconnect Events", 400, 80,
        {
            "trigger_type": "aggregated_webhook",
            "webhook_topic": "device-events",
            "event_type_filter": "AP_DISCONNECTED",
            "closing_event_type": "AP_CONNECTED",
            "device_key": "device_mac",
            "window_seconds": 300,
            "group_by": "site_id",
            "min_events": 3,
        },
    )
    n2 = _node(
        "cond-1", "condition", "Event Count Check", 400, 260,
        {"branches": [{"condition": "{{ trigger.aggregation.event_count >= 5 }}"}]},
        output_ports=[
            NodePort(id="branch_0", label="Critical (5+)", type="branch"),
            NodePort(id="else", label="Warning", type="branch"),
        ],
    )
    n3 = _node(
        "slack-1", "slack", "PagerDuty + Slack", 250, 440,
        {
            "notification_channel": "PLACEHOLDER_SLACK_URL",
            "notification_template": "CRITICAL: {{ trigger.aggregation.event_count }} APs disconnected at site {{ trigger.aggregation.site_id }} in the last 5 minutes.",
            "slack_header": "Multi-AP Outage",
        },
    )
    n4 = _node(
        "slack-2", "slack", "Slack Warning", 550, 440,
        {
            "notification_channel": "PLACEHOLDER_SLACK_URL",
            "notification_template": "WARNING: {{ trigger.aggregation.event_count }} AP(s) disconnected at site {{ trigger.aggregation.site_id }}.",
            "slack_header": "AP Disconnect Warning",
        },
    )

    edges = [
        _edge("e1", "trigger-1", "cond-1"),
        _edge("e2", "cond-1", "slack-1", "branch_0", "Critical (5+)"),
        _edge("e3", "cond-1", "slack-2", "else", "Warning"),
    ]

    return WorkflowRecipe(
        name="Incident Escalation",
        description="When 3+ APs disconnect within 5 minutes at a site, escalate. 5+ triggers critical alert, fewer triggers a warning.",
        category=RecipeCategory.INCIDENT_RESPONSE,
        tags=["aggregated", "incident", "escalation", "slack"],
        difficulty=RecipeDifficulty.INTERMEDIATE,
        nodes=[n1, n2, n3, n4],
        edges=edges,
        placeholders=[
            RecipePlaceholder(
                node_id="slack-1",
                field_path="notification_channel",
                label="Critical Slack Channel",
                description="Slack webhook URL for critical alerts",
                placeholder_type="url",
            ),
            RecipePlaceholder(
                node_id="slack-2",
                field_path="notification_channel",
                label="Warning Slack Channel",
                description="Slack webhook URL for warning alerts",
                placeholder_type="url",
            ),
        ],
        built_in=True,
    )


SEED_RECIPES = [
    _build_ap_offline_alert,
    _build_config_change_notification,
    _build_device_health_check,
    _build_incident_escalation,
]


async def seed_built_in_recipes() -> None:
    """Insert built-in seed recipes, skipping any that already exist by name."""
    created = 0
    for builder in SEED_RECIPES:
        recipe = builder()
        existing = await WorkflowRecipe.find_one(
            WorkflowRecipe.name == recipe.name,
            WorkflowRecipe.built_in == True,  # noqa: E712
        )
        if existing:
            continue
        await recipe.insert()
        logger.info("seed_recipe_created", name=recipe.name)
        created += 1

    if created:
        logger.info("seed_recipes_done", created=created)
    else:
        logger.info("seed_recipes_skipped", reason="all already exist")
