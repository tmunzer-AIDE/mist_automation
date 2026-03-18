# Workflow Guide

This guide covers creating, configuring, and running workflows in Mist Automation. Workflows are graph-based automation pipelines that execute actions in response to events, on a schedule, or on demand.

---

## Table of Contents

1. [Concepts](#concepts)
2. [Creating a Workflow](#creating-a-workflow)
3. [Node Types Reference](#node-types-reference)
4. [Variables and Templates](#variables-and-templates)
5. [Control Flow](#control-flow)
6. [Sub-Flows](#sub-flows)
7. [Error Handling](#error-handling)
8. [Simulation and Testing](#simulation-and-testing)
9. [Examples](#examples)

---

## Concepts

A workflow is a directed graph of **nodes** connected by **edges**. Each node performs an action (API call, notification, data processing, etc.) and passes its output to downstream nodes.

### Workflow Types

- **Standard**: Triggered by a webhook event, a cron schedule, or manually. Starts with a **Trigger** node.
- **Sub-flow**: A reusable workflow callable from other workflows. Starts with a **Sub-Flow Input** node and ends with one or more **Sub-Flow Output** nodes.

### Execution Flow

1. The trigger fires (webhook received, cron schedule hits, or manual run)
2. The executor traverses the graph from the entry node, following edges
3. Each node executes, stores its output, and the next node can reference it
4. Execution ends when all reachable nodes have been processed

---

## Creating a Workflow

1. Navigate to **Workflows** in the sidebar
2. Click **Create Workflow**
3. Choose **Standard** (trigger-based) or **Sub-flow** (reusable)
4. The editor opens with the entry node already placed on the canvas

### Adding Nodes

- Drag a node type from the **palette** on the left onto the canvas
- Or right-click the canvas and select a node type

### Connecting Nodes

- Drag from an **output port** (bottom of a node) to the **input port** (top of another node)
- An edge appears connecting the two nodes
- The execution follows these edges in order

### Configuring a Node

- Click a node on the canvas to open the **config panel** on the right
- Fill in the required fields (varies by node type)
- Use the **variable picker** (the `{ }` button) to insert references to upstream data

### Saving

- Click **Save** in the top bar
- The workflow is validated before saving (orphan nodes, missing connections, cycles)

---

## Node Types Reference

### Trigger

Entry point for standard workflows. Determines when the workflow runs.

| Field | Description |
|-------|-------------|
| `Trigger Type` | `webhook`, `cron`, or `manual` |
| `Webhook Topic` | Which Mist event to listen for: `alarms`, `audits`, `device-updowns`, `device-events` |
| `Event Type Filter` | Optional filter (e.g., `ap_offline` for alarms) |
| `Cron Expression` | 5-field cron (e.g., `0 */6 * * *` for every 6 hours) |
| `Condition` | Optional Jinja2 expression. If it evaluates to false, the workflow is skipped |
| `Skip If Running` | Prevents concurrent executions of the same workflow |

**Output**: The full webhook payload or manual trigger data. Available as `{{ trigger.topic }}`, `{{ trigger.events }}`, etc.

### Mist API (GET, POST, PUT, DELETE)

Calls the Juniper Mist Cloud API.

| Field | Description |
|-------|-------------|
| `API Endpoint` | Path like `/api/v1/sites/{{ site_id }}/devices` |
| `Query Parameters` | Key-value pairs appended as URL params |
| `Request Body` | JSON body (POST/PUT only) |

You can pick an endpoint from the **API Catalog** dropdown, which auto-fills path and query parameters.

**Output**:
```
{
  "status_code": 200,
  "body": { ...API response... }
}
```

Access the response body downstream with `{{ nodes.My_API_Call.body }}`.

### Webhook (HTTP POST)

Sends an HTTP POST to an external URL.

| Field | Description |
|-------|-------------|
| `Webhook URL` | Target URL |
| `Headers` | Custom HTTP headers (JSON) |
| `Body` | JSON payload |

All fields support template variables.

**Output**: `{ "status_code": integer, "response": string }`

### Slack

Sends a message to a Slack channel via incoming webhook.

| Field | Description |
|-------|-------------|
| `Webhook URL` | Slack incoming webhook URL |
| `Message Template` | Message body (supports Markdown) |
| `Header` | Bold header text at top of message |
| `Fields` | Key-value pairs displayed as a structured table |
| `Footer` | Footer text below the message |

All text fields support template variables. The message is formatted using Slack Block Kit for rich display.

**Output**: `{ "status": string, "response": string }`

### Email

Sends an email via the configured SMTP server.

| Field | Description |
|-------|-------------|
| `Recipients` | Comma-separated email addresses |
| `Subject` | Email subject line |
| `Message Template` | Email body |
| `HTML` | If checked, body is sent as HTML |

**Output**: `{ "status": string, "to": [emails], "subject": string }`

### Set Variable

Creates a named variable from an expression. Useful for extracting and transforming data between nodes.

| Field | Description |
|-------|-------------|
| `Variable Name` | Name to store as (e.g., `site_id`) |
| `Expression` | Jinja2 template (e.g., `{{ nodes.Search_Site.body.results[0].id }}`) |

The result is available downstream as `{{ site_id }}` (top-level) or `{{ results.site_id }}`.

If the expression evaluates to valid JSON, the value is parsed as a structured object. Otherwise it is stored as a string.

**Output**: `{ "variable_name": string, "value": any }`

### Condition

Branches execution based on boolean expressions. Each branch evaluates a Jinja2 expression; the first one that is true wins.

| Field | Description |
|-------|-------------|
| `Branches` | List of condition expressions (evaluated in order) |

A condition is true if its rendered value is NOT empty, "false", "0", "none", "null", or "undefined".

**Output ports**: `branch_0`, `branch_1`, ..., `else`

Connect downstream nodes to the appropriate port. Only the matching branch's edges are followed.

**Example conditions**:
```
{{ nodes.API_Call.status_code == 200 }}
{{ nodes.API_Call.body.results | length > 0 }}
{{ trigger.severity == "critical" }}
```

### For Each

Loops over a collection, executing the loop body once per item.

| Field | Description |
|-------|-------------|
| `Loop Over` | Path to the array (e.g., `{{ trigger.events }}`) |
| `Loop Variable` | Name for the current item (default: `item`) |
| `Max Iterations` | Safety limit (default: 100) |
| `Parallel` | Run iterations concurrently instead of sequentially |
| `Max Concurrent` | Concurrency limit when parallel is on (default: 5) |

**Output ports**:
- `Loop` -- connects to nodes inside the loop body
- `Done` -- connects to nodes that run after the loop completes

**During each iteration**, the current item is available as:
```
{{ item }}              -- the current item
{{ item.field_name }}   -- a field on the current item
{{ loop.index }}        -- 0-based iteration number
```

**After the loop completes**, the for_each node's output includes all collected results:
```json
{
  "iterations": 31,
  "loop_over": "nodes.List_Ports.body.results",
  "results": [
    { "status": "success", ... },
    { "status": "success", ... }
  ]
}
```

Access from downstream nodes (connected to the Done port) via `{{ nodes.For_Each_Ports.results }}`.

### Delay

Pauses execution for a specified duration.

| Field | Description |
|-------|-------------|
| `Delay (seconds)` | Number of seconds to wait |

Skipped during dry-run simulation.

### Device Utility

Executes diagnostic commands on Mist-managed devices (APs, switches, firewalls, routers).

| Field | Description |
|-------|-------------|
| `Device Type` | `ap`, `ex` (switch), `srx` (firewall), `ssr` (router) |
| `Function` | Command to run (changes based on device type) |
| `Site ID` | Mist site UUID |
| `Device ID` | Device UUID or MAC-based ID |
| `Parameters` | Function-specific params (e.g., `port_ids`, `host`, `count`) |

**Available functions by device type**:

| Device | Functions |
|--------|-----------|
| **AP** | ping, traceroute, retrieveArpTable |
| **EX (Switch)** | ping, bouncePort, cableTest, retrieveArpTable, retrieveMacTable, clearMacTable, clearBpduError, clearDot1xSessions, retrieveBgpSummary, retrieveDhcpLeases, clearHitCount, monitorTraffic, topCommand |
| **SRX (Firewall)** | ping, bouncePort, retrieveArpTable, retrieveBgpSummary, retrieveDhcpLeases, retrieveOspfSummary, retrieveRoutes, retrieveSessions, clearSessions, monitorTraffic, topCommand |
| **SSR (Router)** | ping, bouncePort, retrieveArpTable, retrieveBgpSummary, retrieveDhcpLeases, retrieveOspfSummary, retrieveRoutes, showServicePath, retrieveSessions, clearSessions |

**Output**:
```json
{
  "status": "success",
  "device_type": "ex",
  "function": "bouncePort",
  "data": [ ...device response... ]
}
```

Note: parameters ending in `_ids` (like `port_ids`) accept comma-separated values and are automatically split into a list. For example, `ge-0/0/0, ge-0/0/1` becomes `["ge-0/0/0", "ge-0/0/1"]`.

### Data Transform

Extracts and filters fields from an array of objects, producing a structured table.

| Field | Description |
|-------|-------------|
| `Source` | Path to the array (e.g., `nodes.API_Call.body.results`) |
| `Fields` | List of `{ path, label }` pairs to extract |
| `Filter` | Optional Jinja2 expression to filter rows |

Field paths support Jinja2 filters: `device.created_at | datetimeformat`.

**Output**:
```json
{
  "rows": [{ "name": "AP-01", "status": "connected" }],
  "columns": [{ "key": "name", "label": "Name" }, { "key": "status", "label": "Status" }],
  "row_count": 42
}
```

### Format Report

Formats structured data (from Data Transform or any array) into a readable table.

| Field | Description |
|-------|-------------|
| `Data Source` | Path to rows array |
| `Columns Source` | Optional path to columns definition |
| `Format` | `markdown`, `csv`, `slack`, or `text` |
| `Title` | Report title |
| `Footer` | Footer text |

When format is `slack`, the output includes `slack_blocks` that downstream Slack nodes automatically use for rich formatting.

**Output**: `{ "report": string, "format": string, "row_count": integer }`

---

## Variables and Templates

All text fields in node configs support **Jinja2 template syntax**. Variables are enclosed in `{{ }}`.

### Variable Sources

| Prefix | Source | Example |
|--------|--------|---------|
| `trigger.*` | Webhook payload or manual input | `{{ trigger.topic }}`, `{{ trigger.events[0].type }}` |
| `nodes.*` | Output of a specific upstream node | `{{ nodes.My_API_Call.body.results }}` |
| `item` | Current item in a for_each loop | `{{ item.mac }}`, `{{ item.port_id }}` |
| `loop.index` | Current iteration index (0-based) | `{{ loop.index }}` |
| *(top-level)* | Variables from set_variable / save_as | `{{ site_id }}`, `{{ device_count }}` |
| `now` | Current UTC datetime | `{{ now_iso }}`, `{{ now_timestamp }}` |

### Node Name Sanitization

Node names are sanitized when used as variable keys. All characters that are not letters, numbers, or underscores are replaced with underscores:

| Node Name | Variable Key |
|-----------|-------------|
| `For Each Events` | `For_Each_Events` |
| `Sub-Flow Call` | `Sub_Flow_Call` |
| `Mist API GET` | `Mist_API_GET` |

The variable picker automatically generates the correct sanitized path when you click a variable.

### Jinja2 Filters

You can pipe values through filters for transformation:

```
{{ trigger.timestamp | datetimeformat }}
{{ nodes.API_Call.body.results | length }}
{{ nodes.API_Call.body | tojson }}
{{ item.mac | upper }}
```

### Save Output As Variables

Every action node has a **Save Output As Variables** section. This lets you extract parts of a node's output into named variables for later use.

- Leave the expression empty to save the entire output
- Use `{{ output.field }}` to extract a specific field (the `output` variable refers to the current node's result)

Available output fields depend on the node type and are shown as a hint above the Save As section.

---

## Control Flow

### Condition Branching

The **Condition** node evaluates expressions in order and follows the first matching branch:

```
Branch 0 (If):      {{ nodes.API_Call.status_code == 200 }}
Branch 1 (Else If):  {{ nodes.API_Call.status_code == 404 }}
Else:                (everything else)
```

Connect downstream nodes to the matching output port (`branch_0`, `branch_1`, `else`).

### For Each Loops

The **For Each** node iterates over an array. Nodes connected to the `Loop` port execute once per item. Nodes connected to the `Done` port execute after all iterations complete.

**Sequential mode** (default): Items are processed one at a time. If an iteration fails and `continue_on_error` is off, the loop stops.

**Parallel mode**: Items are processed concurrently (up to `max_concurrent` at a time). Each iteration runs in an isolated context, so there are no conflicts between iterations. Results are collected in order.

After the loop, the `results` array on the for_each output contains the last body node's output from each iteration.

---

## Sub-Flows

Sub-flows are reusable workflows that can be called from other workflows, like functions.

### Creating a Sub-Flow

1. Create a new workflow and set its type to **Sub-flow**
2. The editor places a **Sub-Flow Input** node as the entry point
3. Click the Sub-Flow Input node to define **input parameters** (name, type, required, description)
4. Build your logic graph as normal
5. Add a **Sub-Flow Output** node at the end
6. Click the Sub-Flow Output node to define **output parameters** and map each one to an expression

### Defining Input Parameters

On the **Sub-Flow Input** node:
1. Click **Add Parameter**
2. Set the parameter name (e.g., `site_name`), type (`string`), and whether it is required
3. Repeat for each input

These parameters become available in the sub-flow as `{{ trigger.site_name }}`, `{{ trigger.parameter_name }}`, etc.

### Defining Output Parameters

On the **Sub-Flow Output** node:
1. Click **Add Output**
2. Set the output name (e.g., `site_id`) and type
3. Map each output to an expression (e.g., `{{ nodes.Search_Site.body.results[0].id }}`)
4. Use the variable picker to browse available upstream data

### Calling a Sub-Flow

In a standard workflow (or another sub-flow):
1. Add an **Invoke Sub-Flow** node
2. Select the target sub-flow from the dropdown
3. Map each input parameter to a value or expression
4. The sub-flow executes and returns its outputs

The invoke node's output looks like:
```json
{
  "child_execution_id": "abc123",
  "status": "success",
  "outputs": {
    "site_id": "053538fb-..."
  }
}
```

Access sub-flow outputs downstream via `{{ nodes.My_Subflow.outputs.site_id }}`.

### Recursion Limit

Sub-flows can call other sub-flows, up to a maximum depth of 5. Circular references (A calls B, B calls A) are detected and blocked at save time.

---

## Error Handling

### Per-Node Retry

Most action nodes support automatic retries:

| Field | Default | Description |
|-------|---------|-------------|
| `Max Retries` | 3 | Number of retry attempts after the initial failure |
| `Retry Delay (s)` | 5 | Seconds to wait between retries |

Total attempts = 1 (initial) + Max Retries.

### Continue on Error

When **Continue on Error** is checked, the workflow continues executing downstream nodes even if this node fails. When unchecked (default), a failure stops the entire workflow.

For **For Each** nodes, this controls whether the loop continues to the next iteration after a failure.

### Execution Statuses

| Status | Meaning |
|--------|---------|
| `success` | All nodes completed successfully |
| `partial` | Some nodes succeeded, some failed |
| `failed` | A required node failed and stopped execution |
| `filtered` | Trigger condition evaluated to false; no nodes executed |
| `timeout` | Execution exceeded the workflow timeout (default: 300s) |
| `cancelled` | Manually cancelled by a user |

---

## Simulation and Testing

The **Simulation Panel** at the bottom of the workflow editor lets you test workflows without affecting production.

### Running a Simulation

1. Expand the simulation panel (click the bar at the bottom)
2. Enter a test payload in the **Payload** tab:
   - For standard workflows: paste a JSON webhook payload, or select a recent webhook event from the list
   - For sub-flows: fill in the structured input parameter form
3. Toggle **Dry Run** to mock external API calls (no real requests are sent)
4. Click **Simulate**

### Reviewing Results

After simulation completes:
- The **Results** tab shows step-by-step execution with input/output for each node
- Use the forward/back buttons to step through the execution
- Each node on the canvas is highlighted with its status (green = success, red = failed)
- The **Logs** tab shows the full execution log

### Dry Run vs Live Simulation

- **Dry Run ON**: API calls return mock data based on the OpenAPI spec. Device utilities and webhooks are skipped. Safe to run repeatedly.
- **Dry Run OFF**: Real API calls are made. Device commands are executed. Use with caution.

---

## Examples

### Example 1: Alert on AP Offline

Sends a Slack notification when an AP goes offline.

**Workflow**:
```
Trigger (webhook: alarms, filter: ap_offline)
  |
  v
Slack (webhook URL, message: "AP {{ trigger.device_name }} went offline at {{ trigger.timestamp | datetimeformat }}")
```

### Example 2: Bounce Switch Ports in Bulk

Finds all active switch ports and bounces them.

**Workflow**:
```
Trigger (manual)
  |
  v
Set Variable (site_id = "your-site-uuid")
  |
  v
Mist API GET (/api/v1/sites/{{ site_id }}/stats/ports/search?device_type=switch&up=true)
  |
  v
For Each (loop_over: {{ nodes.Mist_API_GET.body.results }}, parallel: true, max_concurrent: 5)
  |--- Loop Body:
  |      Device Utility (ex, bouncePort, site_id: {{ site_id }}, device_id: 00000000-0000-0000-1000-{{ item.mac }}, port_ids: {{ item.port_id }})
  |
  |--- Done:
         Slack ("Bounced {{ nodes.For_Each.iterations }} ports. Results: {{ nodes.For_Each.results | length }} completed.")
```

### Example 3: Reusable "Find Site by Name" Sub-Flow

**Sub-flow** (`Find site_id by site_name`):
```
Sub-Flow Input (parameters: site_name: string, required)
  |
  v
Mist API GET (/api/v1/orgs/{org_id}/sites/search?name={{ trigger.site_name }})
  |
  v
Sub-Flow Output (site_id = {{ nodes.Mist_API_GET.body.results[0].id }})
```

**Calling workflow**:
```
Trigger (manual)
  |
  v
Invoke Sub-Flow (target: "Find site_id by site_name", site_name: "NYC Office")
  |
  v
Mist API GET (/api/v1/sites/{{ nodes.Invoke_Sub_Flow.outputs.site_id }}/devices)
  |
  v
Slack ("Found {{ nodes.Mist_API_GET.body | length }} devices at NYC Office")
```

### Example 4: Conditional Alert Routing

Routes alerts to different channels based on severity.

**Workflow**:
```
Trigger (webhook: alarms)
  |
  v
Condition
  |--- Branch 0 (If: {{ trigger.severity == "critical" }}):
  |      PagerDuty (severity: critical, summary: "CRITICAL: {{ trigger.device_name }}")
  |
  |--- Branch 1 (Else If: {{ trigger.severity == "warning" }}):
  |      Slack (#warnings, "Warning: {{ trigger.device_name }} - {{ trigger.type }}")
  |
  |--- Else:
         Email (ops@company.com, "Info alert: {{ trigger.type }}")
```
