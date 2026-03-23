# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mist Automation & Backup — a full-stack application for automating Juniper Mist network operations via webhook-driven workflows and scheduled configuration backups. Python/FastAPI backend + Angular 21 frontend.

## Commands

### Backend (run from `backend/`, using `.venv/`)

```bash
# Activate venv (or prefix commands with .venv/bin/)
source .venv/bin/activate

.venv/bin/python -m app.main          # Dev server with auto-reload at http://localhost:8000
.venv/bin/pip install -e ".[dev,test]" # Install with dev + test dependencies

# Testing
.venv/bin/pytest                      # All tests with coverage
.venv/bin/pytest tests/unit/test_security.py    # Single test file
.venv/bin/pytest -m "unit"            # Only unit tests
.venv/bin/pytest -m "integration"     # Only integration tests

# Code quality
.venv/bin/black .                     # Format
.venv/bin/ruff check .                # Lint
.venv/bin/mypy app                    # Type check
```

### Frontend (run from `frontend/`)

```bash
npm start                             # Dev server at http://localhost:4200 (proxies /api → backend)
npx ng build                          # Production build
npx ng test                           # Unit tests (Vitest)
```

### Prerequisites

- MongoDB on localhost:27017 and Redis on localhost:6379 (or configure via `.env`)
- Copy `.env.example` to `.env` and set `SECRET_KEY`, `MIST_API_TOKEN`, `MIST_ORG_ID`

### API Testing

- **Swagger UI**: http://localhost:8000/api/v1/docs
- **ReDoc**: http://localhost:8000/api/v1/redoc
- **Health check**: `curl http://localhost:8000/health`

```bash
# Login and get JWT token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"YourPassword"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Authenticated request
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/workflows/
```

## Architecture

### Backend (FastAPI + Beanie/MongoDB)

**Module registry pattern**: All features register in `app/modules/__init__.py` as `AppModule` entries. To add a new module: create `app/modules/<name>/` with `router.py` and models, then add one `AppModule(...)` to the `MODULES` list.

**Key layers**:
- `app/api/v1/` — Route handlers for auth, users, admin, and the unified webhook gateway (receives all Mist webhooks, routes to automation/backup, manages Smee.io)
- `app/modules/` — Feature modules: `automation` (workflows, workflow execution, cron/webhook workers), `backup` (config snapshots, restore, git versioning), `reports` (post-deployment validation reports with PDF/CSV export)
- `app/models/` — Beanie Document models (User, UserSession, SystemConfig, AuditLog). Module-specific models live in their module dirs.
- `app/services/` — Business logic: `auth_service`, `mist_service`, `mist_service_factory` (shared async factory for MistService), `notification_service`
- `app/core/` — Database init, security, logging (structlog), middleware, custom exceptions, `smee_service` (dev webhook forwarding), `tasks` (safe background task creation)
- `app/config.py` — pydantic-settings config from environment variables

**Patterns**:
- Async throughout (Motor driver, Beanie ODM, async endpoints)
- Auth via JWT with `get_current_user_from_token()` dependency
- Background tasks via Celery (Redis broker) and APScheduler for cron jobs; use `create_background_task()` from `app.core.tasks` for fire-and-forget async tasks
- Mist API integration via `mistapi` library; use `create_mist_service()` from `app.services.mist_service_factory` to instantiate
- Template rendering uses Jinja2 `SandboxedEnvironment` with a safe env var allowlist (no `os.environ` exposure)
- Models use `TimestampMixin` for `created_at`/`updated_at`

### Frontend (Angular 21 + Material)

See `frontend/CLAUDE.md` for detailed frontend guidance.

**Key points**:
- All standalone components (no NgModules), `inject()` for DI, `@if`/`@for`/`@switch` control flow
- **Zoneless** with `provideZonelessChangeDetection()`; all component state uses `signal()` / `computed()` — no `ChangeDetectorRef`
- NgRx for auth state only; features use service-local observables
- `ApiService` is the single HTTP client (base URL `/api/v1`)
- Lazy-loaded feature areas: auth, dashboard, admin, backup, workflows, profile, reports
- Angular Material with CSS custom property theming; dark mode via `ThemeService` toggling `html.dark-theme` class
- All custom colors use `--app-*` CSS custom properties (defined in `styles.scss` with light defaults + `.dark-theme` overrides) — never hardcode hex colors in component SCSS
- Dev proxy: `/api` and `/health` → `http://localhost:8000` (see `proxy.conf.json`)

