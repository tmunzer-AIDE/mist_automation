# Impact Analysis Change Groups

**Date:** 2026-03-29
**Status:** Approved

## Problem

A single configuration change (template modification, site-level setting) can trigger impact analysis monitoring sessions on many devices simultaneously. Today, each device gets an independent `MonitoringSession` with no indication they share a common cause. Operators see a flat list of sessions and cannot reason about the change as a unit.

## Solution

Add a `ChangeGroup` grouping layer on top of existing per-device `MonitoringSession` documents. Groups are correlated by `audit_id` (shared across all device-events triggered by the same Mist audit event). The UI presents groups as the primary view, with per-device drill-down available from the group detail page. AI analysis runs once per group with a pre-aggregated summary, not per device.

## Approach

**Approach B: Grouping layer on top of existing sessions.** Per-device monitoring pipeline, validation checks, SLE tracking, event handling, and session lifecycle remain unchanged. The `ChangeGroup` is an additive layer that correlates, aggregates, and presents.

**Why not unified sessions (Approach A/C):** The per-device monitoring pipeline is complex and battle-tested (state machine, parallel branches, SLE coordination, event merging). Reworking it into a unified model is high-risk for what is fundamentally a presentation and analysis concern. The 16MB MongoDB document limit is also a concern for large pushes with embedded SLE snapshot data across many devices.

## Data Model

### `ChangeGroup` (new Beanie Document)

```python
class DeviceSummary(BaseModel):
    session_id: PydanticObjectId
    device_mac: str
    device_name: str
    device_type: str  # "ap", "switch", "gateway"
    site_name: str
    status: SessionStatus
    impact_severity: ImpactSeverity
    failed_checks: list[str]
    active_incidents: list[IncidentSummary]  # {type, severity, timestamp, resolved}
    worst_sle_delta: SLEDelta | None  # {metric, baseline, current, delta_pct}

class DeviceTypeCounts(BaseModel):
    total: int
    monitoring: int
    completed: int
    impacted: int

class ValidationCheckSummary(BaseModel):
    check_name: str
    passed: int
    failed: int
    skipped: int

class GroupSummary(BaseModel):
    total_devices: int
    by_type: dict[str, DeviceTypeCounts]  # "ap", "switch", "gateway"
    worst_severity: ImpactSeverity
    validation_summary: list[ValidationCheckSummary]
    sle_summary: dict[str, SLEDelta]  # metric_name -> aggregate delta
    devices: list[DeviceSummary]
    status: str  # "monitoring", "partial", "completed"
    last_updated: datetime

class ChangeGroup(Document, TimestampMixin):
    audit_id: str  # unique index, correlation key from Mist webhooks
    org_id: str
    site_id: str | None  # None for org-level template changes

    # What triggered this
    change_source: str  # "org_template", "site_template", "site_settings", etc.
    change_description: str  # e.g. "Template 'Branch-AP' modified"
    triggered_by: str | None  # user/method from audit event
    triggered_at: datetime

    # Child sessions
    session_ids: list[PydanticObjectId]

    # Live aggregate summary
    summary: GroupSummary

    # AI assessment (one per group)
    ai_assessment: AIAssessment | None
    conversation_thread_id: str | None

    # Group-level timeline (creation, AI analysis, severity escalations)
    timeline: list[TimelineEntry]
```

### Changes to `MonitoringSession`

Add one field:

```python
change_group_id: PydanticObjectId | None = None  # back-reference to parent group
```

Existing fields and lifecycle unchanged. Sessions without a group (`change_group_id = None`) continue to work as standalone entries (e.g., direct device incidents not tied to a config change).

## Group Lifecycle

### Creation

Happens in the event handler when a PRE_CONFIG or CONFIGURED event arrives:

1. Extract `audit_id` from the webhook payload
2. Look up `ChangeGroup` by `audit_id`
   - Not found: create new `ChangeGroup`, extract `change_source` and `change_description` from audit event metadata
   - Found: reuse existing group
3. Create per-device `MonitoringSession` as today, set `change_group_id`
4. Append session ID to `ChangeGroup.session_ids`

### Summary Updates

Triggered inline by session manager (not via WS subscription). Whenever `SessionManager` updates a child session's state (status transition, severity escalation, validation result, incident, SLE snapshot), it also calls `ChangeGroupService.update_summary(change_group_id)`.

This method:

1. Queries all child sessions (projected to needed fields: status, impact_severity, validation_results, incidents, sle_snapshots, device info)
2. Recomputes the aggregate `GroupSummary` including the per-device `DeviceSummary` list
3. Saves the updated `ChangeGroup`
4. Broadcasts via WS on `impact:group:{group_id}` channel

### Group Status Transitions

- `"monitoring"` -- any child session is non-terminal
- `"partial"` -- some completed, others still running
- `"completed"` -- all child sessions reached terminal state (completed/failed/cancelled)

### Edge Cases

