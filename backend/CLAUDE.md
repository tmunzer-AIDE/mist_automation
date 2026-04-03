# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands below must be run from `backend/` using the virtual environment at `.venv/`:

```bash
# Activate venv (or prefix commands with .venv/bin/)
source .venv/bin/activate

.venv/bin/python -m app.main          # Dev server with auto-reload at http://localhost:8000
.venv/bin/pip install -e ".[dev,test]" # Install with dev + test dependencies

# Testing
.venv/bin/pytest                                # All tests with coverage (asyncio_mode=auto, --cov=app)
.venv/bin/pytest tests/unit/test_security.py    # Single test file
.venv/bin/pytest -k "test_substitute"           # Run tests matching name pattern
.venv/bin/pytest -m "unit"                      # Only unit tests
.venv/bin/pytest -m "integration"               # Only integration tests

# Code quality
.venv/bin/black .                               # Format (120 char lines)
.venv/bin/ruff check .                          # Lint (E, W, F, I, B, C4, UP rules)
.venv/bin/ruff check --fix .                    # Lint with auto-fix
.venv/bin/mypy app                              # Type check (pydantic plugin enabled)
```

## Architecture

FastAPI backend with Beanie ODM (MongoDB) and async throughout. See root `CLAUDE.md` for the full-stack overview.

### Startup Lifecycle (app/main.py)

The app uses FastAPI's `lifespan` context manager:
1. **Startup**: `Database.connect_db()` → `start_smee()` (if enabled) → `start_scheduler()`
2. **Shutdown**: `stop_scheduler()` → `stop_smee()` → `Database.close_db()`

Modules are registered via `MODULES` list in `app/modules/__init__.py` — each `AppModule` declares its router import path (in `app/api/v1/`) and model classes. All route handlers live in `app/api/v1/`; module internals (models, services, schemas, workers) live in `app/modules/<name>/`. `get_all_document_models()` collects models for Beanie initialization.

### Configuration Cascade

`app/config.py` uses pydantic-settings `BaseSettings` with `@lru_cache`. Values load from `.env` file, then environment variables override. Access anywhere via `from app.config import settings`.

### Request Pipeline

Three middleware layers execute in order (all inherit from `_SkipWebSocketMiddleware` which auto-bypasses WebSocket connections):
1. `RequestLoggingMiddleware` — generates `request_id`, logs method/path/IP, adds `X-Request-ID` header
2. `ExceptionHandlerMiddleware` — catches `MistAutomationException` subclasses → standardized JSON errors
3. `SecurityHeadersMiddleware` — adds HSTS, X-Frame-Options, X-Content-Type-Options, CSP, Permissions-Policy

### Authentication Flow

JWT with session tracking. `get_current_user_from_token()` (in `app/dependencies.py`) extracts the Bearer token, decodes JWT, looks up `UserSession` by `token_jti`, verifies expiration, returns the `User` document. Admin-only routes use `require_admin` which chains on top.

### Exception Hierarchy (app/core/exceptions.py)

All custom exceptions inherit from `MistAutomationException(message, status_code, details)`. Subclasses are organized by domain: Auth (`InvalidCredentialsException`, `TokenExpiredException`, `TwoFactorRequiredException`), Workflow (`WorkflowNotFoundException`, `WorkflowValidationException`), Backup (`RestoreException`, `GitOperationException`), etc. The `ExceptionHandlerMiddleware` catches these and returns proper HTTP responses.

### Webhook Gateway (app/api/v1/webhooks.py)

Single entry point `POST /webhooks/mist` receives all Mist webhooks. See root `CLAUDE.md` → "Webhook Event Routing" for the full routing architecture (dispatch modes, consumer handler signatures, fan-out behavior).

Current limitation: routing is hardcoded — adding a new consumer requires editing `webhooks.py`. A pub/sub event bus design exists at `docs/superpowers/specs/2026-03-26-webhook-event-bus-design.md`.

Smee.io forwarding (`app/core/smee_service.py`) connects to a Smee SSE channel and replays events to the local webhook endpoint for development. It bypasses signature verification.

### Worker Patterns

Shared Celery app defined in `app/core/celery_app.py` — both automation and backup modules import from there (never create Celery instances in modules directly).

Two separate execution mechanisms:
- **Celery** (`app/modules/automation/workers/webhook_worker.py`): Processes webhook-triggered workflows. Max 3 retries, soft timeout from config, prefetch=1.
- **APScheduler** (`app/modules/automation/workers/scheduler.py`): Cron-triggered workflows and scheduled backups. Uses `MemoryJobStore`, `AsyncIOExecutor`, UTC timezone, `coalesce=True`, `max_instances=1`.

For simple fire-and-forget async work, use `create_background_task(coro, name)` from `app.core.tasks` — it wraps `asyncio.create_task()` with error logging via done callbacks.

### Impact Analysis Workers

The impact analysis module uses `create_background_task()` async coroutines (not Celery) for long-lived monitoring sessions. `recover_active_sessions()` is called during application startup to resume interrupted sessions. `SiteDataCoordinator` manages shared API call batching across concurrent sessions.

