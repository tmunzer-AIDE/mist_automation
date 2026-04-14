# Telemetry UI Redesign

**Date:** 2026-04-13
**Status:** Approved
**Scope:** All telemetry pages except AP detail (already reworked)

---

## Problem Statement

The current telemetry UI suffers from three core issues:

1. **No information hierarchy** — all metrics are presented at equal visual weight; there is no way to quickly identify what matters most
2. **Persistent left sub-sidebar** — the site/device/client selection occupies a fixed left panel inside the telemetry section, consuming horizontal space on every page
3. **Some pages are raw data dumps** — particularly the scope overview and site summary, which stack sections of numbers with no structure, no narrative, and no visual rhythm

---

## Design Approach: Option C — Page Header Context + Tab Navigation

A full-width page-level header replaces the left sub-sidebar. All context selection (site picker, time range) lives in this header. Sub-pages (Summary / Clients / Devices) become tabs within the header. Content areas use a consistent two-column structure: KPI tiles on the left, one contextual chart on the right per section.

**Reference:** AP detail page is already redesigned and serves as the visual reference for the new design language.

---

## Navigation & Page Header

The telemetry left sub-sidebar is removed entirely. Navigation is replaced by a full-width header bar rendered at the top of the telemetry content area (below the main app topbar).

### Three header states

**State 1 — Org-wide (no site selected)**
```
Telemetry                               [🔍 All Sites ▾]  [⏱ 24h ▾]
Org-wide aggregated view · 12 sites
```
- Shows a "12 sites" count badge so users know what is being aggregated
- No tabs (clients/devices lists are too large to be useful at org scope)

**State 2 — Site selected**
```
Telemetry ›
Paris HQ                                [🔍 Paris HQ ▾]  [⏱ 24h ▾]
[Summary]  Clients  Devices
```
- Breadcrumb "Telemetry" is a clickable link back to org view
- Site picker shows the selected site name; clicking opens searchable dropdown to switch sites
- Tabs: Summary / Clients / Devices

**State 3 — Device or client detail**
```
Telemetry › Paris HQ ›
AP-1F-Hall-01  [AP]                     [⏱ 24h ▾]
```
- Full breadcrumb; each ancestor is a clickable link
- No tabs on detail pages
- For client detail: `Telemetry › Paris HQ › Clients › hostname`
- Device type chip (AP / SW / GW) shown in the title
- "stale" badge shown in the title if `last_seen > 60s`
- Time range picker remains available on detail pages

### Site picker behaviour
- Same searchable autocomplete UX as today, relocated to the header
- Selecting a site navigates to that site's Summary tab
- Selecting "All Sites" navigates to the org-wide scope view

### Time range picker
- Options: 1h / 6h / 24h (unchanged)
- Global — affects all charts and queries on the current page
- Persisted via `TelemetryNavService` signal (unchanged)

---

## Scope Overview Page (`/telemetry`)

Single-page org-wide aggregate view. Sections always rendered in this order, hidden entirely if no devices of that type exist in the org.

### Page structure

```
[Header: Telemetry · All Sites · 24h]

Wireless Clients                                   [238 active]
┌─────────────────────────────┬──────────────────────────────┐
│  AVG RSSI   TOTAL TX   RX   │  Protocol  Band  Auth        │
│  Bands: 31×2.4G  5×5G  2×6G │  (3 small doughnuts)        │
└─────────────────────────────┴──────────────────────────────┘

Access Points                              [38 / 40 reporting]
┌──────────────┬──────────────┬────────────────────────────── ┐
│  AVG CPU     │  AVG MEMORY  │                               │
│  CLIENTS     │  BAND UTIL   │   Client count — 24h chart    │
└──────────────┴──────────────┴───────────────────────────────┘

Switches                                    [6 / 6 reporting]
┌──────────────┬──────────────┬───────────────────────────────┐
│  AVG CPU     │  AVG MEMORY  │                               │
│  PORTS UP    │  POE DRAW    │   PoE draw — 24h chart        │
└──────────────┴──────────────┴───────────────────────────────┘

Gateways                                    [1 / 2 reporting]
┌──────────────┬──────────────┬───────────────────────────────┐
│  AVG CPU     │  AVG MEMORY  │                               │
│  WAN LINKS   │  SPU SESS.   │   WAN traffic — 24h (Mbps)   │
└──────────────┴──────────────┴───────────────────────────────┘
```