### Reports Module

**Backend** (`app/modules/reports/`):
- **Report job model**: `ReportJob` Beanie Document stores report type, site, status, progress, and full validation results.
- **Validation service** (`services/validation_service.py`): Runs post-deployment validation as a background task. Checks template variables (Jinja2 extraction across all string values), AP health (name, firmware, eth0 speed with < 1Gbps warning, connection status), switch health (name, firmware, status, virtual chassis consistency, cable tests run sequentially per switch), and gateway health (name, firmware, WAN/LAN port status with pass/warn/fail for full/partial/no connectivity). Template fetching and gateway data fetching are parallelized via `asyncio.gather`.
- **Export service** (`services/export_service.py`): Generates PDF (via `reportlab`) and CSV (ZIP of CSVs) from completed reports.
- **WebSocket progress**: Broadcasts real-time progress on channel `report:{id}` using existing `ws_manager`.
- **Access control**: `require_reports_role` dependency — requires `reports` or `admin` role.

**Frontend** (`features/reports/`):
- **Report list**: Table of past reports with create dialog (site picker dropdown).
- **Report detail**: Live progress view (WebSocket subscription) during generation, then expandable sections for template variables, APs, switches (with VC + cable test sub-tables), and gateways. Export PDF/CSV buttons in topbar.

### Workflow Editor (Graph-based)

Most complex feature, spanning both backend and frontend:

**Backend** (`app/modules/automation/`):
- **Graph data model**: `WorkflowNode[]` + `WorkflowEdge[]` replace the old linear trigger + actions pipeline. Each node has `id`, `type`, `position`, `config`, `output_ports`. Edges connect source/target node:port pairs.
- **Graph executor** (`services/executor_service.py`): BFS traversal from entry node (trigger for standard, `subflow_input` for sub-flows), resolving output ports per node type. Results stored as `node_results: dict[str, NodeExecutionResult]` keyed by node_id. Supports `invoke_subflow` (nested execution with recursion depth limit of 5) and `subflow_output` (terminal node that collects outputs). Node outputs are stored in `variable_context["nodes"]` under both `node.id` and `_sanitize_name(node.name)` (spaces→underscores).
- **OAS service** (`services/oas_service.py`): Loads Mist OpenAPI Spec, indexes endpoints, generates mock responses for simulation dry-run mode.
- **Node schema service** (`services/node_schema_service.py`): Provides upstream variable schemas for the variable picker, combining OAS data with node-type knowledge.
- **Graph validator** (`services/graph_validator.py`): Validates no orphans, no cycles, valid edge references. Workflow-type-aware: standard workflows require exactly one trigger; sub-flow workflows require exactly one `subflow_input` and at least one `subflow_output`. Uses `_require_single_node()` helper for entry node validation. Also validates no circular sub-flow references via BFS through `invoke_subflow` chains.
- **Simulation endpoint**: `POST /workflows/{id}/simulate` with payload picker and dry-run mode. Returns per-node snapshots (input/output/variables at each step).
- **Workflow recipes** (`models/recipe.py`, `router_recipes.py`, `seed_recipes.py`): `WorkflowRecipe` Beanie Document stores reusable workflow templates with category, difficulty, and placeholders. CRUD + `instantiate` (clone into new draft workflow) + `publish-as-recipe` endpoints. 4 built-in seed recipes seeded on startup (`seed_built_in_recipes()`).
- **Smart suggestions** (`services/suggestion_service.py`): Rules-based graph analysis returning contextual improvement hints (e.g., "Add error handling after API call", "Add trigger condition"). `GET /workflows/{id}/suggestions` endpoint. No LLM calls.

