# Frontend Design Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all Critical/Major/Minor issues found in the full-frontend `/design-for-ai:exam` audit pass.

**Architecture:** Pure SCSS/HTML fixes — no new components, no new services. Changes fall into four categories: (1) font-size minimums, (2) CSS token hygiene, (3) deprecated `::ng-deep` removal, (4) minor interaction/visual polish.

**Tech Stack:** Angular 21, Angular Material 3, SCSS with CSS custom properties (`--app-*`, `--mat-sys-*`, `--mdc-*` tokens).

---

## Files to modify

| File | What changes |
|---|---|
| `backup/detail/backup-object-detail.component.scss` | `.mini` 9→11px, `.diff-type-badge` 10→11px, `.ref-type-badge` 10→11px, `.ref-field` 10→11px, `.field-chip` 10→11px |
| `backup/detail/backup-detail.component.scss` | `.log-lvl` 10→11px, `.log-ph` 10→11px |
| `admin/system-logs/system-logs.component.scss` | `.col-level` 10→11px, spinner `::ng-deep circle` → CSS token, remove dead select-panel rule, fix `--app-purple-chip` usage |
| `workflow-list.component.scss` | `.type-badge` 10→11px, `.tag-chip` 10→11px |
| `layout/sidebar/sidebar.component.scss` | `.app-name-sub` 10→11px |
| `workflow-editor/canvas/graph-canvas.component.scss` | `.port-label` 10→11px, `.input-port` `#fff` fallback → `transparent` |
| `styles.scss` | `transition: all` → specific properties; define `--app-neutral-text`, `--app-neutral-border`, `--app-purple-chip` tokens |
| `monitoring/webhook-monitor/webhook-monitor.component.scss` | Spinner `::ng-deep circle` → CSS token |
| `impact-analysis/session-list/session-list.component.scss` | Progress bar `::ng-deep` → CSS token, form field subscript `::ng-deep` → remove |
| `impact-analysis/session-list/session-list.component.html` | Add `subscriptSizing="dynamic"` to 2 form fields |
| `dashboard/dashboard.component.scss` | `.highlight-card` hover opacity → background, `.hero-stat-label` + `.recent-time` 11→12px |

All paths are relative to `frontend/src/app/` unless otherwise noted (`styles.scss` is `frontend/src/`).

---

## Task 1 — Typography sweep: raise all sub-11px font sizes

**Files:**
- Modify: `frontend/src/app/features/backup/detail/backup-object-detail.component.scss`
- Modify: `frontend/src/app/features/backup/detail/backup-detail.component.scss`
- Modify: `frontend/src/app/features/admin/system-logs/system-logs.component.scss`
- Modify: `frontend/src/app/features/workflows/list/workflow-list.component.scss`
- Modify: `frontend/src/app/layout/sidebar/sidebar.component.scss`
- Modify: `frontend/src/app/features/workflows/editor/canvas/graph-canvas.component.scss`

**Why:** 11px is the absolute minimum legible size. 9–10px text fails WCAG SC 1.4.4 (resize text) and reads as noise rather than information on HiDPI displays.

- [ ] **Step 1: Fix `backup-object-detail.component.scss`**

  Five changes in this file:

  Change 1 — `.diff-type-badge` base (the shorthand `font:` line):
  ```scss
  // Before
  .diff-type-badge {
    font: 700 10px/1 inherit;
  ```
  ```scss
  // After
  .diff-type-badge {
    font: 700 11px/1 inherit;
  ```

  Change 2 — `.diff-type-badge.mini` override (9px → remove the font-size line, let base 11px apply):
  ```scss
  // Before
  &.mini { font-size: 9px; padding: 1px 6px; }
  ```
  ```scss
  // After
  &.mini { padding: 1px 6px; }
  ```

  Change 3 — `.ref-type-badge`:
  ```scss
  // Before
  .ref-type-badge { flex-shrink: 0; font-size: 10px; font-weight: 600; padding: 1px 8px;
  ```
  ```scss
  // After
  .ref-type-badge { flex-shrink: 0; font-size: 11px; font-weight: 600; padding: 1px 8px;
  ```

  Change 4 — `.ref-field`:
  ```scss
  // Before
  .ref-field { flex-shrink: 0; font-size: 10px; font-family: var(--app-font-mono);
  ```
  ```scss
  // After
  .ref-field { flex-shrink: 0; font-size: 11px; font-family: var(--app-font-mono);
  ```

  Change 5 — `.field-chip`:
  ```scss
  // Before
  .field-chip {
    font-size: 10px;
    padding: 1px 6px;
  ```
  ```scss
  // After
  .field-chip {
    font-size: 11px;
    padding: 1px 6px;
  ```

