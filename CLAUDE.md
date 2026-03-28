# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mist Automation & Backup — a full-stack application for automating Juniper Mist network operations via webhook-driven workflows and scheduled configuration backups. Python/FastAPI backend + Angular 21 frontend.

## Commands

See `backend/CLAUDE.md` and `frontend/CLAUDE.md` for build, test, and lint commands.

**Prerequisites**: MongoDB on localhost:27017, Redis on localhost:6379, InfluxDB 2.7 on localhost:8086 (optional, for telemetry). Use `docker-compose up` to start all services, or configure via `.env`. Copy `.env.example` to `.env` and set `SECRET_KEY`, `MIST_API_TOKEN`, `MIST_ORG_ID`.

## Architecture

### Backend (FastAPI + Beanie/MongoDB)

**Module registry pattern**: All features register in `app/modules/__init__.py` as `AppModule` entries. To add a new module: create `app/modules/<name>/` with `router.py` and models, then add one `AppModule(...)` to the `MODULES` list.

**Key layers**:
- `app/api/v1/` — Route handlers for auth, users, admin, and the unified webhook gateway (receives all Mist webhooks, routes to automation/backup, manages Smee.io)
- `app/modules/` — Feature modules: `automation` (workflows, workflow execution, cron/webhook workers), `backup` (config snapshots, restore, git versioning), `reports` (post-deployment validation reports with PDF/CSV export), `impact_analysis` (automated config change impact monitoring), `telemetry` (real-time device stats via Mist WebSocket → InfluxDB)
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
- Lazy-loaded feature areas: auth, dashboard, admin, backup, workflows, profile, reports, impact-analysis
- Angular Material with CSS custom property theming; dark mode via `ThemeService` toggling `html.dark-theme` class
- All custom colors use `--app-*` CSS custom properties (defined in `styles.scss` with light defaults + `.dark-theme` overrides) — never hardcode hex colors in component SCSS
- Dev proxy: `/api` and `/health` → `http://localhost:8000` (see `proxy.conf.json`)

### Webhook Event Routing

**Gateway** (`app/api/v1/webhooks.py`): Single `POST /webhooks/mist` endpoint receives all Mist webhooks. Flow:
1. HMAC-SHA256 signature validation (from `SystemConfig.webhook_secret`)
2. IP allowlist enforcement (CIDR-aware, from `SystemConfig.webhook_ip_whitelist`)
3. Smee.io localhost bypass for dev (signature + IP checks skipped)
4. Multi-event payload splitting — each event in `payload["events"]` becomes a separate `WebhookEvent` document (deduped by `webhook_id` unique index)
5. Per-event field enrichment via `enrich_event()` + `extract_event_fields()` from `app.core.webhook_extractor`
6. Module dispatch (see below)
7. WebSocket broadcast to `webhook:monitor` channel for real-time UI

**Current routing** (hardcoded in gateway, lines 172-176):
| Module | Topic filter | Dispatch mode | Handler |
|--------|-------------|---------------|---------|
| **Automation** | All topics | Per-event, async background task | `automation.workers.webhook_worker.process_webhook(event_id, webhook_type, payload, event_type=)` |
| **Backup** | `audits` only | Pre-split, synchronous (awaited, result in HTTP response) | `backup.webhook_handler.process_backup_webhook(payload, config)` |
| **Impact Analysis** | `device-events` only | Per-event, async background task | `impact_analysis.workers.event_handler.handle_device_event(event_id, event_type, payload)` |

**Key details**:
- Fan-out: A single event can go to multiple modules (e.g., `device-events` → automation + impact_analysis)
- Backup receives the **full original payload** (pre-split), not individual events — it does its own event filtering
- `routed_to` field on `WebhookEvent` documents records which modules received the event (audit trail)
- Replay endpoint (`POST /webhooks/events/{id}/replay`) re-dispatches to automation only
- Adding a new consumer currently requires editing `webhooks.py` — a pub/sub event bus is planned to decouple this (see `docs/superpowers/specs/2026-03-26-webhook-event-bus-design.md`)

### Reports Module