**Frontend** (`features/workflows/editor/`):
- **SVG graph canvas** (`canvas/graph-canvas.component`): Raw SVG with pan/zoom/drag, cubic Bezier edges, `foreignObject` for Material node rendering, snap-to-grid. Undo/redo (Ctrl+Z/Shift+Ctrl+Z) via graph history stack in editor. Copy/paste nodes (Ctrl+C/V). "+" buttons on edge midpoints to insert nodes inline.
- **Node config panel** with emit guard pattern (`private emitting = false`) to prevent form rebuild loops. Advanced sections (Save As, Error Handling) collapsed by default in `<mat-expansion-panel>` for progressive disclosure.
- **Variable picker**: Tree view of upstream node outputs with click-to-insert `{{ variable.path }}`. Node names are sanitized (spaces→underscores) for valid Jinja2 dot notation. `set_variable` results appear in a "Variables" section as top-level variables (e.g., `{{ site_id }}`).
- **Simulation panel**: Bottom panel for dry-run and step-by-step replay with visual execution status on canvas. Real-time logs (`liveLogs` signal from `node_completed` WS messages) and live node results during execution. Cancel button calls `POST /workflows/{id}/simulate/{execution_id}/cancel` (backend tracks `asyncio.Task` in `_simulation_tasks` dict, calls `task.cancel()`).
- **AI Agent node** (`ai_agent` ActionType): Autonomous LLM + MCP tool-calling node. Config: `agent_task` (Jinja2 template), `agent_system_prompt`, `max_iterations`, `mcp_servers` (name, URL, headers JSON, SSL verify toggle), `llm_config_id` (selects which LLM to use). Executor: `_execute_ai_agent()` validates MCP URLs via `validate_outbound_url()`, connects in parallel via `asyncio.gather()`, runs `AIAgentService` loop.
- **Syslog action** (`syslog` ActionType): Sends formatted syslog messages to a remote server. Config: `syslog_host`, `syslog_port`, `syslog_protocol` (udp/tcp), `syslog_format` (rfc5424/cef), `syslog_facility` (local0-7), `syslog_severity`. All string fields support Jinja2 templates. CEF mode adds `cef_device_vendor`, `cef_device_product`, `cef_event_class_id`, `cef_name` fields. No external dependency — uses Python's native socket/asyncio.
- **Palette sidebar**: Native HTML drag-and-drop (not CDK), emits action type string.
- **Port-based branching**: Condition nodes → `branch_0`/`branch_1`/`else` ports; for-each → `loop_body`/`done` ports.
- **Sub-flows**: Workflows can be `standard` (trigger-based) or `subflow` (callable from other workflows). Sub-flows use `subflow_input` entry node + `subflow_output` terminal node with explicit `input_parameters`/`output_parameters`. Standard workflows call sub-flows via `invoke_subflow` action nodes with input mappings.

**Frontend** (`features/workflows/list/`):
- **Recipe picker dialog** (`recipe-picker-dialog.component`): 3-path entry replacing "New Workflow" button: Start from Scratch, New Sub-Flow, or Use a Recipe. Recipe section shows category chips, card grid with difficulty badges, and selected recipe detail with "Use this Recipe" button.
- **Recipe service** (`core/services/recipe.service.ts`): API client for recipe CRUD and instantiation.
- **Suggestions bar** (`editor/suggestions-bar.component`): Thin bar above canvas showing 1-2 contextual suggestions from the backend rules engine, dismissible, refreshes on graph changes.
- **Template validation directive** (`shared/directives/template-validation.directive.ts`): `appTemplateValidation` directive for input fields — validates `{{ }}` balanced braces and known variable paths, shows green/red indicator.

### LLM Module

