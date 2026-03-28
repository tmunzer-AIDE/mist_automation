"""
Purpose-built prompt constructors for each LLM feature.

Each function returns a list of LLMMessage dicts (role + content) and is pure
(no I/O), making them easy to test in isolation.
"""

import json


def _sanitize_for_prompt(value: str, max_len: int = 200) -> str:
    """Sanitize a user-sourced value for safe interpolation into an LLM prompt.

    Escapes markdown control sequences, strips potential prompt injection
    markers, and truncates excessively long values.
    """
    if not value:
        return value
    # Strip characters that could break prompt structure
    sanitized = value.replace("```", "").replace("---", "").replace("***", "")
    if len(sanitized) > max_len:
        sanitized = sanitized[:max_len] + "..."
    return sanitized


def build_backup_summary_prompt(
    diff_entries: list[dict],
    object_type: str,
    object_name: str | None,
    old_version: int,
    new_version: int,
    event_type: str,
    changed_fields: list[str],
    version_id_1: str = "",
    version_id_2: str = "",
    object_id: str = "",
) -> list[dict[str, str]]:
    """Build prompt for backup change summarization with MCP tool context."""
    context_lines = ""
    if object_id:
        context_lines = (
            "\n\nYou have tools to fetch additional backup data if needed.\n"
            f"- Object ID (Mist UUID): {object_id}\n"
            f"- Older version document ID: {version_id_1} (v{old_version})\n"
            f"- Newer version document ID: {version_id_2} (v{new_version})\n"
            "If you need more context (other versions, full config, dependencies), "
            "use the backup tool."
        )

    system = (
        "You are a network configuration analyst for Juniper Mist. "
        "Summarize configuration changes concisely and explain their operational impact. "
        "Focus on what changed, why it might matter, and any risks. "
        "Use short paragraphs. Do not repeat the raw diff data — interpret it."
        + context_lines
    )

    # Truncate diff for very large changes to avoid token overflow
    diff_text = json.dumps(diff_entries[:100], indent=2, default=str)
    if len(diff_entries) > 100:
        diff_text += f"\n... and {len(diff_entries) - 100} more changes"

    name_display = _sanitize_for_prompt(object_name or "(unnamed)")
    safe_type = _sanitize_for_prompt(object_type)
    safe_event = _sanitize_for_prompt(event_type)
    safe_fields = ", ".join(_sanitize_for_prompt(f) for f in changed_fields) if changed_fields else "N/A"
    user = (
        f"A Mist `{safe_type}` object named `{name_display}` was changed "
        f"(v{old_version} → v{new_version}, event: `{safe_event}`).\n\n"
        f"**Changed fields**: {safe_fields}\n\n"
        f"**Detailed diff**:\n```json\n{diff_text}\n```\n\n"
        "Please summarize what was changed and explain the operational impact."
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_workflow_editor_context() -> str:
    """Return workflow variable syntax reference for the global chat system prompt.

    Appended when the user is on the Workflow Editor page so the LLM gives
    correct advice about Jinja2 variable paths.
    """
    return (
        "\n\nWorkflow variable syntax — ALWAYS use this when helping with workflow configuration:\n"
        "\n## Standard webhooks (trigger_type: webhook)\n"
        "{{ trigger }} is a SINGLE pre-processed event object (NOT the raw Mist payload array).\n"
        "Common fields: {{ trigger.org_id }}, {{ trigger.site_id }}, {{ trigger.type }}, "
        "{{ trigger.device_name }}, {{ trigger.mac }}, {{ trigger.timestamp }}.\n"
        "Field availability depends on webhook_topic:\n"
        "- alarms: type, severity, reason, device_name, device_type\n"
        "- audits: admin_name, message, src_ip\n"
        "- device-events: type (AP_CONFIGURED, SW_CONFIGURED, etc.), device_name, mac, text, reason\n"
        "- device-updowns: type (AP_CONNECTED, AP_DISCONNECTED, etc.), device_name, mac\n"
        "- client-events: type, mac, ssid, ap\n"
        "\n## Aggregated webhooks (trigger_type: aggregated_webhook)\n"
        "Events are buffered over a time window, then fired together.\n"
        "- {{ trigger.aggregation.event_count }} — number of events in window\n"
        "- {{ trigger.aggregation.site_id }}, {{ trigger.aggregation.site_name }} — from first event\n"
        "- {{ trigger.aggregation.window_seconds }} — window duration\n"
        "- {{ trigger.events }} — array of all buffered events (use with for_each node)\n"
        "- {{ trigger.events[0].device_name }} — individual event access\n"
        "- {{ trigger.first_event.* }}, {{ trigger.last_event.* }} — shortcuts to first/last\n"
        "Each event has: event_type, device_name, device_mac, site_name, org_name, payload (full original data).\n"
        "Opening/closing pairs: AP_DISCONNECTED→AP_CONNECTED, SW_DISCONNECTED→SW_CONNECTED, etc. "
        "Closing events remove devices from the buffer.\n"
        "\n## Node outputs\n"
        "- {{ nodes.NodeName.body.field }} — Mist API response body\n"
        "- {{ nodes.NodeName.status_code }} — HTTP status code\n"
        "- {{ results.var_name }} — variables set by set_variable nodes\n"
        "\nNode names with spaces use underscores: \"Check Status\" → {{ nodes.Check_Status.body }}.\n"
        "ALWAYS use {{ }} Jinja2 syntax. NEVER use payload.* — it does not exist."
    )


_KNOWN_ROLES = {"admin", "automation", "backup", "post_deployment", "impact_analysis"}


def build_global_chat_system_prompt(user_roles: list[str]) -> str:
    """Build system prompt for the global chat with MCP tools."""
    # Only allow known role names to prevent prompt injection via custom roles
    safe_roles = [r for r in user_roles if r in _KNOWN_ROLES] if user_roles else []
    roles = ", ".join(safe_roles) if safe_roles else "none"
    return (
        "You are an assistant for the Mist Automation & Backup platform. "
        "You can query backups, workflows, executions, webhook events, reports, and system stats. "
        f"The current user has roles: {roles}. "
        "Use the available tools to look up data before answering. "
        "Be concise and precise. Format data as markdown tables when appropriate. "
        "Do not guess — if you are unsure, use a tool to verify. "
        "To restore a backup, use backup(action='restore', version_id=...) — "
        "this automatically shows the user a diff and asks for confirmation before restoring."
    )


# ── Workflow Creation Assistant ───────────────────────────────────────────────

_WORKFLOW_SYSTEM_PROMPT = """\
You are a workflow automation assistant for Juniper Mist network management.
You generate workflow graphs as JSON from natural language descriptions.

A workflow is a directed graph of **nodes** connected by **edges**.

## Node types

**Trigger** (exactly one per workflow, entry point):
- type: "trigger"
- config: {trigger_type: "webhook"|"cron"|"manual", webhook_topic: "alarms"|"audits"|"device-events"|"device-updowns"|"client-events"|"occupancy-alerts", event_type_filter: "specific_event_type"}

IMPORTANT: The app preprocesses Mist webhooks. Mist sends {topic, events: [...]}, but the app
splits the array and passes a SINGLE enriched event as the trigger data. So `{{ trigger }}`
is one event object, NOT the full webhook. Access fields directly: `{{ trigger.type }}`,
`{{ trigger.device_name }}`, `{{ trigger.site_id }}`.

Webhook payload schemas per topic (these are the fields available on `{{ trigger }}`):

**alarms** — Device health alerts (AP/switch/gateway offline, online, restarted, etc.):
  fields: topic, type (e.g. "ap_offline","switch_offline","gateway_offline","ap_online"), timestamp, org_id, site_id, device_name, device_type ("ap"|"switch"|"gateway"), mac, severity ("warn"|"critical"), reason

**audits** — Admin actions on the Mist dashboard (logins, configuration changes, user management). Use this for anything related to admin/user activity:
  fields: topic, type, admin_name, message, org_id, site_id, timestamp, src_ip, audit_id

**device-updowns** — Network device connectivity state changes (connected/disconnected):
  fields: topic, type ("AP_CONNECTED","AP_DISCONNECTED","SW_CONNECTED","SW_DISCONNECTED","GW_CONNECTED","GW_DISCONNECTED"), device_name, device_type, mac, org_id, site_id, timestamp

**device-events** — Device lifecycle events (configured, config changed, firmware upgraded, rebooted):
  fields: topic, type (e.g. "AP_CONFIGURED","SW_CONFIGURED","GW_CONFIGURED","AP_CONFIG_CHANGED_BY_USER","AP_RESTARTED"), device_name, device_type, mac, org_id, site_id, timestamp, text, reason

**client-events** — WiFi client activity (wireless clients connecting/disconnecting to APs, NOT admin logins):
  fields: topic, type, mac, ssid, ap, org_id, site_id, timestamp

**occupancy-alerts** — Zone occupancy threshold alerts (people counting):
  fields: topic, type, org_id, site_id, map_id, zone_id, zone_name, timestamp, current_occupancy, occupancy_limit

**Mist API** (call the Mist REST API):
- type: "mist_api_get"|"mist_api_post"|"mist_api_put"|"mist_api_delete"
- config: {api_endpoint: "/api/v1/...", api_params: {}}

**Condition** (branch logic):
- type: "condition"
- config: {branches: [{condition: "{{ jinja2_expression }}"}]}
- output_ports: [{id:"branch_0",label:"If",type:"branch"},{id:"else",label:"Else",type:"branch"}]

**Set Variable** (store a computed value):
- type: "set_variable"
- config: {variable_name: "my_var", variable_expression: "{{ expression }}"}

**Delay** (wait):
- type: "delay"
- config: {delay_seconds: 10}

**For Each** (iterate over a collection):
- type: "for_each"
- config: {loop_over: "nodes.MyNode.body.results", loop_variable: "item", max_iterations: 100}
- output_ports: [{id:"loop_body",label:"Loop",type:"loop_body"},{id:"done",label:"Done",type:"loop_done"}]

**Notifications** (all use notification_channel + notification_template):
- type: "slack" — config: {notification_channel: "https://hooks.slack.com/services/...", notification_template: "{{ message with Jinja2 }}", slack_header: "Alert Title", slack_fields: [{label: "Field", value: "{{ var }}"}], slack_footer: "Footer text"}
- type: "email" — config: {notification_channel: "user@example.com", notification_template: "Email body", email_subject: "Subject line"}
- type: "pagerduty" — config: {notification_channel: "pagerduty_integration_key", notification_template: "Alert summary", severity: "critical"|"error"|"warning"|"info"}
- type: "webhook" — config: {webhook_url: "https://...", webhook_body: {}}
- type: "servicenow" — config: {servicenow_method: "POST", servicenow_table: "incident", servicenow_body: {}}

**Data processing**:
- type: "data_transform" — config: {source: "nodes.X.body", fields: [{path: "...", label: "..."}]}
- type: "format_report" — config: {data_source: "", format: "markdown"|"csv"|"slack"|"text", title: ""}
- type: "device_utils" — config: {device_util_type: "ping"|"traceroute"|"arp"|"cable_test", device_id: "{{ ... }}", site_id: "{{ ... }}"}

## Edges

Each edge connects a source node's output port to a target node's input:
- source_port_id: "default" for most nodes, "branch_0"/"else" for conditions, "loop_body"/"done" for for_each
- target_port_id: always "input"

## Variable syntax

Use Jinja2 templates: {{ trigger.type }}, {{ trigger.device_name }}, {{ nodes.NodeName.body.field }}, {{ results.my_var }}
- trigger.* — fields from the single webhook event (see schemas above)
- nodes.NodeName.status_code / nodes.NodeName.body.* — output from Mist API nodes
- results.my_var — variables set by set_variable nodes

## Output format (JSON)

```json
{
  "name": "Workflow Name",
  "description": "Brief description",
  "nodes": [
    {"id": "uuid", "type": "trigger", "name": "Trigger", "position": {"x": 0, "y": 0}, "config": {...}, "output_ports": [{"id": "default", "label": "", "type": "default"}], "enabled": true, "continue_on_error": false, "max_retries": 0, "retry_delay": 0},
    ...more nodes
  ],
  "edges": [
    {"id": "uuid", "source_node_id": "...", "source_port_id": "default", "target_node_id": "...", "target_port_id": "input", "label": ""},
    ...more edges
  ]
}
```

Rules:
- Every node needs a unique id (use short IDs like "n1", "n2", etc.)
- Every edge needs a unique id (use "e1", "e2", etc.)
- Every node MUST have output_ports. Use [{id:"default",label:"",type:"default"}] unless specified otherwise (condition uses branch_0/else, for_each uses loop_body/done).
- Position nodes top-to-bottom: trigger at y=0, next row at y=150, etc. Space horizontally at x=0, x=300 for branches.
- Standard workflows MUST have exactly one trigger node.
- All non-trigger nodes must be reachable from the trigger via edges.
- No cycles (except inside for_each loops).
- Return ONLY the JSON object, no markdown fences, no explanation outside the JSON.
"""


def build_category_selection_prompt(
    user_request: str,
    categories: list[str],
) -> list[dict[str, str]]:
    """Build prompt for pass 1: select relevant API categories.

    Returns a short prompt asking the LLM to pick which Mist API categories
    are relevant to the user's workflow description.
    """
    cat_list = "\n".join(f"- {c}" for c in categories)
    system = (
        "You are a Juniper Mist API expert. "
        "Given a workflow description and a list of Mist API categories, "
        "return ONLY a JSON array of the category names that are relevant. "
        'Example: ["Sites", "WLANs", "Devices"]\n'
        "Return between 1 and 8 categories. No explanation, just the JSON array.\n\n"
        f"Available API categories:\n{cat_list}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_request},
    ]


def build_workflow_assist_prompt(
    user_request: str,
    api_endpoints: str,
) -> list[dict[str, str]]:
    """Build prompt for pass 2: generate workflow with full endpoint details.

    API endpoints go in the system message (reference material),
    user request stays in the user message (intent).
    """
    system = f"{_WORKFLOW_SYSTEM_PROMPT}\n\n## Available Mist API endpoints\n\n{api_endpoints}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_request},
    ]


