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
            "notification_channel": "{{ slack_url }}",
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
            "notification_channel": "{{ slack_url }}",
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
            "notification_channel": "{{ slack_url }}",
            "notification_template": "CRITICAL: {{ trigger.aggregation.event_count }} APs disconnected at site {{ trigger.aggregation.site_id }} in the last 5 minutes.",
            "slack_header": "Multi-AP Outage",
        },
    )
    n4 = _node(
        "slack-2", "slack", "Slack Warning", 550, 440,
        {
            "notification_channel": "{{ slack_url }}",
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


def _build_rogue_ap_containment() -> WorkflowRecipe:
    """Rogue AP Containment: alarm webhook → for-each BSSID → search switch port → condition → disable port or alert."""
    # Triggers on rogue_ap, honeypot_ssid, and other rogue-related alarm types
    n1 = _node(
        "trigger-1", "trigger", "Rogue AP Alarm", 400, 80,
        {"trigger_type": "webhook", "webhook_topic": "alarms"},
        # No event_type_filter — the condition node below handles type-specific logic.
        # Alarm types with bssids: rogue_ap, honeypot_ssid, rogue_ap_detected
    )
    # Guard: only process alarms that have bssids (rogue/honeypot types)
    n1b = _node(
        "cond-guard", "condition", "Has BSSIDs?", 400, 180,
        {"branches": [{"condition": "{{ trigger.bssids is defined and trigger.bssids | length > 0 }}"}]},
        output_ports=[
            NodePort(id="branch_0", label="Yes", type="branch"),
            NodePort(id="else", label="No", type="branch"),
        ],
    )
    n2 = _node(
        "loop-1", "for_each", "Each Rogue BSSID", 400, 340,
        {"loop_over": "{{ trigger.bssids }}", "loop_variable": "bssid", "max_iterations": 20},
        output_ports=[
            NodePort(id="loop_body", label="Body", type="loop"),
            NodePort(id="done", label="Done", type="default"),
        ],
    )
    n3 = _node(
        "api-search", "mist_api_get", "Search Switch Ports", 400, 520,
        {"api_endpoint": "/api/v1/sites/{{ trigger.site_id }}/stats/ports/search?mac={{ bssid }}&device_type=switch&limit=1"},
        save_as=[VariableBinding(name="port_results", expression="{{ output.body.results }}")],
    )
    n4 = _node(
        "cond-1", "condition", "Found on Switch?", 400, 700,
        {"branches": [{"condition": "{{ port_results | length > 0 }}"}]},
        output_ports=[
            NodePort(id="branch_0", label="Wired", type="branch"),
            NodePort(id="else", label="Wireless Only", type="branch"),
        ],
    )
    # Wired path: disable the switch port
    n5 = _node(
        "api-disable", "mist_api_put", "Disable Switch Port", 200, 880,
        {
            "api_endpoint": "/api/v1/sites/{{ trigger.site_id }}/devices/{{ port_results[0].device_id }}",
            "api_body": '{"port_config": {"{{ port_results[0].port_id }}": {"usage": "disabled", "description": "Rogue AP containment - auto-disabled"}}}',
        },
    )
    n6 = _node(
        "slack-wired", "slack", "Alert: Port Disabled", 200, 1060,
        {
            "notification_channel": "{{ slack_url }}",
            "notification_template": (
                "Rogue AP *{{ bssid }}* contained.\n"
                "Switch port `{{ port_results[0].port_id }}` on *{{ port_results[0].device_name }}* has been disabled.\n"
                "Site: {{ trigger.site_name }}\n"
                "SSIDs: {{ trigger.ssids | join(', ') }}"
            ),
            "slack_header": "Rogue AP Contained",
        },
    )
    n7 = _node(
        "syslog-wired", "syslog", "SIEM: Port Disabled", 200, 1240,
        {
            "syslog_host": "PLACEHOLDER_SYSLOG_HOST",
            "syslog_port": 514,
            "syslog_protocol": "udp",
            "syslog_format": "cef",
            "syslog_facility": "local0",
            "syslog_severity": "warning",
            "cef_device_vendor": "Juniper",
            "cef_device_product": "Mist",
            "cef_event_class_id": "ROGUE_AP_CONTAINED",
            "cef_name": "Rogue AP contained - switch port disabled",
            "notification_template": (
                "Rogue BSSID={{ bssid }} switch={{ port_results[0].device_name }} "
                "port={{ port_results[0].port_id }} site={{ trigger.site_name }}"
            ),
        },
    )
    # Wireless-only path: alert only
    n8 = _node(
        "slack-wireless", "slack", "Alert: Wireless Rogue", 600, 880,
        {
            "notification_channel": "{{ slack_url }}",
            "notification_template": (
                "Rogue AP *{{ bssid }}* detected (wireless only — not found on wired network).\n"
                "Detected by: {{ trigger.aps | join(', ') }}\n"
                "SSIDs: {{ trigger.ssids | join(', ') }}\n"
                "Site: {{ trigger.site_name }}\n"
                "Manual investigation recommended."
            ),
            "slack_header": "Rogue AP Detected",
        },
    )
    n9 = _node(
        "syslog-wireless", "syslog", "SIEM: Wireless Rogue", 600, 1060,
        {
            "syslog_host": "PLACEHOLDER_SYSLOG_HOST",
            "syslog_port": 514,
            "syslog_protocol": "udp",
            "syslog_format": "cef",
            "syslog_facility": "local0",
            "syslog_severity": "notice",
            "cef_device_vendor": "Juniper",
            "cef_device_product": "Mist",
            "cef_event_class_id": "ROGUE_AP_DETECTED",
            "cef_name": "Rogue AP detected - wireless only",
            "notification_template": "Rogue BSSID={{ bssid }} site={{ trigger.site_name }} detected_by={{ trigger.aps | join(',') }}",
        },
    )

    edges = [
        _edge("e1", "trigger-1", "cond-guard"),
        _edge("e1b", "cond-guard", "loop-1", "branch_0", "Yes"),
        _edge("e2", "loop-1", "api-search", "loop_body", "Body"),
        _edge("e3", "api-search", "cond-1"),
        _edge("e4", "cond-1", "api-disable", "branch_0", "Wired"),
        _edge("e5", "api-disable", "slack-wired"),
        _edge("e6", "slack-wired", "syslog-wired"),
        _edge("e7", "cond-1", "slack-wireless", "else", "Wireless Only"),
        _edge("e8", "slack-wireless", "syslog-wireless"),
    ]

    return WorkflowRecipe(
        name="Rogue AP Containment",
        description=(
            "When a rogue AP is detected, search for it on the wired network. "
            "If found on a switch port, automatically disable that port to contain the threat. "
            "Sends Slack alerts and Syslog CEF events to SIEM for all detections."
        ),
        category=RecipeCategory.INCIDENT_RESPONSE,
        tags=["rogue", "security", "containment", "switch", "port", "syslog", "cef"],
        difficulty=RecipeDifficulty.INTERMEDIATE,
        nodes=[n1, n1b, n2, n3, n4, n5, n6, n7, n8, n9],
        edges=edges,
        placeholders=[
            RecipePlaceholder(
                node_id="slack-wired",
                field_path="notification_channel",
                label="Slack Webhook URL",
                description="Slack incoming webhook URL for security alerts",
                placeholder_type="url",
            ),
            RecipePlaceholder(
                node_id="syslog-wired",
                field_path="syslog_host",
                label="Syslog Server",
                description="Syslog/SIEM server hostname or IP for CEF security events",
                placeholder_type="string",
            ),
        ],
        built_in=True,
    )


def _build_ap_power_down() -> WorkflowRecipe:
    """AP Power-Down: cron → fetch data → script cross-references → for-each → disable radios."""
    n1 = _node(
        "trigger-1", "trigger", "Nightly Power-Down", 400, 80,
        {"trigger_type": "cron", "cron_expression": "0 22 * * 1-5", "timezone": "UTC"},
    )
    # Configuration variables (filled by placeholder wizard)
    n2 = _node(
        "var-config", "set_variable", "Configuration", 400, 220,
        {
            "variables": [
                {"name": "site_id", "expression": "PLACEHOLDER_SITE_ID"},
                {"name": "slack_url", "expression": "PLACEHOLDER_SLACK_URL"},
                {"name": "critical_aps", "expression": "PLACEHOLDER_CRITICAL_APS"},
            ],
        },
    )
    # Fetch AP stats (1 API call)
    n3 = _node(
        "api-stats", "mist_api_get", "Get AP Stats", 400, 380,
        {"api_endpoint": "/api/v1/sites/{{ site_id }}/stats/devices?type=ap&limit=1000"},
        save_as=[VariableBinding(name="ap_list", expression="{{ output.body }}")],
    )
    # Fetch RRM neighbors for band 5 (1 API call)
    n4 = _node(
        "api-neighbors", "mist_api_get", "Get RRM Neighbors", 400, 520,
        {"api_endpoint": "/api/v1/sites/{{ site_id }}/rrm/neighbors/band/5"},
        save_as=[VariableBinding(name="rrm_data", expression="{{ output.body }}")],
    )
    # Script node: cross-reference AP stats + RRM neighbors + critical list → safe-to-disable list
    n5 = _node(
        "script-analyze", "script", "Filter Safe to Disable", 400, 680,
        {
            "script_code": (
                "var apList = inputs.results.ap_list || [];\n"
                "var rrmData = inputs.results.rrm_data || {};\n"
                "var criticalStr = inputs.results.critical_aps || '';\n"
                "var criticalSet = new Set(criticalStr.split(',').map(function(s) { return s.trim(); }).filter(Boolean));\n"
                "\n"
                "// Build set of MACs with active clients\n"
                "var activeMacs = new Set();\n"
                "apList.forEach(function(ap) {\n"
                "  if (ap.num_clients > 0) activeMacs.add(ap.mac);\n"
                "});\n"
                "\n"
                "// Build set of protected MACs (neighbors of active APs)\n"
                "var protectedMacs = new Set();\n"
                "if (rrmData && rrmData.results) {\n"
                "  rrmData.results.forEach(function(entry) {\n"
                "    if (activeMacs.has(entry.mac)) {\n"
                "      entry.neighbors.forEach(function(n) { protectedMacs.add(n.mac); });\n"
                "    }\n"
                "  });\n"
                "}\n"
                "\n"
                "// Categorize every AP\n"
                "var toDisable = [], keptCritical = [], keptClients = [], keptNeighbors = [];\n"
                "apList.forEach(function(ap) {\n"
                "  var name = ap.name || ap.mac;\n"
                "  if (criticalSet.has(ap.mac)) {\n"
                "    keptCritical.push(name);\n"
                "  } else if (ap.num_clients > 0) {\n"
                "    keptClients.push(name + ' (' + ap.num_clients + ' clients)');\n"
                "  } else if (protectedMacs.has(ap.mac)) {\n"
                "    keptNeighbors.push(name);\n"
                "  } else {\n"
                "    toDisable.push({ id: ap.id, mac: ap.mac, name: name });\n"
                "  }\n"
                "});\n"
                "\n"
                "// Build summary\n"
                "var lines = [];\n"
                "lines.push('*Powered down (' + toDisable.length + '):* ' + (toDisable.length ? toDisable.map(function(a) { return a.name; }).join(', ') : 'none'));\n"
                "if (keptClients.length) lines.push('*Kept on (connected clients):* ' + keptClients.join(', '));\n"
                "if (keptNeighbors.length) lines.push('*Kept on (neighbor coverage):* ' + keptNeighbors.join(', '));\n"
                "if (keptCritical.length) lines.push('*Kept on (critical):* ' + keptCritical.join(', '));\n"
                "\n"
                "return {\n"
                "  to_disable: toDisable,\n"
                "  summary: lines.join('\\n')\n"
                "};\n"
            ),
        },
        save_as=[
            VariableBinding(name="safe_to_disable", expression="{{ output.to_disable }}"),
            VariableBinding(name="power_summary", expression="{{ output.summary }}"),
        ],
    )
    # Loop through safe-to-disable APs and disable radios
    n6 = _node(
        "loop-aps", "for_each", "Each Safe AP", 400, 860,
        {"loop_over": "{{ safe_to_disable }}", "loop_variable": "ap", "max_iterations": 500},
        output_ports=[
            NodePort(id="loop_body", label="Body", type="loop"),
            NodePort(id="done", label="Done", type="default"),
        ],
    )
    n7 = _node(
        "api-disable", "mist_api_put", "Disable AP Radios", 400, 1040,
        {
            "api_endpoint": "/api/v1/sites/{{ site_id }}/devices/{{ ap.id }}",
            "api_body": '{"radio_config": {"band_24": {"disabled": true}, "band_5": {"disabled": true}, "band_6": {"disabled": true}}}',
        },
    )
    # Summary notification (after loop)
    n8 = _node(
        "slack-summary", "slack", "Notify: Power-Down Complete", 600, 960,
        {
            "notification_channel": "{{ slack_url }}",
            "notification_template": "{{ power_summary }}",
            "slack_header": "Sustainability: AP Power-Down",
        },
    )

    edges = [
        _edge("e1", "trigger-1", "var-config"),
        _edge("e2", "var-config", "api-stats"),
        _edge("e3", "api-stats", "api-neighbors"),
        _edge("e6", "api-neighbors", "script-analyze"),
        _edge("e7", "script-analyze", "loop-aps"),
        _edge("e8", "loop-aps", "api-disable", "loop_body", "Body"),
        _edge("e9", "loop-aps", "slack-summary", "done", "Done"),
    ]

    return WorkflowRecipe(
        name="AP Power-Down (Sustainability)",
        description=(
            "Nightly scheduled workflow that disables AP radios during off-hours to save energy. "
            "Fetches AP stats and RRM neighbor data, then uses a JavaScript script to apply 3 guardrails: "
            "never powers off critical APs, APs with connected clients, or APs whose RRM neighbors have clients "
            "(coverage protection). Only APs safe to disable are powered down."
        ),
        category=RecipeCategory.MAINTENANCE,
        tags=["sustainability", "power", "energy", "green", "ap", "rrm", "script"],
        difficulty=RecipeDifficulty.INTERMEDIATE,
        nodes=[n1, n2, n3, n4, n5, n6, n7, n8],
        edges=edges,
        placeholders=[
            RecipePlaceholder(
                node_id="var-config", field_path="variables.0.expression",
                label="Site", description="Mist Site for AP power management",
                placeholder_type="site_id",
            ),
            RecipePlaceholder(
                node_id="var-config", field_path="variables.2.expression",
                label="Critical APs", description="Select APs that should never be powered down (e.g., lobby, entrance APs)",
                placeholder_type="ap_mac_list",
            ),
            RecipePlaceholder(
                node_id="var-config", field_path="variables.1.expression",
                label="Slack Webhook URL", description="Slack webhook for power-down notifications",
                placeholder_type="url",
            ),
        ],
        built_in=True,
    )


def _build_ap_power_up() -> WorkflowRecipe:
    """AP Power-Up: cron → get all APs → for-each → re-enable radios."""
    n1 = _node(
        "trigger-1", "trigger", "Morning Power-Up", 400, 80,
        {"trigger_type": "cron", "cron_expression": "0 6 * * 1-5", "timezone": "UTC"},
    )
    n1b = _node(
        "var-config", "set_variable", "Configuration", 400, 180,
        {
            "variables": [
                {"name": "site_id", "expression": "PLACEHOLDER_SITE_ID"},
                {"name": "slack_url", "expression": "PLACEHOLDER_SLACK_URL"},
            ],
        },
    )
    n2 = _node(
        "api-devices", "mist_api_get", "Get All APs", 400, 300,
        {"api_endpoint": "/api/v1/sites/{{ site_id }}/devices?type=ap&limit=1000"},
        save_as=[VariableBinding(name="ap_list", expression="{{ output.body }}")],
    )
    n3 = _node(
        "loop-aps", "for_each", "Each AP", 400, 420,
        {"loop_over": "{{ ap_list }}", "loop_variable": "ap", "max_iterations": 500},
        output_ports=[
            NodePort(id="loop_body", label="Body", type="loop"),
            NodePort(id="done", label="Done", type="default"),
        ],
    )
    n4 = _node(
        "api-enable", "mist_api_put", "Enable AP Radios", 400, 600,
        {
            "api_endpoint": "/api/v1/sites/{{ site_id }}/devices/{{ ap.id }}",
            "api_body": '{"radio_config": {"band_24": {"disabled": false}, "band_5": {"disabled": false}, "band_6": {"disabled": false}}}',
        },
    )
    n5 = _node(
        "slack-summary", "slack", "Notify: Power-Up Complete", 600, 520,
        {
            "notification_channel": "{{ slack_url }}",
            "notification_template": "All AP radios re-enabled at site {{ site_id }}. Good morning!",
            "slack_header": "Sustainability: AP Power-Up",
        },
    )

    edges = [
        _edge("e1", "trigger-1", "var-config"),
        _edge("e2", "var-config", "api-devices"),
        _edge("e4", "api-devices", "loop-aps"),
        _edge("e5", "loop-aps", "api-enable", "loop_body", "Body"),
        _edge("e6", "loop-aps", "slack-summary", "done", "Done"),
    ]

    return WorkflowRecipe(
        name="AP Power-Up (Sustainability)",
        description=(
            "Morning scheduled workflow that re-enables all AP radios at the start of business hours. "
            "Pair with 'AP Power-Down' recipe for full off-hours power management."
        ),
        category=RecipeCategory.MAINTENANCE,
        tags=["sustainability", "power", "energy", "green", "ap", "scheduled"],
        difficulty=RecipeDifficulty.BEGINNER,
        nodes=[n1, n1b, n2, n3, n4, n5],
        edges=edges,
        placeholders=[
            RecipePlaceholder(
                node_id="var-config", field_path="variables.0.expression",
                label="Site", description="Mist Site for AP power management",
                placeholder_type="site_id",
            ),
            RecipePlaceholder(
                node_id="var-config", field_path="variables.1.expression",
                label="Slack Webhook URL", description="Slack webhook for power-up notifications",
                placeholder_type="url",
            ),
        ],
        built_in=True,
    )


def _build_offhours_neighbor_enable() -> WorkflowRecipe:
    """Off-Hours Neighbor Enable: device-event → config → fetch data → script cross-ref → enable neighbors."""
    n1 = _node(
        "trigger-1", "trigger", "Client Activity Event", 400, 80,
        {"trigger_type": "webhook", "webhook_topic": "device-events"},
    )
    # Configuration variables
    n2 = _node(
        "var-config", "set_variable", "Configuration", 400, 220,
        {
            "variables": [
                {"name": "site_id", "expression": "PLACEHOLDER_SITE_ID"},
                {"name": "slack_url", "expression": "PLACEHOLDER_SLACK_URL"},
            ],
        },
    )
    # Get RRM neighbors for band 5 (full site, single API call)
    n3 = _node(
        "api-neighbors", "mist_api_get", "Get RRM Neighbors", 400, 380,
        {"api_endpoint": "/api/v1/sites/{{ site_id }}/rrm/neighbors/band/5"},
        save_as=[VariableBinding(name="rrm_data", expression="{{ output.body }}")],
    )
    # Get current AP stats
    n4 = _node(
        "api-stats", "mist_api_get", "Get AP Stats", 400, 520,
        {"api_endpoint": "/api/v1/sites/{{ site_id }}/stats/devices?type=ap&limit=1000"},
        save_as=[VariableBinding(name="all_aps", expression="{{ output.body }}")],
    )
    # Script: cross-reference RRM neighbors with AP stats to find disabled neighbors of the triggering AP
    n5 = _node(
        "script-analyze", "script", "Find Neighbors to Enable", 400, 680,
        {
            "script_code": (
                "var rrmData = inputs.results.rrm_data || {};\n"
                "var allAps = inputs.results.all_aps || [];\n"
                "var triggerMac = inputs.trigger.mac || inputs.trigger.device_mac || '';\n"
                "\n"
                "// Find the triggering AP's RRM neighbors\n"
                "var neighborMacs = [];\n"
                "if (rrmData.results) {\n"
                "  rrmData.results.forEach(function(entry) {\n"
                "    if (entry.mac === triggerMac) {\n"
                "      entry.neighbors.forEach(function(n) { neighborMacs.push(n.mac); });\n"
                "    }\n"
                "  });\n"
                "}\n"
                "\n"
                "// Build lookup of AP stats by MAC\n"
                "var apByMac = {};\n"
                "allAps.forEach(function(ap) { apByMac[ap.mac] = ap; });\n"
                "\n"
                "// Find neighbors that are idle (0 clients) and could benefit from re-enabling\n"
                "var toEnable = [];\n"
                "var alreadyActive = [];\n"
                "neighborMacs.forEach(function(mac) {\n"
                "  var ap = apByMac[mac];\n"
                "  if (!ap) return;\n"
                "  if (ap.num_clients === 0) {\n"
                "    toEnable.push({ id: ap.id, mac: ap.mac, name: ap.name || ap.mac });\n"
                "  } else {\n"
                "    alreadyActive.push(ap.name || ap.mac);\n"
                "  }\n"
                "});\n"
                "\n"
                "// Build summary\n"
                "var lines = [];\n"
                "lines.push('Triggered by client on AP: ' + triggerMac);\n"
                "lines.push('*Enabling (' + toEnable.length + '):* ' + (toEnable.length ? toEnable.map(function(a) { return a.name; }).join(', ') : 'none'));\n"
                "if (alreadyActive.length) lines.push('*Already active:* ' + alreadyActive.join(', '));\n"
                "\n"
                "return { to_enable: toEnable, summary: lines.join('\\n') };\n"
            ),
        },
        save_as=[
            VariableBinding(name="neighbors_to_enable", expression="{{ output.to_enable }}"),
            VariableBinding(name="neighbor_summary", expression="{{ output.summary }}"),
        ],
    )
    # Loop through neighbors to enable
    n6 = _node(
        "loop-neighbors", "for_each", "Each Neighbor", 400, 860,
        {"loop_over": "{{ neighbors_to_enable }}", "loop_variable": "neighbor", "max_iterations": 50},
        output_ports=[
            NodePort(id="loop_body", label="Body", type="loop"),
            NodePort(id="done", label="Done", type="default"),
        ],
    )
    n7 = _node(
        "api-enable", "mist_api_put", "Enable Neighbor Radios", 400, 1040,
        {
            "api_endpoint": "/api/v1/sites/{{ site_id }}/devices/{{ neighbor.id }}",
            "api_body": '{"radio_config": {"band_24": {"disabled": false}, "band_5": {"disabled": false}, "band_6": {"disabled": false}}}',
        },
    )
    # Summary notification
    n8 = _node(
        "slack-1", "slack", "Notify: Neighbors Enabled", 600, 960,
        {
            "notification_channel": "{{ slack_url }}",
            "notification_template": "{{ neighbor_summary }}",
            "slack_header": "Sustainability: Dynamic AP Enable",
        },
    )

    edges = [
        _edge("e1", "trigger-1", "var-config"),
        _edge("e2", "var-config", "api-neighbors"),
        _edge("e3", "api-neighbors", "api-stats"),
        _edge("e4", "api-stats", "script-analyze"),
        _edge("e5", "script-analyze", "loop-neighbors"),
        _edge("e6", "loop-neighbors", "api-enable", "loop_body", "Body"),
        _edge("e7", "loop-neighbors", "slack-1", "done", "Done"),
    ]

    return WorkflowRecipe(
        name="Off-Hours AP Neighbor Enable",
        description=(
            "When a client connects during off-hours (while APs are powered down), "
            "uses RRM neighbor data and AP stats to identify idle neighboring APs and re-enable their radios "
            "for seamless roaming coverage. A JavaScript script cross-references both datasets."
        ),
        category=RecipeCategory.MAINTENANCE,
        tags=["sustainability", "power", "energy", "rrm", "neighbor", "dynamic", "script"],
        difficulty=RecipeDifficulty.ADVANCED,
        nodes=[n1, n2, n3, n4, n5, n6, n7, n8],
        edges=edges,
        placeholders=[
            RecipePlaceholder(
                node_id="var-config", field_path="variables.0.expression",
                label="Site", description="Mist Site for AP power management",
                placeholder_type="site_id",
            ),
            RecipePlaceholder(
                node_id="var-config", field_path="variables.1.expression",
                label="Slack Webhook URL", description="Slack webhook for off-hours AP notifications",
                placeholder_type="url",
            ),
        ],
        built_in=True,
    )


def _build_config_impact_analysis() -> WorkflowRecipe:
    """Config Change Impact Analysis: audit → backup → delay → fetch health data → AI analysis → rollback proposal."""
    # 1. Trigger on audit webhook (config change)
    n1 = _node(
        "trigger-1", "trigger", "Config Change Detected", 400, 200,
        {"trigger_type": "webhook", "webhook_topic": "audits"},
    )
    # 2. Configuration — site_id comes from the webhook payload
    n2 = _node(
        "var-config", "set_variable", "Configuration", 400, 320,
        {
            "variables": [
                {"name": "site_id", "expression": "{{ trigger.site_id }}"},
                {"name": "slack_url", "expression": "PLACEHOLDER_SLACK_URL"},
            ],
        },
    )
    # 4. Wait 10 minutes for the change to take effect
    n3 = _node(
        "delay-1", "delay", "Wait 10 Minutes", 400, 440,
        {"delay_seconds": 600},
    )
    # 5. Search recent alarms
    n4 = _node(
        "api-alarms", "mist_api_get", "Search Recent Alarms", 400, 560,
        {"api_endpoint": "/api/v1/sites/{{ site_id }}/alarms/search?duration=15m&limit=50"},
        save_as=[VariableBinding(name="recent_alarms", expression="{{ output.body }}")],
    )
    # 6. Search config failure events
    n5 = _node(
        "api-events", "mist_api_get", "Search Config Failures", 400, 680,
        {"api_endpoint": "/api/v1/sites/{{ site_id }}/devices/events/search?type=AP_CONFIG_FAILED,SW_CONFIG_FAILED,GW_CONFIG_FAILED,AP_CONFIGURED,SW_CONFIGURED,GW_CONFIGURED&duration=15m&limit=50"},
        save_as=[VariableBinding(name="config_events", expression="{{ output.body }}")],
    )
    # 7. Get device stats
    n6 = _node(
        "api-stats", "mist_api_get", "Get Device Stats", 400, 800,
        {"api_endpoint": "/api/v1/sites/{{ site_id }}/stats/devices?type=ap&limit=200"},
        save_as=[VariableBinding(name="device_stats", expression="{{ output.body }}")],
    )
    # 8. Get site SLE metrics
    n7 = _node(
        "api-sle", "mist_api_get", "Get Site SLE", 400, 920,
        {"api_endpoint": "/api/v1/orgs/{{ trigger.org_id }}/insights/sites-sle?site_id={{ site_id }}&duration=1h"},
        save_as=[VariableBinding(name="sle_data", expression="{{ output.body }}")],
    )
    # 9. Get connected clients
    n8 = _node(
        "api-clients", "mist_api_get", "Get Connected Clients", 400, 1040,
        {"api_endpoint": "/api/v1/sites/{{ site_id }}/clients/search?limit=100"},
        save_as=[VariableBinding(name="client_list", expression="{{ output.body }}")],
    )
    # 10. AI Agent: comprehensive impact analysis
    n9 = _node(
        "agent-analyze", "ai_agent", "Analyze Config Impact", 400, 1200,
        {
            "agent_task": (
                "A configuration change was just made on the Mist network. After waiting 10 minutes, "
                "you need to assess whether this change caused any degradation.\n\n"
                "**Change details:**\n{{ trigger | tojson }}\n\n"
                "**Data collected after 10 minutes:**\n"
                "- Recent alarms: {{ recent_alarms | tojson }}\n"
                "- Config/device events: {{ config_events | tojson }}\n"
                "- Device stats (APs): {{ device_stats | tojson }}\n"
                "- Site SLE metrics: {{ sle_data | tojson }}\n"
                "- Connected clients: {{ client_list | tojson }}\n\n"
                "**Your tasks:**\n"
                "1. Use the backup search tool to find the most recent backup versions for this site\n"
                "2. Compare the latest two versions to see exactly which config fields changed\n"
                "3. Check SLE metrics for degradation (throughput, coverage, roaming, capacity)\n"
                "4. Check if any clients show poor signal, frequent disconnections, or roaming issues\n"
                "5. Check alarms and config failure events\n"
                "6. Correlate the specific changed config fields with any detected degradation\n"
                "7. Identify which specific setting most likely caused the issue (if any)\n\n"
                "Return a JSON object:\n"
                '{"has_impact": true/false, "summary": "detailed Slack-formatted analysis", '
                '"culprit_field": "the specific config field or null", "severity": "critical/warning/info"}'
            ),
            "agent_system_prompt": (
                "You are a senior network operations analyst specializing in Juniper Mist networks. "
                "Your job is to assess the impact of configuration changes on network health. "
                "Be thorough: check SLEs, client experience, device status, and alarms. "
                "Be specific: identify the exact config field that caused the issue. "
                "Be actionable: recommend whether to rollback and explain why. "
                "Format your summary for Slack (use *bold* for emphasis)."
            ),
            "max_iterations": 15,
        },
        save_as=[
            VariableBinding(name="analysis_result", expression="{{ output.result }}"),
        ],
    )
    # 11. Condition: did the AI find impact?
    n10 = _node(
        "cond-impact", "condition", "Impact Detected?", 400, 1400,
        {"branches": [{"condition": "{{ analysis_result.has_impact is defined and analysis_result.has_impact }}"}]},
        output_ports=[
            NodePort(id="branch_0", label="Impact", type="branch"),
            NodePort(id="else", label="OK", type="branch"),
        ],
    )
    # 12. Slack with interactive rollback button (wait_for_callback)
    n11 = _node(
        "wait-rollback", "wait_for_callback", "Propose Rollback", 250, 1600,
        {
            "notification_channel": "{{ slack_url }}",
            "notification_template": "{{ analysis_result.summary }}\n\nClick below to rollback the change.",
            "slack_header": "Config Impact Alert — Rollback?",
            "slack_actions": [
                {"text": "Approve Rollback", "action_id": "approve_rollback", "style": "danger"},
                {"text": "Dismiss", "action_id": "dismiss"},
            ],
            "timeout_seconds": 3600,
        },
        output_ports=[
            NodePort(id="approve_rollback", label="Rollback", type="callback"),
            NodePort(id="dismiss", label="Dismiss", type="callback"),
        ],
    )
    # 13. Restore backup (on rollback approval)
    n12 = _node(
        "restore-1", "restore_backup", "Restore Previous Config", 150, 1800,
        {"dry_run": False, "cascade": False},
    )
    # 14. Slack OK (no impact branch)
    n13 = _node(
        "slack-ok", "slack", "Confirm: Change OK", 550, 1600,
        {
            "notification_channel": "{{ slack_url }}",
            "notification_template": "{{ analysis_result.summary }}",
            "slack_header": "Config Change Validated",
        },
    )

    edges = [
        _edge("e1", "trigger-1", "var-config"),
        _edge("e2", "var-config", "delay-1"),
        _edge("e4", "delay-1", "api-alarms"),
        _edge("e5", "api-alarms", "api-events"),
        _edge("e6", "api-events", "api-stats"),
        _edge("e7", "api-stats", "api-sle"),
        _edge("e8", "api-sle", "api-clients"),
        _edge("e9", "api-clients", "agent-analyze"),
        _edge("e10", "agent-analyze", "cond-impact"),
        _edge("e11", "cond-impact", "wait-rollback", "branch_0", "Impact"),
        _edge("e12", "wait-rollback", "restore-1", "approve_rollback", "Rollback"),
        _edge("e13", "cond-impact", "slack-ok", "else", "OK"),
    ]

    return WorkflowRecipe(
        name="Config Change Impact Analysis",
        description=(
            "Self-driving network recipe: when a configuration change is detected via audit webhook, "
            "captures a backup, waits 10 minutes, then fetches SLE metrics, alarms, device stats, "
            "and client data. An AI Agent analyzes all data, compares backup versions to identify "
            "the exact changed fields, and correlates with any detected degradation. If impact is found, "
            "sends a Slack message with an interactive 'Approve Rollback' button that restores the previous config."
        ),
        category=RecipeCategory.INCIDENT_RESPONSE,
        tags=["config", "drift", "sle", "alarms", "rollback", "audit", "ai", "self-driving"],
        difficulty=RecipeDifficulty.ADVANCED,
        nodes=[n1, n2, n3, n4, n5, n6, n7, n8, n9, n10, n11, n12, n13],
        edges=edges,
        placeholders=[
            RecipePlaceholder(
                node_id="var-config", field_path="variables.1.expression",
                label="Slack Webhook URL", description="Slack webhook for impact alerts and rollback proposals",
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
    _build_rogue_ap_containment,
    _build_ap_power_down,
    _build_ap_power_up,
    _build_offhours_neighbor_enable,
    _build_config_impact_analysis,
]


async def seed_built_in_recipes() -> None:
    """Insert or update built-in seed recipes from code definitions."""
    created = 0
    updated = 0
    for builder in SEED_RECIPES:
        recipe = builder()
        existing = await WorkflowRecipe.find_one(
            WorkflowRecipe.name == recipe.name,
            WorkflowRecipe.built_in == True,  # noqa: E712
        )
        if existing:
            # Update existing recipe with latest code definition
            existing.description = recipe.description
            existing.category = recipe.category
            existing.tags = recipe.tags
            existing.difficulty = recipe.difficulty
            existing.nodes = recipe.nodes
            existing.edges = recipe.edges
            existing.placeholders = recipe.placeholders
            existing.workflow_type = recipe.workflow_type
            await existing.save()
            updated += 1
        else:
            await recipe.insert()
            logger.info("seed_recipe_created", name=recipe.name)
            created += 1

    if created or updated:
        logger.info("seed_recipes_done", created=created, updated=updated)
    else:
        logger.info("seed_recipes_skipped", reason="nothing to do")
