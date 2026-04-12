# Digital Twin UI Improvements — Design Spec

**Date:** 2026-04-12
**Branch:** feature/digital-twin-ui

## Problem

The Digital Twin list and detail views omit information that users need to understand and evaluate a simulation session:

**List view gaps**
- `Source` column shows `LLM Chat` but the actual trigger is the app's MCP server, now also reachable by external clients.
- `Checks` column collapses all layers into a single `X/Y passed` count — users cannot see which validation layer (L1 Config Conflicts, L2 Topology, L3 Routing, L4 Security, L5 STP) is failing.
- `Writes` column value is unclear and duplicates information that lives in the staged writes tab.
- No column communicates **what is being changed** (which object type and name).
- No column communicates **which sites** are being tested. The list cannot scale to sessions that touch tens of sites.

**Detail view gaps**
- Header says `1 site` but never names it, and does not scale beyond a count.
- No header field identifies the object being modified.
- Check Results lists every layer fully expanded by default, burying the one layer that actually failed.
- Staged Writes are collapsed by default and show a raw JSON body — no diff against current state, no summary of what changed.
- Backend simulation logs are not accessible to admins investigating why a session behaved unexpectedly.
- The `description` field recently added to `CheckResult` is emitted by the backend but is not in the API response schema and the frontend row layout does not handle it cleanly.

## Goal

Rework both views so that, for any simulation session, a user can answer — without leaving the page — the questions:
1. What object is being changed?
2. Which sites will the change hit?
3. Which validation layers passed, warned, or failed, and by how much?
4. What is the diff between the staged writes and the current state?
5. (Admin) What did the backend log while running the simulation?

## Non-Goals

- Advanced log features: export, tail-follow, persistent full-text indexing.
- Live refresh of object / site names after session creation. Names are resolved once at session creation and kept stable.
- Changing the approve / reject flow, state machine, or retention policy.
- Redesigning the Remediation History tab.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Source `llm_chat` rename | Rename to `mcp` (single value) | `llm_chat` is a misnomer — the in-app chat already goes through the MCP server, and external MCP clients now hit the same endpoint. One source, not two. |
| MCP client identity | Stored in `source_ref` as a human-readable client label (only when `source == "mcp"`) | Avoids adding a new enum. `source_ref` keeps its existing free-text semantics for `workflow` and `backup_restore` sources. |
| Object name storage | New `affected_object_label` field, resolved at session creation | Cached, stable, no live API calls at display time. |
| Site name storage | New `affected_site_labels` field, resolved at session creation | Same rationale as object name. Stale names are better than spinner delays. |
| Checks-by-layer display (list view) | Stacked `L0..L5` columns: label on top, ratio pill below | User-selected from 5 mockup alternatives. |
| Layer collapse (detail view) | Auto-expanded iff layer has warn/error/critical; clean and skipped layers collapsed | Focuses attention on failures without hiding passing layers entirely. |
| Staged writes default state | Expanded with diff view; raw JSON behind "Show full body" toggle | User-selected (option D) after weighing JSON volume concerns. |
| Logs tab visibility | Completely hidden from non-admins — not rendered in the DOM | No lock icon, no teaser. Tab is an admin surface, not a "please upgrade" CTA. |
| Logs persistence | Per-session buffer on the `TwinSession` document, bounded at 1000 entries | Scopes naturally to the session's 7-day TTL. No new collection. |
| Logs UX | Level filter + text search + grouped-by-phase collapsible sections | Admins usually want "what happened during remediation #2", not a flat stream. |

## Data Model Changes (`backend/app/modules/digital_twin/models.py`)

### 1. `TwinSession` — new fields

```python
source: Literal["mcp", "workflow", "backup_restore"] = "mcp"  # was "llm_chat"
source_ref: str | None = None  # now may carry "Internal Chat", "Claude Desktop", etc.

affected_object_label: str | None = None       # NEW — e.g. "networktemplates: default-campus"
affected_site_labels: list[str] = Field(default_factory=list)  # NEW — resolved site names

simulation_logs: list[SimulationLogEntry] = Field(default_factory=list)  # NEW
```

### 2. `SimulationLogEntry` — new model

