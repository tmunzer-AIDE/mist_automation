# Workflow Editor (Automation Module)

Part of mist_automation — see root `CLAUDE.md` for global architecture and conventions, `backend/CLAUDE.md` for backend patterns.

Most complex feature, spanning both backend and frontend.

## Backend (`app/modules/automation/`)

- **Graph data model**: `WorkflowNode[]` + `WorkflowEdge[]` replace the old linear trigger + actions pipeline. Each node has `id`, `type`, `position`, `config`, `output_ports`. Edges connect source/target node:port pairs.
- **Graph executor** (`services/executor_service.py`): BFS traversal from entry node (trigger for standard, `subflow_input` for sub-flows), resolving output ports per node type. Results stored as `node_results: dict[str, NodeExecutionResult]` keyed by node_id. Supports `invoke_subflow` (nested execution with recursion depth limit of 5) and `subflow_output` (terminal node that collects outputs). Node outputs are stored in `variable_context["nodes"]` under both `node.id` and `_sanitize_name(node.name)` (spaces→underscores).
- **OAS service** (`services/oas_service.py`): Loads Mist OpenAPI Spec, indexes endpoints, generates mock responses for simulation dry-run mode.
- **Node schema service** (`services/node_schema_service.py`): Provides upstream variable schemas for the variable picker, combining OAS data with node-type knowledge.
- **Graph validator** (`services/graph_validator.py`): Validates no orphans, no cycles, valid edge references. Workflow-type-aware: standard workflows require exactly one trigger; sub-flow workflows require exactly one `subflow_input` and at least one `subflow_output`. Uses `_require_single_node()` helper for entry node validation. Also validates no circular sub-flow references via BFS through `invoke_subflow` chains.
- **Simulation endpoint**: `POST /workflows/{id}/simulate` with payload picker and dry-run mode. Returns per-node snapshots (input/output/variables at each step).
- **Workflow recipes** (`models/recipe.py`, `router_recipes.py`, `seed_recipes.py`): `WorkflowRecipe` Beanie Document stores reusable workflow templates with category, difficulty, and placeholders. CRUD + `instantiate` (clone into new draft workflow) + `publish-as-recipe` endpoints. 4 built-in seed recipes seeded on startup (`seed_built_in_recipes()`).
- **Smart suggestions** (`services/suggestion_service.py`): Rules-based graph analysis returning contextual improvement hints (e.g., "Add error handling after API call", "Add trigger condition"). `GET /workflows/{id}/suggestions` endpoint. No LLM calls.

## Frontend (`features/workflows/editor/`)

- **SVG graph canvas** (`canvas/graph-canvas.component`): Raw SVG with pan/zoom/drag, cubic Bezier edges, `foreignObject` for Material node rendering, snap-to-grid. Undo/redo (Ctrl+Z/Shift+Ctrl+Z) via graph history stack in editor. Copy/paste nodes (Ctrl+C/V). "+" buttons on edge midpoints to insert nodes inline.
- **Node config panel** with emit guard pattern (`private emitting = false`) to prevent form rebuild loops. Advanced sections (Save As, Error Handling) collapsed by default in `<mat-expansion-panel>` for progressive disclosure.
- **Variable picker**: Tree view of upstream node outputs with click-to-insert `{{ variable.path }}`. Node names are sanitized (spaces→underscores) for valid Jinja2 dot notation. `set_variable` results appear in a "Variables" section as top-level variables (e.g., `{{ site_id }}`).
- **Simulation panel**: Bottom panel for dry-run and step-by-step replay with visual execution status on canvas. Real-time logs (`liveLogs` signal from `node_completed` WS messages) and live node results during execution. Cancel button calls `POST /workflows/{id}/simulate/{execution_id}/cancel` (backend tracks `asyncio.Task` in `_simulation_tasks` dict, calls `task.cancel()`).
- **AI Agent node** (`ai_agent` ActionType): Autonomous LLM + MCP tool-calling node. Config: `agent_task` (Jinja2 template), `agent_system_prompt`, `max_iterations`, `mcp_servers` (name, URL, headers JSON, SSL verify toggle), `llm_config_id` (selects which LLM to use). Executor: `_execute_ai_agent()` validates MCP URLs via `validate_outbound_url()`, connects in parallel via `asyncio.gather()`, runs `AIAgentService` loop.
- **Syslog action** (`syslog` ActionType): Sends formatted syslog messages to a remote server. Config: `syslog_host`, `syslog_port`, `syslog_protocol` (udp/tcp), `syslog_format` (rfc5424/cef), `syslog_facility` (local0-7), `syslog_severity`. All string fields support Jinja2 templates. CEF mode adds `cef_device_vendor`, `cef_device_product`, `cef_event_class_id`, `cef_name` fields. No external dependency — uses Python's native socket/asyncio.
- **Palette sidebar**: Native HTML drag-and-drop (not CDK), emits action type string.
- **Port-based branching**: Condition nodes → `branch_0`/`branch_1`/`else` ports; for-each → `loop_body`/`done` ports.
- **Sub-flows**: Workflows can be `standard` (trigger-based) or `subflow` (callable from other workflows). Sub-flows use `subflow_input` entry node + `subflow_output` terminal node with explicit `input_parameters`/`output_parameters`. Standard workflows call sub-flows via `invoke_subflow` action nodes with input mappings.

## Frontend (`features/workflows/list/`)

- **Recipe picker dialog** (`recipe-picker-dialog.component`): 3-path entry replacing "New Workflow" button: Start from Scratch, New Sub-Flow, or Use a Recipe. Recipe section shows category chips, card grid with difficulty badges, and selected recipe detail with "Use this Recipe" button.
- **Recipe service** (`core/services/recipe.service.ts`): API client for recipe CRUD and instantiation.
- **Suggestions bar** (`editor/suggestions-bar.component`): Thin bar above canvas showing 1-2 contextual suggestions from the backend rules engine, dismissible, refreshes on graph changes.
- **Template validation directive** (`shared/directives/template-validation.directive.ts`): `appTemplateValidation` directive for input fields — validates `{{ }}` balanced braces and known variable paths, shows green/red indicator.
