# Digital Twin Check Descriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `description` field to every `CheckResult` so the Digital Twin UI can show a plain-English explanation of what each check validates, inline below the check name.

**Architecture:** One new field (`description: str = ""`) on the `CheckResult` Pydantic model; each check function populates it with a constant string. The Angular frontend adds the field to its model interface and renders it as a subtitle in both pass and fail check rows.

**Tech Stack:** Python 3.10+, Pydantic v2, pytest; Angular 21, TypeScript, Angular Material SCSS.

---

## Files

| File | Change |
|---|---|
| `backend/app/modules/digital_twin/models.py` | Add `description: str = ""` field to `CheckResult` |
| `backend/app/modules/digital_twin/checks/config_conflicts.py` | Add `description=` to all CheckResult constructions |
| `backend/app/modules/digital_twin/checks/template_checks.py` | Add `description=` to all CheckResult constructions |
| `backend/app/modules/digital_twin/checks/connectivity.py` | Add `description=` to all CheckResult constructions |
| `backend/app/modules/digital_twin/checks/port_impact.py` | Add `description=` to all CheckResult constructions |
| `backend/app/modules/digital_twin/checks/routing.py` | Add `description=` to all CheckResult constructions |
| `backend/app/modules/digital_twin/checks/security.py` | Add `description=` to all CheckResult constructions |
| `backend/app/modules/digital_twin/checks/stp.py` | Add `description=` to all CheckResult constructions |
| `backend/app/modules/digital_twin/services/twin_service.py` | Add `description=` to SYS-00, SYS-01, SYS-02, SYS-03 CheckResult constructions |
| `backend/tests/unit/test_digital_twin_schemas.py` | Add `TestCheckResultDescription` class |
| `backend/tests/unit/test_config_conflict_checks.py` | Add `TestCheckDescriptions` class |
| `backend/tests/unit/test_template_checks.py` | Add `TestCheckDescriptions` class |
| `backend/tests/unit/test_snapshot_checks.py` | Add `TestCheckDescriptions` class |
| `backend/tests/unit/test_port_impact_checks.py` | Add `TestCheckDescriptions` class |
| `backend/tests/unit/test_routing_checks.py` | Add `TestCheckDescriptions` class |
| `backend/tests/unit/test_security_snapshot_checks.py` | Add `TestCheckDescriptions` class |
| `backend/tests/unit/test_stp_checks.py` | Add `TestCheckDescriptions` class |
| `backend/tests/unit/test_twin_service_preflight.py` | Add `TestSysCheckDescriptions` class |
| `frontend/src/app/features/digital-twin/models/twin-session.model.ts` | Add `description: string` to `CheckResultModel` |
| `frontend/src/app/features/digital-twin/session-detail/session-detail.component.html` | Replace `<span class="check-name">` with `<div class="check-name-block">` in both row types |
| `frontend/src/app/features/digital-twin/session-detail/session-detail.component.scss` | Add `.check-name-block`, `.check-description`; update `align-items` on pass row and summary row |

---

### Task 1: Add `description` field to `CheckResult` model

**Files:**
- Modify: `backend/app/modules/digital_twin/models.py`
- Test: `backend/tests/unit/test_digital_twin_schemas.py`

All commands run from `backend/`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_digital_twin_schemas.py`:

```python
@pytest.mark.unit
class TestCheckResultDescription:
    def test_description_defaults_to_empty_string(self):
        result = CheckResult(
            check_id="TEST-01",
            check_name="Test check",
            layer=1,
            status="pass",
            summary="All good",
        )
        assert result.description == ""

    def test_description_accepts_string(self):
        result = CheckResult(
            check_id="TEST-01",
            check_name="Test check",
            layer=1,
            status="pass",
            summary="All good",
            description="Validates that the test thing works.",
        )
        assert result.description == "Validates that the test thing works."
