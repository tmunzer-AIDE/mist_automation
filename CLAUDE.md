# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mist Automation & Backup — a full-stack application for automating Juniper Mist network operations via webhook-driven workflows and scheduled configuration backups. Python/FastAPI backend + Angular 21 frontend.

## Commands

### Backend (run from `backend/`)

```bash
python -m app.main                    # Dev server with auto-reload at http://localhost:8000
pip install -e ".[dev,test]"          # Install with dev + test dependencies

# Testing
pytest                                # All tests with coverage
pytest tests/unit/test_security.py    # Single test file
pytest -m "unit"                      # Only unit tests
pytest -m "integration"               # Only integration tests

# Code quality
black .                               # Format
ruff check .                          # Lint
mypy app                              # Type check
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

**Frontend** (`features/workflows/editor/`):
- **SVG graph canvas** (`canvas/graph-canvas.component`): Raw SVG with pan/zoom/drag, cubic Bezier edges, `foreignObject` for Material node rendering, snap-to-grid.
- **Node config panel** with emit guard pattern (`private emitting = false`) to prevent form rebuild loops.
- **Variable picker**: Tree view of upstream node outputs with click-to-insert `{{ variable.path }}`. Node names are sanitized (spaces→underscores) for valid Jinja2 dot notation. `set_variable` results appear in a "Variables" section as top-level variables (e.g., `{{ site_id }}`).
- **Simulation panel**: Bottom panel for dry-run and step-by-step replay with visual execution status on canvas.
- **Palette sidebar**: Native HTML drag-and-drop (not CDK), emits action type string.
- **Port-based branching**: Condition nodes → `branch_0`/`branch_1`/`else` ports; for-each → `loop_body`/`done` ports.
- **Sub-flows**: Workflows can be `standard` (trigger-based) or `subflow` (callable from other workflows). Sub-flows use `subflow_input` entry node + `subflow_output` terminal node with explicit `input_parameters`/`output_parameters`. Standard workflows call sub-flows via `invoke_subflow` action nodes with input mappings.

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

### KISS (Keep It Simple)

- Initialize data structures with expected shapes upfront (e.g., `variable_context = {"trigger": {}, "nodes": {}, "results": {}}`).
- Extract small helpers for repeated response construction patterns (e.g., `_user_to_response()` in auth.py).
- Don't add abstractions until the same pattern appears 3+ times.
- **Minimize clicks**: High-frequency actions belong directly on the topbar/toolbar as icon buttons, not hidden in dropdown menus. Keep menus for rare/secondary actions only.

### DRY (Don't Repeat Yourself)

- **MistService instantiation**: Always use `create_mist_service()` from `app.services.mist_service_factory` — never manually create MistService with config+decrypt inline.
- **Template brace stripping**: Use `strip_template_braces()` from `app/utils/variables.py` instead of inline `{{ }}` removal.
- **MistService API methods**: `_api_call()` is the single implementation for GET/POST/PUT/DELETE; thin wrappers (`api_get`, `api_post`, etc.) delegate to it.
- **Webhook response helpers**: `_event_fields()` in `webhooks.py` provides shared fields used by both REST responses and WebSocket monitor dicts.
- **Variable substitution dispatch**: `_substitute_value()` in `app/utils/variables.py` is the single recursive dispatcher for str/dict/list types; `substitute_in_dict` and `substitute_in_list` are thin wrappers.
- **Node name sanitization**: Use `_sanitize_name()` from `executor_service.py` (spaces→underscores) when storing or referencing node names as variable keys. The schema service, executor, and frontend variable picker all use the same convention.
- **Workflow execution response helpers**: `_execution_summary()`, `_node_result_to_dict()`, and `_snapshot_to_dict()` in `automation/router.py` build response dicts from aggregation results, `NodeExecutionResult`, and `NodeSnapshot` objects respectively — never inline these dict comprehensions.
- **Report response construction**: `_dict_to_response()` in `reports/router.py` builds `ReportJobResponse` from raw MongoDB aggregation dicts; `_job_to_response()` builds from `ReportJob` documents.

### Efficiency

- **MongoDB `$facet` aggregation**: Admin stats endpoint uses `$facet` to batch multiple count queries into a single DB round-trip per collection.
- **DB-level filtering**: Webhook worker uses `$elemMatch` queries to filter workflows at the database level instead of loading all enabled workflows and filtering in Python.
- **Render context caching**: Executor service caches the Jinja2 render context per node execution (`_cached_render_context`), invalidated after each node completes.
- **Batch gateway API calls**: Validation service pre-fetches all gateway device configs (`listSiteDevices`) and port stats (`searchSiteSwOrGwPorts`) in a single parallel call, then distributes to per-gateway validators — avoids N+1 API calls.
- **Parallel template fetching**: `_fetch_all_templates` uses `asyncio.gather` to fetch all 6 derived template types concurrently instead of sequentially.

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

## Maintenance

**Always update these CLAUDE.md files** (root and `frontend/CLAUDE.md`) when making architectural changes, adding new patterns, modifying conventions, or restructuring features. These files are the primary reference for AI-assisted development and must stay accurate. When in doubt, update — stale documentation is worse than none.