**Backend** (`app/modules/reports/`):
- **Report job model**: `ReportJob` Beanie Document stores report type, site, status, progress, and full validation results.
- **Validation service** (`services/validation_service.py`): Runs post-deployment validation as a background task. Checks template variables (Jinja2 extraction across all string values), AP health (name, firmware, eth0 speed with < 1Gbps warning, connection status), switch health (name, firmware, status, virtual chassis consistency, cable tests run sequentially per switch), and gateway health (name, firmware, WAN/LAN port status with pass/warn/fail for full/partial/no connectivity). Template fetching and gateway data fetching are parallelized via `asyncio.gather`.
- **Export service** (`services/export_service.py`): Generates PDF (via `reportlab`) and CSV (ZIP of CSVs) from completed reports.
- **WebSocket progress**: Broadcasts real-time progress on channel `report:{id}` using existing `ws_manager`.
- **Access control**: `require_post_deployment_role` dependency — requires `post_deployment` or `admin` role. `require_reports_role` kept as backwards-compat alias.

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

### Impact Analysis Module

**Backend** (`app/modules/impact_analysis/`):
- **MonitoringSession model**: Beanie Document tracking config change impact. States: PENDING → BASELINE_CAPTURE → AWAITING_CONFIG → MONITORING → VALIDATING → COMPLETED/FAILED/CANCELLED. Single active session per `device_mac` (merge on new config events during active monitoring). `timeline: list[TimelineEntry]` provides chronological record of all events, checks, and AI analyses. Impact tracked separately via `impact_severity` field (none/info/warning/critical) — escalation only, never downgrades. Use `session_manager.escalate_impact()`.
- **SessionLogger** (`services/session_logger.py`): Per-session diagnostic logging (structlog + MongoDB `SessionLogEntry`). Created at pipeline start, captures API responses, validation results, correlation checks. Queryable via `/impact-analysis/sessions/{id}/logs`.
- **Event handler** (`workers/event_handler.py`): Routes device-events webhooks to session manager. Six event categories: PRE_CONFIG, CONFIGURED, CONFIG_FAILED, INCIDENT, REVERT, RESOLUTION. Uses `get_monitoring_defaults(device_type)` for device-type-specific timing. Tags `WebhookEvent.routed_to` with `"impact_analysis"` when consumed. Adds `TimelineEntry` for every routed event. Triggers AI analysis on bad events (disconnects, config failures, reverts) during MONITORING/VALIDATING states. Incidents escalate `impact_severity` directly (not via AI). Audit webhook lookup (`_lookup_audit`) searches by `payload.id` (NOT `webhook_id`) to extract `config_before`/`config_after` JSON.
- **LLDP client capture** (`_fetch_device_clients` in monitoring_worker): Uses `listOrgDevicesStats(org_id, type, site_id, mac, fields="*")` — the site-level list endpoint strips the `clients` array. Captured at baseline, with fallback during validation.
- **Topology dict helpers**: Public functions in `topology_service.py` (moved from validation_service): `build_adjacency`, `find_device_id_by_mac`, `get_topology_devices`, `get_topology_connections`, `bfs_reachable`, `bfs_path_exists`, `find_gateways`, `safe_list`.
- **SLE service** (`services/sle_service.py`): Two-tier SLE monitoring. Site-level at every poll via `SiteDataCoordinator` (zero extra API calls per device). Device-level drill-down only when degradation detected (`impacted-aps`, `impacted-switches`, etc.). Baseline captured with 1h lookback before config change. Metrics by device type: AP (`time-to-connect`, `throughput`, `roaming`, `coverage`, `capacity`, `ap-availability`), Switch (`sw-throughput`, `sw-health`), Gateway (`wan-throughput`, `wan-link-health`, `gw-health`).
- **Topology integration** (`topology/`): Copied from `mist_topology` project. BFS path finding, link classification (VC/MCLAG/LAG/Fabric), VLAN segment analysis. Used for connectivity, loop detection, and black hole checks. Topology service adapts `MistService` to the topology builder with parallel data fetching. Per-site topology cached with 30s TTL.
- **Site data coordinator** (`services/site_data_coordinator.py`): Fetches site-level data once per poll interval, shares across all active sessions at that site. Org-level upgrade for non-SLE data when 3+ sites active (`maybe_upgrade_to_org_level()`). `get_or_create(site_id)` factory. Cleanup when no more active sessions at a site.
- **Monitoring pipeline** (`workers/monitoring_worker.py`): Single async coroutine per session via `create_background_task()`. Phases: PENDING (5s batch) → BASELINE_CAPTURE → AWAITING_CONFIG (10-min timeout) → three parallel tracks: **Branch A** (device validation at 2/5/10 min by device type → VALIDATING), **Branch B** (webhook event monitoring via event_handler, 60 min), **Branch C** (SLE monitoring every 10min x 6 = 60 min). Device-type defaults: AP 2 min, Switch 5 min, Gateway 10 min (`DEVICE_TYPE_MONITORING_DEFAULTS` in models.py). AI analysis is event-driven — triggered when validation finds issues, bad webhook events arrive, or SLE degrades. All steps recorded in session `timeline`.
- **Validation service** (`services/validation_service.py`): 12 post-change checks (removed #2 SLE Performance → SLE branch, removed #7 Alarm Correlation → webhook events). AP: {1,3-6,8,12}. Switch: {1,3-6,8-13}. Gateway: {1,3-6,8,9,11,12,14}. Takes targeted data (device_stats, port_stats, topology) instead of full SiteDataCoordinator. Each check returns `{status: "pass|warn|fail", details}`.
- **Template service** (`services/template_service.py`): Captures org/site template configs at baseline, compares against end-of-monitoring state using `deep_diff()` from backup utils, and correlates template changes with device CONFIGURED events.
- **AI analysis service** (`services/analysis_service.py`): Event-driven — triggered by validation issues, bad webhook events, or SLE degradation. Accepts `trigger` and `trigger_context` params. Includes previous AI analyses from timeline + `config_before`/`config_after` from audit webhook in prompt. Uses `AIAgentService` + in-process MCP. Returns `{has_impact, severity, summary, recommendations, trigger}`. Rule-based fallback when LLM unavailable. Dedup via atomic `_pending` claim in `trigger_ai_analysis()`.
- **Access control**: `require_impact_role` dependency — requires `impact_analysis` or `admin` role.
- **WebSocket channels**: `impact:{session_id}` for per-session updates (status changes, SLE snapshots, incidents, validation/analysis completion), `impact:summary` for dashboard widget (active/alert count changes), `impact:alerts` for new alert notifications.
- **Cleanup worker**: APScheduler job `cleanup_old_sessions()` runs nightly (3:30 UTC), purges `MonitoringSession` documents older than `SystemConfig.impact_analysis_retention_days`.
- **MCP tools**: Impact analysis search/details exposed via MCP server for AI chat context.

**Frontend** (`features/impact-analysis/`):
- **Session list** (`session-list/`): `mat-table` with columns: Impact (severity badge, first column), Device, Type, Site, Changes, Detected, Progress (mini progress bar). Filters by status and device type. Impact severity shown as colored `StatusBadgeComponent` (critical=red, warning=amber, info=blue, none=green).
- **Session detail** (`session-detail/`): Progress bar during active monitoring. Event timeline (from `session.timeline` field, real-time WS updates via `timeline_entry` events). Expandable sections: SLE metrics table (baseline vs current with delta), validation check panels (pass/warn/fail per check), AI assessment (rendered markdown with severity badge and recommendations). Impact severity badge in header. "Cancel" button for active sessions, "Reanalyze" button for completed sessions.
- **SLE chart** (`sle-chart/`): Pre/post SLE comparison via Chart.js (ng2-charts). Baseline vs snapshot trend lines.
- **Topology view** (`topology-view/`): Mermaid diagram with pre/post toggle and impact radius highlight.
- **Event timeline** (`event-timeline/`): Chronological incidents with resolution status indicators.
- **AI assessment** (`ai-assessment/`): Rendered markdown (marked + DOMPurify), severity badge, recommendations list.
- **Dashboard widget**: Active/impacted session counts with live WS updates via `impact:summary` channel. Click navigates to `/impact-analysis`.
- **Impact analysis service** (`core/services/impact-analysis.service.ts`): API client for sessions CRUD, summary, SLE data, and settings.

### Telemetry Module

**Backend** (`app/modules/telemetry/`):
- **Always-on WebSocket ingestion**: Connects to Mist Cloud WebSocket (`wss://api-ws.{region}.mist.com`) at startup, subscribes to `/sites/{site_id}/stats/devices` for all configured sites. Auto-scales connections (max 1000 channels per WebSocket). Uses `mistapi.websockets.sites.DeviceStatsEvents` with thread-to-asyncio bridge.
- **InfluxDB storage**: `InfluxDBService` with async batched writes (500 points or 10s flush interval), bounded buffer (10K items, drop on overflow). Query methods: `query_range`, `query_latest`, `query_aggregate` (Flux-based). InfluxDB 2.7 added to `docker-compose.yml`.
- **Hybrid CoV filtering**: `CoVFilter` with three threshold types: `"exact"` (state changes), `"always"` (counters), `float` (absolute deadband). Max staleness timeout (300s) forces periodic writes. Device summaries always written, per-port/radio metrics CoV-filtered.
- **LatestValueCache**: In-memory dict keyed by device MAC, updated on every WebSocket message. Zero-latency reads for impact analysis (`get_all_for_site()`) and AI chat. Replaces HTTP API polling in `SiteDataCoordinator` when cache has fresh data (< 60s).
- **Device-type extractors** (`extractors/`): Pure functions parsing raw WebSocket payloads into InfluxDB data points. `ap_extractor` (device_summary + radio_stats), `switch_extractor` (device_summary + port_stats + module_stats), `gateway_extractor` (SRX standalone/cluster + SSR — gateway_health, gateway_wan, gateway_spu, gateway_resources, gateway_cluster, gateway_dhcp).
- **Ingestion pipeline** (`services/ingestion_service.py`): Consumes from asyncio.Queue, dispatches to extractors, applies CoV filtering, writes to InfluxDB + cache. Tracks message rate and error stats.
- **MistWsManager** (`services/mist_ws_manager.py`): Manages WebSocket connections with auto-scaling (`ceil(sites / 1000)`), health monitoring (90s no-message threshold), dynamic site add/remove.
- **REST endpoints**: `GET /telemetry/status` (admin), `GET /telemetry/latest/{mac}`, `GET /telemetry/query/range`, `GET /telemetry/query/aggregate` (require_impact_role), `PUT /telemetry/settings`, `POST /telemetry/reconnect` (admin).
- **Config**: `SystemConfig` fields: `telemetry_enabled`, `influxdb_url`, `influxdb_token` (encrypted), `influxdb_org`, `influxdb_bucket`, `telemetry_retention_days`. InfluxDB token encrypted via `encrypt_sensitive_data()`.

**Frontend** (`features/admin/settings/telemetry/`):
- **Settings page**: Enable toggle, InfluxDB connection form (url, org, bucket, token, retention), test connection button, pipeline status display.

## Code Style

**Backend**: Black (120 char lines), Ruff (isort, pycodestyle, pyflakes, bugbear), MyPy with Pydantic plugin. Python 3.10+.

**Frontend**: Prettier (100 char, single quotes), strict TypeScript with `strictTemplates`. See `frontend/CLAUDE.md` for Angular-specific conventions.

## Engineering Principles

### Security

- **Access control**: All endpoints enforce role-based access via `require_admin`, `require_automation_role`, `require_backup_role`, `require_post_deployment_role`, or `require_impact_role` from `app/dependencies.py`. Workflow-scoped endpoints also check `workflow.can_be_accessed_by(current_user)`. MCP write tools mirror REST enforcement via `mcp_user_id_var`.
- **SSRF protection**: Call `validate_outbound_url()` before any outbound HTTP to user-controlled URLs. Exception: local LLM providers (lm_studio, ollama) skip validation.
- **Error sanitization**: Never leak `str(e)` to API clients. Log full errors server-side, return generic messages. Use `_sanitize_execution_error()` for workflow/node error fields.
- **Sensitive data**: Use `encrypt_sensitive_data()` for stored tokens/passwords. Return `*_set: bool` fields in API responses. Empty string in `PUT /admin/settings` clears the field.
- **Session management**: Password changes invalidate all sessions. Login enforces `max_concurrent_sessions`. JTI-based revocation via `UserSession`.
- **Input validation**: Use Pydantic schemas with field validators. Never accept raw `dict = Body(...)`.
- **XSS on LLM output**: All markdown rendered via `marked.parse()` + `DOMPurify.sanitize()`.
- **Password policy**: Use `validate_password_with_policy()` (reads from `SystemConfig`) not `validate_password_strength()` (env only).
- **Prompt safety**: Use `_sanitize_for_prompt()` for all user-sourced values injected into LLM prompts.

### KISS (Keep It Simple)

- Initialize data structures with expected shapes upfront (e.g., `variable_context = {"trigger": {}, "nodes": {}, "results": {}}`).
- Extract small helpers for repeated response construction patterns (e.g., `_user_to_response()` in auth.py).
- Don't add abstractions until the same pattern appears 3+ times.
- **Minimize clicks**: High-frequency actions belong directly on the topbar/toolbar as icon buttons, not hidden in dropdown menus. Keep menus for rare/secondary actions only.

### DRY (Don't Repeat Yourself)

- **Service factories**: Always use `create_mist_service()`, `create_llm_service()`, `create_local_mcp_client()` — never instantiate manually.
- **Response helpers**: Extract `_*_to_response()` helpers for building API responses from documents (e.g., `user_to_response()`, `_dict_to_response()`, `_execution_summary()`).
- **Shared utilities**: Use `facet_counts()`, `strip_template_braces()`, `_sanitize_for_prompt()`, `deep_diff()`, `_paginated_query()` — search codebase before creating new helpers.
- **Variable substitution**: `_substitute_value()` is the single recursive dispatcher; `substitute_in_dict`/`substitute_in_list` are thin wrappers.
- **Node name sanitization**: Use `_sanitize_name()` (spaces to underscores) — consistent across executor, schema service, and frontend variable picker.
- **Celery app**: Import from `app.core.celery_app` — never create Celery instances in modules.
- **Impact analysis sessions**: Use `session_manager` functions — never query/update `MonitoringSession` directly from other modules.
- **Site data coordinator**: Use `SiteDataCoordinator.get_or_create(site_id)` for shared site-level data.

### Efficiency

- **`$facet` aggregation**: Batch multiple count queries into a single DB round-trip per collection.
- **DB-level filtering**: Use MongoDB query operators instead of loading all documents and filtering in Python.
- **Parallel API calls**: Use `asyncio.gather()` for independent API calls (template fetching, MCP connections, gateway data).
- **Caching**: `MistService` config cached with 30s TTL. Topology cached with 30s TTL. LLM status cached with `shareReplay(1)`. Maintenance mode cached with 5s TTL. Call `invalidate_*()` when admin updates settings.
- **WebSocket reuse**: Singleton connection, multiplexed channels. Never close on last unsubscribe.
- **Site data coordinator**: Fetches site-level data once per poll, shares across all active sessions. Org-level upgrade when 3+ sites active.
- **Nightly cleanup**: APScheduler purges old `WorkflowExecution` (3:00 UTC) and `MonitoringSession` (3:30 UTC) based on retention settings.

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

- `listSiteDevicesStats(type="ap"|"switch"|"gateway")` — device stats list; defaults to `type="ap"` when omitted (mistapi default). **The `clients` (LLDP neighbors) array is stripped from site-level list responses.** Use `listOrgDevicesStats(org_id, type, site_id, mac, fields="*")` for full stats including `clients`, or `getSiteDeviceStats(site_id, device_id)` for a single device. `port_stat` may be **empty for gateways**.
- `searchSiteSwOrGwPorts(device_type="switch"|"gateway")` — reliable port status for switches and gateways
- `searchSiteDeviceEvents` (in `devices` module, NOT `events`) — config events: `AP_CONFIGURED`, `SW_CONFIGURED`, `GW_CONFIGURED`, `*_CONFIG_CHANGED_BY_USER`, `AP_CONFIG_CHANGED_BY_RRM`, `*_CONFIG_FAILED`
- Device `status` values: `"connected"` (pass), `"upgrading"`/`"restarting"` (warn), anything else (fail)

### VC Links (Virtual Chassis) — IMPORTANT

**The `vc_links` array in switch stats ONLY contains links that are UP.** Down/disconnected VC links are simply absent from the array. Therefore, every entry in `vc_links` is an active link — do NOT check for an `up` field or filter entries. Counting `len(vc_links)` (or summing dicts) directly gives the number of UP VC ports. **Do not add `.get("up")` or any similar filter — this has been incorrectly flagged by code review multiple times and is WRONG.**

## Maintenance

**Always update these CLAUDE.md files** (root and `frontend/CLAUDE.md`) when making architectural changes, adding new patterns, modifying conventions, or restructuring features. These files are the primary reference for AI-assisted development and must stay accurate. When in doubt, update — stale documentation is worse than none.