- **Devices configuring minutes apart**: group already exists by `audit_id`, new sessions appended
- **Device never sends CONFIGURED after PRE_CONFIG**: session times out as today, group summary reflects it as failed
- **Single-device changes**: still create a group (1 session), same UX, no special-casing
- **Monitoring windows**: each device keeps its own full monitoring window (sliding per device). The group closes when the last device's window expires.

## API

### New Endpoints

All under `/api/v1/impact-analysis/groups`, requiring `require_impact_role`.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/groups` | List change groups (paginated, filterable by status/severity/date) |
| GET | `/groups/{group_id}` | Group detail with summary |
| GET | `/groups/{group_id}/sessions` | Child sessions with current state |
| GET | `/groups/{group_id}/logs` | Aggregated logs across child sessions |
| POST | `/groups/{group_id}/analyze` | Trigger/re-trigger AI analysis |
| POST | `/groups/{group_id}/chat` | Chat with AI about this group |
| POST | `/groups/{group_id}/cancel` | Cancel all active child sessions |

### Existing Endpoint Changes

- Individual session endpoints (`/sessions/{id}`) remain for drill-down
- Session list endpoint (`/sessions`) gains `group_id` query param for filtering
- Summary endpoint (`/summary`) adds group-level stats: `active_groups`, `impacted_groups_24h`

## WebSocket Channels

| Channel | Payload | Trigger |
|---------|---------|---------|
| `impact:group:{group_id}` | Updated GroupSummary | Any child session state change |
| `impact:group:{group_id}:timeline` | New TimelineEntry | Group-level events (creation, AI analysis, severity change) |
| `impact:summary` | Updated dashboard counts | Existing + group counts added |

Per-device channels (`impact:{session_id}`) remain unchanged.

## Frontend UI

### Session List Page (modified)

- Default view shows `ChangeGroup` entries, not individual sessions
- Each row: change description, triggered by, device count, device type breakdown (AP/SW/GW icons with counts), worst severity badge, status, timestamp
- Clicking a row navigates to the group detail page
- Ungrouped sessions (`change_group_id = None`) appear as regular rows in the same list, visually distinguished

### Group Detail Page (new)

- **Header**: change description, source, triggered by, timestamp, overall severity badge
- **Summary cards**: total devices, impacted count, active incidents count, group status
- **Device breakdown**: table/expandable rows per device showing name, type, MAC, site, status, severity, key validation failures. Clicking a device navigates to existing session detail page
- **Validation overview**: aggregated check matrix -- check name vs pass/fail count across devices
- **SLE overview**: grouped by metric, showing baseline vs current with delta, worst-performing devices highlighted
- **AI assessment panel**: single analysis result with chat (same AI chat component, wired to group conversation thread)
- **Timeline**: group-level events (creation, severity escalations, AI analysis runs)

### Existing Session Detail Page

Unchanged. Add breadcrumb/back link to parent group when `change_group_id` is set.

### Dashboard

Existing impact analysis summary widget adds group-level counts alongside device counts.

## AI Analysis

### Input

The group's `summary` field provides the full picture in one read. The prompt context includes a per-device table:

```
Change: "Template 'Branch-AP' modified" by admin@company.com at 2026-03-29T14:30Z
Scope: 8 APs, 3 switches across site "HQ-Floor2"

Device Status: 8/11 completed, 3/11 monitoring
Impacted: 3 devices (2 APs, 1 switch)
Worst Severity: warning

| Device       | Type | Site      | Status    | Severity | Failed Checks           | Incidents                         | SLE Worst Delta |
|--------------|------|-----------|-----------|----------|-------------------------|-----------------------------------|-----------------|
| AP-lobby-01  | AP   | HQ-Floor2 | completed | warning  | connectivity, stability | disconnected T+3m (resolved T+5m) | throughput -18% |
| AP-lobby-02  | AP   | HQ-Floor2 | completed | critical | connectivity            | disconnected T+3m (unresolved)    | throughput -22% |
| AP-conf-01   | AP   | HQ-Floor2 | completed | none     | -                       | -                                 | -               |
| SW-core-01   | SW   | HQ-Floor2 | completed | warning  | -                       | -                                 | throughput -12% |
| ...          |      |           |           |          |                         |                                   |                 |
```

### Drill-Down

The AI has MCP access to query individual session details via `session_id` from the device table. This is only needed for unusual cases (e.g., "show me the exact config diff on AP-lobby-02"). A new `get_change_group_sessions` MCP tool returns per-device details.

### Trigger

- Automatic: fires once when group status reaches `"completed"`
- Manual: re-trigger via API endpoint or chat

### Conversation Thread

One thread per group (not per device). Chat questions receive the group summary as context automatically.

### Fallback

Rule-based analysis reads the summary, classifies patterns (e.g., "all failures are same device type at same site"), outputs severity + recommendations.

## Non-Goals

- Bulk operations (firmware upgrades, profile assignments) remain independent sessions -- no grouping
- No changes to the per-device monitoring pipeline (validation checks, SLE polling, event handling, state machine)
- No changes to the webhook gateway routing