```

Add the import at the top of the file (it may already exist — skip if so):

```python
from app.modules.digital_twin.models import CheckResult
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
.venv/bin/pytest tests/unit/test_digital_twin_schemas.py::TestCheckResultDescription -v -m unit
```

Expected: `FAILED` — `CheckResult` does not yet accept `description`.

- [ ] **Step 3: Add the field to `CheckResult`**

In `app/modules/digital_twin/models.py`, after `pre_existing: bool = False` (line 57), add:

```python
description: str = ""
```

The full `CheckResult` class should now be:

```python
class CheckResult(BaseModel):
    """Result of a single validation check."""

    check_id: str
    check_name: str
    layer: int
    status: Literal["pass", "info", "warning", "error", "critical", "skipped"]
    summary: str
    details: list[str] = Field(default_factory=list)
    affected_objects: list[str] = Field(default_factory=list)
    affected_sites: list[str] = Field(default_factory=list)
    remediation_hint: str | None = None
    pre_existing: bool = False
    description: str = ""
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
.venv/bin/pytest tests/unit/test_digital_twin_schemas.py::TestCheckResultDescription -v -m unit
```

Expected: `PASSED` (2 tests).

- [ ] **Step 5: Confirm existing tests still pass**

```bash
.venv/bin/pytest tests/unit/test_digital_twin_schemas.py -v -m unit
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add app/modules/digital_twin/models.py tests/unit/test_digital_twin_schemas.py
git commit -m "feat(twin): add description field to CheckResult model"
```

---

### Task 2: Add descriptions to config conflict checks

**Files:**
- Modify: `backend/app/modules/digital_twin/checks/config_conflicts.py`
- Test: `backend/tests/unit/test_config_conflict_checks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_config_conflict_checks.py`:

```python
@pytest.mark.unit
class TestCheckDescriptions:
    """Every config conflict check must return a non-empty description."""

    def _empty_snap(self) -> SiteSnapshot:
        return _snap()

    def test_cfg_subnet_description_populated(self):
        results = check_config_conflicts(self._empty_snap())
        by_id = {r.check_id: r for r in results}
        assert by_id["CFG-SUBNET"].description != ""

    def test_cfg_vlan_description_populated(self):
        results = check_config_conflicts(self._empty_snap())
        by_id = {r.check_id: r for r in results}
        assert by_id["CFG-VLAN"].description != ""

    def test_cfg_ssid_description_populated(self):
        results = check_config_conflicts(self._empty_snap())
        by_id = {r.check_id: r for r in results}
        assert by_id["CFG-SSID"].description != ""

    def test_cfg_dhcp_rng_description_populated(self):
        results = check_config_conflicts(self._empty_snap())
        by_id = {r.check_id: r for r in results}
        assert by_id["CFG-DHCP-RNG"].description != ""

    def test_cfg_dhcp_cfg_description_populated(self):
        results = check_config_conflicts(self._empty_snap())
        by_id = {r.check_id: r for r in results}
        assert by_id["CFG-DHCP-CFG"].description != ""
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/test_config_conflict_checks.py::TestCheckDescriptions -v -m unit
```

Expected: `FAILED` — all 5 assertions fail because `description == ""`.

- [ ] **Step 3: Add `description=` to each `CheckResult` in `config_conflicts.py`**

There are two `CheckResult` constructions per check (pass and fail paths). Add the same `description=` string to both.

**`_check_subnet_overlap`** — pass return and fail return both get:
```python
description="Checks all network subnets pairwise for IP address range overlaps.",
```

**`_check_vlan_collision`** — both paths:
```python
description="Detects VLAN IDs assigned to more than one network, which causes forwarding ambiguity.",
```

**`_check_duplicate_ssid`** — both paths:
```python
description="Flags duplicate SSIDs among enabled WLANs on the same site.",
```

**`_check_dhcp_scope_overlap`** — both paths:
```python
description="Checks all DHCP server scopes pairwise for overlapping address ranges.",
```

**`_check_dhcp_misconfiguration`** — both paths:
```python
description="Validates that each DHCP scope's gateway and address range fall within the network's subnet.",
```

For example, the pass return in `_check_subnet_overlap` becomes:

```python
return CheckResult(
    check_id="CFG-SUBNET",
    check_name="IP Subnet Overlap",
    layer=1,
    status="pass",
    summary="No subnet overlaps detected",
    description="Checks all network subnets pairwise for IP address range overlaps.",
)
```

And the fail return becomes:

```python
return CheckResult(
    check_id="CFG-SUBNET",
    check_name="IP Subnet Overlap",
    layer=1,
    status="critical",
    summary=f"Found {len(conflicts)} subnet overlap(s)",
    details=conflicts,
    affected_objects=affected_objects,
    affected_sites=[snap.site_id],
    remediation_hint="Assign non-overlapping subnets to each network.",
    description="Checks all network subnets pairwise for IP address range overlaps.",
)
```

Apply the same pattern to all remaining checks in the file.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/test_config_conflict_checks.py::TestCheckDescriptions -v -m unit
```