- [ ] **Step 2: Fix `backup-detail.component.scss`**

  Change 1 — `.log-lvl`:
  ```scss
  // Before
  .log-lvl {
    ...
    font-size: 10px;
    font-weight: 700;
  ```
  ```scss
  // After
  .log-lvl {
    ...
    font-size: 11px;
    font-weight: 700;
  ```

  Change 2 — `.log-ph`:
  ```scss
  // Before
  .log-ph {
    font-size: 10px;
    font-weight: 500;
  ```
  ```scss
  // After
  .log-ph {
    font-size: 11px;
    font-weight: 500;
  ```

- [ ] **Step 3: Fix `system-logs.component.scss`**

  One change — `.col-level`:
  ```scss
  // Before
  .col-level {
    flex-shrink: 0;
    width: 52px;
    text-align: center;
    font-weight: 700;
    font-size: 10px;
  ```
  ```scss
  // After
  .col-level {
    flex-shrink: 0;
    width: 52px;
    text-align: center;
    font-weight: 700;
    font-size: 11px;
  ```

- [ ] **Step 4: Fix `workflow-list.component.scss`**

  Change 1 — `.type-badge`:
  ```scss
  // Before
  .type-badge {
    display: inline-block;
    font-size: 10px;
  ```
  ```scss
  // After
  .type-badge {
    display: inline-block;
    font-size: 11px;
  ```

  Change 2 — `.tag-chip`:
  ```scss
  // Before
  .tag-chip {
    display: inline-block;
    font-size: 10px;
  ```
  ```scss
  // After
  .tag-chip {
    display: inline-block;
    font-size: 11px;
  ```

- [ ] **Step 5: Fix `sidebar.component.scss`**

  One change — `.app-name-sub` (search for `font-size: 10px` in that file, around line 45):
  ```scss
  // Before
  .app-name-sub {
    font-size: 10px;
  ```
  ```scss
  // After
  .app-name-sub {
    font-size: 11px;
  ```

- [ ] **Step 6: Fix `graph-canvas.component.scss`**

  One change — `.port-label` (around line 192):
  ```scss
  // Before
  .port-label {
    font-size: 10px;
    fill: var(--mat-sys-on-surface-variant, #757575);
  ```
  ```scss
  // After
  .port-label {
    font-size: 11px;
    fill: var(--mat-sys-on-surface-variant, #757575);
  ```

- [ ] **Step 7: Commit typography fixes**

  ```bash
  git add \
    frontend/src/app/features/backup/detail/backup-object-detail.component.scss \
    frontend/src/app/features/backup/detail/backup-detail.component.scss \
    frontend/src/app/features/admin/system-logs/system-logs.component.scss \
    frontend/src/app/features/workflows/list/workflow-list.component.scss \
    frontend/src/app/layout/sidebar/sidebar.component.scss \
    frontend/src/app/features/workflows/editor/canvas/graph-canvas.component.scss
  git commit -m "fix(design): raise all sub-11px font sizes to 11px minimum (WCAG SC 1.4.4)"
  ```

---

## Task 2 — Fix `transition: all` in global styles

**Files:**
- Modify: `frontend/src/styles.scss`

**Why:** `transition: all` includes layout properties (width, height, padding), causing browser layout recalculation on every state change. Should only transition compositor-friendly properties.

- [ ] **Step 1: Replace the global interactive transition rule**

  Find the block (around line 260 in styles.scss):
  ```scss
  // Before
  button:not([disabled]),
  a,
  input:not([disabled]),
  select:not([disabled]),
  textarea:not([disabled]) {
    transition: all var(--app-duration-default) ease;
  }
  ```
  ```scss
  // After
  button:not([disabled]),
  a,
  input:not([disabled]),
  select:not([disabled]),
  textarea:not([disabled]) {
    transition:
      background-color var(--app-duration-default) ease,
      color var(--app-duration-default) ease,
      border-color var(--app-duration-default) ease,
      box-shadow var(--app-duration-default) ease,
      opacity var(--app-duration-default) ease;
  }
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add frontend/src/styles.scss
  git commit -m "fix(design): replace transition:all with specific compositor properties"
  ```

---

## Task 3 — Define missing CSS tokens

