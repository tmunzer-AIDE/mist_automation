# Backup Object Time Travel View — Design Spec

**Date:** 2026-04-14  
**Scope:** `backup-object-detail` Angular component  
**Status:** Approved

---

## Overview

Rework the `backup-object-detail` page to provide a "time travel" experience for navigating configuration version history. The key goals are:

1. Show all changes at a glance with visual weight (bigger = more changed)
2. Make diffing any two arbitrary versions always easy and explicit
3. Keep rollback and simulate-rollback actions per-version and always visible

The current page has a version table and a toggleable compare mode. This design replaces that with a persistent three-zone layout.

---

## Layout

Three vertical zones, top to bottom:

### Zone 1 — Object Header

Breadcrumb-style metadata bar: `object_type` badge · `object_name` · `device_name / site_name` · version count + first-seen date.

### Zone 2 — Time-Proportional Sparkline Timeline

A horizontal timeline showing all versions as bubbles. Key properties:

- **Horizontal position** is time-proportional: `left% = (version.backed_up_at − earliest) / (latest − earliest) × 100`. This means gaps between bubbles reflect real elapsed time — clusters show "busy periods", wide gaps show quiet periods.
- **Minimum spacing guarantee**: if two adjacent bubbles would be closer than 20px after proportional placement, shift the later one right just enough to avoid overlap. This handles versions created on the same day or minutes apart.
- **Bubble size** maps to number of changed fields: `diameter = clamp(8 + changes × 2, 8, 28)px`. This gives an at-a-glance sense of change magnitude.
- **Bubble vertical position**: bubbles are **centered on the track line** — the center of each bubble sits exactly on the track, so larger bubbles extend equally above and below. This is the standard scatter-timeline convention and avoids the track looking like a baseline the bubbles sit on top of.
- **Bubble color**: green (1–2 changes), yellow (3–6 changes), red (7+ changes). The latest version (B pin) uses blue regardless.
- **A/B pins**: the currently selected A and B versions show their pin label below the bubble. A gradient connector line renders between A and B on the track.
- **Date axis**: evenly-spaced date labels below the track spanning the full date range.
- Clicking a bubble selects that version in the list below (same as clicking the list row).

### Zone 3 — Split Layout

Two panes side by side:

**Left pane — Version list** (fixed ~265px width, scrollable):

- Sorted newest first.
- Each row has: A/B pin indicator (circle with letter, or empty dot), version number, date, actor (`commit_user` or event type), change-magnitude bar (proportional width), changed-field tags (top 2 + "+N more").
- The two pinned rows (A and B) are highlighted with a left border and background tint in their respective colors (red for A, blue for B).
- The **3 newest versions** use the full row format. Older versions use a compact single-line format (no tags, no magnitude bar) showing only version number, date, and change count. Pinned versions (A or B) always use the full format regardless of their position in the list.
- **Per-row action buttons** (always visible, not hover-only):
  - Full rows: `View` (opens JSON dialog), `Rollback`, `Simulate`
  - Compact rows: icon-only `↩` (rollback) and `⚡` (simulate)
- `Rollback`: calls the existing `POST /backups/objects/versions/{id}/restore` endpoint. Requires confirmation dialog.
- `Simulate`: passes the version's `configuration` to the Digital Twin as a simulated `update` action against the current live config. Uses the `object_type`, `org_id`, `site_id`, and `object_id` fields already present on the `BackupObject` document. Uses the existing `digital_twin` MCP tool / Digital Twin API.

**Right pane — Persistent Diff Panel** (flexible width, scrollable):

- Always visible — no toggle required.
- Header: `A vX → B vY · N changes · M days apart` with `+added / −removed / ~modified` pill counts.
- Body: diff entries grouped by top-level key, each showing old value (red) and new value (green) in a two-row block. Unchanged nested keys are collapsed.
- Default state on load: B = latest version, A = the version immediately before it.

**Status bar** (below the split):

- Left: pin interaction hint — "1st click → set A · 2nd click → set B · click A or B again to clear"
- Right: "⚡ Simulate = rollback via Digital Twin pre-check"

---

## A/B Pin Interaction Model

The pin model works as a simple two-slot cycle:

1. No pins set → click any row → sets A (red).
2. A set, B not set → click any other row → sets B (blue). Diff panel updates.
3. Both set → click any unselected row → the clicked version becomes the new A (the previous A is discarded). Clicking a third row always reassigns A, never B.
4. Click the current A row → clears A.
5. Click the current B row → clears B.

Clicking a bubble in the sparkline timeline is equivalent to clicking the corresponding row in the list.

The diff panel always reflects the current A → B pair. If only one pin is set, the diff panel shows a "select a second version to compare" placeholder.

---

## Default State on Load

- B pin = latest version (highest version number).
- A pin = the version immediately before B.
- Diff panel is populated on load — user sees the most recent change immediately, no clicks required.
- Timeline: B bubble highlighted in blue, A bubble highlighted in red, gradient connector between them.

---

## Reuse of Existing Code

The following existing code is reused as-is:

| Existing item | Reused for |
|---|---|
| `deepDiff()` function in `backup-object-detail.component.ts` | Computing the diff entries for the right panel |
| `GET /backups/objects/{id}/versions` endpoint | Fetching all versions on load |
| `POST /backups/objects/versions/{id}/restore` endpoint | Rollback action |
| JSON viewer dialog | "View" button per row |
| Digital Twin integration | "Simulate" rollback action |

The current compare mode toggle, version table, and separate diff section are replaced entirely by this design. The AI summary feature (LLM summarize button) can be retained in the diff panel header as an optional action.

---

## Edge Cases

| Case | Handling |
|---|---|
| Object with only 1 version | No A pin set on load; diff panel shows "only one version — nothing to compare yet" |
| Two versions created within minutes of each other | Minimum 20px spacing applied; the later bubble is shifted right |
| Very large number of versions (50+) | Timeline still works (proportional positions computed from full range); list is virtualized or paginated if needed |
| Deleted object (latest version has `is_deleted: true`) | Show a "DELETED" badge on v_latest in the list; rollback from any earlier version effectively restores the object |
| Object with no `changed_fields` metadata | Compute change count from `deepDiff()` against the previous version at load time; use that for bubble size |
| v1 (initial backup, no previous version) | No diff possible — show a fixed minimum bubble size (8px) with an "initial" label; Rollback/Simulate are still available |

---

## Files to Change

| File | Change |
|---|---|
| `frontend/src/app/features/backup/detail/backup-object-detail.component.ts` | Full rework of component logic: add pin state, timeline position computation, minimum-spacing algorithm |
| `frontend/src/app/features/backup/detail/backup-object-detail.component.html` | Full rework of template: three-zone layout |
| `frontend/src/app/features/backup/detail/backup-object-detail.component.scss` | New styles for timeline, bubbles, A/B pins, split panes, compact rows |

No backend changes required — all necessary endpoints already exist.