### KPI tiles

Each tile shows: label (small caps, muted) + value (large, bold). Values are colored when thresholds are exceeded:
- CPU: > 40% → amber, > 80% → red
- Memory: > 70% → amber, > 90% → red
- No color on non-percentage values (client counts, ports, sessions)

### Reporting badge colors
- 100% reporting → green
- 50–99% reporting → amber
- < 50% reporting → red

### Wireless Clients section details
- Left: 3 KPI tiles (Avg RSSI, Total TX Mbps, Total RX Mbps) + 1 wide band-count tile (2.4G / 5G / 6G inline)
- Right: 3 small doughnuts — Protocol split, Band split, Auth split

### AP section details
- 4 KPI tiles: Avg CPU, Avg Memory, Total Clients, Band Util (2.4G and 5G as two-row mini-table inside one tile)
- Chart: Client count over time

### Switch section details
- 4 KPI tiles: Avg CPU, Avg Memory, Ports Up/Total, PoE Draw (W)
- Chart: PoE draw over time

### Gateway section details
- 4 KPI tiles: Avg CPU, Avg Memory, WAN Links Up/Total, SPU Sessions
- Chart: WAN traffic TX + RX over time (Mbps, two lines)

### Traffic chart units
All traffic values displayed in **Mbps** throughout the entire UI. Raw bps values from the backend are converted on the frontend.

---

## Site Summary Page (`/site/:id` → Summary tab)

Identical structure to the scope overview page, but:
- Header shows breadcrumb + site name + tabs (Summary / Clients / Devices)
- All metrics are site-scoped
- WAN traffic chart shows both TX and RX lines (more meaningful at single-site level)
- No "12 sites" badge (not applicable at site level)

---

## Clients Tab (`/site/:id` → Clients tab)

### Page structure

```
[Header: Telemetry › Paris HQ · 24h · Summary | Clients | Devices]

[TOTAL CLIENTS]  [AVG RSSI]  [TOTAL TX Mbps]  [TOTAL RX Mbps]

[Client count — 24h]  [Avg RSSI — 24h]  [Band split]  [Protocol split]
     (line chart)          (line chart)    (doughnut)     (doughnut)

[🔍 Search...]  [All]  [2.4G]  [5G]  [6G]

Table: HOSTNAME/MAC · AP · BAND · RSSI · SNR · TX · RX · AUTH · LAST SEEN
```

### KPI strip
4 tiles: Total Clients, Avg RSSI (dBm), Total TX (Mbps), Total RX (Mbps)

### Charts (4-column grid)
- **Client count over time** (line, blue) — respects time range picker
- **Avg RSSI over time** (line, green) — respects time range picker
- **Radio band split** (doughnut) — 2.4G amber / 5G blue / 6G green — current snapshot
- **Protocol split** (doughnut) — ax / ac / n — current snapshot

### Band filter chips
All / 2.4G / 5G / 6G — filters the table only (charts always show all bands)

### Table columns (9 columns)
| Column | Notes |
|---|---|
| Hostname / MAC | Two-line cell. No hostname → MAC as primary, dimmed |
| AP | AP name |
| Band | Colored chip: 2.4G=amber, 5G=blue, 6G=green |
| RSSI | Colored: > -60 dBm green, -60 to -75 amber, worse red |
| SNR | Colored: > 25 dB green, 15–25 amber, < 15 red |
| TX | Mbps |
| RX | Mbps |
| Auth | PSK / 802.1X |
| Last Seen | HH:MM:SS format |

- Clicking any row navigates to client detail page
- Pagination: 25 / 50 / 100 rows

---

## Devices Tab (`/site/:id` → Devices tab)

### Page structure

```
[Header: Telemetry › Paris HQ · 24h · Summary | Clients | Devices]

[ACCESS POINTS: 12 total · 12/12 reporting]
[SWITCHES: 2 total · 2/2 reporting]
[GATEWAYS: 1 total · 1/2 reporting]

[Avg CPU — 24h]  [Avg Memory — 24h]  [Device types]  [Reporting status]
  (3-line chart)    (3-line chart)     (doughnut)         (doughnut)

[🔍 Search...]  [All (15)]  [AP (12)]  [Switch (2)]  [Gateway (1)]

Table: NAME/MAC · TYPE · MODEL · CPU · MEMORY · KEY METRIC · LAST SEEN
```