**Backend** (`app/modules/llm/`):
- **Multi-LLM config**: `LLMConfig` Beanie Document stores named provider configs (provider, api_key encrypted, model, base_url, temperature, max_tokens). `SystemConfig.llm_enabled` is the global kill switch. Individual configs managed via `/llm/configs` CRUD endpoints.
- **LLM service factory**: `create_llm_service(config_id=None)` from `app.modules.llm.services.llm_service_factory` — loads default or specific config. Uses openai SDK for OpenAI-compatible providers (openai, lm_studio, azure_openai), litellm for others (anthropic, ollama, bedrock, vertex).
- **SSRF on LLM base_url**: Skip `validate_outbound_url()` for local providers (`lm_studio`, `ollama`) since they run on localhost by design.
- **Agent service** (`services/agent_service.py`): LLM + MCP tool-calling loop with `max_iterations` cap (server-side max 25). Returns `AgentResult` with status, result text, `tool_calls` log (each `ToolCallRecord` has `tool`, `arguments`, `result`, `server`, `is_error`), `thinking_texts` (intermediate reasoning per iteration). Accepts optional `on_tool_call` async callback for real-time WS events (`thinking`, `tool_start`, `tool_end`). When callback is provided, uses `stream_with_tools()` for streaming to capture intermediate content that non-streaming mode drops.
- **LLM streaming with tools** (`services/llm_service.py`): `stream_with_tools()` uses OpenAI-compatible streaming (`stream=True`) to capture content deltas alongside tool_call deltas. Broadcasts content tokens via `on_content` callback. Falls back to non-streaming `complete_with_tools()` for litellm providers (thinking tokens not available).
- **MCP client** (`services/mcp_client.py`): `MCPClientWrapper` for remote HTTP MCP servers (streamable HTTP only, with SSL verify toggle + custom headers). `InProcessMCPClient` for the local FastMCP server (memory transport, ContextVars propagate). `create_local_mcp_client()` factory. Both `call_tool()` methods return `(text, is_error)` tuple — `MCPClientWrapper` reads `result.isError` from the MCP SDK, `InProcessMCPClient` returns `False` (errors raise exceptions instead).
- **Prompt builders** (`services/prompt_builders.py`): Per-feature prompt constructors. Webhook payload schemas with domain descriptions in the workflow assist system prompt. API endpoints go in system message (not user message).
- **Context service** (`services/context_service.py`): Gathers data from other modules for prompts. `get_webhook_summary_context()` returns `(summary_text, event_count)` tuple.
- **Conversation threads**: `ConversationThread` with `to_llm_messages(max_turns=20)` sliding window. TTL index (90 days). `_load_or_create_thread()` helper raises 400/404/403 on invalid/missing/unauthorized thread IDs (never silently creates new). `ConversationMessage` has optional `metadata` field for persisting tool_calls and thinking_texts alongside assistant messages.
- **Router helpers**: `_usage_dict(response)`, `_log_llm_usage()`, `_stream_or_complete()` (WebSocket token streaming when `stream_id` provided), `_mcp_user_session()` context manager, `_check_llm_rate_limit()`, `_make_tool_notifier(stream_id)` (builds WS callback for agent tool events), `_agent_result_metadata(result)` (builds conversation metadata from `AgentResult`).
- **Model discovery**: `/llm/configs/{id}/models` and `/llm/discover-models` (anonymous, pre-save). OpenAI-compat uses `client.models.list()`, Anthropic uses `GET /v1/models`.
- **Slack Block Kit extraction**: `_extract_slack_blocks()` uses `json.JSONDecoder().raw_decode()` to find Block Kit JSON in AI Agent text responses. Falls back to `mrkdwn` sections for plain text, code blocks for structured data.

**MCP Server** (`app/modules/mcp_server/`):
- FastMCP server exposing app data as MCP tools (backups, workflows, executions, webhook events, reports, system stats)
- HTTP endpoint (`/mcp`) gated by `MCPAuthMiddleware` (`auth_middleware.py`) — validates Bearer JWT, sets `mcp_user_id_var`. Returns 401 for unauthenticated requests.
- In-process memory transport (`InProcessMCPClient`) bypasses HTTP entirely — unaffected by auth middleware
- `mcp_user_id_var` ContextVar for user context in tool handlers
- **Elicitation bridge** (`helpers.py`): `elicit_confirmation()` sends simple text confirmations via WebSocket; `elicit_restore_confirmation()` sends rich payloads with `elicitation_type` and `data` fields for structured UI (e.g., diff viewer in restore confirmation card)
- **Backup restore action**: `backup(action="restore")` auto-computes diff between target and current version, sends rich elicitation with diff data, executes restore on approval

