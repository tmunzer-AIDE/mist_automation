# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
npm start          # Dev server at http://localhost:4200 (proxies /api → localhost:8000)
npx ng build       # Production build → dist/frontend/
npx ng test        # Unit tests (Vitest)
```

## Architecture

Angular 21 frontend for the Mist Automation platform. Uses standalone components (no NgModules), functional routing with lazy loading, and NgRx for auth state.

### Project Layout

- `src/app/core/` — Singleton services, models, guards, interceptors, NgRx auth state
- `src/app/features/` — Lazy-loaded feature areas: auth, dashboard, admin, backup, workflows, profile
- `src/app/shared/` — Reusable components (DataTable, StatusBadge, ConfirmDialog, PageHeader), directives (hasRole), pipes (fileSize, relativeTime), validators
- `src/app/layout/` — Responsive sidebar + topbar shell (wraps authenticated routes)

### Key Patterns

- **All components are standalone** — no NgModules anywhere
- **New control flow syntax** — use `@if`, `@for`, `@switch` (not `*ngIf`, `*ngFor`)
- **Dependency injection** via `inject()` function, not constructor injection
- **ApiService** (`core/services/api.service.ts`) is the single HTTP client; all API calls go through it with base URL `/api/v1`
- **NgRx** is only used for auth state (`core/state/auth/`); feature state uses service-local observables
- **HTTP interceptors**: `authInterceptor` injects JWT tokens, `errorInterceptor` handles 401 → redirect to login
- **Route guards**: `authGuard` (requires login), `adminGuard` (requires admin role), `onboardGuard` (initial setup)

### Workflow Editor

The workflow editor (`features/workflows/editor/`) is the most complex feature:
- **Pipeline canvas** renders trigger → action blocks with drag/drop
- **Block config panel** uses reactive forms with dynamic FormArrays (branches, save_as bindings, path/query params)
- **API catalog** fetched from backend, filtered by HTTP method matching action type, with dynamic path/query parameter inputs
- **Emit guard pattern**: `private emitting = false` flag in config panel prevents `ngOnChanges` from rebuilding the form when changes originate from the component's own `configChanged` emission

### Backend Proxy

Dev server proxies `/api` and `/health` to `http://localhost:8000` (Python/FastAPI backend). See `proxy.conf.json`.

## Conventions

- **Prettier**: 100 char width, single quotes, Angular HTML parser (config in `package.json`)
- **Strict TypeScript**: All strict flags enabled including `strictTemplates`
- **Angular Material** for all UI components with CSS custom property theming
- **Lazy loading**: Every feature uses `loadChildren` or `loadComponent` in routes
