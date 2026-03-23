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

Modules are registered via `MODULES` list in `app/modules/__init__.py` — each `AppModule` declares its router import path and model classes. `get_all_document_models()` collects models for Beanie initialization.

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

Single entry point `POST /webhooks/mist` receives all Mist webhooks:
1. Validates HMAC-SHA256 signature (from `SystemConfig.webhook_secret`)
2. Creates `WebhookEvent` document (deduped by `webhook_id` unique index)
3. Routes to automation module (always) and backup module (if `topic=audits`)
4. Processing runs as a background task via `create_background_task()`

Smee.io forwarding (`app/core/smee_service.py`) connects to a Smee SSE channel and replays events to the local webhook endpoint for development. It bypasses signature verification.

### Worker Patterns

Shared Celery app defined in `app/core/celery_app.py` — both automation and backup modules import from there (never create Celery instances in modules directly).

Two separate execution mechanisms:
- **Celery** (`app/modules/automation/workers/webhook_worker.py`): Processes webhook-triggered workflows. Max 3 retries, soft timeout from config, prefetch=1.
- **APScheduler** (`app/modules/automation/workers/scheduler.py`): Cron-triggered workflows and scheduled backups. Uses `MemoryJobStore`, `AsyncIOExecutor`, UTC timezone, `coalesce=True`, `max_instances=1`.

For simple fire-and-forget async work, use `create_background_task(coro, name)` from `app.core.tasks` — it wraps `asyncio.create_task()` with error logging via done callbacks.

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

Workflow actions use Jinja2 `SandboxedEnvironment` with `ChainableUndefined` for safe nesting. Key functions:
- `substitute_variables(template_string, context)` — resolves `{{variable}}` expressions
- `_substitute_value(value, **kwargs)` — core recursive dispatcher for str/dict/list types
- `substitute_in_dict(data, context)` / `substitute_in_list(data, context)` — thin wrappers around `_substitute_value`
- `build_context()` — combines webhook data, API results, workflow context, and allowed env vars
- `get_nested_value(data, dotted_path)` — dot-notation access like `event.device.name`

### Encryption

`app/core/security.py` provides AES-256-GCM encryption via `encrypt_sensitive_data()` / `decrypt_sensitive_data()` using PBKDF2 key derivation from `settings.secret_key`. Used for storing Mist API tokens in `SystemConfig`.

### Mist API Integration

Always instantiate via `create_mist_service()` from `app.services.mist_service_factory` — it handles config lookup and token decryption. `MistService` wraps the `mistapi` library with `asyncio.to_thread()` for async compatibility. Cloud regions map to: `global_01` → api.mist.com, `emea_01` → api.eu.mist.com, `apac_01` → api.ac5.mist.com.

### SSRF Protection (app/utils/url_safety.py)

`validate_outbound_url(url)` validates scheme (http/https only), resolves hostname, and blocks private/reserved/loopback/link-local IP ranges. Must be called before any outbound HTTP request to a user-controlled URL (webhook actions, generic webhook notifications).

### Admin Settings Validation (app/schemas/admin.py)

`SystemSettingsUpdate` is a Pydantic model with `field_validator` for cron expressions and URLs, plus `Field(ge=, le=)` bounds on numeric settings. Used by `PUT /admin/settings` instead of raw `dict`.

## Key Patterns

- **Models use `TimestampMixin`** for `created_at`/`updated_at` — call `update_timestamp()` before save
- **`SystemConfig` is a singleton** — use `await SystemConfig.get_config()` which creates one if missing
- **`AuditLog.log_event()`** is a class method that creates and saves in one call
- **`UserSession` has a TTL index** on `expires_at` — MongoDB auto-cleans expired sessions
- **Module-specific models** live in their module dirs (e.g., `app/modules/automation/models/`), not in `app/models/`
- **Shared models** (User, UserSession, SystemConfig, AuditLog) live in `app/models/`

## Security Conventions

