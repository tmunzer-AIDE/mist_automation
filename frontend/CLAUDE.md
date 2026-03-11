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
- `src/app/shared/` — Reusable components (DataTable, StatusBadge, ConfirmDialog, PageHeader), directives (hasRole), pipes (fileSize, dateTime), validators, utils (chart-defaults)
- `src/app/layout/` — Responsive sidebar + topbar shell (wraps authenticated routes)

### Key Patterns

- **All components are standalone** — no NgModules anywhere
- **New control flow syntax** — use `@if`, `@for`, `@switch` (not `*ngIf`, `*ngFor`)
- **Dependency injection** via `inject()` function, not constructor injection
- **ApiService** (`core/services/api.service.ts`) is the single HTTP client; all API calls go through it with base URL `/api/v1`
- **NgRx** is only used for auth state (`core/state/auth/`); feature state uses service-local observables
- **HTTP interceptors**: `authInterceptor` injects JWT tokens, `errorInterceptor` handles 401 → redirect to login (re-throws original `HttpErrorResponse`)
- **Route guards**: `authGuard` (requires login), `adminGuard` (requires admin role), `onboardGuard` (initial setup)
- **Action metadata**: `ACTION_META` in `core/models/workflow-meta.ts` is the single source of truth for action type icons, colors, and labels — do not duplicate
- **Signals for state**: Use `signal()` for component state, `computed()` for derived values. Never use `ChangeDetectorRef` — signals auto-trigger change detection in zoneless mode.
- **Template reads**: Access signals with `()` syntax: `@if (loading())`, `{{ data().name }}`
- **Subscription cleanup**: Use `takeUntilDestroyed(destroyRef)` for `ngOnInit` subscriptions; use a `rebuild$` subject with `takeUntil` for subscriptions that reset on input changes (see block-config-panel)

### Workflow Editor (Graph-based)

The workflow editor (`features/workflows/editor/`) is the most complex feature, built as an n8n-style node graph editor:

- **Data model**: Workflows use `WorkflowNode[]` + `WorkflowEdge[]` (not a linear pipeline). Each node has `id`, `type`, `position: {x, y}`, `config`, `output_ports[]`. Edges connect `source_node_id:source_port_id` → `target_node_id:target_port_id`.
- **SVG graph canvas** (`editor/canvas/graph-canvas.component`): Raw SVG with pointer events for pan (middle-click/Ctrl+drag), zoom (scroll wheel 0.25–2.0x), node drag, edge creation (drag from output port to input port). Nodes rendered via `<foreignObject>` for Material icons. Edges rendered as cubic Bezier `<path>` elements. Snap-to-grid on node move.
- **Node config panel** (`editor/config/node-config-panel.component`): Side panel that configures the selected node. Uses reactive forms with dynamic FormArrays. The **emit guard pattern** (`private emitting = false`) prevents `ngOnChanges` from rebuilding the form when changes originate from the component's own `configChanged` emission.
- **Variable picker** (`editor/config/variable-picker.component`): Tree view of upstream node output variables. Queries backend for available variables per node. Click-to-insert `{{ variable.path }}` at cursor position.
- **Simulation panel** (`editor/simulation/simulation-panel.component`): Bottom panel for workflow dry-run and step-by-step debugging. Pick a payload (JSON editor or recent webhook events), run simulation, replay node snapshots with per-node input/output inspection and visual execution status on the canvas.
- **Palette sidebar** (`editor/palette/block-palette-sidebar.component`): Uses native HTML drag-and-drop (`draggable="true"` + `dragstart` event setting `dataTransfer`), NOT CDK drag-drop. Emits action type string.
- **Action metadata**: `ACTION_META` in `core/models/workflow-meta.ts` is the single source of truth for action type icons, colors, labels, and default output ports — do not duplicate.
- **API catalog** fetched from backend, filtered by HTTP method matching action type, with dynamic path/query parameter inputs.
- **Port-based branching**: Condition nodes have `branch_0`/`branch_1`/`else` output ports. For-each nodes have `loop_body`/`done` output ports. Trigger nodes have no input port, only a `default` output port.
- **Execution results**: `node_results: Record<string, NodeExecutionResult>` dict keyed by node_id (not a flat array).

### Backend Proxy

Dev server proxies `/api` and `/health` to `http://localhost:8000` (Python/FastAPI backend). See `proxy.conf.json`.

## Conventions

- **Prettier**: 100 char width, single quotes, Angular HTML parser (config in `package.json`)
- **Strict TypeScript**: All strict flags enabled including `strictTemplates`
- **Angular Material** for all UI components with CSS custom property theming
- **Lazy loading**: Every feature uses `loadChildren` or `loadComponent` in routes
- **Tables**: All list pages use `mat-table` inside a `div.table-card` wrapper (global styles in `styles.scss`). Use `.clickable-row` for clickable rows. Pagination: `[25, 50, 100]` with default 25.
- **Loading indicators**: Use `<mat-progress-bar mode="indeterminate">` consistently (not spinners or custom divs)
- **Forms**: Use reactive forms (`ReactiveFormsModule`) for all form inputs including filters — do not use `ngModel`/template-driven forms
- **Confirmations**: Use `ConfirmDialogComponent` via `MatDialog` — do not use native `confirm()`
- **TopbarService**: Use `setActions(templateRef)` / `clearActions()` to inject action buttons into the topbar from feature components
- **ThemeService** (`core/services/theme.service.ts`): Manages dark mode via `preference` signal (`'light' | 'dark' | 'auto'`), persisted to localStorage. Toggles `html.dark-theme` class and `document.body.style.colorScheme`. Injected in `App` to run at startup. Theme selector in Profile > General Settings.
- **`--app-*` CSS custom properties**: All semantic colors (success, error, warning, info, purple, pink, yellow, indigo, neutral, canvas, sim, spinner, chart) are defined as `--app-*` tokens in `styles.scss` `:root` (light) and `.dark-theme` (dark). New components must use these vars — never hardcode hex colors in component SCSS.

## Maintenance

**Always update this CLAUDE.md file** when making architectural changes, adding new patterns, modifying conventions, or changing the workflow editor structure. This file is the primary reference for AI-assisted development and must stay accurate.