### Reporting summary strip
3 tiles (AP / Switch / Gateway), each showing total count + reporting status with green/amber/red badge.

### Charts (4-column grid)
- **Avg CPU over time** — 3 lines: AP (blue), SW (green), GW (amber). Filters when a type chip is active.
- **Avg Memory over time** — same 3 lines
- **Device type doughnut** — fleet composition
- **Reporting status doughnut** — Active (green) vs Stale (red)

### Filter chips
Show device counts per type. Filtering adapts charts and table.

### Table columns (7 columns)
| Column | Notes |
|---|---|
| Name / MAC | Two-line cell. Stale badge inline with name. |
| Type | Colored chip: AP=blue, SW=green, GW=amber |
| Model | Device model string |
| CPU | Colored at thresholds (>40% amber, >80% red) |
| Memory | Colored at thresholds (>70% amber, >90% red) |
| Key Metric | Adapts by type: Clients (AP), Ports up/total (SW), WAN links (GW) |
| Last Seen | Colored red when stale (> 60s) |

- Clicking any row navigates to device detail page
- Pagination: 25 / 50 / 100 rows

---

## Device Detail Pages (Switch & Gateway)

AP detail is unchanged (already reworked). Switch and Gateway detail follow the same structure.

### Shared structure

```
[Header: Telemetry › Paris HQ › Device Name  [TYPE] [stale?]   ⏱ 24h ▾]

[MODEL]  [UPTIME]  [CPU]  [MEMORY]  [KEY1]  [KEY2]
         (6-tile info strip, colored at thresholds)

[Chart 1]          [Chart 2]          [Chart 3]
(CPU & Mem %)      (type-specific)    (type-specific)

▸ Section A    summary line...  ▾
▸ Section B    summary line...  ▾
▸ Section C    summary line...  ▾
▸ Live Events  last event Xs ago  ▾
```

### Switch detail specifics
- Info strip: Model, Uptime, CPU, Memory, Ports Up/Total, PoE Draw
- Chart 1: CPU (solid) & Memory (dashed) over time
- Chart 2: Wired clients over time
- Chart 3: PoE draw over time (W)
- Sections: Modules, Ports, DHCP Networks, Live Events

### Gateway detail specifics
- Info strip: Model, Uptime, CPU, Memory, WAN Links Up/Total, SPU Sessions
- Chart 1: CPU (solid) & Memory (dashed) over time
- Chart 2: WAN traffic TX (solid) + RX (dashed) over time in Mbps
- Chart 3: SPU Sessions (solid) & SPU CPU (dashed) over time
- Sections: WAN Ports, SPU, DHCP Networks, Resources (if present), Cluster (if present), Live Events

### Collapsible sections
Each section (Modules, Ports, WAN Ports, SPU, etc.) renders as a collapsible row using `MatExpansionPanel`:
- **Default state: expanded** — sections are open on first load so content is immediately visible
- Collapsed: section title + one-line summary (e.g. "48 ports · 42 up · 6 down")
- Expanded: full table with all detail
- **Live Events is the exception: collapsed by default** — it is raw data and secondary to the structured sections above it

---

## Client Detail Page

```
[Header: Telemetry › Paris HQ › Clients › hostname  [BAND]   ⏱ 24h ▾]

[AP]  [SSID]  [RSSI]  [SNR]  [AUTH]  [UPTIME]
       (6-tile info strip)

[RSSI over time — 24h]     [Throughput TX/RX — 24h (Mbps)]
      (line, green)               (2 lines, blue)

▸ Live Events   last event Xs ago  [Formatted | Raw JSON]  ▾
```

- Breadcrumb "Clients" links back to the Clients tab of the parent site
- RSSI chart: green line, dBm y-axis
- Throughput chart: TX solid / RX dashed, Mbps
- Live Events: formatted view (tabular: time, RSSI, SNR, TX rate, RX rate, channel) with toggle to raw JSON. Last 100 events, copy-to-clipboard per row.

---

## Color & Threshold Reference

### Status colors (use `--app-*` CSS custom properties)
| State | Color |
|---|---|
| Healthy / OK | `--app-success` (green) |
| Warning | `--app-warning` (amber) |
| Critical | `--app-error` (red) |
| Info / neutral | `--app-info` (blue) |

