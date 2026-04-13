# Digital Twin UI Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the Digital Twin list and detail views to surface object/site context, per-layer check breakdowns, staged-write diffs, and admin-only simulation logs.

**Architecture:** Backend additions are additive on the `TwinSession` document (new fields, new endpoint, structlog processor) with a single-value source rename migration. Frontend rewrites the list view columns and polishes the detail view; admin role is read from the existing NgRx `selectIsAdmin` selector.

**Tech Stack:** Python 3.10+, FastAPI, Beanie (MongoDB), structlog, pytest • Angular 21 standalone components, signals, Angular Material, Vitest.

**Source spec:** `docs/superpowers/specs/2026-04-12-digital-twin-ui-improvements-design.md`

---

## Phase A — Backend Data Model & Schemas

### Task 1: Extend `TwinSession` model with new fields

**Files:**
- Modify: `backend/app/modules/digital_twin/models.py`
- Test: `backend/tests/unit/test_digital_twin_models.py` (create if missing)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_digital_twin_models.py
from datetime import datetime, timezone

from app.modules.digital_twin.models import (
    SimulationLogEntry,
    TwinSession,
    TwinSessionStatus,
)


def test_twin_session_new_fields_defaults():
    session = TwinSession(
        user_id="507f1f77bcf86cd799439011",  # type: ignore[arg-type]
        org_id="8aa21779-1178-4357-b3e0-42c02b93b870",
        source="mcp",
    )
    assert session.source == "mcp"
    assert session.source_ref is None
    assert session.affected_object_label is None
    assert session.affected_site_labels == []
    assert session.simulation_logs == []


def test_simulation_log_entry_roundtrip():
    entry = SimulationLogEntry(
        timestamp=datetime(2026, 4, 12, 18, 50, 40, tzinfo=timezone.utc),
        level="info",
        event="twin_write_parse_error",
        phase="simulate",
        context={"sequence": 0, "error": "bad endpoint"},
    )
    data = entry.model_dump()
    restored = SimulationLogEntry.model_validate(data)
    assert restored == entry
    assert restored.context["sequence"] == 0


def test_twin_session_source_literal_accepts_mcp():
    # Type-level check: model accepts the new literal value
    session = TwinSession(
        user_id="507f1f77bcf86cd799439011",  # type: ignore[arg-type]
        org_id="org",
        source="mcp",
    )
    assert session.source == "mcp"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_digital_twin_models.py -v`
Expected: FAIL — `SimulationLogEntry` not defined, `affected_object_label`/`affected_site_labels`/`simulation_logs` not on `TwinSession`, or `source` Literal does not include `"mcp"`.

- [ ] **Step 3: Add `SimulationLogEntry` model and new fields**

Edit `backend/app/modules/digital_twin/models.py`:

```python
class SimulationLogEntry(BaseModel):
    """A single structlog entry captured during a Twin session phase."""

    timestamp: datetime
    level: Literal["debug", "info", "warning", "error"]
    event: str
    phase: Literal["simulate", "remediate", "approve", "execute", "other"]
    context: dict[str, Any] = Field(default_factory=dict)
```

Place it right above `class TwinSession(...)`. Then update the `TwinSession` class: change the `source` literal and add the three new fields.

```python
class TwinSession(TimestampMixin, Document):
    # ... existing fields above ...
    user_id: PydanticObjectId
    org_id: str
    source: Literal["mcp", "workflow", "backup_restore"] = "mcp"
    source_ref: str | None = None
    status: TwinSessionStatus = TwinSessionStatus.PENDING
    staged_writes: list[StagedWrite] = Field(default_factory=list)
    affected_sites: list[str] = Field(default_factory=list)
    affected_object_types: list[str] = Field(default_factory=list)
    affected_object_label: str | None = None
    affected_site_labels: list[str] = Field(default_factory=list)
    base_snapshot_refs: list[BaseSnapshotRef] = Field(default_factory=list)
    live_fetched_at: datetime | None = None
    resolved_state: dict[str, Any] | None = None
    prediction_report: PredictionReport | None = None
    overall_severity: Literal["clean", "info", "warning", "error", "critical"] = "clean"
    remediation_count: int = 0
    remediation_history: list[RemediationAttempt] = Field(default_factory=list)
    ai_assessment: str | None = None
    ia_session_ids: list[str] = Field(default_factory=list)
    simulation_logs: list[SimulationLogEntry] = Field(default_factory=list)
    # ... existing timestamps below ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_digital_twin_models.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full preflight suite to catch regressions**

Run: `cd backend && pytest tests/unit/test_twin_service_preflight.py tests/unit/test_digital_twin_schemas.py -v`
Expected: existing tests still pass (these tests reference `source="llm_chat"` — if any fail, they'll be fixed in Task 9's migration; do not edit them yet).
If any existing test instantiates `TwinSession(source="llm_chat")`, note the failing test names to revisit in Task 9.

- [ ] **Step 6: Commit**

```bash
cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui
git add backend/app/modules/digital_twin/models.py backend/tests/unit/test_digital_twin_models.py
git commit -m "feat(digital-twin): add mcp source, labels, and simulation_logs fields"
```

---

### Task 2: Extend response schemas

**Files:**
- Modify: `backend/app/modules/digital_twin/schemas.py`
- Modify: `backend/tests/unit/test_digital_twin_schemas.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_digital_twin_schemas.py`:

```python
def test_check_result_response_includes_description():
    from app.modules.digital_twin.models import CheckResult
    from app.modules.digital_twin.schemas import CheckResultResponse

    cr = CheckResult(
        check_id="CFG-SUBNET",
        check_name="IP Subnet Overlap",
        layer=1,
        status="pass",
        summary="",
        description="Checks all network subnets pairwise for IP address range overlaps.",
    )
    resp = CheckResultResponse(**cr.model_dump())
    assert resp.description.startswith("Checks all network subnets")


def test_twin_session_response_carries_new_label_fields():
    from app.modules.digital_twin.models import TwinSession, TwinSessionStatus
    from app.modules.digital_twin.schemas import session_to_response

    session = TwinSession(
        user_id="507f1f77bcf86cd799439011",  # type: ignore[arg-type]
        org_id="org",
        source="mcp",
        source_ref="Claude Desktop",
        affected_object_label="networktemplates: default-campus",
        affected_object_types=["networktemplates"],
        affected_site_labels=["HQ", "Boston"],
        status=TwinSessionStatus.AWAITING_APPROVAL,
    )
    resp = session_to_response(session)
    assert resp.source == "mcp"
    assert resp.source_ref == "Claude Desktop"
    assert resp.affected_object_label == "networktemplates: default-campus"
    assert resp.affected_object_types == ["networktemplates"]
    assert resp.affected_site_labels == ["HQ", "Boston"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_digital_twin_schemas.py::test_check_result_response_includes_description tests/unit/test_digital_twin_schemas.py::test_twin_session_response_carries_new_label_fields -v`
Expected: FAIL — `description` / `affected_object_label` / `affected_object_types` / `affected_site_labels` not on the response model.

- [ ] **Step 3: Update `CheckResultResponse`**

Edit `backend/app/modules/digital_twin/schemas.py`:

```python
class CheckResultResponse(BaseModel):
    check_id: str
    check_name: str
    layer: int
    status: str
    summary: str
    details: list[str] = Field(default_factory=list)
    affected_objects: list[str] = Field(default_factory=list)
    affected_sites: list[str] = Field(default_factory=list)
    remediation_hint: str | None = None
    pre_existing: bool = False
    description: str = ""
```

- [ ] **Step 4: Update `TwinSessionResponse`**

Add the three new fields and drop `writes_count`. Keep `writes_count` temporarily for frontend compatibility during the frontend rollout — it will be dropped in Task 12 when the list view stops reading it. Mark it as deprecated in a comment.