Expected: all 5 `PASSED`.

- [ ] **Step 5: Confirm existing tests still pass**

```bash
.venv/bin/pytest tests/unit/test_config_conflict_checks.py -v -m unit
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add app/modules/digital_twin/checks/config_conflicts.py tests/unit/test_config_conflict_checks.py
git commit -m "feat(twin): add descriptions to config conflict checks"
```

---

### Task 3: Add description to template variable check

**Files:**
- Modify: `backend/app/modules/digital_twin/checks/template_checks.py`
- Test: `backend/tests/unit/test_template_checks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_template_checks.py`:

```python
@pytest.mark.unit
class TestCheckDescriptions:
    """TMPL-VAR must return a non-empty description."""

    def _empty_snap(self) -> SiteSnapshot:
        return SiteSnapshot(
            site_id="site-1",
            site_name="Test",
            site_setting={},
            networks={},
            wlans={},
            devices={},
            port_usages={},
            lldp_neighbors={},
            port_status={},
            ap_clients={},
            port_devices={},
        )

    def test_tmpl_var_description_populated(self):
        results = check_template_variables(self._empty_snap())
        assert len(results) == 1
        assert results[0].check_id == "TMPL-VAR"
        assert results[0].description != ""
```

Add this import at the top if missing:

```python
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
.venv/bin/pytest tests/unit/test_template_checks.py::TestCheckDescriptions -v -m unit
```

Expected: `FAILED`.

- [ ] **Step 3: Add `description=` to both `CheckResult` constructions in `template_checks.py`**

Both the pass and fail return in `check_template_variables` get:

```python
description="Detects Jinja2 {{ variable }} placeholders in device or site config that are not defined in site vars.",
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
.venv/bin/pytest tests/unit/test_template_checks.py::TestCheckDescriptions -v -m unit
```

Expected: `PASSED`.

- [ ] **Step 5: Confirm existing tests still pass**

```bash
.venv/bin/pytest tests/unit/test_template_checks.py -v -m unit
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add app/modules/digital_twin/checks/template_checks.py tests/unit/test_template_checks.py
git commit -m "feat(twin): add description to template variable check"
```

---

### Task 4: Add descriptions to connectivity checks

**Files:**
- Modify: `backend/app/modules/digital_twin/checks/connectivity.py`
- Test: `backend/tests/unit/test_snapshot_checks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_snapshot_checks.py` (which already has `_dev` and `_snap` helpers):

```python
@pytest.mark.unit
class TestCheckDescriptions:
    """Every connectivity check must return a non-empty description."""

    def _empty_pair(self):
        snap = _snap()
        return snap, snap

    def test_conn_phys_description_populated(self):
        baseline, predicted = self._empty_pair()
        results = check_connectivity(baseline, predicted)
        by_id = {r.check_id: r for r in results}
        assert by_id["CONN-PHYS"].description != ""

    def test_conn_vlan_description_populated(self):
        baseline, predicted = self._empty_pair()
        results = check_connectivity(baseline, predicted)
        by_id = {r.check_id: r for r in results}
        assert by_id["CONN-VLAN"].description != ""

    def test_conn_vlan_path_description_populated(self):
        baseline, predicted = self._empty_pair()
        results = check_connectivity(baseline, predicted)
        by_id = {r.check_id: r for r in results}
        assert by_id["CONN-VLAN-PATH"].description != ""
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/test_snapshot_checks.py::TestCheckDescriptions -v -m unit
```

Expected: `FAILED` (3 assertions).

- [ ] **Step 3: Add `description=` to every `CheckResult` in `connectivity.py`**

`_check_conn_phys` — all three return paths (skipped, pass, critical/error) get:
```python
description="Detects devices that were reachable from a gateway in baseline but become isolated after the change.",
```

`_check_conn_vlan` — both paths (pass, critical) get:
```python
description="Detects VLANs that lose all gateway L3 interfaces after the change, cutting off inter-VLAN routing.",
```

`_check_conn_vlan_path` — both paths (pass, critical/error) get:
```python
description="Detects devices that lose gateway reachability within a specific VLAN's L2 subgraph (e.g., a switchport trunk change silently drops an AP's WLAN VLAN).",
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/test_snapshot_checks.py::TestCheckDescriptions -v -m unit
```

Expected: all 3 `PASSED`.