**Frontend**:
- **Global floating chat** (`shared/components/global-chat/`): Bottom-right FAB with glass style, expands to 420x560 chat panel. Uses `GlobalChatService` for open/pre-fill from any page. Passes `page_context` (current page + details) to the LLM.
- **AI icon** (`shared/components/ai-icon/`): Animated Network Pulse SVG icon (nodes drift + green pulses). `[animated]="false"` for toolbar buttons (static, lighter). `vertical-align: middle` for button text alignment.
- **AiChatPanel** (`shared/components/ai-chat-panel/`): Reusable chat component with unified `timeline` signal (`TimelineItem[]` — messages + inline tool call cards in chronological order). Markdown rendering (marked + DOMPurify), WebSocket streaming for thinking/tool events, auto-scroll. `startStream(streamId, text)` method initiates WS subscription synchronously (NOT via effects — effects are unreliable for WS in zoneless mode). `_subscribeToStream(channel)` private method handles all WS event types (thinking, tool_start, tool_end, token, elicitation, done). `reset()` method for full state teardown. Tool calls persist in conversation thread metadata and reconstruct on thread reload.
- **Multi-LLM admin** (`features/admin/settings/llm/`): Config list table + add/edit dialog with connection-first flow (test + fetch models before save).
- **LlmService**: `getStatus()` cached with `shareReplay(1)`. `globalChat()`, `followUp()`, config CRUD, `testConnectionAnonymous()`, `discoverModels()`.
- **Page context**: Components call `globalChatService.setContext({page, details})` on init so the global chat LLM knows what the user is viewing.

## Code Style

**Backend**: Black (120 char lines), Ruff (isort, pycodestyle, pyflakes, bugbear), MyPy with Pydantic plugin. Python 3.10+.

**Frontend**: Prettier (100 char, single quotes), strict TypeScript with `strictTemplates`. See `frontend/CLAUDE.md` for Angular-specific conventions.

## Engineering Principles

### Security

- **Access control**: All endpoints MUST enforce role-based access via `require_admin`, `require_automation_role`, `require_backup_role`, or `require_reports_role` from `app/dependencies.py`. Workflow-scoped endpoints must also check `workflow.can_be_accessed_by(current_user)`.
- **SSRF protection**: Outbound HTTP requests to user-controlled URLs MUST call `validate_outbound_url()` from `app/utils/url_safety.py` before sending.
- **Sensitive data in responses**: Never leak internal error details (`str(e)`) to API clients. Log full errors server-side, return generic messages to the user. Use `*_set: bool` fields for sensitive config (tokens, passwords) instead of returning actual values.
- **Session management**: Password changes invalidate all other sessions. Login enforces `max_concurrent_sessions`. Sessions use JTI-based revocation via `UserSession` DB lookup.
- **Input validation**: Admin settings use `SystemSettingsUpdate` Pydantic model (`app/schemas/admin.py`) with field validators for cron expressions, URLs, and numeric bounds. Never accept raw `dict = Body(...)`.
- **CSP & security headers**: `SecurityHeadersMiddleware` in `app/core/middleware.py` adds CSP, Permissions-Policy, HSTS, X-Frame-Options, X-Content-Type-Options.
- **CORS**: Restricted to specific methods (`GET, POST, PUT, DELETE, OPTIONS`) and headers (`Authorization, Content-Type, X-Request-ID`).
- **LLM API keys**: Stored encrypted in `LLMConfig.api_key` via `encrypt_sensitive_data()`. Admin API returns `api_key_set: bool`. Anonymous test/discover endpoints accept raw key or `config_id` to use stored key.
- **MCP server URLs**: Must pass `validate_outbound_url()` before connecting (SSRF protection). Exception: local providers (lm_studio, ollama) skip validation.
- **XSS on LLM output**: All LLM markdown rendered via `marked.parse()` + `DOMPurify.sanitize()` before `[innerHTML]` binding.
- **Agent tool errors**: Sanitize `str(e)` — log full error server-side, send generic message to LLM ("Error: tool 'X' failed to execute").
- **Execution ownership**: `debug_execution` endpoint verifies `workflow.can_be_accessed_by(current_user)` before exposing execution data.
- **`max_iterations` cap**: AI Agent node config `max_iterations` clamped to 25 server-side regardless of user input.
- **Conversation thread ownership**: `_load_or_create_thread()` raises 403 if thread belongs to another user. Raises 404 if thread_id provided but not found (never silently creates new).
- **Password policy**: Use `validate_password_with_policy()` from `app/core/security.py` (reads policy from `SystemConfig` at runtime) instead of `validate_password_strength()` (reads from env only) in all endpoint code.
- **Prompt safety**: Use `_sanitize_for_prompt()` from `app/modules/llm/services/prompt_builders.py` for all user-sourced values injected into LLM prompts (strips markdown control chars, truncates).
- **MCP tool access control**: MCP write tools (workflow update, backup trigger) must check user roles/permissions via `mcp_user_id_var` — mirrors REST API enforcement. Read-only tools (search, details) do not need role checks.
- **Error sanitization**: Use `_sanitize_execution_error()` from `executor_service.py` for all exception messages stored in execution/node results. Never store raw `str(e)` in client-visible fields.
- **MCP HTTP auth**: `MCPAuthMiddleware` validates Bearer JWT on all HTTP requests to `/mcp`. In-process memory transport is unaffected.
- **Webhook IP allowlist**: `SystemConfig.webhook_ip_whitelist` list of CIDR ranges. Enforced in `receive_mist_webhook()` via `_ip_in_allowlist()` before signature verification. Smee-forwarded localhost requests bypass.
- **SMTP credentials**: `smtp_password` encrypted via `encrypt_sensitive_data()`. Admin API returns `smtp_password_set: bool`.
- **Sensitive field clearing**: Empty string values for sensitive fields (tokens, passwords) in `PUT /admin/settings` clear the field (`setattr(config, field, None)`) instead of encrypting the empty string.
- **Notification failure isolation**: `notify_workflow_failure()` catches all exceptions — notification failures must never affect workflow execution status.
- **Maintenance mode**: `MaintenanceModeMiddleware` returns 503 for non-admin/auth paths when `SystemConfig.maintenance_mode` is True. `/health`, `/api/v1/auth/*`, `/api/v1/admin/*`, and `/mcp` are always allowed.