**Files:**
- Modify: `frontend/src/styles.scss`
- Modify: `frontend/src/app/features/admin/system-logs/system-logs.component.scss`

**Why:** `system-logs.component.scss` references `--app-neutral-text` (7 uses), `--app-neutral-border` (2 uses), and `--app-purple-chip` (1 use), none of which are defined in `styles.scss`. Missing tokens render as empty (color: nothing = `transparent`/invisible).

- [ ] **Step 1: Define the three tokens in `styles.scss` `:root`**

  In `styles.scss`, find the `// Neutral / disabled` comment block inside `:root` and add after it:
  ```scss
  // Neutral / disabled
  --app-neutral-bg: #fafafa;
  --app-neutral: #757575;
  // ADD these three lines:
  --app-neutral-text: #757575;
  --app-neutral-border: rgba(0, 0, 0, 0.12);
  --app-purple-chip: #7c3aed;
  ```

- [ ] **Step 2: Define the three tokens in `.dark-theme`**

  In `styles.scss`, find the `// Neutral / disabled` block inside `.dark-theme` and add after it:
  ```scss
  --app-neutral-bg: rgba(255, 255, 255, 0.05);
  --app-neutral: #a3a3a3;
  // ADD these three lines:
  --app-neutral-text: #9e9e9e;
  --app-neutral-border: rgba(255, 255, 255, 0.12);
  --app-purple-chip: #c4b5fd;
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/src/styles.scss
  git commit -m "fix(tokens): define missing --app-neutral-text, --app-neutral-border, --app-purple-chip tokens"
  ```

---

## Task 4 — Remove `::ng-deep circle` for spinner colors

**Files:**
- Modify: `frontend/src/app/features/monitoring/webhook-monitor/webhook-monitor.component.scss`
- Modify: `frontend/src/app/features/admin/system-logs/system-logs.component.scss`

**Why:** `::ng-deep` is deprecated in Angular; it will be removed. Angular Material 3 exposes `--mdc-circular-progress-active-indicator-color` as a CSS custom property that cascades into the component without `::ng-deep`.

- [ ] **Step 1: Fix `webhook-monitor.component.scss`**

  ```scss
  // Before (lines 15-26)
  .connection-spinner {
    margin-left: 12px;
    margin-right: 8px;

    &.spinner-disconnected ::ng-deep circle {
      stroke: var(--app-spinner-disconnected) !important;
    }

    &.spinner-paused ::ng-deep circle {
      stroke: var(--app-spinner-paused) !important;
    }

    &.spinner-live ::ng-deep circle {
      stroke: var(--app-spinner-live) !important;
    }
  }
  ```
  ```scss
  // After
  .connection-spinner {
    margin-left: 12px;
    margin-right: 8px;

    &.spinner-disconnected {
      --mdc-circular-progress-active-indicator-color: var(--app-spinner-disconnected);
    }

    &.spinner-paused {
      --mdc-circular-progress-active-indicator-color: var(--app-spinner-paused);
    }

    &.spinner-live {
      --mdc-circular-progress-active-indicator-color: var(--app-spinner-live);
    }
  }
  ```

- [ ] **Step 2: Apply the same fix in `system-logs.component.scss`**

  ```scss
  // Before (lines 21-31)
  .connection-spinner {
    margin-left: 12px;
    margin-right: 8px;

    &.spinner-disconnected ::ng-deep circle {
      stroke: var(--app-spinner-disconnected) !important;
    }

    &.spinner-paused ::ng-deep circle {
      stroke: var(--app-spinner-paused) !important;
    }

    &.spinner-live ::ng-deep circle {
      stroke: var(--app-spinner-live) !important;
    }
  }
  ```
  ```scss
  // After
  .connection-spinner {
    margin-left: 12px;
    margin-right: 8px;

    &.spinner-disconnected {
      --mdc-circular-progress-active-indicator-color: var(--app-spinner-disconnected);
    }

    &.spinner-paused {
      --mdc-circular-progress-active-indicator-color: var(--app-spinner-paused);
    }

    &.spinner-live {
      --mdc-circular-progress-active-indicator-color: var(--app-spinner-live);
    }
  }
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add \
    frontend/src/app/features/monitoring/webhook-monitor/webhook-monitor.component.scss \
    frontend/src/app/features/admin/system-logs/system-logs.component.scss
  git commit -m "fix(a11y): replace ::ng-deep circle with --mdc-circular-progress token for spinner colors"
  ```

