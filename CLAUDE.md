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
- `app/modules/` — Feature modules: `automation` (workflows, workflow execution, cron/webhook workers), `backup` (config snapshots, restore, git versioning)
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
- Lazy-loaded feature areas: auth, dashboard, admin, backup, workflows, profile
- Angular Material with CSS custom property theming
- Dev proxy: `/api` and `/health` → `http://localhost:8000` (see `proxy.conf.json`)

### Workflow Editor (Graph-based)

Most complex feature, spanning both backend and frontend:

**Backend** (`app/modules/automation/`):
- **Graph data model**: `WorkflowNode[]` + `WorkflowEdge[]` replace the old linear trigger + actions pipeline. Each node has `id`, `type`, `position`, `config`, `output_ports`. Edges connect source/target node:port pairs.
- **Graph executor** (`services/executor_service.py`): BFS traversal from trigger node, resolving output ports per node type. Results stored as `node_results: dict[str, NodeExecutionResult]` keyed by node_id.
- **OAS service** (`services/oas_service.py`): Loads Mist OpenAPI Spec, indexes endpoints, generates mock responses for simulation dry-run mode.
- **Node schema service** (`services/node_schema_service.py`): Provides upstream variable schemas for the variable picker, combining OAS data with node-type knowledge.
- **Graph validator** (`services/graph_validator.py`): Validates no orphans, no cycles, exactly one trigger, valid edge references.
- **Simulation endpoint**: `POST /workflows/{id}/simulate` with payload picker and dry-run mode. Returns per-node snapshots (input/output/variables at each step).

**Frontend** (`features/workflows/editor/`):
- **SVG graph canvas** (`canvas/graph-canvas.component`): Raw SVG with pan/zoom/drag, cubic Bezier edges, `foreignObject` for Material node rendering, snap-to-grid.
- **Node config panel** with emit guard pattern (`private emitting = false`) to prevent form rebuild loops.
- **Variable picker**: Tree view of upstream node outputs with click-to-insert `{{ variable.path }}`.
- **Simulation panel**: Bottom panel for dry-run and step-by-step replay with visual execution status on canvas.
- **Palette sidebar**: Native HTML drag-and-drop (not CDK), emits action type string.
- **Port-based branching**: Condition nodes → `branch_0`/`branch_1`/`else` ports; for-each → `loop_body`/`done` ports.

## Code Style

**Backend**: Black (120 char lines), Ruff (isort, pycodestyle, pyflakes, bugbear), MyPy with Pydantic plugin. Python 3.10+.

**Frontend**: Prettier (100 char, single quotes), strict TypeScript with `strictTemplates`. See `frontend/CLAUDE.md` for Angular-specific conventions.

## Maintenance

**Always update these CLAUDE.md files** (root and `frontend/CLAUDE.md`) when making architectural changes, adding new patterns, modifying conventions, or restructuring features. These files are the primary reference for AI-assisted development and must stay accurate. When in doubt, update — stale documentation is worse than none.