- [ ] **Step 5: Confirm existing tests still pass**

```bash
.venv/bin/pytest tests/unit/test_snapshot_checks.py -v -m unit
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add app/modules/digital_twin/checks/connectivity.py tests/unit/test_snapshot_checks.py
git commit -m "feat(twin): add descriptions to connectivity checks"
```

---

### Task 5: Add descriptions to port impact checks

**Files:**
- Modify: `backend/app/modules/digital_twin/checks/port_impact.py`
- Test: `backend/tests/unit/test_port_impact_checks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_port_impact_checks.py` (which already has `_dev` and `_snap` helpers):

```python
@pytest.mark.unit
class TestCheckDescriptions:
    """PORT-DISC and PORT-CLIENT must return non-empty descriptions."""

    def test_port_disc_description_populated(self):
        snap = _snap()
        results = check_port_impact(snap, snap)
        by_id = {r.check_id: r for r in results}
        assert by_id["PORT-DISC"].description != ""

    def test_port_client_description_populated(self):
        snap = _snap()
        results = check_port_impact(snap, snap)
        by_id = {r.check_id: r for r in results}
        assert by_id["PORT-CLIENT"].description != ""
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/test_port_impact_checks.py::TestCheckDescriptions -v -m unit
```

Expected: `FAILED`.

- [ ] **Step 3: Add `description=` to every `CheckResult` in `port_impact.py`**

The skipped pair, the `port_disc` result, and the `port_client` result all need descriptions.

Skipped PORT-DISC (inside the `if has_l2_device and not any(...)` branch):
```python
CheckResult(
    check_id="PORT-DISC",
    check_name="Port Profile Disconnect Risk",
    layer=2,
    status="skipped",
    summary=skipped_summary,
    affected_sites=[baseline.site_id],
    remediation_hint=skipped_hint,
    description="Compares switch/gateway port profiles to find LLDP-confirmed neighbors that would be disconnected or lose VLAN membership.",
),
```

Skipped PORT-CLIENT (same branch):
```python
CheckResult(
    check_id="PORT-CLIENT",
    check_name="Client Impact Estimation",
    layer=2,
    status="skipped",
    summary="Live LLDP data unavailable — client impact was not estimated.",
    affected_sites=[baseline.site_id],
    remediation_hint=skipped_hint,
    description="Estimates the number of wireless clients affected by APs disconnected by port profile changes.",
),
```

`port_disc` CheckResult (built further down):
```python
port_disc = CheckResult(
    check_id="PORT-DISC",
    check_name="Port Profile Disconnect Risk",
    layer=2,
    status=disc_max_severity,
    summary=disc_summary,
    details=disc_details,
    affected_objects=disc_affected,
    affected_sites=[baseline.site_id] if disc_details else [],
    remediation_hint=(...),
    description="Compares switch/gateway port profiles to find LLDP-confirmed neighbors that would be disconnected or lose VLAN membership.",
)
```

`port_client` CheckResult:
```python
port_client = CheckResult(
    check_id="PORT-CLIENT",
    check_name="Client Impact Estimation",
    layer=2,
    status=client_status,
    summary=client_summary,
    details=client_details,
    affected_objects=[...],
    affected_sites=[baseline.site_id] if disconnected_ap_ids else [],
    remediation_hint=(...),
    description="Estimates the number of wireless clients affected by APs disconnected by port profile changes.",
)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/test_port_impact_checks.py::TestCheckDescriptions -v -m unit
```

Expected: all 2 `PASSED`.

- [ ] **Step 5: Confirm existing tests still pass**

```bash
.venv/bin/pytest tests/unit/test_port_impact_checks.py -v -m unit
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add app/modules/digital_twin/checks/port_impact.py tests/unit/test_port_impact_checks.py
git commit -m "feat(twin): add descriptions to port impact checks"
```

---

### Task 6: Add descriptions to routing checks

**Files:**
- Modify: `backend/app/modules/digital_twin/checks/routing.py`
- Test: `backend/tests/unit/test_routing_checks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_routing_checks.py` (which already has snapshot helpers):