---

## Task 5 — Remove `::ng-deep` for progress bar color in session-list

**Files:**
- Modify: `frontend/src/app/features/impact-analysis/session-list/session-list.component.scss`

**Why:** `::ng-deep .mdc-linear-progress__bar-inner` pierces internal Material DOM. Angular Material 3 exposes `--mdc-linear-progress-active-indicator-color` as a cascading token — set it on the parent class instead.

- [ ] **Step 1: Replace the `::ng-deep` progress bar rules**

  In `session-list.component.scss`, find and replace (around lines 91–100):
  ```scss
  // Before
  .bar-completed {
    ::ng-deep .mdc-linear-progress__bar-inner {
      border-color: var(--app-success);
    }
  }

  .bar-failed,
  .bar-cancelled {
    ::ng-deep .mdc-linear-progress__bar-inner {
      border-color: var(--app-error-status);
    }
  }
  ```
  ```scss
  // After
  .bar-completed {
    --mdc-linear-progress-active-indicator-color: var(--app-success);
  }

  .bar-failed,
  .bar-cancelled {
    --mdc-linear-progress-active-indicator-color: var(--app-error-status);
  }
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add frontend/src/app/features/impact-analysis/session-list/session-list.component.scss
  git commit -m "fix(a11y): replace ::ng-deep progress bar with --mdc-linear-progress token"
  ```

---

## Task 6 — Remove `::ng-deep` for form field subscript in session-list

**Files:**
- Modify: `frontend/src/app/features/impact-analysis/session-list/session-list.component.html`
- Modify: `frontend/src/app/features/impact-analysis/session-list/session-list.component.scss`

**Why:** `::ng-deep .mat-mdc-form-field-subscript-wrapper { display: none }` hides the hint/error area below filter fields. Angular Material 3 has a first-class API for this: `subscriptSizing="dynamic"` collapses the subscript area when there is no hint or error — no internal DOM manipulation needed.

- [ ] **Step 1: Add `subscriptSizing="dynamic"` to both filter form fields in `session-list.component.html`**

  Change 1 — View mode filter (line 3):
  ```html
  <!-- Before -->
  <mat-form-field appearance="outline" class="view-mode-filter">
  ```
  ```html
  <!-- After -->
  <mat-form-field appearance="outline" subscriptSizing="dynamic" class="view-mode-filter">
  ```

  Change 2 — Status filter (line 11):
  ```html
  <!-- Before -->
  <mat-form-field appearance="outline" class="status-filter">
  ```
  ```html
  <!-- After -->
  <mat-form-field appearance="outline" subscriptSizing="dynamic" class="status-filter">
  ```

- [ ] **Step 2: Remove the `::ng-deep` subscript rules from `session-list.component.scss`**

  Remove from `.view-mode-filter` (the `::ng-deep` block, leaving only `width: 170px`):
  ```scss
  // Before
  .view-mode-filter {
    width: 170px;

    ::ng-deep .mat-mdc-form-field-subscript-wrapper {
      display: none;
    }
  }
  ```
  ```scss
  // After
  .view-mode-filter {
    width: 170px;
  }
  ```

  Remove from `.status-filter` (the `::ng-deep` block, leaving only `width: 180px`):
  ```scss
  // Before
  .status-filter {
    width: 180px;

    ::ng-deep .mat-mdc-form-field-subscript-wrapper {
      display: none;
    }
  }
  ```
  ```scss
  // After
  .status-filter {
    width: 180px;
  }
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add \
    frontend/src/app/features/impact-analysis/session-list/session-list.component.html \
    frontend/src/app/features/impact-analysis/session-list/session-list.component.scss
  git commit -m "fix(a11y): replace ::ng-deep subscript hide with subscriptSizing=dynamic"
  ```

---

## Task 7 — Remove dead `::ng-deep .mat-mdc-select-panel` rule

**Files:**
- Modify: `frontend/src/app/features/admin/system-logs/system-logs.component.scss`

**Why:** The `.filter-field-logger` block targets `.mat-mdc-select-panel` via `::ng-deep`, but the logger filter uses `mat-chip-grid` + `mat-autocomplete` (not `mat-select`). This rule has never matched anything — it is dead code and should be removed to avoid confusion in future maintenance.