### KISS (Keep It Simple)

- Initialize data structures with expected shapes upfront (e.g., `variable_context = {"trigger": {}, "nodes": {}, "results": {}}`).
- Extract small helpers for repeated response construction patterns (e.g., `_user_to_response()` in auth.py).
- Don't add abstractions until the same pattern appears 3+ times.
- **Minimize clicks**: High-frequency actions belong directly on the topbar/toolbar as icon buttons, not hidden in dropdown menus. Keep menus for rare/secondary actions only.

### DRY (Don't Repeat Yourself)

- **MistService instantiation**: Always use `create_mist_service()` from `app.services.mist_service_factory` — never manually create MistService with config+decrypt inline.
- **LLM service instantiation**: Always use `create_llm_service(config_id=None)` from `app.modules.llm.services.llm_service_factory` — never manually create LLMService.
- **LLM router helpers**: `_usage_dict(response)` for API response usage dicts, `_log_llm_usage()` for DB logging, `_load_or_create_thread()` for conversation thread lifecycle, `_mcp_user_session()` for MCP client connect/disconnect, `_agent_result_metadata(result)` for building conversation metadata from `AgentResult`, `_make_tool_notifier(stream_id)` for WS tool event callbacks.
- **Deep diff utility**: Use `deep_diff()` from `app.modules.backup.utils` — not from `backup/router.py` (moved to shared utility).
- **Conversation thread messages**: Use `thread.to_llm_messages()` — not inline list comprehension converting dicts to LLMMessage objects.
- **Template brace stripping**: Use `strip_template_braces()` from `app/utils/variables.py` instead of inline `{{ }}` removal.
- **MistService API methods**: `_api_call()` is the single implementation for GET/POST/PUT/DELETE; thin wrappers (`api_get`, `api_post`, etc.) delegate to it.
- **Webhook response helpers**: `_event_fields()` in `webhooks.py` provides shared fields used by both REST responses and WebSocket monitor dicts.
- **Variable substitution dispatch**: `_substitute_value()` in `app/utils/variables.py` is the single recursive dispatcher for str/dict/list types; `substitute_in_dict` and `substitute_in_list` are thin wrappers.
- **Node name sanitization**: Use `_sanitize_name()` from `executor_service.py` (spaces→underscores) when storing or referencing node names as variable keys. The schema service, executor, and frontend variable picker all use the same convention.
- **Workflow execution response helpers**: `_execution_summary()`, `_node_result_to_dict()`, and `_snapshot_to_dict()` in `automation/router.py` build response dicts from aggregation results, `NodeExecutionResult`, and `NodeSnapshot` objects respectively — never inline these dict comprehensions.
- **Report response construction**: `_dict_to_response()` in `reports/router.py` builds `ReportJobResponse` from raw MongoDB aggregation dicts; `_job_to_response()` builds from `ReportJob` documents.
- **Celery app**: Import `celery_app` from `app.core.celery_app` — never create Celery instances in module workers directly.
- **User response construction**: Use `user_to_response()` from `app.schemas.user` — single canonical User→UserResponse builder used by both `auth.py` and `users.py`.
- **MCP paginated search**: Use `_paginated_query()` from `app/modules/mcp_server/tools/search.py` for `$facet`-based MongoDB aggregations with pagination.
- **Workflow failure notification**: Use `notify_workflow_failure()` from `app.modules.automation.workers.notification_helper` — do not inline notification dispatch in workers.
- **DB facet counts**: Use `facet_counts()` from `app.utils.db_helpers` for `$facet`-based count aggregations — shared by `admin.py` and `dashboard.py`.