```python
@pytest.mark.unit
class TestCheckDescriptions:
    """Every routing check must return a non-empty description."""

    def _empty_pair(self):
        snap = _snap()
        return snap, snap

    def test_route_gw_description_populated(self):
        baseline, predicted = self._empty_pair()
        results = check_routing(baseline, predicted)
        by_id = {r.check_id: r for r in results}
        assert by_id["ROUTE-GW"].description != ""

    def test_route_ospf_description_populated(self):
        baseline, predicted = self._empty_pair()
        results = check_routing(baseline, predicted)
        by_id = {r.check_id: r for r in results}
        assert by_id["ROUTE-OSPF"].description != ""

    def test_route_bgp_description_populated(self):
        baseline, predicted = self._empty_pair()
        results = check_routing(baseline, predicted)
        by_id = {r.check_id: r for r in results}
        assert by_id["ROUTE-BGP"].description != ""

    def test_route_wan_description_populated(self):
        baseline, predicted = self._empty_pair()
        results = check_routing(baseline, predicted)
        by_id = {r.check_id: r for r in results}
        assert by_id["ROUTE-WAN"].description != ""
```

Add at the top of the file if missing:
```python
from app.modules.digital_twin.checks.routing import check_routing
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/test_routing_checks.py::TestCheckDescriptions -v -m unit
```

Expected: `FAILED` (4 assertions).

- [ ] **Step 3: Add `description=` to every `CheckResult` in `routing.py`**

`_check_route_gw` — both paths (pass, error):
```python
description="Detects routed networks (with subnet/gateway config) that have no corresponding L3 interface on any gateway device.",
```

`_check_route_ospf` — all three paths (skipped-no-config, pass, critical):
```python
description="Checks that OSPF peer IPs from live telemetry remain reachable within the predicted gateway interface subnets.",
```

`_check_route_bgp` — all three paths (skipped-no-config, pass, critical):
```python
description="Checks that BGP peer IPs from live telemetry remain reachable within the predicted gateway interface subnets.",
```

`_check_route_wan` — both paths (pass, warning/error):
```python
description="Detects WAN ports removed from gateway devices, which reduces redundancy and available bandwidth.",
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/test_routing_checks.py::TestCheckDescriptions -v -m unit
```

Expected: all 4 `PASSED`.

- [ ] **Step 5: Confirm existing tests still pass**

```bash
.venv/bin/pytest tests/unit/test_routing_checks.py -v -m unit
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add app/modules/digital_twin/checks/routing.py tests/unit/test_routing_checks.py
git commit -m "feat(twin): add descriptions to routing checks"
```

---

### Task 7: Add descriptions to security checks

**Files:**
- Modify: `backend/app/modules/digital_twin/checks/security.py`
- Test: `backend/tests/unit/test_security_snapshot_checks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_security_snapshot_checks.py`:

```python
@pytest.mark.unit
class TestCheckDescriptions:
    """Every security check must return a non-empty description."""

    def _empty_pair(self):
        snap = _snap()
        return snap, snap

    def test_sec_guest_description_populated(self):
        baseline, predicted = self._empty_pair()
        results = check_security(baseline, predicted)
        by_id = {r.check_id: r for r in results}
        assert by_id["SEC-GUEST"].description != ""

    def test_sec_policy_description_populated(self):
        baseline, predicted = self._empty_pair()
        results = check_security(baseline, predicted)
        by_id = {r.check_id: r for r in results}
        assert by_id["SEC-POLICY"].description != ""

    def test_sec_nac_description_populated(self):
        baseline, predicted = self._empty_pair()
        results = check_security(baseline, predicted)
        by_id = {r.check_id: r for r in results}
        assert by_id["SEC-NAC"].description != ""
```

Add import at top of file if missing:
```python
from app.modules.digital_twin.checks.security import check_security
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/test_security_snapshot_checks.py::TestCheckDescriptions -v -m unit
```

Expected: `FAILED`.

- [ ] **Step 3: Add `description=` to every `CheckResult` in `security.py`**

`_check_guest_ssid` — both paths (pass, warning):
```python
description="Flags open (unauthenticated) SSIDs that do not have client isolation enabled, allowing lateral traffic between clients.",
```

`_check_security_policies` — both paths (pass, warning):
```python
description="Reports additions, removals, or modifications to security policies between baseline and predicted state.",
```

`_check_nac_rules` — both paths (pass, warning):
```python
description="Reports changes to NAC rules between baseline and predicted state.",
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/test_security_snapshot_checks.py::TestCheckDescriptions -v -m unit
```

Expected: all 3 `PASSED`.

- [ ] **Step 5: Confirm existing tests still pass**