- [ ] **Step 1: Remove the dead rule from `system-logs.component.scss`**

  Find and remove the `::ng-deep` block inside `.filter-field-logger` (lines 56–62):
  ```scss
  // Before
  .filter-field-logger {
    width: 360px;

    ::ng-deep .mat-mdc-select-panel {
      min-width: 400px !important;
    }
  }
  ```
  ```scss
  // After
  .filter-field-logger {
    width: 360px;
  }
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add frontend/src/app/features/admin/system-logs/system-logs.component.scss
  git commit -m "chore: remove dead ::ng-deep .mat-mdc-select-panel rule from system-logs"
  ```

---

## Task 8 — Dashboard: fix hover feedback and raise 11px uppercase labels

**Files:**
- Modify: `frontend/src/app/features/dashboard/dashboard.component.scss`

**Why:** `.highlight-card:hover { opacity: 0.85 }` makes the card's content appear to fade out — opacity hover signals the *element* is disappearing, not the surface reacting. Use a background change instead. Separately, `.hero-stat-label` and `.recent-time` at 11px uppercase reduce effective readability to ~8–9pt — raise to 12px.

- [ ] **Step 1: Replace opacity hover on `.highlight-card`**

  ```scss
  // Before
  .highlight-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 16px;
    border-radius: var(--app-radius-sm);
    cursor: pointer;
    transition: opacity 0.12s;

    &:hover {
      opacity: 0.85;
    }
  ```
  ```scss
  // After
  .highlight-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 16px;
    border-radius: var(--app-radius-sm);
    cursor: pointer;
    transition: background-color var(--app-duration-default) ease;

    &:hover {
      background: var(--mat-sys-surface-container-high);
    }
  ```

- [ ] **Step 2: Raise `.hero-stat-label` from 11px to 12px**

  ```scss
  // Before
  .hero-stat-label {
    font-size: 11px;
    font-weight: 500;
  ```
  ```scss
  // After
  .hero-stat-label {
    font-size: 12px;
    font-weight: 500;
  ```

- [ ] **Step 3: Raise `.recent-time` from 11px to 12px**

  ```scss
  // Before
  .recent-time {
    font-size: 11px;
    color: var(--mat-sys-on-surface-variant);
  ```
  ```scss
  // After
  .recent-time {
    font-size: 12px;
    color: var(--mat-sys-on-surface-variant);
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add frontend/src/app/features/dashboard/dashboard.component.scss
  git commit -m "fix(design): dashboard highlight-card hover background, raise 11px labels to 12px"
  ```

---

## Task 9 — Fix canvas SVG `#fff` fallback

**Files:**
- Modify: `frontend/src/app/features/workflows/editor/canvas/graph-canvas.component.scss`

**Why:** Two places use `#fff` as a fallback for CSS custom properties: `.canvas-toolbar { background: var(--mat-sys-surface, #fff) }` and `.input-port { fill: var(--mat-sys-surface, #fff) }`. A white fallback breaks dark mode if the variable fails to resolve. Safe fallback is `transparent` — the element inherits the page background cleanly.

- [ ] **Step 1: Fix `.canvas-toolbar` background fallback (around line 20)**

  ```scss
  // Before
  .canvas-toolbar {
    ...
    background: var(--mat-sys-surface, #fff);
  ```
  ```scss
  // After
  .canvas-toolbar {
    ...
    background: var(--mat-sys-surface);
  ```

- [ ] **Step 2: Fix `.input-port` fill fallback (around line 182)**

  ```scss
  // Before
  .input-port {
    fill: var(--mat-sys-surface, #fff);
  ```
  ```scss
  // After
  .input-port {
    fill: var(--mat-sys-surface);
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/src/app/features/workflows/editor/canvas/graph-canvas.component.scss
  git commit -m "fix(design): remove #fff dark-mode-breaking fallbacks from canvas SVG"
  ```

---

## Verification

After all tasks complete, visually verify:

1. **Font sizes** — Open backup object detail, backup job detail log stream, system logs column headers, workflow list (type badges, tag chips), sidebar (app sub-name) — all text should be readable at 11px minimum
2. **Spinners** — Connect/disconnect on system-logs or webhook-monitor pages — spinner circle should turn red (disconnected), amber (paused), green (live)
3. **Progress bars** — Impact analysis session list with in-progress sessions — completed bar should be green, failed/cancelled should be red
4. **Session-list filters** — View and Status filter fields should not have extra whitespace below them
5. **Dashboard hover** — Hover over highlight cards (recent changes) — background should shift rather than the card fading out
6. **Dark mode** — Toggle dark mode on each page above — no white flashes on canvas, all text remains visible