### Efficiency

- **MongoDB `$facet` aggregation**: Admin stats endpoint uses `$facet` to batch multiple count queries into a single DB round-trip per collection.
- **DB-level filtering**: Webhook worker uses `$elemMatch` queries to filter workflows at the database level instead of loading all enabled workflows and filtering in Python.
- **Render context caching**: Executor service caches the Jinja2 render context per node execution (`_cached_render_context`), invalidated after each node completes.
- **Batch gateway API calls**: Validation service pre-fetches all gateway device configs (`listSiteDevices`) and port stats (`searchSiteSwOrGwPorts`) in a single parallel call, then distributes to per-gateway validators — avoids N+1 API calls.
- **Parallel template fetching**: `_fetch_all_templates` uses `asyncio.gather` to fetch all 6 derived template types concurrently instead of sequentially.
- **WebSocket connection reuse**: `WebSocketService` is a singleton that multiplexes channels over one connection. Do NOT close the connection when the last channel unsubscribes — keep it alive for reuse.
- **LLM status caching**: `LlmService.getStatus()` uses `shareReplay(1)` — all components share one cached HTTP call. Do NOT call `getStatus()` independently per component.
- **MCP connections in parallel**: AI Agent node connects to multiple MCP servers via `asyncio.gather()`, not sequentially.
- **Simulation task tracking**: Running simulation `asyncio.Task` objects tracked in module-level `_simulation_tasks` dict for cancellation support.
- **MistService config caching**: Factory caches resolved config (token, region, org_id) with 30s TTL. Call `invalidate_mist_config_cache()` from `app.services.mist_service_factory` when admin updates Mist settings.
- **Maintenance mode cache**: `MaintenanceModeMiddleware` caches `SystemConfig.maintenance_mode` with 5s TTL. Call `set_maintenance_cache()` from `app.core.middleware` when admin updates the setting.
- **Execution cleanup**: APScheduler job `cleanup_old_executions()` runs nightly (3:00 UTC), purges `WorkflowExecution` documents older than `SystemConfig.execution_retention_days`.

## Mist Cloud Object Model

Based on OAS v2602.1.6. Hierarchy: **MSP** → **Organization** → **Site**.

### Object Hierarchy & CRUD

**MSP level**: MSP (CRUD), SSOs, SSO Roles, Org Groups, Licenses (R/U)

**Org level** — grouped by domain:

| Domain | Objects |
|--------|---------|
| **Identity & Access** | SSOs, SSO Roles, NAC Portals, NAC Rules (→ refs NAC Tags), NAC Tags, PSK Portals, PSKs, User MACs |
| **Wireless Config** | WLANs, WLAN Templates (→ contains WLANs), RF Templates, AP Templates, SDK Templates, SDK Invites, WxRules (→ refs WxTags), WxTags, WxTunnels |
| **Network & Security** | Networks, Network Templates (→ refs Networks), VPNs, Services, Service Policies (→ refs Services), Security Policies (→ refs Services), IDP Profiles, SecIntel Profiles, AAMW Profiles, AV Profiles |
| **Device Management** | Device Profiles, Gateway Templates, Inventory (CRU), MxEdges (→ belongs to MxClusters), MxClusters, MxTunnels, EVPN Topologies |
| **Site Management** | Site Groups (→ groups Sites), Site Templates, Alarm Templates, Asset Filters, Assets, Webhooks, Licenses (R/U), Tickets (CRU) |