```bash
.venv/bin/pytest tests/unit/test_security_snapshot_checks.py -v -m unit
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add app/modules/digital_twin/checks/security.py tests/unit/test_security_snapshot_checks.py
git commit -m "feat(twin): add descriptions to security checks"
```

---

### Task 8: Add descriptions to STP checks

**Files:**
- Modify: `backend/app/modules/digital_twin/checks/stp.py`
- Test: `backend/tests/unit/test_stp_checks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_stp_checks.py`:

```python
@pytest.mark.unit
class TestCheckDescriptions:
    """Every STP check must return a non-empty description."""

    def _empty_pair(self):
        snap = _snap()
        return snap, snap

    def test_stp_root_description_populated(self):
        baseline, predicted = self._empty_pair()
        results = check_stp(baseline, predicted)
        by_id = {r.check_id: r for r in results}
        assert by_id["STP-ROOT"].description != ""

    def test_stp_bpdu_description_populated(self):
        baseline, predicted = self._empty_pair()
        results = check_stp(baseline, predicted)
        by_id = {r.check_id: r for r in results}
        assert by_id["STP-BPDU"].description != ""

    def test_stp_loop_description_populated(self):
        baseline, predicted = self._empty_pair()
        results = check_stp(baseline, predicted)
        by_id = {r.check_id: r for r in results}
        assert by_id["STP-LOOP"].description != ""
```

Add import at top if missing:
```python
from app.modules.digital_twin.checks.stp import check_stp
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/test_stp_checks.py::TestCheckDescriptions -v -m unit
```

Expected: `FAILED`.

- [ ] **Step 3: Add `description=` to every `CheckResult` in `stp.py`**

`_check_stp_root` — all paths (skipped-no-prio, skipped-insufficient, pass, warning):
```python
description="Detects STP root bridge shifts caused by bridge priority changes, which trigger network-wide reconvergence.",
```

`_check_stp_bpdu` — both paths (pass, warning):
```python
description="Flags trunk ports with BPDU filter enabled, which disables STP loop protection on switch-to-switch uplinks.",
```

`_check_stp_loop` — both paths (pass, warning):
```python
description="Detects new L2 cycles introduced in the physical topology graph that could cause broadcast storms.",
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/test_stp_checks.py::TestCheckDescriptions -v -m unit
```

Expected: all 3 `PASSED`.

- [ ] **Step 5: Confirm existing tests still pass**

```bash
.venv/bin/pytest tests/unit/test_stp_checks.py -v -m unit
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add app/modules/digital_twin/checks/stp.py tests/unit/test_stp_checks.py
git commit -m "feat(twin): add descriptions to STP checks"
```

---

### Task 9: Add descriptions to SYS preflight checks

**Files:**
- Modify: `backend/app/modules/digital_twin/services/twin_service.py`
- Test: `backend/tests/unit/test_twin_service_preflight.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_twin_service_preflight.py`:

```python
@pytest.mark.unit
class TestSysCheckDescriptions:
    """All SYS-* check constructions must produce non-empty descriptions."""

    def test_sys_00_description_populated(self):
        result = CheckResult(
            check_id="SYS-00",
            check_name="Simulation Context Validation",
            layer=0,
            status="error",
            summary="test",
            description="Verifies that an organization context (org_id) is present before simulation can proceed.",
        )
        assert result.description != ""

    @pytest.mark.asyncio
    async def test_sys_02_description_populated(self, monkeypatch):
        import app.modules.backup.models as backup_models
        monkeypatch.setattr(backup_models, "BackupObject", _FakeBackupObject)
        _FakeBackupObject.docs = []

        from app.modules.digital_twin.models import StagedWrite
        writes = [
            StagedWrite(
                sequence=0,
                method="PUT",
                endpoint="/api/v1/sites/unknown-site/wlans/wlan-1",
                body={},
                object_type="wlans",
                site_id="unknown-site",
                object_id="wlan-1",
            )
        ]
        results = await validate_write_targets("org-1", writes)
        assert len(results) == 1
        assert results[0].check_id == "SYS-02-0"
        assert results[0].description != ""

    @pytest.mark.asyncio
    async def test_sys_00_missing_org_description_populated(self, monkeypatch):
        import app.modules.backup.models as backup_models
        monkeypatch.setattr(backup_models, "BackupObject", _FakeBackupObject)
        results = await validate_write_targets("", [])
        assert len(results) == 1
        assert results[0].check_id == "SYS-00"
        assert results[0].description != ""
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/test_twin_service_preflight.py::TestSysCheckDescriptions -v -m unit
```