- **Access control**: Every endpoint must use the appropriate auth dependency: `require_admin`, `require_automation_role`, `require_backup_role`, or `get_current_user_from_token`. Workflow-scoped endpoints must also check `workflow.can_be_accessed_by(current_user)`.
- **Sensitive data**: Use `encrypt_sensitive_data()` / `decrypt_sensitive_data()` for tokens and passwords stored in `SystemConfig`. Return `*_set: bool` fields in API responses instead of actual values.
- **Error messages**: Never leak `str(e)` to API clients. Log full errors server-side with structlog, return generic messages in HTTP responses. Use `_sanitize_execution_error()` from `executor_service.py` for workflow/node error fields.
- **SSRF**: Call `validate_outbound_url()` before any outbound HTTP request to a user-controlled URL.
- **Session invalidation**: Password changes must invalidate all other sessions. Login enforces `max_concurrent_sessions`.
- **Input validation**: Admin settings use Pydantic schemas with validators, not raw dicts.
- **Re-raise from**: Always use `raise ... from e` or `raise ... from None` in except clauses (ruff B904).
- **Password policy**: Use `validate_password_with_policy()` (reads from `SystemConfig` at runtime) instead of `validate_password_strength()` (reads from env only) in endpoint code.
- **MCP access control**: MCP write tools must enforce role/ownership checks via `mcp_user_id_var`, mirroring REST API enforcement.

## DRY Conventions

- **MistService**: Always instantiate via `create_mist_service()` factory — never inline config+decrypt.
- **Template braces**: Use `strip_template_braces()` from `app/utils/variables.py` for `{{ }}` stripping.
- **API methods**: `MistService._api_call()` is the single implementation; thin wrappers for each HTTP verb.
- **Shared helpers**: Extract common field construction into helpers (e.g., `_event_fields()`, `user_to_response()`).
- **Variable substitution dispatch**: `_substitute_value()` is the single recursive dispatcher; `substitute_in_dict`/`substitute_in_list` are thin wrappers.
- **Report response helpers**: `_dict_to_response()` for raw aggregation dicts, `_job_to_response()` for `ReportJob` documents — never inline `ReportJobResponse(...)` construction.
- **Celery app**: Always import from `app.core.celery_app` — never create Celery instances in modules.
- **User response**: `user_to_response()` from `app.schemas.user` — single canonical User→UserResponse builder.
- **LLM service**: Always use `create_llm_service()` factory from `app.modules.llm.services.llm_service_factory`.
- **Syslog format**: `_execute_syslog()` in `executor_service.py` handles both RFC 5424 and CEF format construction — do not create a separate syslog service.
- **DB facet counts**: Use `facet_counts()` from `app.utils.db_helpers` for `$facet`-based count aggregations.

## Testing

Tests use `pytest-asyncio` with `asyncio_mode = "auto"` — async test functions run automatically without `@pytest.mark.asyncio`.

Key fixtures in `tests/conftest.py`:
- `test_db` — creates isolated `mist_automation_test` MongoDB, initializes Beanie, drops DB after test
- `test_user` — creates admin user (email: `test@example.com`, password: `Test123!`, all roles)
- `client` — `httpx.AsyncClient` with mocked lifespan and auth dependency overridden to return `test_user`

## API Testing

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

# Common endpoints
# GET  /api/v1/workflows/              — list workflows
# POST /api/v1/workflows/              — create workflow
# GET  /api/v1/workflows/{id}          — get workflow
# PUT  /api/v1/workflows/{id}          — update workflow
# POST /api/v1/workflows/{id}/simulate — simulate workflow
# GET  /api/v1/backup/jobs             — list backup jobs
# POST /api/v1/backup/jobs             — create backup job
# GET  /api/v1/admin/stats             — system stats (admin only)
# GET  /api/v1/admin/settings          — system settings (admin only)
# PUT  /api/v1/admin/settings          — update settings (admin only)
# GET  /api/v1/admin/users             — list users (admin only)
# GET  /api/v1/admin/audit-logs        — audit logs (admin only)
```

## Code Style

Black (120 char), Ruff (isort + pycodestyle + pyflakes + bugbear + comprehensions + pyupgrade), MyPy with Pydantic plugin. Python >=3.10. See `pyproject.toml` for full config.

## OpenAPI Specification

When modifying API endpoints, update the OpenAPI spec in `openapi.yaml` accordingly. This file is used for generating API client SDKs and must be kept in sync with the actual implementation. Use `openapi-generator validate -i ./openapi.yaml` to validate the spec after editing.