```python
class SimulationLogEntry(BaseModel):
    timestamp: datetime
    level: Literal["debug", "info", "warning", "error"]
    event: str                              # structlog event name
    phase: Literal["simulate", "remediate", "approve", "execute", "other"]
    context: dict[str, Any] = Field(default_factory=dict)
```

The bounded list is capped at 1000 entries by the emitting processor; overflow drops the oldest entries and appends a single `simulation_logs_truncated` marker entry.

### 3. Migration

A one-time migration script updates every existing document where `source == "llm_chat"` to `source = "mcp"`. No other fields need backfilling — the new fields default to `None` / empty, and historical sessions simply have no labels / logs.

## Backend Changes

### 1. Source resolution (MCP handshake)

`app/modules/mcp_server/server.py` — capture client info from the MCP `initialize` handshake (`clientInfo.name`). Store it on the request-scoped context and pass it into `twin_service.simulate()` as `source_ref`. Default to `"Internal Chat"` when the in-app chat tool calls the local MCP client.

### 2. Object / site label resolution (`services/twin_service.py`)

During `simulate()`, after `collect_affected_metadata()` runs, resolve labels from backup data:

```python
affected_object_label = await _resolve_object_label(
    org_id, affected_types, staged_writes
)
affected_site_labels = await _resolve_site_labels(org_id, affected_sites)
```

- **Object label**: for single-object sessions, `"{canonical_type}: {object_name}"` (e.g., `"networktemplates: default-campus"`). For multi-object same-type, `"3 Network Templates"`. For multi-object mixed-type, `"3 objects: 2 Templates, 1 WLAN"`.
- **Site labels**: resolve each `site_id` from `BackupObject` where `object_type in {"info", "site", "sites"}` and extract the `name` field. Fall back to the truncated site_id if not found.

Both resolutions happen once at session creation and are never refreshed.

### 3. Staged write diffs (`services/twin_service.py` + `schemas.py`)

Add a `diff` field to `StagedWriteResponse`:

```python
class WriteDiffField(BaseModel):
    path: str                   # dotted path, e.g., "port_usages.trunk.vlan_id"
    change: Literal["added", "removed", "modified"]
    before: Any | None = None
    after: Any | None = None

class StagedWriteResponse(BaseModel):
    # existing fields unchanged
    diff: list[WriteDiffField] = Field(default_factory=list)
    diff_summary: str | None = None   # "3 fields changed" / "new object" / "deleted"
```

Diff is computed in `session_to_detail_response()` by comparing each staged write's `body` against the corresponding key in `session.resolved_state` (or empty dict for POST / missing key for DELETE). Uses the existing `deep_diff()` helper.

### 4. Simulation log capture

A new structlog processor `capture_twin_session_logs` checks a `twin_session_id` context variable. When set, it appends an entry to an in-memory buffer keyed by session id. The buffer is flushed to `TwinSession.simulation_logs` at the end of each phase (simulate / remediate / approve / execute).

```python
# app/modules/digital_twin/services/twin_logging.py
twin_session_id_var: ContextVar[str | None] = ContextVar("twin_session_id", default=None)
twin_session_phase_var: ContextVar[str | None] = ContextVar("twin_session_phase", default=None)

def bind_twin_session(session_id: str, phase: str) -> AbstractContextManager[None]:
    """Context manager to bind session id and phase to the logging processor."""
```

`twin_service.simulate()`, `approve_and_execute()`, and remediation paths wrap their work in `bind_twin_session(...)`. No existing log call sites need to change.

### 5. API schema and endpoints (`api/v1/digital_twin.py`, `schemas.py`)

`TwinSessionResponse` additions (list view):

```python
source: str                         # now also carries "mcp"
source_ref: str | None = None       # now carries client label
affected_object_label: str | None = None
affected_object_types: list[str] = Field(default_factory=list)
affected_site_labels: list[str] = Field(default_factory=list)
# writes_count is REMOVED from the response shape
```

`TwinSessionDetailResponse` additions: everything above plus `staged_writes[].diff`, `staged_writes[].diff_summary`.

`CheckResultResponse` addition:

```python
description: str = ""
```

New endpoint:

```python
@router.get("/sessions/{session_id}/logs")
async def get_session_logs(
    session_id: str,
    level: str | None = Query(None),
    phase: str | None = Query(None),
    search: str | None = Query(None),
    current_user: User = Depends(require_admin),   # admin-only
) -> list[SimulationLogEntry]:
    ...
```

Filtering is applied server-side over the stored `simulation_logs` buffer. No pagination — the buffer is bounded.

## Frontend Changes

### 1. Models (`features/digital-twin/models/twin-session.model.ts`)

```typescript
interface TwinSessionSummary {
  // existing fields
  source: 'mcp' | 'workflow' | 'backup_restore';
  source_ref: string | null;
  affected_object_label: string | null;
  affected_object_types: string[];
  affected_site_labels: string[];
  // writes_count removed
}

interface StagedWriteModel {
  // existing fields
  diff: WriteDiffField[];
  diff_summary: string | null;
}

interface WriteDiffField {
  path: string;
  change: 'added' | 'removed' | 'modified';
  before: unknown;
  after: unknown;
}

interface SimulationLogEntry {
  timestamp: string;
  level: 'debug' | 'info' | 'warning' | 'error';
  event: string;
  phase: 'simulate' | 'remediate' | 'approve' | 'execute' | 'other';
  context: Record<string, unknown>;
}

interface CheckResultModel {
  // existing fields
  description: string;
}
```

### 2. List view (`features/digital-twin/session-list/`)

Column set: `Status | Source | Object Changed | Sites | Severity | Checks by Layer | Created`.

- **Source** cell: two-line — primary label (from a `sourceLabel()` helper) over `source_ref` as secondary muted text.
- **Object Changed** cell: `<span class="object-type">{type}</span> <span class="object-name">{name}</span>` using `affected_object_label`.
- **Sites** cell: `<span class="sites-count-pill">{N} sites</span>` with a `matTooltip` listing up to 10 names (`, ` separated). When no sites are scoped (org-level change with no template fan-out), show `—`.
- **Checks by Layer**: 6 stacked columns for L0..L5. Each column renders a small uppercase `Lx` label above a colored pill (`{passed}/{total}` or `—` when skipped / not run). Pill color reflects the worst status inside the layer.
- **Writes column removed.**

New component helpers:

```typescript
// Groups prediction_report.check_results by layer and returns:
// { layer: 0..5, passed: number, total: number, status: 'pass'|'warn'|'err'|'crit'|'skip' }[]
computeLayerRollup(report: PredictionReportModel | null): LayerRollup[]
```

### 3. Detail view (`features/digital-twin/session-detail/`)

**Header meta grid** replaces the current `.meta-row`:

```
[ Object Changed ]  [ Sites Tested ]   [ Source ]    [ Created ]
  type + name         5-chip list        MCP           12 Apr 2026
                      + "Expand all"     Internal      18:50:40
                                         Chat
```

The Sites block is a `max-height: 64px; overflow: hidden` chip container plus an `Expand all` toggle when overflowing. Chip label = site name.

**Summary cards**: unchanged structure. Confirmed style: dark surface + colored border + colored number, no fill.

**Check Results tab**:
- Layer sections render in order L0..L5.
- `isLayerExpanded(layer)` starts as `true` iff `issueCountForLayer(layer) > 0`; otherwise `false`.
- User clicks still toggle manually. Expansion state is per-layer local signal state.

**Check row layout polish**:
- Grid template: `[icon][check_id][name_block][severity_chip]`, with `name_block` being a 2-line flex column (name bold, description muted 12px).
- Description wraps under the name without pushing the severity chip.
- Pass and fail rows share the same grid template for visual consistency.

**Staged Writes tab**:
- Per write: header row always visible (`#seq | METHOD | endpoint | object_type`).
- Below the header: default view is the diff rendered as a 2-column list — path on the left, `before → after` (or `+added` / `-removed`) on the right. Modified values are yellow, added are green, removed are red.
- `diff_summary` shown as a subtle label above the diff: `3 fields changed` / `new object` / `deleted`.
- "Show full body" button reveals the raw `body` JSON in a `<pre>` below the diff. Toggle per-write.