Expected: `FAILED` on the two async tests (the first is a construction test and will pass).

- [ ] **Step 3: Add `description=` to SYS checks in `twin_service.py`**

**`SYS-00`** (inside `_validate_write_targets`, early return when `org_id` is empty):
```python
description="Verifies that an organization context (org_id) is present before simulation can proceed.",
```

**`SYS-01-{i}`** (inside `_parse_and_enrich_writes`, the parse error CheckResult):
```python
description="Validates that the staged write targets a well-formed, recognized Mist API endpoint.",
```

**`SYS-02-{i}`** (site not found):
```python
description="Confirms the target site exists in backup data so baseline state can be built.",
```

**`SYS-03-{i}`** (object not found):
```python
description="Confirms the target object ID exists in backup data for PUT/DELETE operations.",
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/test_twin_service_preflight.py::TestSysCheckDescriptions -v -m unit
```

Expected: all `PASSED`.

- [ ] **Step 5: Confirm existing tests still pass**

```bash
.venv/bin/pytest tests/unit/test_twin_service_preflight.py -v -m unit
```

Expected: all green.

- [ ] **Step 6: Run all unit tests**

```bash
.venv/bin/pytest -m unit --tb=short -q
```

Expected: all green, zero failures.

- [ ] **Step 7: Commit**

```bash
git add app/modules/digital_twin/services/twin_service.py tests/unit/test_twin_service_preflight.py
git commit -m "feat(twin): add descriptions to SYS preflight checks"
```

---

### Task 10: Frontend — model, template, and styles

**Files:**
- Modify: `frontend/src/app/features/digital-twin/models/twin-session.model.ts`
- Modify: `frontend/src/app/features/digital-twin/session-detail/session-detail.component.html`
- Modify: `frontend/src/app/features/digital-twin/session-detail/session-detail.component.scss`

All commands run from `frontend/`.

- [ ] **Step 1: Add `description` to `CheckResultModel`**

In `src/app/features/digital-twin/models/twin-session.model.ts`, add the field after `remediation_hint`:

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

- [ ] **Step 2: Update the pass row in the template**

In `session-detail.component.html`, inside the `@if (check.status === 'pass' || ...)` branch, replace:

```html
<span class="check-name">{{ check.check_name }}</span>
```

with:

```html
<div class="check-name-block">
  <span class="check-name">{{ check.check_name }}</span>
  @if (check.description) {
    <span class="check-description">{{ check.description }}</span>
  }
</div>
```

- [ ] **Step 3: Update the fail row in the template**

In the `@else` branch, inside `.check-summary-row`, replace:

```html
<span class="check-name">{{ check.check_name }}</span>
```

with:

```html
<div class="check-name-block">
  <span class="check-name">{{ check.check_name }}</span>
  @if (check.description) {
    <span class="check-description">{{ check.description }}</span>
  }
</div>
```

- [ ] **Step 4: Update the SCSS**

In `session-detail.component.scss`, make three changes:

**Change 1** — `check-passed` row: change `align-items: center` to `align-items: flex-start`:

```scss
&.check-passed { display: flex; align-items: flex-start; gap: 8px; padding: 6px 10px; font-size: 13px; color: var(--mat-sys-on-surface-variant); }
```

**Change 2** — `.check-summary-row`: change `align-items: center` to `align-items: flex-start`:

```scss
.check-summary-row { display: flex; align-items: flex-start; gap: 8px; padding: 7px 10px; font-size: 13px; }
```

**Change 3** — remove `flex: 1` from `.check-name` (it moves to `.check-name-block`) and add the two new rules after `.check-name`:

```scss
.check-name { font-size: 13px; }
.check-name-block {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.check-description {
  font-size: 11px;
  color: var(--mat-sys-on-surface-variant);
  line-height: 1.4;
}
```

- [ ] **Step 5: Verify the build compiles without errors**

```bash
npx ng build 2>&1 | tail -20
```

Expected: `Build at: ... - Hash: ... - Time: ...ms` with no TypeScript or template errors.

- [ ] **Step 6: Commit**

```bash
git add src/app/features/digital-twin/models/twin-session.model.ts \
        src/app/features/digital-twin/session-detail/session-detail.component.html \
        src/app/features/digital-twin/session-detail/session-detail.component.scss
git commit -m "feat(twin): show check descriptions inline in session detail UI"
```
