# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mist Automation Platform — a full-stack application for automating Juniper Mist network operations via webhook-driven workflows and scheduled configuration backups. Python/FastAPI backend + Angular 21 frontend.

## Commands

See `backend/CLAUDE.md` and `frontend/CLAUDE.md` for build, test, and lint commands.

**Prerequisites**: MongoDB on localhost:27017, Redis on localhost:6379, InfluxDB 2.7 on localhost:8086 (optional, for telemetry). Use `docker-compose up` to start all services, or configure via `.env`. Copy `.env.example` to `.env` and set `SECRET_KEY`, `MIST_API_TOKEN`, `MIST_ORG_ID`.

## Architecture

### Backend (FastAPI + Beanie/MongoDB)

**Module registry pattern**: All features register in `app/modules/__init__.py` as `AppModule` entries. To add a new module: create `app/modules/<name>/` with models and services, create a router at `app/api/v1/<name>.py`, then add one `AppModule(...)` to the `MODULES` list.

**Key layers**:
- `app/api/v1/` — All route handlers (auth, users, admin, webhooks, automation, backup, reports, llm, impact_analysis, telemetry, power_scheduling)
- `app/modules/` — Feature module internals (models, services, schemas, workers): `automation`, `backup`, `reports`, `impact_analysis`, `telemetry`, `llm`, `mcp_server`, `power_scheduling`
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

**Dedicated collector** (`app/webhook_server.py`): Optional lightweight FastAPI app on port 9000 for internet-facing webhook ingestion. Reuses the same webhook router with minimal middleware (no frontend, no auth routes, no scheduler). Deploy as a separate container with different CMD — see Helm chart `webhookCollector` values and `docker-compose.yml`. Backward compatible: if not deployed, the main app handles webhooks on port 8000.

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

See `backend/app/modules/reports/CLAUDE.md` for full details.

### Workflow Editor (Graph-based)

See `backend/app/modules/automation/CLAUDE.md` for full details.

### LLM Module

See `backend/app/modules/llm/CLAUDE.md` and `backend/app/modules/mcp_server/CLAUDE.md` for full details.

The MCP server at `/mcp` (streamable HTTP) is reachable by external MCP clients using Personal Access Tokens created from Profile → Tokens. `MCPAuthMiddleware` accepts both JWTs (in-app) and PATs (external).

### LLM Memory System

Per-user persistent memory (key-value store) exposed via MCP tools (`memory_store`, `memory_recall`, `memory_forget`) in interactive chat contexts. Weekly "dreaming" consolidation job merges/deduplicates entries via LLM. User management in profile page, admin consolidation logs in LLM settings. See `backend/app/modules/llm/CLAUDE.md` and `backend/app/modules/mcp_server/CLAUDE.md` for details.

### Impact Analysis Module

See `backend/app/modules/impact_analysis/CLAUDE.md` for full details.
Change groups correlate sessions triggered by the same audit event — see module CLAUDE.md.

### Telemetry Module

See `backend/app/modules/telemetry/CLAUDE.md` for full details.

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

- **Service factories**: Always use `create_mist_service()`, `create_llm_service()`, `create_local_mcp_client()`, `await GitService.create()` — never instantiate manually.
- **Response helpers**: Extract `_*_to_response()` helpers for building API responses from documents (e.g., `user_to_response()`, `_dict_to_response()`, `_execution_summary()`).
- **Shared utilities**: Use `facet_counts()`, `strip_template_braces()`, `_sanitize_for_prompt()`, `deep_diff()`, `_paginated_query()` — search codebase before creating new helpers.
- **Variable substitution**: `_substitute_value()` is the single recursive dispatcher; `substitute_in_dict`/`substitute_in_list` are thin wrappers.
- **Node name sanitization**: Use `_sanitize_name()` (spaces to underscores) — consistent across executor, schema service, and frontend variable picker.
- **Celery app**: Import from `app.core.celery_app` — never create Celery instances in modules.
- **Impact analysis sessions**: Use `session_manager` functions — never query/update `MonitoringSession` directly from other modules.
- **Site data coordinator**: Use `SiteDataCoordinator.get_or_create(site_id)` for shared site-level data.
- **Aggregation window summaries**: Use `AggregationWindow.to_summary()` model method — never build summary dicts inline.

### Efficiency

- **`$facet` aggregation**: Batch multiple count queries into a single DB round-trip per collection.
- **DB-level filtering**: Use MongoDB query operators instead of loading all documents and filtering in Python.
- **Parallel API calls**: Use `asyncio.gather()` for independent API calls (template fetching, MCP connections, gateway data).
- **Caching**: `MistService` config cached with 30s TTL. Topology cached with 30s TTL. LLM status cached with `shareReplay(1)`. Maintenance mode cached with 5s TTL. Call `invalidate_*()` when admin updates settings.
- **WebSocket reuse**: Singleton connection, multiplexed channels. Never close on last unsubscribe.
- **Site data coordinator**: Fetches site-level data once per poll, shares across all active sessions. Org-level upgrade when 3+ sites active.
- **Nightly cleanup**: APScheduler purges old `WorkflowExecution` (3:00 UTC) and `MonitoringSession` (3:30 UTC) based on retention settings.

## Mist Cloud Object Model

See `backend/CLAUDE.md` for the full Mist API reference (object hierarchy, template assignments, gateway config, device stats quirks including the VC Links gotcha).

## Maintenance

**Always update the relevant CLAUDE.md files** when making architectural changes, adding new patterns, modifying conventions, or restructuring features. Files:
- Root `CLAUDE.md` — global architecture, principles, webhook routing
- `backend/CLAUDE.md` — backend patterns, Mist API reference
- `frontend/CLAUDE.md` — Angular patterns and conventions
- `backend/app/modules/*/CLAUDE.md` — per-module details (automation, llm, mcp_server, impact_analysis, telemetry, reports)

These files are the primary reference for AI-assisted development and must stay accurate. When in doubt, update — stale documentation is worse than none.