def build_field_assist_prompt(
    node_type: str,
    field_name: str,
    description: str,
    upstream_variables: dict | None = None,
) -> list[dict[str, str]]:
    """Build prompt for helping fill a single workflow node field."""
    system = (
        "You are a Juniper Mist workflow field assistant. "
        "Given a node type, field name, and the user's intent, "
        "return the exact value for that field. "
        "Use Jinja2 template syntax ({{ ... }}) for dynamic values. "
        "Return ONLY the field value, no explanation."
    )

    variables_text = ""
    if upstream_variables:
        variables_text = f"\n\nAvailable upstream variables:\n```json\n{json.dumps(upstream_variables, indent=2, default=str)[:2000]}\n```"

    user = (
        f"Node type: {_sanitize_for_prompt(node_type, max_len=50)}\n"
        f"Field: {_sanitize_for_prompt(field_name, max_len=100)}\n"
        f"What I want: {_sanitize_for_prompt(description, max_len=2000)}"
        f"{variables_text}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ── Workflow Debugging ────────────────────────────────────────────────────────


def build_debug_prompt(
    execution_summary: dict,
    failed_nodes: list[dict],
    logs: list[str],
) -> list[dict[str, str]]:
    """Build prompt for explaining why a workflow execution failed."""
    system = (
        "You are a Juniper Mist workflow debugging assistant. "
        "Given a workflow execution summary with failed nodes, their errors, "
        "inputs, and logs, explain WHY the failure happened and suggest fixes. "
        "Be specific: reference node names, variable paths, and error messages. "
        "Keep it concise — use bullet points for fixes."
    )

    nodes_text = json.dumps(failed_nodes[:10], indent=2, default=str)
    logs_text = "\n".join(logs[-30:]) if logs else "(no logs)"

    user = (
        f"**Execution**: status={execution_summary.get('status')}, "
        f"duration={execution_summary.get('duration_ms')}ms, "
        f"{execution_summary.get('nodes_succeeded', 0)} succeeded / "
        f"{execution_summary.get('nodes_failed', 0)} failed\n\n"
        f"**Failed nodes**:\n```json\n{nodes_text}\n```\n\n"
        f"**Logs** (last 30 lines):\n```\n{logs_text}\n```\n\n"
        "Explain why this failed and how to fix it."
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ── Webhook Event Summarization ───────────────────────────────────────────────


def build_webhook_summary_prompt(
    events_summary: str,
    time_range_hours: int,
) -> list[dict[str, str]]:
    """Build prompt for summarizing recent webhook events."""
    system = (
        "You are a Juniper Mist network operations analyst. "
        "Summarize the recent webhook events: highlight patterns, anomalies, "
        "devices with repeated issues, and anything that needs attention. "
        "Be concise — use bullet points grouped by topic."
    )

    user = (
        f"Summarize these Mist webhook events from the last {time_range_hours} hours:\n\n"
        f"{events_summary}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_dashboard_summary_prompt(context: str) -> list[dict[str, str]]:
    """Build prompt for dashboard state summarization."""
    system = (
        "You are a Juniper Mist network operations analyst. "
        "Summarize the current system state: highlight failures, anomalies, "
        "active incidents, and anything that needs attention. "
        "Be concise — use bullet points grouped by priority."
    )
    user = f"Summarize this system dashboard state:\n\n{context}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_audit_log_summary_prompt(context: str, filters: dict) -> list[dict[str, str]]:
    """Build prompt for audit log summarization."""
    filter_desc = ", ".join(f"{k}={v}" for k, v in filters.items() if v) or "last 24 hours"
    system = (
        "You are a security and operations analyst for a Juniper Mist automation platform. "
        "Analyze these audit logs. Identify patterns, anomalies, security concerns, "
        "suspicious activity, and notable operational events. "
        "Be concise — use bullet points grouped by category."
    )
    user = f"Analyze these audit logs (filter: {filter_desc}):\n\n{context}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_system_log_summary_prompt(context: str, filters: dict) -> list[dict[str, str]]:
    """Build prompt for system log summarization."""
    filter_desc = ", ".join(f"{k}={v}" for k, v in filters.items() if v) or "all recent logs"
    system = (
        "You are a systems engineer analyzing application logs for a Juniper Mist automation platform. "
        "Identify error patterns, recurring issues, performance concerns, and anything requiring attention. "
        "Be concise — use bullet points grouped by severity."
    )
    user = f"Analyze these system logs (filter: {filter_desc}):\n\n{context}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_backup_list_summary_prompt(context: str, filters: dict) -> list[dict[str, str]]:
    """Build prompt for backup health and change activity summarization."""
    filter_desc = ", ".join(f"{k}={v}" for k, v in filters.items() if v) or "all objects"
    system = (
        "You are a network configuration analyst for a Juniper Mist automation platform. "
        "Analyze backup health and change activity. Identify objects with stale backups, "
        "repeated job failures, unusual change patterns, and overall backup coverage gaps. "
        "Be concise — use bullet points grouped by concern."
    )
    user = f"Analyze this backup health data (filter: {filter_desc}):\n\n{context}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