### CPU thresholds
- < 40% → no color (default text)
- 40–80% → amber
- > 80% → red

### Memory thresholds
- < 70% → no color
- 70–90% → amber
- > 90% → red

### RSSI thresholds
- > -60 dBm → green
- -60 to -75 dBm → amber
- < -75 dBm → red

### SNR thresholds
- > 25 dB → green
- 15–25 dB → amber
- < 15 dB → red

### Device type chip colors
- AP → blue (`--app-info`)
- Switch → green (`--app-success`)
- Gateway → amber (`--app-warning`)

### Band chip colors
- 2.4G → amber
- 5G → blue
- 6G → green

---

## Traffic Unit Convention

**All traffic values are displayed in Mbps.** The backend returns values in bps. Conversion is done on the frontend at display time (`value / 1_000_000`, rounded to 1 decimal place). The unit "Mbps" is always shown inline (or abbreviated "M" in tight table cells).

---

## Pages Not Changed

- **AP detail page** (`/device/:mac` where device_type = AP) — already reworked, kept as-is
- **Backend API** — no changes required; all data already available
- **WebSocket subscriptions** — no changes; same topics, same debouncing

---

## Angular Implementation Notes

- Remove `TelemetryShellComponent` left sidebar template; replace with a shared `TelemetryHeaderComponent` rendered at the top of the content area
- The `TelemetryNavService` signals (site, time range) remain the source of truth; the header component reads and writes them
- Tabs (Summary / Clients / Devices) at site level map to existing child routes — no route changes needed, just the shell template changes
- All collapsible sections use `MatExpansionPanel` (already available via Angular Material)
- Doughnut charts use Chart.js with `animation: { duration: 0 }` to prevent re-animation on WebSocket ticks (per existing feedback)
- Traffic bps → Mbps conversion: create a shared `toMbps(bps: number): string` pipe in `shared/pipes/`
- Stale detection: `Date.now() / 1000 - last_seen > 60` (60-second threshold, unchanged from current `fresh` flag logic)

---

## Implementation Plan

Target: deliver in small, reviewable frontend-only slices without backend/API changes.

### Phase 0 - Baseline and guardrails (0.5 day)
- Capture current telemetry screenshots for: scope, site summary, clients tab, devices tab, switch detail, gateway detail, client detail.
- Confirm no API contract changes are required by validating current `TelemetryService` calls against existing views.
- Add a short implementation checklist issue with links to this spec and affected components.

### Phase 1 - Shared shell and header architecture (1-1.5 days)
- Replace left sub-sidebar shell layout with top header layout in:
  - `frontend/src/app/features/telemetry/telemetry-shell.component.html`
  - `frontend/src/app/features/telemetry/telemetry-shell.component.scss`
  - `frontend/src/app/features/telemetry/telemetry-shell.component.ts`
- Introduce reusable `TelemetryHeaderComponent` under `frontend/src/app/features/telemetry/components/` with three display modes:
  - Org-wide
  - Site with tabs
  - Detail breadcrumbs
- Wire header controls to existing `TelemetryNavService` signals (site + range) without route changes.

**Exit criteria**
- Left telemetry sub-sidebar is fully removed.
- Site picker and time range selector work from the header on all telemetry routes.
- Existing routes continue to load unchanged.

### Phase 2 - Scope and site summary hierarchy redesign (1.5-2 days)
- Rebuild summary layouts to the two-column section rhythm and KPI+chart composition in:
  - `frontend/src/app/features/telemetry/scope/telemetry-scope.component.html`
  - `frontend/src/app/features/telemetry/scope/telemetry-scope.component.scss`
  - `frontend/src/app/features/telemetry/site/telemetry-site.component.html`
  - `frontend/src/app/features/telemetry/site/telemetry-site.component.scss`
- Implement reporting badges and threshold color helpers (CPU, memory, reporting ratio).
- Ensure section-order consistency: Wireless Clients → AP → Switch → Gateway.

**Exit criteria**
- Org and site summary pages match target hierarchy and ordering.
- Hidden-section behavior works when device types are absent.

### Phase 3 - Clients tab redesign (1-1.5 days)
- Implement KPI strip, four-chart grid, band filter chips, and revised table in:
  - `frontend/src/app/features/telemetry/clients/telemetry-clients.component.html`
  - `frontend/src/app/features/telemetry/clients/telemetry-clients.component.scss`
  - `frontend/src/app/features/telemetry/clients/telemetry-clients.component.ts`