### Workflow Failure Notifications (app/modules/automation/workers/notification_helper.py)

`notify_workflow_failure(workflow, execution)` dispatches failure alerts to Slack, Email, PagerDuty, or ServiceNow based on `workflow.failure_notification` config. Called from both `webhook_worker.py` and `cron_worker.py` via `create_background_task()` when execution status is FAILED or TIMEOUT. Catches all exceptions — notification failures never affect execution state.

### Execution Cleanup (app/modules/automation/workers/cleanup_worker.py)

`cleanup_old_executions()` deletes `WorkflowExecution` documents older than `SystemConfig.execution_retention_days` (default 90). Scheduled by APScheduler as a nightly job at 3:00 UTC.

### Maintenance Mode (app/core/middleware.py)

`MaintenanceModeMiddleware` returns 503 for all non-admin/auth requests when `SystemConfig.maintenance_mode` is True. Bypasses: `/health`, `/api/v1/auth/*`, `/api/v1/admin/*`, `/mcp`. Uses 5-second cache (`set_maintenance_cache()` invalidates on admin settings update).

### Integration Test Endpoints

Three admin-only POST endpoints for testing outbound notification channels:
- `POST /admin/integrations/test-slack` — sends test Slack message
- `POST /admin/integrations/test-servicenow` — validates ServiceNow auth
- `POST /admin/integrations/test-pagerduty` — validates PagerDuty key format

All accept optional config overrides in request body (test before saving). Return `{"status": "connected"|"failed", "error": ...}`.

### Variable Substitution (app/utils/variables.py)

Workflow actions use Jinja2 `SandboxedEnvironment` with `ChainableUndefined` for safe nesting. Entry point: `substitute_variables(template_string, context)`. `build_context()` combines webhook data, API results, workflow context, and allowed env vars. `get_nested_value(data, dotted_path)` for dot-notation access.

### Encryption & Mist API

- `app/core/security.py`: AES-256-GCM via `encrypt_sensitive_data()` / `decrypt_sensitive_data()` using PBKDF2 from `settings.secret_key`.
- `create_mist_service()` from `app.services.mist_service_factory` handles config lookup and token decryption. `MistService` wraps `mistapi` with `asyncio.to_thread()`. Regions: `global_01` → api.mist.com, `emea_01` → api.eu.mist.com, `apac_01` → api.ac5.mist.com.
- `validate_outbound_url()` from `app/utils/url_safety.py` blocks private/reserved/loopback IPs. Required before outbound HTTP to user-controlled URLs.

## Key Patterns

- **Models use `TimestampMixin`** for `created_at`/`updated_at` — call `update_timestamp()` before save
- **`SystemConfig` is a singleton** — use `await SystemConfig.get_config()` which creates one if missing
- **`AuditLog.log_event()`** is a class method that creates and saves in one call
- **`UserSession` has a TTL index** on `expires_at` — MongoDB auto-cleans expired sessions
- **Module-specific models** live in their module dirs (e.g., `app/modules/automation/models/`), not in `app/models/`
- **Shared models** (User, UserSession, SystemConfig, AuditLog) live in `app/models/`

## Security Conventions

See root `CLAUDE.md` Security section for full conventions. Backend-specific additions:
- Use `_sanitize_execution_error()` from `executor_service.py` for workflow/node error fields
- Use `validate_password_with_policy()` (reads from `SystemConfig`) not `validate_password_strength()` (env only)
- MCP write tools must enforce role/ownership checks via `mcp_user_id_var`
- Always use `raise ... from e` or `raise ... from None` in except clauses (ruff B904)

## DRY Conventions

See root `CLAUDE.md` DRY section for full conventions. Backend-specific additions:
- `MistService._api_call()` is the single implementation; thin wrappers for each HTTP verb
- `_event_fields()` in `webhooks.py` provides shared webhook monitor fields
- `_execution_summary()`, `_node_result_to_dict()` in `automation/router.py` for execution responses
- `_execute_syslog()` in `executor_service.py` handles both RFC 5424 and CEF — do not create a separate syslog service

## Testing

Tests use `pytest-asyncio` with `asyncio_mode = "auto"` — async test functions run automatically without `@pytest.mark.asyncio`.

Key fixtures in `tests/conftest.py`:
- `test_db` — creates isolated `mist_automation_test` MongoDB, initializes Beanie, drops DB after test
- `test_user` — creates admin user (email: `test@example.com`, password: `Test123!`, all roles)
- `client` — `httpx.AsyncClient` with mocked lifespan and auth dependency overridden to return `test_user`

## API Testing

- **Swagger UI**: http://localhost:8000/api/v1/docs — full endpoint reference
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

## Code Style

Black (120 char), Ruff (isort + pycodestyle + pyflakes + bugbear + comprehensions + pyupgrade), MyPy with Pydantic plugin. Python >=3.10. See `pyproject.toml` for full config.

## OpenAPI Specification

When modifying API endpoints, update the OpenAPI spec in `openapi.yaml` accordingly. This file is used for generating API client SDKs and must be kept in sync with the actual implementation. Use `openapi-generator validate -i ./openapi.yaml` to validate the spec after editing.

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