**Org singletons**: Org Setting (R/U)

**Site level**:

| Domain | Objects |
|--------|---------|
| **Wireless** | WLANs, WxRules (→ refs WxTags), WxTags, WxTunnels, PSKs, RSSI Zones, Zones |
| **Maps & Assets** | Maps, Beacons, vBeacons, Asset Filters (→ filters Assets), Assets |
| **Infrastructure** | Devices (R/U, assigned from Org Inventory), EVPN Topologies, MxEdges (RUD), Webhooks |

**Site singletons**: Site Setting (R/U)

### Template/Profile Inheritance (Org → Site via "derived" APIs)

Org objects are inherited at site level through `listSite*Derived` endpoints:
- **WLANs**, **WxRules** → derived at site wireless level
- **RF Templates**, **AP Templates**, **Network Templates**, **Site Templates** → derived into Site Setting
- **Networks**, **Services**, **Service Policies**, **VPNs** → derived into Site Setting
- **SecIntel/AAMW/AV/IDP Profiles** → derived into Site Setting
- **Device Profiles**, **Gateway Templates** → derived into Site Devices

### Site → Template Assignment (via site info fields)

Sites reference templates via ID fields in the **site info** response (`getSiteInfo`):
`alarmtemplate_id`, `aptemplate_id`, `gatewaytemplate_id`, `networktemplate_id`, `rftemplate_id`, `sitetemplate_id`, `secpolicy_id`, `sitegroup_ids`

### Gateway Configuration Merge Order

Effective config = **Gateway Template** (org) → overridden by **Device-level config** (`getSiteDevice`). Key config sections:
- `port_config`: dict of interface → `{usage: "wan"|<network_name>, name, wan_type, ...}`
- `ip_configs`: dict of network_name → `{ip, netmask, type}`
- `dhcpd_config`: dict with top-level `enabled` bool + per-network keys → `{type: "local"|"relay", ip_start, ip_end, servers}`. `type: "local"` = DHCP server.
- `networks`: list of network objects

### Jinja2 Variable Sources

Objects that can contain `{{ variable }}` patterns resolved against `site_setting.vars`:
- Site Templates, Network Templates, RF Templates, Gateway Templates
- WLANs (org and site level)
- Services (Applications), Service Policies (Application Policies)

### Device Stats & Events

- `listSiteDevicesStats(type="ap"|"switch"|"gateway")` — device stats; `port_stat` may be **empty for gateways**
- `searchSiteSwOrGwPorts(device_type="switch"|"gateway")` — reliable port status for switches and gateways
- `searchSiteDeviceEvents` (in `devices` module, NOT `events`) — config events: `AP_CONFIGURED`, `SW_CONFIGURED`, `GW_CONFIGURED`, `*_CONFIG_CHANGED_BY_USER`, `*_CONFIG_FAILED`
- Device `status` values: `"connected"` (pass), `"upgrading"`/`"restarting"` (warn), anything else (fail)

### VC Links (Virtual Chassis) — IMPORTANT

**The `vc_links` array in switch stats ONLY contains links that are UP.** Down/disconnected VC links are simply absent from the array. Therefore, every entry in `vc_links` is an active link — do NOT check for an `up` field or filter entries. Counting `len(vc_links)` (or summing dicts) directly gives the number of UP VC ports. **Do not add `.get("up")` or any similar filter — this has been incorrectly flagged by code review multiple times and is WRONG.**

## Maintenance

**Always update these CLAUDE.md files** (root and `frontend/CLAUDE.md`) when making architectural changes, adding new patterns, modifying conventions, or restructuring features. These files are the primary reference for AI-assisted development and must stay accurate. When in doubt, update — stale documentation is worse than none.