**Logs tab** (admin-only):
- `*ngIf="isAdmin()"` controls both the tab trigger and its contents. Non-admin users do not see the tab at all.
- Top bar: level selector (`mat-button-toggle-group` for All / Info / Warn / Error), text search input (`debounceTime(200)`), collapse-all / expand-all buttons.
- Body: grouped by `phase` in this order: Simulate → Remediation #N → Approve → Execute → Other. Each group is collapsible and shows a count badge. The first group with entries starts expanded.
- Entry row: `timestamp | level-chip | event | context` in monospace. Context is rendered as inline `key=value` pairs, newest first.
- When `simulation_logs` is empty, render an empty state: "No simulation logs captured for this session."

### 4. Admin detection

Use the existing `hasRole` directive / `AuthService.hasRole('admin')` signal. The Logs tab control reads from a `isAdmin = computed(() => this.auth.hasRole('admin'))` signal local to the component.

## Data Flow

```
User triggers simulation via MCP or workflow
  → twin_service.simulate(source_ref=<client_label>, ...)
     → bind_twin_session(session_id, phase="simulate")
        → run checks + resolve labels + persist logs
  → (optional) twin_service.remediate_iteration()
     → bind_twin_session(session_id, phase="remediate")
  → twin_service.approve_and_execute()
     → bind_twin_session(session_id, phase="approve"/"execute")

GET /digital-twin/sessions          → list view (labels, layer rollup)
GET /digital-twin/sessions/{id}     → detail view (+ diffs)
GET /digital-twin/sessions/{id}/logs → logs tab (admin only)
```

## Acceptance Criteria

**List view**
- Sessions triggered via the in-app chat show `Source = MCP` with `Internal Chat` secondary label.
- Sessions from external MCP clients show the reported client name as secondary label.
- Object Changed column shows `networktemplates: default-campus` for the example document in the problem statement.
- Sites column displays `5 sites` / `42 sites` with hover tooltip listing names; renders without wrapping at 1200px viewport.
- Checks by Layer shows 6 vertical columns L0..L5. A session with one L1 error and everything else passing renders `L0 3/3` green, `L1 5/6` red, `L2 5/5` green, `L3 3/3` green, `L4 —` faded, `L5 —` faded.
- Writes column is gone.

**Detail view**
- Header meta grid shows Object Changed, Sites Tested (with chip list), Source, Created.
- A session with 42 sites renders a chip list capped at ~2 rows with an "Expand all" toggle that reveals all names.
- Layer sections with failures start expanded; clean and not-run layers start collapsed.
- Every check row (pass and fail) displays the `description` as muted text under the check name without crowding neighbors.
- Staged Writes tab shows headers always visible, diff rendered by default, `Show full body` button reveals raw JSON.
- `DELETE` writes show `deleted` summary and no diff body.
- `POST` writes show every body field as `added` in the diff.

**Logs tab (admin only)**
- Non-admin user does not see the Logs tab.
- Admin user sees the tab with groups per phase, level filter, and text search.
- Empty sessions show the empty state message.
- A session whose backend emitted 500+ log lines renders at interactive speed (virtual scroll not required at this volume).

**No regressions**
- Approve and Reject flows behave exactly as before.
- Existing sessions where `source == "llm_chat"` are migrated to `source == "mcp"` and display correctly.
- Existing sessions without `affected_object_label` / `affected_site_labels` render gracefully (show `—` or fall back to `affected_object_types` and truncated site_ids).

## Risks & Open Questions

- **Site label resolution cost**: resolving 50 site names at session creation adds DB round-trips. Mitigation: use a single `$in` query against `BackupObject` rather than N individual lookups.
- **Diff computation cost at render time**: computing diffs for 10 staged writes per detail response is bounded and cheap (deep_diff is in-memory). No caching needed.
- **Log buffer growth**: capped at 1000 entries with a truncation marker. Admin can investigate if truncation happens often.
- **Backward-compat of `source_ref`**: the new semantics ("MCP client name") only apply when `source == "mcp"`. `workflow` and `backup_restore` sessions continue to carry whatever reference their workers already set. No migration of existing `source_ref` values.
- **Multi-object label wording**: `"3 objects: 2 Templates, 1 WLAN"` is the chosen format but may feel long in the list cell. Revisit during implementation if it truncates awkwardly.