- Keep charts unfiltered by band chips (chips affect table only).
- Preserve row navigation to client detail and pagination options 25/50/100.

**Exit criteria**
- All 9 required columns and threshold color rules are present.
- Search + band chips + pagination can be combined without state bugs.

### Phase 4 - Devices tab redesign (1-1.5 days)
- Implement reporting summary strip, CPU/memory trend charts, doughnuts, type filters, and table in:
  - `frontend/src/app/features/telemetry/site-devices/telemetry-site-devices.component.html`
  - `frontend/src/app/features/telemetry/site-devices/telemetry-site-devices.component.scss`
  - `frontend/src/app/features/telemetry/site-devices/telemetry-site-devices.component.ts`
- Ensure type chips dynamically update both chart series and table rows.

**Exit criteria**
- Device-type and reporting doughnuts render correctly from live site data.
- Table key metric column adapts by type (AP/SW/GW).

### Phase 5 - Switch/Gateway detail alignment (1.5-2 days)
- Align detail page layout with shared detail pattern in:
  - `frontend/src/app/features/telemetry/device/telemetry-device.component.html`
  - `frontend/src/app/features/telemetry/device/telemetry-device.component.scss`
  - `frontend/src/app/features/telemetry/device/telemetry-device.component.ts`
- Add/update expansion-panel sections with defaults:
  - Structured sections expanded on load
  - Live Events collapsed on load
- Keep AP detail behavior unchanged; only switch/gateway paths are updated.

**Exit criteria**
- Switch and gateway pages show 6-tile strip, 3 charts, and collapsible sections per spec.
- Stale badge and threshold coloring are consistent with summary/tables.

### Phase 6 - Client detail finalization (0.5-1 day)
- Finish breadcrumb behavior, KPI strip consistency, RSSI/throughput chart formatting, and live-event formatting toggle in:
  - `frontend/src/app/features/telemetry/client-detail/telemetry-client-detail.component.html`
  - `frontend/src/app/features/telemetry/client-detail/telemetry-client-detail.component.scss`
  - `frontend/src/app/features/telemetry/client-detail/telemetry-client-detail.component.ts`

**Exit criteria**
- Breadcrumb returns to site clients tab correctly.
- Live events support formatted/raw modes and preserve latest-event summary.

### Phase 7 - Shared presentation utilities and styling tokens (0.5 day)
- Add shared Mbps conversion pipe and common threshold helpers in:
  - `frontend/src/app/shared/pipes/`
  - telemetry feature helper files as needed
- Centralize telemetry-specific semantic classes for status chips and metric state colors.
- Verify all newly added colors use existing `--app-*` variables only.

**Exit criteria**
- No hardcoded hex colors in telemetry feature styles.
- All traffic values display as Mbps in tiles, tables, and charts.

### Phase 8 - QA, performance, and accessibility pass (1 day)
- Functional verification:
  - Header navigation and breadcrumbs on every route
  - Time-range propagation and live refresh behavior
  - Empty/loading/error states for each page type
- Performance checks:
  - Confirm charts do not re-animate on WebSocket updates
  - Verify no redundant polling/subscription leaks during route changes
- Accessibility checks:
  - Keyboard access for tabs, chips, and expansion panels
  - Color contrast and non-color status cues for metric severity

### Phase 9 - Release plan (0.5 day)
- Merge behind a temporary telemetry UI feature flag if needed for staged validation.
- Conduct product/design walkthrough with side-by-side old/new screenshots.
- Remove obsolete sidebar-specific code after sign-off.

---

## Task Breakdown Checklist

- [ ] Phase 0 complete
- [ ] Phase 1 complete
- [ ] Phase 2 complete
- [ ] Phase 3 complete
- [ ] Phase 4 complete
- [ ] Phase 5 complete
- [ ] Phase 6 complete
- [ ] Phase 7 complete
- [ ] Phase 8 complete
- [ ] Phase 9 complete

---

## Validation Commands

Run from `frontend/`:

```bash
npm start
npx ng test
npx ng build
```

Run from `backend/` (smoke only, no expected API changes):

```bash
source .venv/bin/activate
pytest -k telemetry
```
