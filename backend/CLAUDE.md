# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
python -m app.main                    # Dev server with auto-reload at http://localhost:8000
pip install -e ".[dev,test]"          # Install with dev + test dependencies

# Testing
pytest                                # All tests with coverage (asyncio_mode=auto, --cov=app)
pytest tests/unit/test_security.py    # Single test file
pytest -k "test_substitute"           # Run tests matching name pattern
pytest -m "unit"                      # Only unit tests
pytest -m "integration"               # Only integration tests

# Code quality
black .                               # Format (120 char lines)
ruff check .                          # Lint (E, W, F, I, B, C4, UP rules)
ruff check --fix .                    # Lint with auto-fix
mypy app                              # Type check (pydantic plugin enabled)
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

Three middleware layers execute in order:
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

Two separate execution mechanisms:
- **Celery** (`app/modules/automation/workers/webhook_worker.py`): Processes webhook-triggered workflows. Max 3 retries, soft timeout from config, prefetch=1.
- **APScheduler** (`app/modules/automation/workers/scheduler.py`): Cron-triggered workflows and scheduled backups. Uses `MemoryJobStore`, `AsyncIOExecutor`, UTC timezone, `coalesce=True`, `max_instances=1`.

For simple fire-and-forget async work, use `create_background_task(coro, name)` from `app.core.tasks` — it wraps `asyncio.create_task()` with error logging via done callbacks.

### Variable Substitution (app/utils/variables.py)

Workflow actions use Jinja2 `SandboxedEnvironment` with `ChainableUndefined` for safe nesting. Key functions:
- `substitute_variables(template_string, context)` — resolves `{{variable}}` expressions
- `substitute_in_dict(data, context)` — recursively substitutes in nested dicts/lists
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
- **Error messages**: Never leak `str(e)` to API clients. Log full errors server-side with structlog, return generic messages in HTTP responses.
- **SSRF**: Call `validate_outbound_url()` before any outbound HTTP request to a user-controlled URL.
- **Session invalidation**: Password changes must invalidate all other sessions. Login enforces `max_concurrent_sessions`.
- **Input validation**: Admin settings use Pydantic schemas with validators, not raw dicts.
- **Re-raise from**: Always use `raise ... from e` or `raise ... from None` in except clauses (ruff B904).

## DRY Conventions

- **MistService**: Always instantiate via `create_mist_service()` factory — never inline config+decrypt.
- **Template braces**: Use `strip_template_braces()` from `app/utils/variables.py` for `{{ }}` stripping.
- **API methods**: `MistService._api_call()` is the single implementation; thin wrappers for each HTTP verb.
- **Shared helpers**: Extract common field construction into helpers (e.g., `_event_fields()`, `_user_to_response()`).

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