```python
class TwinSessionResponse(BaseModel):
    id: str
    status: str
    source: str
    source_ref: str | None = None
    overall_severity: str
    writes_count: int  # deprecated — will be removed after frontend migration
    affected_sites: list[str] = Field(default_factory=list)
    affected_site_labels: list[str] = Field(default_factory=list)
    affected_object_label: str | None = None
    affected_object_types: list[str] = Field(default_factory=list)
    remediation_count: int = 0
    prediction_report: PredictionReportResponse | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

- [ ] **Step 5: Update `session_to_response()` to populate new fields**

```python
def session_to_response(session: TwinSession) -> TwinSessionResponse:
    return TwinSessionResponse(
        id=str(session.id),
        status=session.status.value,
        source=session.source,
        source_ref=session.source_ref,
        overall_severity=session.overall_severity,
        writes_count=len(session.staged_writes),
        affected_sites=session.affected_sites,
        affected_site_labels=session.affected_site_labels,
        affected_object_label=session.affected_object_label,
        affected_object_types=session.affected_object_types,
        remediation_count=session.remediation_count,
        prediction_report=_build_report_response(session),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_digital_twin_schemas.py -v`
Expected: PASS (all tests in file, including the new ones).

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/digital_twin/schemas.py backend/tests/unit/test_digital_twin_schemas.py
git commit -m "feat(digital-twin): expose description and session labels in API schemas"
```

---

### Task 3: Staged write diff computation

**Files:**
- Create: `backend/app/modules/digital_twin/services/write_diff.py`
- Modify: `backend/app/modules/digital_twin/schemas.py`
- Test: `backend/tests/unit/test_write_diff.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_write_diff.py
from app.modules.digital_twin.models import StagedWrite
from app.modules.digital_twin.services.write_diff import build_write_diff


def test_diff_for_put_modifies_existing():
    base = {"name": "default", "port_usages": {"trunk": {"vlan_id": 10}}}
    write = StagedWrite(
        sequence=0,
        method="PUT",
        endpoint="/api/v1/orgs/org-id/networktemplates/t1",
        body={"name": "default", "port_usages": {"trunk": {"vlan_id": 20}}},
        object_type="networktemplates",
        object_id="t1",
    )
    diff, summary = build_write_diff(write, base)
    assert summary == "1 field changed"
    assert len(diff) == 1
    assert diff[0]["path"] == "port_usages.trunk.vlan_id"
    assert diff[0]["change"] == "modified"
    assert diff[0]["before"] == 10
    assert diff[0]["after"] == 20


def test_diff_for_post_marks_all_fields_added():
    write = StagedWrite(
        sequence=0,
        method="POST",
        endpoint="/api/v1/orgs/org-id/networktemplates",
        body={"name": "new-template", "enabled": True},
        object_type="networktemplates",
    )
    diff, summary = build_write_diff(write, None)
    assert summary == "new object"
    paths = {d["path"] for d in diff}
    assert paths == {"name", "enabled"}
    assert all(d["change"] == "added" for d in diff)


def test_diff_for_delete_has_no_fields():
    write = StagedWrite(
        sequence=0,
        method="DELETE",
        endpoint="/api/v1/orgs/org-id/networktemplates/t1",
        body=None,
        object_type="networktemplates",
        object_id="t1",
    )
    diff, summary = build_write_diff(write, {"name": "doomed"})
    assert summary == "deleted"
    assert diff == []


def test_diff_for_put_against_missing_base_treats_all_as_added():
    write = StagedWrite(
        sequence=0,
        method="PUT",
        endpoint="/api/v1/orgs/org-id/networktemplates/t1",
        body={"name": "x"},
        object_type="networktemplates",
        object_id="t1",
    )
    diff, summary = build_write_diff(write, None)
    assert summary == "1 field changed"
    assert diff[0]["change"] == "added"
    assert diff[0]["path"] == "name"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_write_diff.py -v`
Expected: FAIL — `build_write_diff` does not exist.

- [ ] **Step 3: Implement `build_write_diff`**

Create `backend/app/modules/digital_twin/services/write_diff.py`:

```python
"""Compute a before/after diff between a staged write and the base state."""

from __future__ import annotations

from typing import Any

from app.modules.backup.utils import deep_diff
from app.modules.digital_twin.models import StagedWrite


def build_write_diff(
    write: StagedWrite,
    base_body: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str]:
    """Return (diff_entries, summary) for a single staged write.

    diff_entries shape matches the frontend WriteDiffField:
        { path, change: 'added'|'removed'|'modified', before, after }
    summary is human-readable: "N fields changed" / "new object" / "deleted".
    """
    if write.method == "DELETE":
        return [], "deleted"

    new_body = write.body or {}
    old_body = base_body or {}

    if write.method == "POST":
        entries = [
            {"path": k, "change": "added", "before": None, "after": v}
            for k, v in new_body.items()
        ]
        return entries, "new object"

    # PUT — deep diff
    raw_changes = deep_diff(old_body, new_body)
    entries: list[dict[str, Any]] = []
    for change in raw_changes:
        ctype = change["type"]
        if ctype == "added":
            entries.append({
                "path": change["path"],
                "change": "added",
                "before": None,
                "after": change["value"],
            })
        elif ctype == "removed":
            entries.append({
                "path": change["path"],
                "change": "removed",
                "before": change["value"],
                "after": None,
            })
        else:  # modified
            entries.append({
                "path": change["path"],
                "change": "modified",
                "before": change["old"],
                "after": change["new"],
            })

    count = len(entries)
    summary = f"{count} field changed" if count == 1 else f"{count} fields changed"
    return entries, summary
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_write_diff.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Add `diff`/`diff_summary` to `StagedWriteResponse`**

Edit `backend/app/modules/digital_twin/schemas.py`:

```python
class WriteDiffField(BaseModel):
    path: str
    change: Literal["added", "removed", "modified"]
    before: Any | None = None
    after: Any | None = None


class StagedWriteResponse(BaseModel):
    sequence: int
    method: str
    endpoint: str
    body: dict[str, Any] | None = None
    object_type: str | None = None
    site_id: str | None = None
    object_id: str | None = None
    diff: list[WriteDiffField] = Field(default_factory=list)
    diff_summary: str | None = None
```

Add `from typing import Literal` at the top of `schemas.py` if not already present.

- [ ] **Step 6: Populate `diff` in `session_to_detail_response()`**

Edit the existing function — for each staged write, look up the base body from `session.resolved_state` and call `build_write_diff`. The `resolved_state` dict is keyed by `(object_type, site_id, object_id)` tuples (see `state_resolver.StateKey`). However the persisted field is a plain dict in Mongo, so keys are stringified. Use the staged write fields to reconstruct the key lookup.

```python
def session_to_detail_response(session: TwinSession) -> TwinSessionDetailResponse:
    from app.modules.digital_twin.services.state_resolver import canonicalize_object_type
    from app.modules.digital_twin.services.write_diff import build_write_diff

    base = session_to_response(session)

    base_state = session.resolved_state or {}

    def _base_body_for(write: StagedWrite) -> dict[str, Any] | None:
        canonical = canonicalize_object_type(write.object_type) or ""
        key = (canonical, write.site_id, write.object_id)
        value = base_state.get(key) or base_state.get(str(key))
        return value if isinstance(value, dict) else None

    staged_writes: list[StagedWriteResponse] = []
    for w in session.staged_writes:
        diff_entries, diff_summary = build_write_diff(w, _base_body_for(w))
        staged_writes.append(
            StagedWriteResponse(
                sequence=w.sequence,
                method=w.method,
                endpoint=w.endpoint,
                body=w.body,
                object_type=w.object_type,
                site_id=w.site_id,
                object_id=w.object_id,
                diff=[WriteDiffField(**d) for d in diff_entries],
                diff_summary=diff_summary,
            )
        )

    return TwinSessionDetailResponse(
        **base.model_dump(),
        ai_assessment=session.ai_assessment,
        execution_safe=session.prediction_report.execution_safe if session.prediction_report else True,
        staged_writes=staged_writes,
        remediation_history=[
            RemediationAttemptResponse(**r.model_dump()) for r in session.remediation_history
        ],
    )
```

- [ ] **Step 7: Run schema tests again**

Run: `cd backend && pytest tests/unit/test_digital_twin_schemas.py tests/unit/test_write_diff.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/modules/digital_twin/services/write_diff.py backend/app/modules/digital_twin/schemas.py backend/tests/unit/test_write_diff.py
git commit -m "feat(digital-twin): compute staged write diffs against base state"
```

---

### Task 4: Object and site label resolvers

**Files:**
- Create: `backend/app/modules/digital_twin/services/label_resolver.py`
- Test: `backend/tests/unit/test_label_resolver.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_label_resolver.py
import pytest

from app.modules.digital_twin.services.label_resolver import (
    format_object_label,
    _count_by_type,
)


def test_single_object_formats_as_type_and_name():
    label = format_object_label(
        object_types=["networktemplates"],
        object_names_by_type={"networktemplates": ["default-campus"]},
    )
    assert label == "networktemplates: default-campus"


def test_multiple_same_type_formats_as_count():
    label = format_object_label(
        object_types=["networktemplates", "networktemplates", "networktemplates"],
        object_names_by_type={"networktemplates": ["a", "b", "c"]},
    )
    assert label == "3 networktemplates"


def test_multiple_mixed_types_formats_as_mixed_summary():
    label = format_object_label(
        object_types=["networktemplates", "networktemplates", "wlans"],
        object_names_by_type={"networktemplates": ["a", "b"], "wlans": ["guest"]},
    )
    assert label == "3 objects: 2 networktemplates, 1 wlans"


def test_empty_object_types_returns_none():
    assert format_object_label(object_types=[], object_names_by_type={}) is None


def test_count_by_type():
    counts = _count_by_type(["a", "a", "b", "c", "a"])
    assert counts == {"a": 3, "b": 1, "c": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_label_resolver.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `format_object_label`**

Create `backend/app/modules/digital_twin/services/label_resolver.py`:

```python
"""Resolve human-readable labels for Twin sessions.

Separates the pure formatting logic (testable) from the DB lookups
(integration-tested via twin_service).
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.digital_twin.models import StagedWrite


def _count_by_type(object_types: list[str]) -> dict[str, int]:
    """Return a {type: count} dict preserving insertion order of first occurrence."""
    counts: dict[str, int] = {}
    for t in object_types:
        counts[t] = counts.get(t, 0) + 1
    return counts


def format_object_label(
    *,
    object_types: list[str],
    object_names_by_type: dict[str, list[str]],
) -> str | None:
    """Build the human-readable object label for a Twin session.

    - empty -> None
    - 1 object -> "{type}: {name}"
    - N objects of same type -> "N {type}"
    - mixed types -> "N objects: a type_a, b type_b"
    """
    if not object_types:
        return None

    counts = _count_by_type(object_types)

    if len(object_types) == 1:
        the_type = object_types[0]
        names = object_names_by_type.get(the_type, [])
        if names:
            return f"{the_type}: {names[0]}"
        return the_type

    if len(counts) == 1:
        the_type = next(iter(counts))
        return f"{counts[the_type]} {the_type}"

    parts = [f"{count} {t}" for t, count in counts.items()]
    total = len(object_types)
    return f"{total} objects: {', '.join(parts)}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_label_resolver.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Add the async DB lookup helpers**

Append to `backend/app/modules/digital_twin/services/label_resolver.py`:

```python
async def fetch_object_names_by_type(
    *,
    org_id: str,
    writes: "list[StagedWrite]",
) -> dict[str, list[str]]:
    """Resolve object names from backup data for each staged write.

    Returns a dict keyed by object_type with a list of names (one per write that
    touched that type). Missing names fall back to the first 8 chars of object_id.
    """
    from app.modules.backup.models import BackupObject
    from app.modules.digital_twin.services.state_resolver import canonicalize_object_type

    result: dict[str, list[str]] = {}
    for w in writes:
        canonical = canonicalize_object_type(w.object_type) or ""
        if not canonical:
            continue

        name: str | None = None
        if w.object_id:
            doc = await BackupObject.find(
                {
                    "org_id": org_id,
                    "object_type": canonical,
                    "object_id": w.object_id,
                    "is_deleted": False,
                }
            ).first_or_none()
            if doc:
                data = getattr(doc, "data", None) or {}
                name = data.get("name") or data.get("ssid")

        if not name:
            name = (w.object_id[:8] if w.object_id else canonical)

        result.setdefault(canonical, []).append(name)

    return result


async def fetch_site_names(*, org_id: str, site_ids: list[str]) -> list[str]:
    """Resolve site names for a list of site IDs via a single query.

    Missing sites fall back to the site_id itself (truncated to 8 chars).
    """
    from app.modules.backup.models import BackupObject

    if not site_ids:
        return []

    cursor = BackupObject.find(
        {
            "org_id": org_id,
            "object_type": "info",
            "site_id": {"$in": site_ids},
            "is_deleted": False,
        }
    )
    id_to_name: dict[str, str] = {}
    async for doc in cursor:
        data = getattr(doc, "data", None) or {}
        sid = getattr(doc, "site_id", None)
        if sid:
            id_to_name[sid] = data.get("name") or sid[:8]

    return [id_to_name.get(sid, sid[:8]) for sid in site_ids]
```

- [ ] **Step 6: Run tests to verify nothing regressed**

Run: `cd backend && pytest tests/unit/test_label_resolver.py -v`
Expected: PASS (still 5 tests).

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/digital_twin/services/label_resolver.py backend/tests/unit/test_label_resolver.py
git commit -m "feat(digital-twin): add object and site label resolvers"
```

---

### Task 5: Wire label resolvers into `twin_service.simulate()`

**Files:**
- Modify: `backend/app/modules/digital_twin/services/twin_service.py`
- Test: `backend/tests/integration/test_twin_service_labels.py` (create)

- [ ] **Step 1: Locate the existing label-write path**

Read lines 240-300 of `twin_service.py`. Identify the block that sets `session.affected_sites` and `session.affected_object_types`. Both the new-session and existing-session branches need the new fields populated.

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/integration/test_twin_service_labels.py
import pytest
from unittest.mock import AsyncMock, patch

from app.modules.digital_twin.models import StagedWrite


@pytest.mark.asyncio
async def test_simulate_populates_object_and_site_labels(monkeypatch):
    from app.modules.digital_twin.services import twin_service

    writes = [
        {
            "method": "PUT",
            "endpoint": "/api/v1/orgs/org-id/networktemplates/t1",
        }
    ]

    async def fake_fetch_object_names_by_type(*, org_id, writes):
        return {"networktemplates": ["default-campus"]}

    async def fake_fetch_site_names(*, org_id, site_ids):
        return [f"site-{s[:4]}" for s in site_ids]

    monkeypatch.setattr(
        "app.modules.digital_twin.services.label_resolver.fetch_object_names_by_type",
        fake_fetch_object_names_by_type,
    )
    monkeypatch.setattr(
        "app.modules.digital_twin.services.label_resolver.fetch_site_names",
        fake_fetch_site_names,
    )

    # Stub the rest of the simulate flow so we isolate the label path.
    # The real integration test is heavy; here we only assert that if we
    # CALL the label resolvers directly (no mocks needed), we get a
    # correctly formatted label back.
    from app.modules.digital_twin.services.label_resolver import format_object_label

    names = await fake_fetch_object_names_by_type(
        org_id="org-id", writes=writes
    )
    label = format_object_label(
        object_types=["networktemplates"],
        object_names_by_type=names,
    )
    assert label == "networktemplates: default-campus"

    site_labels = await fake_fetch_site_names(org_id="org-id", site_ids=["aaaa-bbbb"])
    assert site_labels == ["site-aaaa"]
```

Note: a full end-to-end `simulate()` test would require MongoDB and a backup fixture. This task verifies the *integration point* — the actual wiring into `twin_service` is exercised by manual smoke testing (Step 4).

- [ ] **Step 3: Wire the resolvers into `twin_service.simulate()`**

In `backend/app/modules/digital_twin/services/twin_service.py`, find the block near line 260 where `affected_sites` and `affected_object_types` are assigned. Import the resolvers at the top of the file:

```python
from app.modules.digital_twin.services.label_resolver import (
    fetch_object_names_by_type,
    fetch_site_names,
    format_object_label,
)
```

After the existing assignment:

```python
affected_sites, affected_types = collect_affected_metadata(staged_writes)

# NEW — resolve human-readable labels
object_names = await fetch_object_names_by_type(
    org_id=org_id, writes=staged_writes
)
affected_object_label = format_object_label(
    object_types=affected_types,
    object_names_by_type=object_names,
)
# NOTE: site labels are resolved LATER, after template fan-out
#       expands affected_sites (see line ~293).
```

Update the new-session branch:

```python
session.affected_sites = affected_sites
session.affected_object_types = affected_types
session.affected_object_label = affected_object_label
```

And in the create-path (the `TwinSession(...)` constructor call in the same block):

```python
session = TwinSession(
    user_id=user_id,
    org_id=org_id,
    source=source,
    source_ref=source_ref,
    staged_writes=staged_writes,
    affected_sites=affected_sites,
    affected_object_types=affected_types,
    affected_object_label=affected_object_label,
)
```

- [ ] **Step 4: Resolve site labels after template fan-out**

Find the block near line 292-294 where `all_impacted_sites` is merged. After the assignment `session.affected_sites = affected_sites`, add:

```python
# Resolve site labels once the full fan-out is known
session.affected_site_labels = await fetch_site_names(
    org_id=org_id, site_ids=affected_sites
)
```

- [ ] **Step 5: Run unit tests**

Run: `cd backend && pytest tests/unit/test_label_resolver.py tests/integration/test_twin_service_labels.py -v`
Expected: PASS.

- [ ] **Step 6: Smoke test against dev mongo**

Start the dev stack and call the MCP digital_twin simulate tool with a real object:

```bash
# In one terminal:
cd backend && uvicorn app.main:app --reload --port 8000

# Then via the in-app chat or an HTTP request, trigger a simulation of
# a networktemplate update. Query MongoDB:
mongosh mist_automation --eval \
  'db.twin_sessions.find().sort({created_at: -1}).limit(1).forEach(d => print(JSON.stringify({label: d.affected_object_label, sites: d.affected_site_labels}, null, 2)))'
```

Expected: `affected_object_label` matches `"networktemplates: <real-name>"`; `affected_site_labels` is a list of real site names.

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/digital_twin/services/twin_service.py backend/tests/integration/test_twin_service_labels.py
git commit -m "feat(digital-twin): populate object and site labels during simulate"
```

---

### Task 6: Simulation log capture

**Files:**
- Create: `backend/app/modules/digital_twin/services/twin_logging.py`
- Modify: `backend/app/modules/digital_twin/services/twin_service.py`
- Modify: `backend/app/core/logging.py` (register the processor)
- Test: `backend/tests/unit/test_twin_logging.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_twin_logging.py
import structlog

from app.modules.digital_twin.services.twin_logging import (
    bind_twin_session,
    capture_twin_session_logs,
    drain_buffer,
)


def test_processor_ignored_when_no_session_bound():
    processor = capture_twin_session_logs
    event_dict = {"event": "anything", "level": "info"}
    result = processor(None, "info", dict(event_dict))
    # Processor must return the event_dict unchanged and not store anything.
    assert result == event_dict
    # No bound session id -> buffer remains empty
    assert drain_buffer("nonexistent") == []


def test_processor_captures_events_when_session_is_bound():
    with bind_twin_session("sess-A", phase="simulate"):
        capture_twin_session_logs(
            None, "info", {"event": "foo", "level": "info", "k": 1}
        )
        capture_twin_session_logs(
            None, "warning", {"event": "bar", "level": "warning", "k": 2}
        )

    entries = drain_buffer("sess-A")
    assert len(entries) == 2
    assert entries[0].event == "foo"
    assert entries[0].phase == "simulate"
    assert entries[0].context == {"k": 1}
    assert entries[1].level == "warning"


def test_buffer_is_bounded():
    with bind_twin_session("sess-B", phase="simulate"):
        for i in range(1100):
            capture_twin_session_logs(
                None, "info", {"event": f"ev{i}", "level": "info"}
            )

    entries = drain_buffer("sess-B")
    assert len(entries) == 1000
    # Oldest entries are dropped — entry 0 should be ev100 (1100 - 1000)
    assert entries[0].event == "ev100"


def test_nested_session_bindings_use_latest():
    with bind_twin_session("outer", phase="simulate"):
        capture_twin_session_logs(None, "info", {"event": "outer1", "level": "info"})
        with bind_twin_session("outer", phase="remediate"):
            capture_twin_session_logs(None, "info", {"event": "inner", "level": "info"})
        capture_twin_session_logs(None, "info", {"event": "outer2", "level": "info"})

    entries = drain_buffer("outer")
    phases = [e.phase for e in entries]
    assert phases == ["simulate", "remediate", "simulate"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_twin_logging.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `twin_logging`**

Create `backend/app/modules/digital_twin/services/twin_logging.py`:

```python
"""Structlog processor + context bindings for per-session log capture.

Usage in call sites:

    with bind_twin_session(session_id, phase="simulate"):
        ... run structlog.get_logger().info("event", key=value) ...

    # Later, to persist:
    entries = drain_buffer(session_id)
    session.simulation_logs.extend(entries)
    await session.save()
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Iterator

from app.modules.digital_twin.models import SimulationLogEntry

_MAX_ENTRIES_PER_SESSION = 1000

twin_session_id_var: ContextVar[str | None] = ContextVar("twin_session_id", default=None)
twin_session_phase_var: ContextVar[str | None] = ContextVar("twin_session_phase", default=None)

_buffers: dict[str, list[SimulationLogEntry]] = {}
_buffers_lock = Lock()


@contextmanager
def bind_twin_session(session_id: str, phase: str) -> Iterator[None]:
    """Bind session id and phase to the current logging context."""
    sid_token = twin_session_id_var.set(session_id)
    phase_token = twin_session_phase_var.set(phase)
    try:
        yield
    finally:
        twin_session_phase_var.reset(phase_token)
        twin_session_id_var.reset(sid_token)


def capture_twin_session_logs(
    _logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Structlog processor — appends the event to the per-session buffer if bound."""
    session_id = twin_session_id_var.get()
    if not session_id:
        return event_dict

    phase = twin_session_phase_var.get() or "other"
    event = event_dict.get("event", "")
    level = event_dict.get("level", method_name) or method_name
    context = {
        k: v for k, v in event_dict.items() if k not in {"event", "level", "timestamp"}
    }

    entry = SimulationLogEntry(
        timestamp=datetime.now(timezone.utc),
        level=level if level in {"debug", "info", "warning", "error"} else "info",
        event=str(event),
        phase=phase if phase in {"simulate", "remediate", "approve", "execute", "other"} else "other",
        context=context,
    )

    with _buffers_lock:
        buf = _buffers.setdefault(session_id, [])
        buf.append(entry)
        if len(buf) > _MAX_ENTRIES_PER_SESSION:
            # Drop oldest, keep most recent _MAX_ENTRIES_PER_SESSION
            del buf[: len(buf) - _MAX_ENTRIES_PER_SESSION]

    return event_dict


def drain_buffer(session_id: str) -> list[SimulationLogEntry]:
    """Return and clear the log buffer for the given session id."""
    with _buffers_lock:
        return _buffers.pop(session_id, [])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_twin_logging.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Register the processor with structlog**

Edit `backend/app/core/logging.py`. Find the `structlog.configure(processors=[...])` call and append `capture_twin_session_logs` to the processors list AFTER the standard level/event formatter but BEFORE the final renderer (JSON or console).

```python
from app.modules.digital_twin.services.twin_logging import capture_twin_session_logs

structlog.configure(
    processors=[
        # ... existing processors ...
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        capture_twin_session_logs,   # NEW — must come before the final renderer
        structlog.processors.JSONRenderer(),
    ],
)
```

If `backend/app/core/logging.py` has a different structure, place the new processor immediately before the final renderer.

- [ ] **Step 6: Wire `bind_twin_session` into `twin_service`**

In `twin_service.py`, wrap the body of `simulate()`, `approve_and_execute()`, and any remediation-loop function. Example for `simulate()`:

```python
from app.modules.digital_twin.services.twin_logging import bind_twin_session, drain_buffer

async def simulate(*, user_id, org_id, writes, source, source_ref=None, existing_session_id=None):
    # ... early setup that doesn't need a session id yet ...

    # Create/load session first (this bit existed)
    session = await _create_or_load_session(...)

    with bind_twin_session(str(session.id), phase="simulate"):
        # ... existing body of simulate goes here ...
        pass

    # Drain and persist logs
    entries = drain_buffer(str(session.id))
    if entries:
        session.simulation_logs.extend(entries)
        # Trim to bound size after remediations too
        if len(session.simulation_logs) > 1000:
            session.simulation_logs = session.simulation_logs[-1000:]
        await session.save()

    return session
```

Apply the same pattern to `approve_and_execute()` with `phase="approve"` → `phase="execute"` transitions, and to the remediation loop with `phase="remediate"`.

- [ ] **Step 7: Run existing twin_service tests**

Run: `cd backend && pytest tests/unit/test_twin_service_preflight.py tests/unit/test_twin_service_session_security.py -v`
Expected: PASS (no behavioral changes to existing logic).

- [ ] **Step 8: Commit**

```bash
git add backend/app/modules/digital_twin/services/twin_logging.py backend/app/modules/digital_twin/services/twin_service.py backend/app/core/logging.py backend/tests/unit/test_twin_logging.py
git commit -m "feat(digital-twin): capture per-session simulation logs via structlog"
```

---

### Task 7: Admin-only logs endpoint

**Files:**
- Modify: `backend/app/api/v1/digital_twin.py`
- Test: `backend/tests/unit/test_digital_twin_logs_endpoint.py`

- [ ] **Step 1: Read the existing router to match patterns**

Read the first 50 lines and the handler signatures in `backend/app/api/v1/digital_twin.py`. Match the dependency-injection style for auth.

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/unit/test_digital_twin_logs_endpoint.py
from datetime import datetime, timezone

import pytest
from unittest.mock import AsyncMock, patch

from app.modules.digital_twin.models import SimulationLogEntry


@pytest.fixture
def sample_entries():
    return [
        SimulationLogEntry(
            timestamp=datetime(2026, 4, 12, 18, 50, 40, tzinfo=timezone.utc),
            level="info",
            event="simulate_start",
            phase="simulate",
            context={"org_id": "org"},
        ),
        SimulationLogEntry(
            timestamp=datetime(2026, 4, 12, 18, 50, 41, tzinfo=timezone.utc),
            level="warning",
            event="twin_write_parse_error",
            phase="simulate",
            context={"sequence": 0},
        ),
        SimulationLogEntry(
            timestamp=datetime(2026, 4, 12, 18, 50, 42, tzinfo=timezone.utc),
            level="error",
            event="resolved_failed",
            phase="remediate",
            context={},
        ),
    ]


@pytest.mark.asyncio
async def test_filter_by_level(sample_entries):
    from app.api.v1.digital_twin import _filter_logs

    result = _filter_logs(sample_entries, level="warning", phase=None, search=None)
    assert len(result) == 1
    assert result[0].event == "twin_write_parse_error"


@pytest.mark.asyncio
async def test_filter_by_phase(sample_entries):
    from app.api.v1.digital_twin import _filter_logs

    result = _filter_logs(sample_entries, level=None, phase="remediate", search=None)
    assert len(result) == 1
    assert result[0].phase == "remediate"


@pytest.mark.asyncio
async def test_filter_by_search(sample_entries):
    from app.api.v1.digital_twin import _filter_logs

    result = _filter_logs(sample_entries, level=None, phase=None, search="parse")
    assert len(result) == 1
    assert "parse" in result[0].event


@pytest.mark.asyncio
async def test_combined_filters(sample_entries):
    from app.api.v1.digital_twin import _filter_logs

    result = _filter_logs(sample_entries, level="info", phase="simulate", search="start")
    assert len(result) == 1
    assert result[0].event == "simulate_start"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_digital_twin_logs_endpoint.py -v`
Expected: FAIL — `_filter_logs` not defined.

- [ ] **Step 4: Add the helper and the endpoint**

Edit `backend/app/api/v1/digital_twin.py`:

```python
from fastapi import Query

from app.dependencies import require_admin
from app.models.user import User
from app.modules.digital_twin.models import SimulationLogEntry


def _filter_logs(
    entries: list[SimulationLogEntry],
    *,
    level: str | None,
    phase: str | None,
    search: str | None,
) -> list[SimulationLogEntry]:
    """Apply level/phase/search filters to a list of SimulationLogEntry."""
    results = entries
    if level:
        results = [e for e in results if e.level == level]
    if phase:
        results = [e for e in results if e.phase == phase]
    if search:
        needle = search.lower()
        results = [
            e
            for e in results
            if needle in e.event.lower()
            or any(needle in str(v).lower() for v in e.context.values())
        ]
    return results


@router.get("/sessions/{session_id}/logs", response_model=list[SimulationLogEntry])
async def get_session_logs(
    session_id: str,
    level: str | None = Query(None, pattern="^(debug|info|warning|error)$"),
    phase: str | None = Query(None, pattern="^(simulate|remediate|approve|execute|other)$"),
    search: str | None = Query(None, max_length=200),
    current_user: User = Depends(require_admin),
) -> list[SimulationLogEntry]:
    """Return the persisted simulation logs for a Twin session (admin only)."""
    from app.modules.digital_twin.services import twin_service

    session = await twin_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return _filter_logs(session.simulation_logs, level=level, phase=phase, search=search)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_digital_twin_logs_endpoint.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/digital_twin.py backend/tests/unit/test_digital_twin_logs_endpoint.py
git commit -m "feat(digital-twin): add admin-only simulation logs endpoint"
```

---

## Phase B — MCP Client Identity and Migration

### Task 8: Propagate MCP client name into `twin_service.simulate()`

**Files:**
- Modify: `backend/app/modules/mcp_server/tools/digital_twin.py`
- Modify: `backend/app/modules/mcp_server/server.py` (if client info is captured here)
- Modify: `backend/app/modules/digital_twin/services/twin_service.py`
- Test: `backend/tests/unit/test_mcp_tool_source_ref.py`

- [ ] **Step 1: Locate where fastmcp exposes client info**

Read `backend/app/modules/mcp_server/server.py`. Search for `clientInfo`, `client_name`, or usage of `Context` / `CurrentContext`. Modern fastmcp exposes client info via the `Context` object — typically `ctx.client.name` or similar. If nothing is captured yet, capture it from the `initialize` handshake via a middleware or per-request context var.

If fastmcp does not expose client info directly, fall back to reading it from the MCP request headers / session initialization params. Document the chosen approach inline.

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/unit/test_mcp_tool_source_ref.py
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_simulate_passes_source_ref_from_mcp_context():
    from app.modules.mcp_server.tools.digital_twin import _resolve_source_ref

    # Internal chat — no external client, default to Internal Chat
    ref = _resolve_source_ref(client_name=None)
    assert ref == "Internal Chat"

    # External MCP client
    ref = _resolve_source_ref(client_name="Claude Desktop")
    assert ref == "Claude Desktop"

    # Empty string normalized to Internal Chat
    ref = _resolve_source_ref(client_name="")
    assert ref == "Internal Chat"

    # Whitespace normalized
    ref = _resolve_source_ref(client_name="  Cursor  ")
    assert ref == "Cursor"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_mcp_tool_source_ref.py -v`
Expected: FAIL — `_resolve_source_ref` not defined.

- [ ] **Step 4: Implement `_resolve_source_ref`**

Edit `backend/app/modules/mcp_server/tools/digital_twin.py`:

```python
def _resolve_source_ref(client_name: str | None) -> str:
    """Normalize the MCP client name into a display label.

    Empty / None -> "Internal Chat" (in-app LLM chat).
    Trimmed client name -> displayed as-is.
    """
    if not client_name:
        return "Internal Chat"
    trimmed = client_name.strip()
    return trimmed or "Internal Chat"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_mcp_tool_source_ref.py -v`
Expected: PASS.

- [ ] **Step 6: Wire into the `digital_twin` tool body**

In the same file, find the `simulate` branch that calls `twin_service.simulate(...)`. Pass the resolved source ref:

```python
client_name: str | None = None
try:
    client_name = getattr(ctx, "client", None) and getattr(ctx.client, "name", None)
except Exception:
    client_name = None

source_ref = _resolve_source_ref(client_name)

session = await twin_service.simulate(
    user_id=user_id,
    org_id=validated['org_id'],
    writes=write_list,
    source='mcp',           # CHANGED from 'llm_chat'
    source_ref=source_ref,  # NEW
    existing_session_id=existing_id,
)
```

- [ ] **Step 7: Update `twin_service.simulate` signature**

In `twin_service.py`, add `source_ref: str | None = None` to the `simulate()` signature and pass it through to the `TwinSession(...)` constructor. If `source_ref` is provided for an existing session, overwrite the stored value.

- [ ] **Step 8: Run the MCP tool tests**

Run: `cd backend && pytest tests/unit/test_mcp_tool_input_validation.py tests/unit/test_mcp_tool_source_ref.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/modules/mcp_server/tools/digital_twin.py backend/app/modules/digital_twin/services/twin_service.py backend/tests/unit/test_mcp_tool_source_ref.py
git commit -m "feat(digital-twin): record MCP client identity as source_ref"
```

---

### Task 9: One-time migration of legacy `llm_chat` sessions

**Files:**
- Create: `backend/migrations/20260412_rename_llm_chat_to_mcp.py`
- Test: run manually via `pytest -k migration` or via a dev mongo instance.

- [ ] **Step 1: Write the migration script**

```python
# backend/migrations/20260412_rename_llm_chat_to_mcp.py
"""One-time migration: rename TwinSession.source from 'llm_chat' to 'mcp'.

Run manually:
    python -m backend.migrations.20260412_rename_llm_chat_to_mcp
"""

import asyncio
import structlog

from app.core.database import init_db
from app.modules.digital_twin.models import TwinSession

logger = structlog.get_logger(__name__)


async def main() -> None:
    await init_db()
    result = await TwinSession.find({"source": "llm_chat"}).update(
        {"$set": {"source": "mcp"}}
    )
    updated = getattr(result, "modified_count", None)
    logger.info("twin_source_migration_done", modified=updated)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Fix any existing test fixtures that use `llm_chat`**

Search and replace the hardcoded string in test files only:

```bash
cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui
grep -rn '"llm_chat"\|'"'"'llm_chat'"'"'' backend/tests/ backend/app/modules/digital_twin/ backend/app/modules/mcp_server/
```

For each hit: if the string is inside a test fixture or assertion, replace with `"mcp"`. If the string is a comment describing legacy behavior, leave it alone. If the hit is in the `Literal[...]` declaration of the model field, leave it alone (already updated in Task 1).

- [ ] **Step 3: Run all Twin-adjacent tests**

Run:
```bash
cd backend && pytest tests/unit/test_digital_twin_models.py tests/unit/test_digital_twin_schemas.py tests/unit/test_twin_service_preflight.py tests/unit/test_twin_service_session_security.py tests/unit/test_mcp_tool_input_validation.py tests/unit/test_mcp_tool_source_ref.py tests/unit/test_write_diff.py tests/unit/test_label_resolver.py tests/unit/test_twin_logging.py tests/unit/test_digital_twin_logs_endpoint.py -v
```
Expected: PASS.

- [ ] **Step 4: Run the migration against local dev mongo**

```bash
cd backend && python -m backend.migrations.20260412_rename_llm_chat_to_mcp
```

Then verify in mongosh:

```bash
mongosh mist_automation --eval 'db.twin_sessions.countDocuments({source: "llm_chat"})'
# Expected: 0

mongosh mist_automation --eval 'db.twin_sessions.countDocuments({source: "mcp"})'
# Expected: > 0 (equal to previous llm_chat count)
```

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/20260412_rename_llm_chat_to_mcp.py backend/tests/
git commit -m "chore(digital-twin): migrate legacy llm_chat sessions to mcp"
```

---

## Phase C — Frontend Models and Service

### Task 10: Update TypeScript models and service

**Files:**
- Modify: `frontend/src/app/features/digital-twin/models/twin-session.model.ts`

- [ ] **Step 1: Update `CheckResultModel`**

Add `description` if missing:

```typescript
export interface CheckResultModel {
  check_id: string;
  check_name: string;
  layer: number;
  status: 'pass' | 'info' | 'warning' | 'error' | 'critical' | 'skipped';
  summary: string;
  details: string[];
  affected_objects: string[];
  affected_sites: string[];
  remediation_hint: string | null;
  description: string;
}
```

(If the field is already on the interface from the earlier check-description work, no change needed.)

- [ ] **Step 2: Add `WriteDiffField` and extend `StagedWriteModel`**

```typescript
export interface WriteDiffField {
  path: string;
  change: 'added' | 'removed' | 'modified';
  before: unknown;
  after: unknown;
}

export interface StagedWriteModel {
  sequence: number;
  method: string;
  endpoint: string;
  body: Record<string, unknown> | null;
  object_type: string | null;
  site_id: string | null;
  object_id: string | null;
  diff: WriteDiffField[];
  diff_summary: string | null;
}
```

- [ ] **Step 3: Extend `TwinSessionSummary`**

```typescript
export interface TwinSessionSummary {
  id: string;
  status: string;
  source: 'mcp' | 'workflow' | 'backup_restore';
  source_ref: string | null;
  overall_severity: string;
  writes_count: number;
  affected_sites: string[];
  affected_site_labels: string[];
  affected_object_label: string | null;
  affected_object_types: string[];
  remediation_count: number;
  prediction_report: PredictionReportModel | null;
  created_at: string;
  updated_at: string;
}
```

- [ ] **Step 4: Add `SimulationLogEntry`**

```typescript
export interface SimulationLogEntry {
  timestamp: string;
  level: 'debug' | 'info' | 'warning' | 'error';
  event: string;
  phase: 'simulate' | 'remediate' | 'approve' | 'execute' | 'other';
  context: Record<string, unknown>;
}
```

- [ ] **Step 5: Add a `getSessionLogs` method to the service**

Edit `frontend/src/app/features/digital-twin/digital-twin.service.ts`:

```typescript
getSessionLogs(
  id: string,
  filters: { level?: string; phase?: string; search?: string } = {},
): Observable<SimulationLogEntry[]> {
  const params: Record<string, string> = {};
  if (filters.level) params['level'] = filters.level;
  if (filters.phase) params['phase'] = filters.phase;
  if (filters.search) params['search'] = filters.search;
  return this.api.get<SimulationLogEntry[]>(`/digital-twin/sessions/${id}/logs`, params);
}
```

Update the top-level import to include `SimulationLogEntry`.

- [ ] **Step 6: Type check**

Run: `cd frontend && npx ng build --configuration=development 2>&1 | tail -30`
Expected: build succeeds with no type errors, or the only errors are in files we haven't touched yet (session-list, session-detail).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/features/digital-twin/models/twin-session.model.ts frontend/src/app/features/digital-twin/digital-twin.service.ts
git commit -m "feat(digital-twin): extend TS models for labels, diffs, and logs"
```

---

## Phase D — Frontend List View

### Task 11: Add `computeLayerRollup` helper

**Files:**
- Create: `frontend/src/app/features/digital-twin/utils/layer-rollup.ts`
- Test: `frontend/src/app/features/digital-twin/utils/layer-rollup.spec.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/app/features/digital-twin/utils/layer-rollup.spec.ts
import { describe, expect, it } from 'vitest';
import { computeLayerRollup, LayerRollup } from './layer-rollup';
import { CheckResultModel, PredictionReportModel } from '../models/twin-session.model';

function check(id: string, layer: number, status: CheckResultModel['status']): CheckResultModel {
  return {
    check_id: id,
    check_name: id,
    layer,
    status,
    summary: '',
    details: [],
    affected_objects: [],
    affected_sites: [],
    remediation_hint: null,
    description: '',
  };
}

function report(checks: CheckResultModel[]): PredictionReportModel {
  return {
    total_checks: checks.length,
    passed: checks.filter((c) => c.status === 'pass').length,
    warnings: checks.filter((c) => c.status === 'warning').length,
    errors: checks.filter((c) => c.status === 'error').length,
    critical: checks.filter((c) => c.status === 'critical').length,
    skipped: checks.filter((c) => c.status === 'skipped').length,
    check_results: checks,
    overall_severity: 'clean',
    summary: '',
    execution_safe: true,
  };
}

describe('computeLayerRollup', () => {
  it('returns all 6 layers L0..L5 in order', () => {
    const rollup = computeLayerRollup(report([]));
    expect(rollup.map((r) => r.layer)).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it('marks layers with no checks as skipped', () => {
    const rollup = computeLayerRollup(report([check('a', 1, 'pass')]));
    expect(rollup[0].status).toBe('skip');
    expect(rollup[1].status).toBe('pass');
    expect(rollup[1].passed).toBe(1);
    expect(rollup[1].total).toBe(1);
  });

  it('picks the worst status within a layer', () => {
    const rollup = computeLayerRollup(
      report([
        check('a', 1, 'pass'),
        check('b', 1, 'warning'),
        check('c', 1, 'error'),
      ]),
    );
    expect(rollup[1].status).toBe('err');
    expect(rollup[1].passed).toBe(1);
    expect(rollup[1].total).toBe(3);
  });

  it('treats critical as worse than error', () => {
    const rollup = computeLayerRollup(
      report([check('a', 2, 'error'), check('b', 2, 'critical')]),
    );
    expect(rollup[2].status).toBe('crit');
  });

  it('returns a fully-skipped rollup for null report', () => {
    const rollup = computeLayerRollup(null);
    expect(rollup.every((r) => r.status === 'skip')).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/app/features/digital-twin/utils/layer-rollup.spec.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `computeLayerRollup`**

Create `frontend/src/app/features/digital-twin/utils/layer-rollup.ts`:

```typescript
import { CheckResultModel, PredictionReportModel } from '../models/twin-session.model';

export interface LayerRollup {
  layer: number;
  passed: number;
  total: number;
  status: 'pass' | 'warn' | 'err' | 'crit' | 'skip';
}

const LAYER_NUMBERS = [0, 1, 2, 3, 4, 5];

const STATUS_RANK: Record<CheckResultModel['status'], number> = {
  pass: 0,
  info: 0,
  skipped: 0,
  warning: 1,
  error: 2,
  critical: 3,
};

const RANK_TO_LAYER_STATUS: Record<number, LayerRollup['status']> = {
  0: 'pass',
  1: 'warn',
  2: 'err',
  3: 'crit',
};

export function computeLayerRollup(
  report: PredictionReportModel | null,
): LayerRollup[] {
  const checksByLayer = new Map<number, CheckResultModel[]>();
  for (const layer of LAYER_NUMBERS) {
    checksByLayer.set(layer, []);
  }

  for (const check of report?.check_results ?? []) {
    const arr = checksByLayer.get(check.layer);
    if (arr) arr.push(check);
  }

  return LAYER_NUMBERS.map((layer) => {
    const checks = checksByLayer.get(layer) ?? [];
    if (checks.length === 0) {
      return { layer, passed: 0, total: 0, status: 'skip' as const };
    }
    const passed = checks.filter((c) => c.status === 'pass' || c.status === 'info').length;
    const worstRank = Math.max(...checks.map((c) => STATUS_RANK[c.status] ?? 0));
    const status = RANK_TO_LAYER_STATUS[worstRank] ?? 'pass';
    return { layer, passed, total: checks.length, status };
  });
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/app/features/digital-twin/utils/layer-rollup.spec.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/features/digital-twin/utils/
git commit -m "feat(digital-twin): add computeLayerRollup helper"
```

---

### Task 12: Rework the session-list columns

**Files:**
- Modify: `frontend/src/app/features/digital-twin/session-list/session-list.component.ts`
- Modify: `frontend/src/app/features/digital-twin/session-list/session-list.component.html`
- Modify: `frontend/src/app/features/digital-twin/session-list/session-list.component.scss`

- [ ] **Step 1: Update the component class**

Edit `session-list.component.ts`. Replace `displayedColumns` and add helpers:

```typescript
import { LayerRollup, computeLayerRollup } from '../utils/layer-rollup';

// In the class:
readonly displayedColumns = [
  'status',
  'source',
  'object',
  'sites',
  'severity',
  'layers',
  'created_at',
];

layerRollupFor(summary: TwinSessionSummary): LayerRollup[] {
  return computeLayerRollup(summary.prediction_report);
}

sourceLabel(summary: TwinSessionSummary): string {
  switch (summary.source) {
    case 'mcp':
      return 'MCP';
    case 'workflow':
      return 'Workflow';
    case 'backup_restore':
      return 'Backup Restore';
    default:
      return summary.source;
  }
}

sourceSubLabel(summary: TwinSessionSummary): string | null {
  if (summary.source === 'mcp') return summary.source_ref ?? 'Internal Chat';
  return summary.source_ref;
}

objectTypeBadge(summary: TwinSessionSummary): string {
  if (summary.affected_object_types.length === 0) return '—';
  if (summary.affected_object_types.length === 1) return summary.affected_object_types[0];
  return 'multiple';
}

objectLabel(summary: TwinSessionSummary): string {
  return summary.affected_object_label ?? '—';
}

sitesLabel(summary: TwinSessionSummary): string {
  const count = summary.affected_sites.length;
  if (count === 0) return '—';
  return `${count} site${count === 1 ? '' : 's'}`;
}

sitesTooltip(summary: TwinSessionSummary): string {
  const names = summary.affected_site_labels ?? [];
  if (names.length === 0) return '';
  if (names.length <= 10) return names.join(', ');
  return `${names.slice(0, 10).join(', ')}, +${names.length - 10} more`;
}
```

Also drop any existing `statusOptions` entry for `"llm_chat"` and add/replace with `"mcp"`. `sourceOptions` should become:

```typescript
readonly sourceOptions = [
  { value: 'mcp', label: 'MCP' },
  { value: 'workflow', label: 'Workflow' },
  { value: 'backup_restore', label: 'Backup Restore' },
];
```

- [ ] **Step 2: Update the template**

Edit `session-list.component.html`. Replace the column definitions with the new set. Between the existing `status` column and the existing `severity` column, add the new columns. The template below shows the NEW columns only — keep the existing `status`, `severity`, and `created_at` column bodies.

```html
<!-- Source column (replaces the existing one) -->
<ng-container matColumnDef="source">
  <th mat-header-cell *matHeaderCellDef>Source</th>
  <td mat-cell *matCellDef="let s">
    <div class="source-cell">
      <span class="source-main">{{ sourceLabel(s) }}</span>
      @if (sourceSubLabel(s)) {
        <span class="source-sub">{{ sourceSubLabel(s) }}</span>
      }
    </div>
  </td>
</ng-container>

<!-- Object Changed column (new) -->
<ng-container matColumnDef="object">
  <th mat-header-cell *matHeaderCellDef>Object Changed</th>
  <td mat-cell *matCellDef="let s">
    <div class="object-cell">
      <span class="object-type">{{ objectTypeBadge(s) }}</span>
      <span class="object-name">{{ objectLabel(s) }}</span>
    </div>
  </td>
</ng-container>

<!-- Sites column (new) -->
<ng-container matColumnDef="sites">
  <th mat-header-cell *matHeaderCellDef>Sites</th>
  <td mat-cell *matCellDef="let s">
    <span class="sites-count-pill" [matTooltip]="sitesTooltip(s)">
      {{ sitesLabel(s) }}
    </span>
  </td>
</ng-container>

<!-- Checks by Layer column (new) -->
<ng-container matColumnDef="layers">
  <th mat-header-cell *matHeaderCellDef>Checks by Layer</th>
  <td mat-cell *matCellDef="let s">
    <div class="layers">
      @for (rollup of layerRollupFor(s); track rollup.layer) {
        <div class="layer-col">
          <span class="layer-label">L{{ rollup.layer }}</span>
          <span
            class="layer-pill"
            [class.pill-pass]="rollup.status === 'pass'"
            [class.pill-warn]="rollup.status === 'warn'"
            [class.pill-err]="rollup.status === 'err'"
            [class.pill-crit]="rollup.status === 'crit'"
            [class.pill-skip]="rollup.status === 'skip'"
          >
            @if (rollup.status === 'skip') {
              —
            } @else {
              {{ rollup.passed }}/{{ rollup.total }}
            }
          </span>
        </div>
      }
    </div>
  </td>
</ng-container>
```

Remove the old `checks` and `writes` column definitions from the template. Ensure `displayedColumns` in the TS matches the template columns exactly.

- [ ] **Step 3: Add the styles**

Append to `session-list.component.scss`:

```scss
.source-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;

  .source-main { font-weight: 500; font-size: 13px; }
  .source-sub { font-size: 11px; color: var(--mat-sys-on-surface-variant); }
}

.object-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 180px;

  .object-type {
    align-self: flex-start;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 2px 6px;
    border-radius: 3px;
    background: var(--app-purple-bg);
    color: var(--app-purple);
  }

  .object-name {
    font-family: 'SF Mono', Monaco, monospace;
    font-size: 12px;
    max-width: 240px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.sites-count-pill {
  display: inline-flex;
  padding: 3px 10px;
  border-radius: 12px;
  background: var(--app-neutral-bg);
  font-size: 12px;
  color: var(--mat-sys-on-surface);
  cursor: help;
}

.layers {
  display: inline-flex;
  gap: 6px;

  .layer-col {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }

  .layer-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--mat-sys-on-surface-variant);
  }

  .layer-pill {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 38px;
    padding: 3px 8px;
    border-radius: 12px;
    font-family: 'SF Mono', Monaco, monospace;
    font-size: 11px;
    font-weight: 600;
    background: var(--app-neutral-bg);
    color: var(--mat-sys-on-surface-variant);

    &.pill-pass { background: var(--app-success-bg); color: var(--app-success); }
    &.pill-warn { background: var(--app-warning-bg); color: var(--app-warning); }
    &.pill-err  { background: var(--app-error-status-bg); color: var(--app-error-status); }
    &.pill-crit { background: var(--app-error-status-bg); color: var(--app-spinner-disconnected); }
    &.pill-skip { opacity: 0.4; }
  }
}
```

If any of the `--app-*` custom properties above don't exist, use the closest existing token in `frontend/src/styles.scss`. Check first with `grep -n "app-purple\|app-neutral-bg" frontend/src/styles.scss`.

- [ ] **Step 4: Remove `llm_chat` references in the list component**

Search the component files and swap any `'llm_chat'` for `'mcp'`:

```bash
grep -n "llm_chat" frontend/src/app/features/digital-twin/session-list/*
```

- [ ] **Step 5: Start the dev server and smoke test**

```bash
cd frontend && npm start
# Open http://localhost:4200/digital-twin
```

Verify:
- All 7 columns render
- `Source` column shows `MCP` with client label as secondary
- `Object Changed` column shows type badge + name
- `Sites` column shows count pill with tooltip
- `Checks by Layer` shows L0..L5 with colored ratio pills
- No `Writes` column

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/features/digital-twin/session-list/
git commit -m "feat(digital-twin): rework session list columns"
```

---

## Phase E — Frontend Detail View

### Task 13: Detail header meta grid

**Files:**
- Modify: `frontend/src/app/features/digital-twin/session-detail/session-detail.component.ts`
- Modify: `frontend/src/app/features/digital-twin/session-detail/session-detail.component.html`
- Modify: `frontend/src/app/features/digital-twin/session-detail/session-detail.component.scss`

- [ ] **Step 1: Add helpers to the component class**

```typescript
// session-detail.component.ts
import { computed, signal } from '@angular/core';

// In class body — the existing signals + new ones:
readonly sitesExpanded = signal(false);

toggleSitesExpanded(): void {
  this.sitesExpanded.update((v) => !v);
}

sourceLabel(source: string): string {
  switch (source) {
    case 'mcp':
      return 'MCP';
    case 'workflow':
      return 'Workflow';
    case 'backup_restore':
      return 'Backup Restore';
    default:
      return source;
  }
}

sourceSubLabel(summary: { source: string; source_ref: string | null }): string | null {
  if (summary.source === 'mcp') return summary.source_ref ?? 'Internal Chat';
  return summary.source_ref;
}
```

- [ ] **Step 2: Replace the header block in the template**

In `session-detail.component.html`, replace the existing `.session-header` with:

```html
<div class="session-header">
  <div class="title-row">
    <h2>Twin Session</h2>
    <app-status-badge [status]="s.status" />
  </div>

  <div class="meta-grid">
    <div class="meta-block">
      <div class="meta-label">Object Changed</div>
      <div class="object-pill">
        <span class="object-type">{{ s.affected_object_types[0] ?? '—' }}</span>
        <span class="object-name">{{ s.affected_object_label ?? '—' }}</span>
      </div>
    </div>

    <div class="meta-block">
      <div class="meta-label">Sites Tested</div>
      @if (s.affected_sites.length === 0) {
        <div class="meta-value">—</div>
      } @else {
        <div class="sites-container">
          <div class="sites-header">
            <span class="sites-count-pill">
              {{ s.affected_sites.length }} site{{ s.affected_sites.length === 1 ? '' : 's' }}
            </span>
            @if (s.affected_site_labels.length > 5) {
              <button type="button" class="sites-toggle" (click)="toggleSitesExpanded()">
                {{ sitesExpanded() ? 'Collapse' : 'Expand all' }}
              </button>
            }
          </div>
          <div class="sites-chips" [class.expanded]="sitesExpanded()">
            @for (name of s.affected_site_labels; track name) {
              <span class="site-chip">{{ name }}</span>
            }
          </div>
        </div>
      }
    </div>

    <div class="meta-block">
      <div class="meta-label">Source</div>
      <div class="meta-value">{{ sourceLabel(s.source) }}</div>
      @if (sourceSubLabel(s)) {
        <div class="meta-value meta-sub">{{ sourceSubLabel(s) }}</div>
      }
    </div>

    <div class="meta-block">
      <div class="meta-label">Created</div>
      <div class="meta-value">{{ s.created_at | dateTime: 'short' }}</div>
      @if (s.remediation_count > 0) {
        <div class="meta-value meta-sub">
          {{ s.remediation_count }} remediation{{ s.remediation_count === 1 ? '' : 's' }}
        </div>
      }
    </div>
  </div>

  @if (s.ai_assessment) {
    <div class="ai-assessment">
      <mat-icon class="ai-icon">smart_toy</mat-icon>
      <span>{{ s.ai_assessment }}</span>
    </div>
  }
</div>
```

- [ ] **Step 3: Add the SCSS**

Append to `session-detail.component.scss`:

```scss
.meta-grid {
  display: grid;
  grid-template-columns: 2fr 2fr 1fr 1fr;
  gap: 24px;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--mat-sys-outline-variant);
}

.meta-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.meta-label {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--mat-sys-on-surface-variant);
}

.meta-value { font-size: 13px; }
.meta-sub { font-size: 11px; color: var(--mat-sys-on-surface-variant); }

.object-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;

  .object-type {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 3px 7px;
    border-radius: 3px;
    background: var(--app-purple-bg);
    color: var(--app-purple);
  }

  .object-name { font-family: 'SF Mono', Monaco, monospace; font-size: 13px; }
}

.sites-container {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sites-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.sites-count-pill {
  display: inline-flex;
  padding: 3px 10px;
  border-radius: 12px;
  background: var(--app-neutral-bg);
  color: var(--mat-sys-on-surface);
  font-size: 12px;
}

.sites-toggle {
  background: none;
  border: none;
  padding: 0;
  font-size: 11px;
  color: var(--app-info);
  cursor: pointer;
}

.sites-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-height: 64px;
  overflow: hidden;

  &.expanded { max-height: none; }
}

.site-chip {
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--app-info-bg);
  color: var(--app-info);
  font-size: 11px;
  white-space: nowrap;
}
```

- [ ] **Step 4: Start the dev server and smoke test the detail page**

```bash
cd frontend && npm start
# Navigate to /digital-twin/<session-id>
```

Verify: header shows Object Changed, Sites Tested (chip list), Source (MCP + sub-label), Created. A session with >5 sites shows the "Expand all" toggle.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/features/digital-twin/session-detail/
git commit -m "feat(digital-twin): add meta grid and scalable sites display to detail header"
```

---

### Task 14: Auto-expand failing layers, collapse clean layers

**Files:**
- Modify: `frontend/src/app/features/digital-twin/session-detail/session-detail.component.ts`

- [ ] **Step 1: Update the initial state of `expandedLayers`**

Find the existing `expandedLayers` signal / Set in the component. Replace its initialization and add a computed that seeds it from the report.

```typescript
import { computed, effect, signal } from '@angular/core';

readonly expandedLayers = signal(new Set<number>());

// Seed once when session loads
private readonly seedLayerExpansion = effect(() => {
  const s = this.session();
  if (!s?.prediction_report) return;

  const initial = new Set<number>();
  for (const check of s.prediction_report.check_results) {
    if (check.status === 'warning' || check.status === 'error' || check.status === 'critical') {
      initial.add(check.layer);
    }
  }
  this.expandedLayers.set(initial);
});
```

If the existing `isLayerExpanded(layer)` helper reads from a plain boolean map, convert it to read from the signal's Set:

```typescript
isLayerExpanded(layer: number): boolean {
  return this.expandedLayers().has(layer);
}

toggleLayer(layer: number): void {
  this.expandedLayers.update((set) => {
    const next = new Set(set);
    next.has(layer) ? next.delete(layer) : next.add(layer);
    return next;
  });
}
```

- [ ] **Step 2: Smoke test**

Navigate to a session with mixed layer statuses. Verify: layers with failures are expanded on page load; clean layers are collapsed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/features/digital-twin/session-detail/session-detail.component.ts
git commit -m "feat(digital-twin): auto-expand failing layers in session detail"
```

---

### Task 15: Check row polish with description

**Files:**
- Modify: `frontend/src/app/features/digital-twin/session-detail/session-detail.component.html`
- Modify: `frontend/src/app/features/digital-twin/session-detail/session-detail.component.scss`

- [ ] **Step 1: Unify the check row grid**

Currently pass and fail rows use different HTML shapes. Refactor to a consistent grid. In `session-detail.component.html`, replace the `@for (check of checks; track check.check_id)` block inside `.layer-checks` with:

```html
@for (check of checks; track check.check_id) {
  @let isFailing = check.status !== 'pass' && check.status !== 'skipped' && check.status !== 'info';
  <div
    class="check-row"
    [class.check-pass]="!isFailing"
    [class.check-fail]="isFailing"
    [class.check-expanded]="isFailing && isCheckExpanded(check.check_id)"
    (click)="isFailing ? toggleCheck(check.check_id) : null"
  >
    <div class="check-grid">
      <mat-icon
        class="check-icon"
        [class.icon-pass]="check.status === 'pass' || check.status === 'info'"
        [class.icon-fail]="isFailing"
      >
        {{ isFailing ? 'cancel' : 'check_circle' }}
      </mat-icon>
      <span class="check-id">{{ check.check_id }}</span>
      <div class="check-name-block">
        <span class="check-name">{{ check.check_name }}</span>
        @if (check.description) {
          <span class="check-description">{{ check.description }}</span>
        }
      </div>
      @if (isFailing) {
        <span class="check-severity severity-{{ check.status }}">
          {{ severityLabel(check.status) }}
        </span>
        <mat-icon class="toggle-icon">
          {{ isCheckExpanded(check.check_id) ? 'expand_less' : 'expand_more' }}
        </mat-icon>
      } @else if (check.status === 'info') {
        <span class="check-severity severity-info">Info</span>
        <span></span>
      } @else {
        <span></span>
        <span></span>
      }
    </div>

    @if (isFailing && isCheckExpanded(check.check_id)) {
      <div class="check-details" (click)="$event.stopPropagation()">
        @if (check.summary) {
          <p class="check-summary-text">{{ check.summary }}</p>
        }
        @if (check.details.length > 0) {
          <ul class="details-list">
            @for (detail of check.details; track $index) {
              <li>{{ detail }}</li>
            }
          </ul>
        }
        @if (check.affected_objects.length > 0) {
          <div class="affected-section">
            <span class="affected-label">Affected objects:</span>
            @for (obj of check.affected_objects; track $index) {
              <code class="affected-item">{{ obj }}</code>
            }
          </div>
        }
        @if (check.remediation_hint) {
          <div class="remediation-hint">
            <mat-icon class="hint-icon">lightbulb</mat-icon>
            <span>{{ check.remediation_hint }}</span>
          </div>
        }
      </div>
    }
  </div>
}
```

- [ ] **Step 2: Update SCSS for the grid**

Replace the existing `.check-row`, `.check-name-block`, and `.check-description` rules in `session-detail.component.scss`:

```scss
.check-row {
  border-radius: 6px;
  padding: 0;

  &.check-pass,
  &.check-fail {
    display: block;
  }

  &.check-fail {
    cursor: pointer;
    &:hover { background: var(--mat-sys-surface-container-low); }
    &.check-expanded {
      background: var(--mat-sys-surface-container-low);
      border: 1px solid var(--mat-sys-outline-variant);
    }
  }

  .check-grid {
    display: grid;
    grid-template-columns: 20px auto 1fr auto auto;
    gap: 10px;
    align-items: start;
    padding: 8px 12px;
  }

  .check-icon {
    font-size: 16px;
    width: 16px;
    height: 16px;
    margin-top: 2px;
    &.icon-pass { color: var(--app-success); }
    &.icon-fail { color: var(--app-error-status); }
  }

  .check-id {
    font-family: monospace;
    font-size: 11px;
    color: var(--mat-sys-on-surface-variant);
    white-space: nowrap;
    padding: 2px 6px;
    border-radius: 3px;
    background: var(--app-neutral-bg);
    margin-top: 1px;
  }

  .check-name-block {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }

  .check-name { font-size: 13px; font-weight: 500; }

  .check-description {
    font-size: 11px;
    color: var(--mat-sys-on-surface-variant);
    line-height: 1.4;
  }

  .check-severity {
    font-size: 11px;
    font-weight: 600;
    padding: 2px 10px;
    border-radius: 10px;
    white-space: nowrap;
    margin-top: 1px;
    &.severity-info    { background: var(--app-info-bg); color: var(--app-info-chip); }
    &.severity-warning { background: var(--app-warning-bg); color: var(--app-warning); }
    &.severity-error   { background: var(--app-error-status-bg); color: var(--app-error-status); }
    &.severity-critical { background: var(--app-error-status-bg); color: var(--app-spinner-disconnected); }
  }

  .toggle-icon { color: var(--mat-sys-on-surface-variant); }
}
```

- [ ] **Step 3: Smoke test**

Refresh the detail page. Verify:
- Pass and fail rows have identical column alignment
- Descriptions appear under the check name without pushing the severity chip
- Descriptions wrap gracefully on narrow screens

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/features/digital-twin/session-detail/
git commit -m "feat(digital-twin): unify check row grid with description line"
```

---

### Task 16: Staged writes diff view

**Files:**
- Modify: `frontend/src/app/features/digital-twin/session-detail/session-detail.component.html`
- Modify: `frontend/src/app/features/digital-twin/session-detail/session-detail.component.ts`
- Modify: `frontend/src/app/features/digital-twin/session-detail/session-detail.component.scss`

- [ ] **Step 1: Default-expand all writes and track raw-body toggle**

Update the component class. Find the existing `expandedWrites` state and replace:

```typescript
readonly rawBodyVisible = signal(new Set<number>());

isRawBodyVisible(sequence: number): boolean {
  return this.rawBodyVisible().has(sequence);
}

toggleRawBody(sequence: number): void {
  this.rawBodyVisible.update((set) => {
    const next = new Set(set);
    next.has(sequence) ? next.delete(sequence) : next.add(sequence);
    return next;
  });
}

// Remove the old isWriteExpanded / toggleWrite helpers if they exist
```

- [ ] **Step 2: Replace the Staged Writes tab body**

In the HTML, replace the existing `<mat-tab [label]="'Staged Writes ...'">` content with:

```html
<mat-tab [label]="'Staged Writes (' + s.staged_writes.length + ')'">
  <div class="tab-content">
    @if (s.staged_writes.length === 0) {
      <div class="empty-tab">No staged writes for this session.</div>
    } @else {
      @for (write of s.staged_writes; track write.sequence) {
        <div class="write-card">
          <div class="write-head">
            <span class="write-seq">#{{ write.sequence }}</span>
            <span class="method-badge {{ methodClass(write.method) }}">{{ write.method }}</span>
            <code class="write-endpoint">{{ write.endpoint }}</code>
            @if (write.object_type) {
              <span class="object-type">{{ write.object_type }}</span>
            }
          </div>

          @if (write.diff_summary) {
            <div class="diff-summary">{{ write.diff_summary }}</div>
          }

          @if (write.diff.length > 0) {
            <ul class="diff-list">
              @for (entry of write.diff; track entry.path) {
                <li class="diff-entry diff-{{ entry.change }}">
                  <span class="diff-path">{{ entry.path }}</span>
                  <span class="diff-values">
                    @switch (entry.change) {
                      @case ('added') {
                        <span class="diff-after">+ {{ entry.after | json }}</span>
                      }
                      @case ('removed') {
                        <span class="diff-before">- {{ entry.before | json }}</span>
                      }
                      @default {
                        <span class="diff-before">{{ entry.before | json }}</span>
                        <span class="diff-arrow">→</span>
                        <span class="diff-after">{{ entry.after | json }}</span>
                      }
                    }
                  </span>
                </li>
              }
            </ul>
          }

          @if (write.body) {
            <button
              type="button"
              class="raw-toggle"
              (click)="toggleRawBody(write.sequence)"
            >
              {{ isRawBodyVisible(write.sequence) ? 'Hide' : 'Show' }} full body
            </button>

            @if (isRawBodyVisible(write.sequence)) {
              <pre class="raw-body">{{ write.body | json }}</pre>
            }
          }
        </div>
      }
    }
  </div>
</mat-tab>
```

- [ ] **Step 3: Add SCSS**

Append to `session-detail.component.scss`:

```scss
.write-card {
  background: var(--mat-sys-surface-container-low);
  border: 1px solid var(--mat-sys-outline-variant);
  border-radius: 8px;
  padding: 14px 18px;
  margin-bottom: 12px;
}

.write-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.diff-summary {
  font-size: 11px;
  color: var(--mat-sys-on-surface-variant);
  margin-bottom: 8px;
  text-transform: lowercase;
}

.diff-list {
  list-style: none;
  padding: 0;
  margin: 0 0 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.diff-entry {
  display: grid;
  grid-template-columns: minmax(160px, 30%) 1fr;
  gap: 14px;
  font-family: 'SF Mono', Monaco, monospace;
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 4px;

  .diff-path { color: var(--mat-sys-on-surface-variant); }
  .diff-values { color: var(--mat-sys-on-surface); }
  .diff-before { color: var(--app-error-status); }
  .diff-after  { color: var(--app-success); }
  .diff-arrow  { color: var(--mat-sys-on-surface-variant); margin: 0 6px; }
}

.diff-modified { background: rgba(234, 179, 8, 0.06); }
.diff-added    { background: rgba(34, 197, 94, 0.06); }
.diff-removed  { background: rgba(239, 68, 68, 0.06); }

.raw-toggle {
  background: none;
  border: 1px solid var(--mat-sys-outline-variant);
  border-radius: 4px;
  padding: 4px 10px;
  font-size: 11px;
  color: var(--mat-sys-on-surface-variant);
  cursor: pointer;

  &:hover { background: var(--mat-sys-surface-container); }
}

.raw-body {
  margin-top: 10px;
  background: var(--mat-sys-surface-container);
  border-radius: 4px;
  padding: 10px 12px;
  font-family: 'SF Mono', Monaco, monospace;
  font-size: 11px;
  overflow-x: auto;
}
```

- [ ] **Step 4: Smoke test**

Refresh the detail page. Verify:
- All staged writes visible at page load
- Each shows a diff summary line and a diff list
- "Show full body" reveals the raw JSON per write
- DELETE writes show only the summary `deleted`, no diff list

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/features/digital-twin/session-detail/
git commit -m "feat(digital-twin): render staged writes as diffs with raw-body toggle"
```

---

### Task 17: Logs tab (admin-only)

**Files:**
- Create: `frontend/src/app/features/digital-twin/session-detail/logs-tab.component.ts`
- Create: `frontend/src/app/features/digital-twin/session-detail/logs-tab.component.html`
- Create: `frontend/src/app/features/digital-twin/session-detail/logs-tab.component.scss`
- Modify: `frontend/src/app/features/digital-twin/session-detail/session-detail.component.ts`
- Modify: `frontend/src/app/features/digital-twin/session-detail/session-detail.component.html`

- [ ] **Step 1: Create the LogsTabComponent**

Create `frontend/src/app/features/digital-twin/session-detail/logs-tab.component.ts`:

```typescript
import { Component, Input, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormControl } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { debounceTime, switchMap, startWith } from 'rxjs/operators';
import { combineLatest } from 'rxjs';
import { DatePipe } from '@angular/common';

import { DigitalTwinService } from '../digital-twin.service';
import { SimulationLogEntry } from '../models/twin-session.model';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';

type Phase = 'simulate' | 'remediate' | 'approve' | 'execute' | 'other';
const PHASE_ORDER: Phase[] = ['simulate', 'remediate', 'approve', 'execute', 'other'];

@Component({
  selector: 'app-digital-twin-logs-tab',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatIconModule,
    DateTimePipe,
  ],
  templateUrl: './logs-tab.component.html',
  styleUrl: './logs-tab.component.scss',
})
export class LogsTabComponent implements OnInit {
  @Input({ required: true }) sessionId!: string;

  private readonly service = inject(DigitalTwinService);

  readonly levelControl = new FormControl<string>('');
  readonly searchControl = new FormControl<string>('');

  readonly entries = signal<SimulationLogEntry[]>([]);
  readonly loading = signal(false);
  readonly collapsedPhases = signal(new Set<Phase>());

  readonly grouped = computed(() => {
    const byPhase = new Map<Phase, SimulationLogEntry[]>();
    for (const phase of PHASE_ORDER) byPhase.set(phase, []);
    for (const entry of this.entries()) {
      byPhase.get(entry.phase as Phase)?.push(entry);
    }
    return PHASE_ORDER.map((phase) => ({
      phase,
      entries: byPhase.get(phase) ?? [],
    })).filter((g) => g.entries.length > 0);
  });

  ngOnInit(): void {
    combineLatest([
      this.levelControl.valueChanges.pipe(startWith(this.levelControl.value)),
      this.searchControl.valueChanges.pipe(
        startWith(this.searchControl.value),
        debounceTime(200),
      ),
    ])
      .pipe(
        switchMap(([level, search]) => {
          this.loading.set(true);
          return this.service.getSessionLogs(this.sessionId, {
            level: level || undefined,
            search: search || undefined,
          });
        }),
      )
      .subscribe((entries) => {
        this.entries.set(entries);
        this.loading.set(false);
        // First group with entries starts expanded, rest collapsed
        const collapsed = new Set<Phase>();
        let firstFound = false;
        for (const phase of PHASE_ORDER) {
          if (entries.some((e) => e.phase === phase)) {
            if (firstFound) collapsed.add(phase);
            firstFound = true;
          }
        }
        this.collapsedPhases.set(collapsed);
      });
  }

  togglePhase(phase: Phase): void {
    this.collapsedPhases.update((set) => {
      const next = new Set(set);
      next.has(phase) ? next.delete(phase) : next.add(phase);
      return next;
    });
  }

  isCollapsed(phase: Phase): boolean {
    return this.collapsedPhases().has(phase);
  }

  contextEntries(context: Record<string, unknown>): { key: string; value: string }[] {
    return Object.entries(context).map(([key, value]) => ({
      key,
      value: typeof value === 'object' ? JSON.stringify(value) : String(value),
    }));
  }

  phaseLabel(phase: Phase): string {
    return { simulate: 'Simulate', remediate: 'Remediation', approve: 'Approve', execute: 'Execute', other: 'Other' }[phase];
  }
}
```

- [ ] **Step 2: Create the template**

`logs-tab.component.html`:

```html
<div class="logs-tab">
  <div class="filter-bar">
    <mat-form-field appearance="outline" class="filter-level">
      <mat-label>Level</mat-label>
      <mat-select [formControl]="levelControl">
        <mat-option value="">All</mat-option>
        <mat-option value="info">Info</mat-option>
        <mat-option value="warning">Warning</mat-option>
        <mat-option value="error">Error</mat-option>
      </mat-select>
    </mat-form-field>

    <mat-form-field appearance="outline" class="filter-search">
      <mat-label>Search</mat-label>
      <input matInput type="text" [formControl]="searchControl" placeholder="event or context value" />
    </mat-form-field>
  </div>

  @if (loading()) {
    <div class="log-loading">Loading logs…</div>
  }

  @if (!loading() && grouped().length === 0) {
    <div class="empty-tab">No simulation logs captured for this session.</div>
  }

  @for (group of grouped(); track group.phase) {
    <div class="phase-group">
      <div class="phase-header" (click)="togglePhase(group.phase)">
        <mat-icon>{{ isCollapsed(group.phase) ? 'chevron_right' : 'expand_more' }}</mat-icon>
        <span class="phase-name">{{ phaseLabel(group.phase) }}</span>
        <span class="phase-count">{{ group.entries.length }}</span>
      </div>
      @if (!isCollapsed(group.phase)) {
        <div class="log-list">
          @for (entry of group.entries; track entry.timestamp + entry.event) {
            <div class="log-line" [class]="'log-' + entry.level">
              <span class="log-time">{{ entry.timestamp | dateTime: 'medium' }}</span>
              <span class="log-level">{{ entry.level }}</span>
              <span class="log-event">{{ entry.event }}</span>
              @if (contextEntries(entry.context).length > 0) {
                <span class="log-context">
                  @for (kv of contextEntries(entry.context); track kv.key) {
                    <span class="log-kv">{{ kv.key }}=<em>{{ kv.value }}</em></span>
                  }
                </span>
              }
            </div>
          }
        </div>
      }
    </div>
  }
</div>
```

- [ ] **Step 3: Add SCSS**

`logs-tab.component.scss`:

```scss
.logs-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filter-bar {
  display: flex;
  gap: 12px;
  align-items: baseline;

  .filter-level { width: 140px; }
  .filter-search { flex: 1; }
}

.log-loading,
.empty-tab {
  padding: 24px;
  text-align: center;
  color: var(--mat-sys-on-surface-variant);
}

.phase-group {
  border: 1px solid var(--mat-sys-outline-variant);
  border-radius: 6px;
  overflow: hidden;
}

.phase-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
  background: var(--mat-sys-surface-container-low);

  &:hover { background: var(--mat-sys-surface-container); }

  .phase-name { font-weight: 500; flex: 1; }
  .phase-count {
    font-size: 11px;
    padding: 2px 10px;
    border-radius: 12px;
    background: var(--app-neutral-bg);
    color: var(--mat-sys-on-surface-variant);
  }
}

.log-list {
  display: flex;
  flex-direction: column;
  font-family: 'SF Mono', Monaco, monospace;
  font-size: 11px;
}

.log-line {
  display: grid;
  grid-template-columns: 170px 60px 1fr 2fr;
  gap: 10px;
  padding: 6px 14px;
  border-top: 1px solid var(--mat-sys-outline-variant);

  &.log-warning { background: var(--app-warning-bg); }
  &.log-error   { background: var(--app-error-status-bg); }

  .log-time  { color: var(--mat-sys-on-surface-variant); }
  .log-level { text-transform: uppercase; font-weight: 600; }
  .log-event { font-weight: 500; }
  .log-context { display: flex; flex-wrap: wrap; gap: 8px; color: var(--mat-sys-on-surface-variant); }
  .log-kv em { color: var(--mat-sys-on-surface); font-style: normal; }
}
```

- [ ] **Step 4: Gate the tab on admin role and wire in the component**

Edit `session-detail.component.ts`:

```typescript
import { Store } from '@ngrx/store';
import { selectIsAdmin } from '../../../core/state/auth/auth.selectors';
import { toSignal } from '@angular/core/rxjs-interop';

// In the class:
private readonly store = inject(Store);
readonly isAdmin = toSignal(this.store.select(selectIsAdmin), { initialValue: false });
```

Edit `session-detail.component.html`. Import `LogsTabComponent` at the top of the component file and add it to the `imports` array. Insert the tab inside `<mat-tab-group>` after the remediation tab:

```html
@if (isAdmin()) {
  <mat-tab label="Logs">
    <div class="tab-content">
      <app-digital-twin-logs-tab [sessionId]="s.id" />
    </div>
  </mat-tab>
}
```

- [ ] **Step 5: Smoke test with an admin user**

Start the dev server. Log in as an admin user. Open a Twin session detail. Verify:
- Logs tab is visible
- Filters work
- Groups are collapsible
- Empty state shows when the session has no logs

Then log in as a non-admin user (or temporarily remove the `admin` role from your user). Verify the Logs tab is completely absent from the DOM.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/features/digital-twin/session-detail/
git commit -m "feat(digital-twin): add admin-only simulation logs tab"
```

---

## Self-Review Checklist

- [ ] **Spec coverage**
  - Source rename → Task 1, Task 8, Task 9, Task 12
  - `source_ref` → Task 2, Task 8, Task 12, Task 13
  - `affected_object_label` → Task 1, Task 2, Task 4, Task 5
  - `affected_site_labels` → Task 1, Task 2, Task 4, Task 5
  - CheckResult `description` → Task 2, Task 10, Task 15
  - Staged write diff → Task 3, Task 10, Task 16
  - Simulation log capture → Task 6
  - Admin logs endpoint → Task 7
  - One-time migration → Task 9
  - List view columns → Task 12
  - Detail header meta grid → Task 13
  - Sites chip list with expand → Task 13
  - Layer auto-expand → Task 14
  - Check row polish → Task 15
  - Staged writes diff view → Task 16
  - Admin-only Logs tab → Task 17

- [ ] **Placeholder scan**: no TBDs, TODOs, "similar to", or hand-waving steps.
- [ ] **Type consistency**: `SimulationLogEntry`, `WriteDiffField`, `LayerRollup`, `computeLayerRollup()`, `_filter_logs()`, `build_write_diff()`, `format_object_label()`, `fetch_object_names_by_type()`, `fetch_site_names()`, `bind_twin_session()`, `capture_twin_session_logs()`, `drain_buffer()`, `_resolve_source_ref()` — all names used consistently across tasks.
- [ ] **Imports**: every new import used later is introduced at the step where it first appears.

## Risks and Notes for the Engineer

- **MongoDB index on `source`**: no index currently targets this field; the migration uses `find.update()` which is a full scan. Acceptable for a one-time script.
- **Existing tests referencing `"llm_chat"`**: Task 9 Step 2 covers them. Do not force-replace across every file — read each match first and skip comments.
- **fastmcp client info**: the exact API for reading the client name may differ from what Step 1 of Task 8 assumes. Read `server.py` carefully before implementing. If client info truly isn't available, default to `"Internal Chat"` and log a warning — the feature still works, just without external client distinction.
- **`resolved_state` key shape**: MongoDB cannot store tuple keys. The existing code either stringifies them on write or builds a different structure on load. Verify by inspecting `twin_service` before Task 3 Step 6; the `_base_body_for()` helper tries both shapes but you may need to adapt.
- **Vitest path**: adjust `npx vitest run` to the project-local command if the repo uses a different runner invocation.
- **`--app-*` CSS variables**: verify that `--app-purple`, `--app-purple-bg`, `--app-neutral-bg`, `--app-info`, `--app-info-bg`, `--app-info-chip`, `--app-success`, `--app-success-bg`, `--app-warning`, `--app-warning-bg`, `--app-error-status`, `--app-error-status-bg`, `--app-spinner-disconnected` all exist in `frontend/src/styles.scss`. Substitute the nearest existing token if any are missing.
