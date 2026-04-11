# Digital Twin Check Rework — Site Snapshot Simulation Engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current 37 fragmented checks with a complete site snapshot simulation engine that builds baseline/predicted snapshots, constructs networkx graphs, and runs 20 focused checks across 9 categories.

**Architecture:** For each affected site: (1) build a `SiteSnapshot` from backup + one API call, (2) apply staged mutations via virtual state overrides, (3) build `SiteGraph` (L1 physical + per-VLAN L2 graphs), (4) run all check categories against baseline vs predicted snapshots. The existing `twin_service.simulate()` flow is preserved through step 6 (parse → resolve → compile); only the check dispatch (steps 7+) is replaced.

**Tech Stack:** Python 3.10+, networkx (graph algorithms), netaddr (IP math), Beanie/MongoDB (backup queries), mistapi (live data API), pytest (TDD)

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `backend/app/modules/digital_twin/services/site_snapshot.py` | `SiteSnapshot`, `DeviceSnapshot`, `LiveSiteData` dataclasses + `build_site_snapshot()`, `fetch_live_data()` |
| `backend/app/modules/digital_twin/services/site_graph.py` | `SiteGraph` dataclass + `build_site_graph()` — L1 physical graph, per-VLAN L2 graphs |
| `backend/app/modules/digital_twin/services/snapshot_analyzer.py` | `analyze_site()` orchestrator — runs all 9 check categories, returns `list[CheckResult]` |
| `backend/app/modules/digital_twin/checks/__init__.py` | Package init (empty) |
| `backend/app/modules/digital_twin/checks/connectivity.py` | Categories 1+2: physical connectivity loss + VLAN reachability |
| `backend/app/modules/digital_twin/checks/config_conflicts.py` | Category 3: subnet overlap, VLAN collision, duplicate SSID, DHCP checks |
| `backend/app/modules/digital_twin/checks/port_impact.py` | Categories 5+6: port profile disconnect + client impact estimation |
| `backend/app/modules/digital_twin/checks/template_checks.py` | Category 4: template override crush + unresolved variables |
| `backend/app/modules/digital_twin/checks/routing.py` | Category 7: gateway gap, OSPF/BGP adjacency, WAN failover |
| `backend/app/modules/digital_twin/checks/security.py` | Category 8: guest SSID, security policy changes, NAC changes |
| `backend/app/modules/digital_twin/checks/stp.py` | Category 9: root bridge shift, BPDU filter on trunk, loop risk |
| `backend/tests/unit/test_site_snapshot.py` | Tests for dataclasses + snapshot builder |
| `backend/tests/unit/test_site_graph.py` | Tests for graph builder |
| `backend/tests/unit/test_snapshot_checks.py` | Tests for all 9 check categories |

### Modified Files

| File | Change |
|------|--------|
| `backend/app/modules/digital_twin/services/twin_service.py` | Replace check dispatch (lines 137-172) with snapshot-based analysis |
| `backend/app/modules/digital_twin/CLAUDE.md` | Update architecture docs |

### Removed Files (Task 13 only)

| File | Replaced By |
|------|------------|
| `services/prediction_service.py` | `snapshot_analyzer.py` (keep `build_prediction_report()` moved to models or analyzer) |
| `services/config_checks.py` | `checks/config_conflicts.py` + `checks/port_impact.py` + `checks/template_checks.py` |
| `services/topology_checks.py` | `checks/connectivity.py` |
| `services/routing_checks.py` | `checks/routing.py` |
| `services/security_checks.py` | `checks/security.py` |
| `services/l2_checks.py` | `checks/stp.py` |
| `services/predicted_topology.py` | `services/site_graph.py` |

### Kept Files (no changes)

| File | Reason |
|------|--------|
| `services/config_compiler.py` | Used by `build_site_snapshot()` for device compilation |
| `services/state_resolver.py` | Used for base state loading + staged write application |
| `services/endpoint_parser.py` | Used for write parsing (unchanged) |
| `services/template_resolver.py` | Used by template checks |
| `services/twin_ia_bridge.py` | Post-deployment IA bridge (unchanged) |
| `services/prediction_comparison.py` | Accuracy tracking (unchanged) |
| `models.py` | CheckResult, PredictionReport, TwinSession (unchanged) |
| `schemas.py` | Response DTOs (unchanged) |

---

## Check ID Mapping

| New ID | Layer | Old IDs Replaced | Description |
|--------|-------|-----------------|-------------|
| `CFG-SUBNET` | 1 | L1-01, L1-02 | IP subnet overlap (cross-site + within-site) |
| `CFG-VLAN` | 1 | L1-03 | VLAN ID collision |
| `CFG-SSID` | 1 | L1-04 | Duplicate SSID |
| `CFG-DHCP-RNG` | 1 | L1-08 | DHCP scope overlap |
| `CFG-DHCP-CFG` | 1 | L1-09 | DHCP server misconfiguration |
| `TMPL-CRUSH` | 1 | L1-06 | Template override crush |
| `TMPL-VAR` | 1 | L1-07 | Unresolved template variables |
| `CONN-PHYS` | 2 | L2-01, L2-03, L2-04 | Physical connectivity loss (includes LAG/VC) |
| `CONN-VLAN` | 2 | L2-02 | VLAN gateway reachability |
| `PORT-DISC` | 2 | L1-15, L1-05 | Port profile disconnect risk |
| `PORT-CLIENT` | 2 | L1-11, L1-12, L1-13, L1-14 | Client impact estimation |
| `ROUTE-GW` | 3 | L3-01 | Default gateway gap |
| `ROUTE-OSPF` | 3 | L3-02 | OSPF adjacency break |
| `ROUTE-BGP` | 3 | L3-03 | BGP adjacency break |
| `ROUTE-WAN` | 3 | L3-05 | WAN failover impact |
| `SEC-GUEST` | 4 | L4-01 | Guest SSID without isolation |
| `SEC-POLICY` | 4 | L4-04, L4-05, L4-06 | Security/service policy change detection |
| `SEC-NAC` | 4 | L4-02, L4-03 | NAC rule change detection |
| `STP-ROOT` | 5 | L5-03 | STP root bridge shift |
| `STP-BPDU` | 5 | L5-02 | BPDU filter on trunk |
| `STP-LOOP` | 5 | L5-01 | L2 loop risk |

---

## Tasks

### Task 1: SiteSnapshot + DeviceSnapshot + LiveSiteData Dataclasses

**Files:**
- Create: `backend/app/modules/digital_twin/services/site_snapshot.py`
- Test: `backend/tests/unit/test_site_snapshot.py`

- [ ] **Step 1: Write failing tests for dataclass construction**

```python
# backend/tests/unit/test_site_snapshot.py
"""Tests for the SiteSnapshot data model and builder."""

import pytest


class TestDeviceSnapshot:
    def test_construction_switch(self):
        from app.modules.digital_twin.services.site_snapshot import DeviceSnapshot

        dev = DeviceSnapshot(
            device_id="dev-1",
            mac="aabbccddeeff",
            name="SW-01",
            type="switch",
            model="EX4100-48P",
            port_config={"ge-0/0/0": {"usage": "trunk"}},
            ip_config={},
            dhcpd_config={},
        )
        assert dev.device_id == "dev-1"
        assert dev.type == "switch"
        assert dev.port_usages is None
        assert dev.ospf_config is None

    def test_construction_gateway(self):
        from app.modules.digital_twin.services.site_snapshot import DeviceSnapshot

        dev = DeviceSnapshot(
            device_id="gw-1",
            mac="112233445566",
            name="GW-01",
            type="gateway",
            model="SRX320",
            port_config={"ge-0/0/0": {"usage": "wan"}},
            ip_config={"Corp": {"ip": "10.1.1.1", "netmask": "255.255.255.0"}},
            dhcpd_config={"enabled": True},
            port_usages={"wan": {"mode": "wan"}},
            ospf_config={"areas": {"0": {}}},
            bgp_config={"neighbors": {}},
        )
        assert dev.type == "gateway"
        assert dev.ospf_config is not None


class TestSiteSnapshot:
    def test_construction(self):
        from app.modules.digital_twin.services.site_snapshot import SiteSnapshot

        snap = SiteSnapshot(
            site_id="site-1",
            site_name="HQ",
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
        assert snap.site_id == "site-1"
        assert snap.ospf_peers == {}
        assert snap.bgp_peers == {}

    def test_device_access(self):
        from app.modules.digital_twin.services.site_snapshot import (
            DeviceSnapshot,
            SiteSnapshot,
        )

        dev = DeviceSnapshot(
            device_id="dev-1", mac="aa", name="SW", type="switch",
            model="EX", port_config={}, ip_config={}, dhcpd_config={},
        )
        snap = SiteSnapshot(
            site_id="s", site_name="S", site_setting={},
            networks={}, wlans={}, devices={"dev-1": dev},
            port_usages={}, lldp_neighbors={}, port_status={},
            ap_clients={}, port_devices={},
        )
        assert snap.devices["dev-1"].name == "SW"


class TestLiveSiteData:
    def test_construction(self):
        from app.modules.digital_twin.services.site_snapshot import LiveSiteData

        live = LiveSiteData(
            lldp_neighbors={"aa": {"ge-0/0/0": "bb"}},
            port_status={"aa": {"ge-0/0/0": True}},
            ap_clients={"ap-1": 23},
            port_devices={"aa": {"ge-0/0/9": "cc"}},
        )
        assert live.lldp_neighbors["aa"]["ge-0/0/0"] == "bb"
        assert live.ap_clients["ap-1"] == 23
        assert live.ospf_peers == {}
        assert live.bgp_peers == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_site_snapshot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.modules.digital_twin.services.site_snapshot'`

- [ ] **Step 3: Implement the dataclasses**

```python
# backend/app/modules/digital_twin/services/site_snapshot.py
"""
Site Snapshot model for the Digital Twin simulation engine.

SiteSnapshot is a complete virtual replica of a Mist site: all devices,
networks, WLANs, topology (LLDP), clients, and routing state. Built from
backup data + one API call per site for live data (LLDP, port status, clients).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DeviceSnapshot:
    """Compiled device configuration snapshot."""

    device_id: str
    mac: str
    name: str
    type: str  # "ap" | "switch" | "gateway"
    model: str
    port_config: dict[str, dict[str, Any]]  # port_name -> {usage, vlan_id, ...}
    ip_config: dict[str, dict[str, Any]]  # network_name -> {ip, netmask, type}
    dhcpd_config: dict[str, Any]  # DHCP server config
    oob_ip_config: dict[str, Any] | None = None
    # Gateway-specific
    port_usages: dict[str, dict[str, Any]] | None = None  # device-level overrides
    # Routing
    ospf_config: dict[str, Any] | None = None
    bgp_config: dict[str, Any] | None = None
    extra_routes: list[dict[str, Any]] | None = None
    # STP
    stp_config: dict[str, Any] | None = None


@dataclass
class LiveSiteData:
    """Live data fetched once per site from API, shared between baseline and predicted."""

    lldp_neighbors: dict[str, dict[str, str]]  # device_mac -> {port_id -> neighbor_mac}
    port_status: dict[str, dict[str, bool]]  # device_mac -> {port_id -> up/down}
    ap_clients: dict[str, int]  # device_id -> wireless client count
    port_devices: dict[str, dict[str, str]]  # device_mac -> {port_id -> connected_mac}
    ospf_peers: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    bgp_peers: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


@dataclass
class SiteSnapshot:
    """Complete virtual replica of a Mist site."""

    site_id: str
    site_name: str

    # Config layer (from backup, compiled via config_compiler)
    site_setting: dict[str, Any]
    networks: dict[str, dict[str, Any]]  # network_id -> config
    wlans: dict[str, dict[str, Any]]  # wlan_id -> config
    devices: dict[str, DeviceSnapshot]  # device_id -> compiled device
    port_usages: dict[str, dict[str, Any]]  # profile_name -> profile config

    # Topology layer (from live data)
    lldp_neighbors: dict[str, dict[str, str]]  # device_mac -> {port -> neighbor_mac}
    port_status: dict[str, dict[str, bool]]  # device_mac -> {port -> up/down}

    # Client layer (from live data)
    ap_clients: dict[str, int]  # device_id -> wireless client count
    port_devices: dict[str, dict[str, str]]  # device_mac -> {port -> connected_mac}

    # Routing layer (from live data, optional)
    ospf_peers: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    bgp_peers: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_site_snapshot.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend
git add app/modules/digital_twin/services/site_snapshot.py tests/unit/test_site_snapshot.py
git commit -m "feat(digital-twin): add SiteSnapshot, DeviceSnapshot, LiveSiteData dataclasses"
```

---

### Task 2: fetch_live_data() — API Calls for Site Live Data

**Files:**
- Modify: `backend/app/modules/digital_twin/services/site_snapshot.py`
- Test: `backend/tests/unit/test_site_snapshot.py`

This task adds `fetch_live_data()` which makes one org-level API call per site to get LLDP neighbors, port status, and client stats. It also adds `_extract_lldp_from_stats()` and `_extract_port_status()` helpers.

- [ ] **Step 1: Write failing tests for the extraction helpers**

```python
# Append to backend/tests/unit/test_site_snapshot.py

class TestExtractLldpFromStats:
    def test_extracts_lldp_neighbors(self):
        from app.modules.digital_twin.services.site_snapshot import _extract_lldp_from_stats

        stats = {
            "mac": "aabbccddeeff",
            "clients": [
                {"source": "lldp", "mac": "112233445566", "port_ids": ["ge-0/0/9"]},
                {"source": "lldp", "mac": "aabbcc000000", "port_ids": ["ge-0/0/0", "ge-0/0/1"]},
                {"source": "wifi", "mac": "ignored"},
            ],
        }
        result = _extract_lldp_from_stats(stats)
        assert result == {
            "ge-0/0/9": "112233445566",
            "ge-0/0/0": "aabbcc000000",
            "ge-0/0/1": "aabbcc000000",
        }

    def test_empty_clients(self):
        from app.modules.digital_twin.services.site_snapshot import _extract_lldp_from_stats

        assert _extract_lldp_from_stats({"mac": "aa"}) == {}

    def test_skips_empty_mac(self):
        from app.modules.digital_twin.services.site_snapshot import _extract_lldp_from_stats

        stats = {"clients": [{"source": "lldp", "mac": "", "port_ids": ["ge-0/0/0"]}]}
        assert _extract_lldp_from_stats(stats) == {}


class TestExtractPortStatus:
    def test_extracts_if_stat(self):
        from app.modules.digital_twin.services.site_snapshot import _extract_port_status

        stats = {
            "if_stat": {
                "ge-0/0/0": {"up": True, "speed": 1000},
                "ge-0/0/1": {"up": False},
            }
        }
        result = _extract_port_status(stats)
        assert result == {"ge-0/0/0": True, "ge-0/0/1": False}

    def test_empty_if_stat(self):
        from app.modules.digital_twin.services.site_snapshot import _extract_port_status

        assert _extract_port_status({}) == {}
        assert _extract_port_status({"if_stat": None}) == {}


class TestExtractClientCount:
    def test_from_num_clients(self):
        from app.modules.digital_twin.services.site_snapshot import _extract_client_count

        assert _extract_client_count({"num_clients": 23}) == 23

    def test_zero_when_missing(self):
        from app.modules.digital_twin.services.site_snapshot import _extract_client_count

        assert _extract_client_count({}) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_site_snapshot.py::TestExtractLldpFromStats -v`
Expected: FAIL with `ImportError: cannot import name '_extract_lldp_from_stats'`

- [ ] **Step 3: Implement the extraction helpers and fetch_live_data()**

Add to `backend/app/modules/digital_twin/services/site_snapshot.py` after the dataclass definitions:

```python
import structlog

logger = structlog.get_logger(__name__)

StateKey = tuple[str, str | None, str | None]


def _extract_lldp_from_stats(device_stats: dict[str, Any]) -> dict[str, str]:
    """Extract LLDP neighbor map from device stats.

    Mist clients[] with source=="lldp" use port_ids (plural, list).
    """
    neighbors: dict[str, str] = {}
    for client in device_stats.get("clients", []):
        if client.get("source") != "lldp":
            continue
        neighbor_mac = client.get("mac", "")
        if not neighbor_mac:
            continue
        for port_id in client.get("port_ids", []):
            if port_id:
                neighbors[port_id] = neighbor_mac
    return neighbors


def _extract_port_status(device_stats: dict[str, Any]) -> dict[str, bool]:
    """Extract port up/down status from device stats if_stat field."""
    result: dict[str, bool] = {}
    for port_id, if_info in (device_stats.get("if_stat") or {}).items():
        result[port_id] = bool(if_info.get("up", False))
    return result


def _extract_client_count(device_stats: dict[str, Any]) -> int:
    """Extract wireless client count from AP device stats."""
    return device_stats.get("num_clients", 0) or 0


async def fetch_live_data(site_id: str, org_id: str) -> LiveSiteData:
    """Fetch live site data with one org-level API call.

    Calls listOrgDevicesStats(site_id=..., fields="*") which returns
    full device stats including clients[] (LLDP) and if_stat (port status).
    Falls back to empty LiveSiteData if API call fails.
    """
    lldp_neighbors: dict[str, dict[str, str]] = {}
    port_status: dict[str, dict[str, bool]] = {}
    ap_clients: dict[str, int] = {}
    port_devices: dict[str, dict[str, str]] = {}

    try:
        import mistapi
        from app.services.mist_service_factory import create_mist_service
        from mistapi.api.v1.orgs import stats as org_stats

        mist = await create_mist_service()
        resp = await mistapi.arun(
            org_stats.listOrgDevicesStats,
            mist.get_session(),
            org_id,
            site_id=site_id,
            fields="*",
        )

        if resp.status_code == 200 and resp.data:
            devices_list = resp.data if isinstance(resp.data, list) else resp.data.get("results", [])
            for stats in devices_list:
                mac = stats.get("mac", "")
                if not mac:
                    continue

                # LLDP neighbors
                neighbors = _extract_lldp_from_stats(stats)
                if neighbors:
                    lldp_neighbors[mac] = neighbors

                # Port status
                ports = _extract_port_status(stats)
                if ports:
                    port_status[mac] = ports

                # AP client count (keyed by device_id for snapshot lookup)
                device_id = stats.get("id", "")
                device_type = stats.get("type", "")
                if device_type == "ap" and device_id:
                    ap_clients[device_id] = _extract_client_count(stats)

                # Port-connected devices (from LLDP — same source, different keying)
                for port_id, neighbor_mac in neighbors.items():
                    port_devices.setdefault(mac, {})[port_id] = neighbor_mac

            logger.info(
                "live_data_fetched",
                site_id=site_id,
                devices=len(devices_list),
                lldp_devices=len(lldp_neighbors),
            )
    except Exception as e:
        logger.warning("live_data_fetch_failed", site_id=site_id, error=str(e))

    return LiveSiteData(
        lldp_neighbors=lldp_neighbors,
        port_status=port_status,
        ap_clients=ap_clients,
        port_devices=port_devices,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_site_snapshot.py -v`
Expected: PASS (all 13 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend
git add app/modules/digital_twin/services/site_snapshot.py tests/unit/test_site_snapshot.py
git commit -m "feat(digital-twin): add live data extraction helpers and fetch_live_data()"
```

---

### Task 3: build_site_snapshot() — Complete Snapshot Builder

**Files:**
- Modify: `backend/app/modules/digital_twin/services/site_snapshot.py`
- Test: `backend/tests/unit/test_site_snapshot.py`

Loads all backup objects for a site, overlays virtual state overrides, compiles device configs, and combines with live data to produce a `SiteSnapshot`.

- [ ] **Step 1: Write failing tests for the snapshot builder**

```python
# Append to backend/tests/unit/test_site_snapshot.py
from unittest.mock import AsyncMock, patch


class TestBuildSiteSnapshot:
    """Tests for build_site_snapshot using mocked backup data."""

    @pytest.fixture
    def mock_backup_objects(self):
        """Return a factory that creates mock BackupObject query results."""

        def _make(configs: list[dict]):
            """Each config dict becomes a mock BackupObject."""
            mock_results = []
            for cfg in configs:
                obj = type("MockBackup", (), {"configuration": cfg, "object_id": cfg.get("id", "")})()
                mock_results.append(obj)
            return mock_results

        return _make

    @pytest.fixture
    def sample_live_data(self):
        from app.modules.digital_twin.services.site_snapshot import LiveSiteData

        return LiveSiteData(
            lldp_neighbors={"aabbccddeeff": {"ge-0/0/9": "112233445566"}},
            port_status={"aabbccddeeff": {"ge-0/0/0": True, "ge-0/0/9": True}},
            ap_clients={"ap-1": 15},
            port_devices={"aabbccddeeff": {"ge-0/0/9": "112233445566"}},
        )

    @pytest.mark.asyncio
    async def test_builds_snapshot_from_backup(self, sample_live_data, mock_backup_objects):
        from app.modules.digital_twin.services.site_snapshot import build_site_snapshot

        device_cfg = {
            "id": "dev-1",
            "mac": "aabbccddeeff",
            "name": "SW-01",
            "type": "switch",
            "model": "EX4100-48P",
            "port_config": {"ge-0/0/0": {"usage": "trunk"}, "ge-0/0/9": {"usage": "ap"}},
        }
        network_cfg = {"id": "net-1", "name": "Corp", "vlan_id": 100, "subnet": "10.1.0.0/24"}
        site_setting_cfg = {"port_usages": {"ap": {"mode": "access", "port_network": "Corp"}}}

        async def mock_load_site_objects(org_id, obj_type, site_id=None):
            mapping = {
                "devices": [device_cfg],
                "networks": [network_cfg],
                "wlans": [],
                "settings": [site_setting_cfg],
                "info": [{"name": "HQ"}],
            }
            return mapping.get(obj_type, [])

        with patch(
            "app.modules.digital_twin.services.site_snapshot._load_site_objects",
            side_effect=mock_load_site_objects,
        ):
            snap = await build_site_snapshot("site-1", "org-1", sample_live_data)

        assert snap.site_id == "site-1"
        assert snap.site_name == "HQ"
        assert "dev-1" in snap.devices
        assert snap.devices["dev-1"].type == "switch"
        assert "net-1" in snap.networks
        assert snap.port_usages.get("ap") is not None
        assert snap.lldp_neighbors == sample_live_data.lldp_neighbors

    @pytest.mark.asyncio
    async def test_state_overrides_replace_backup(self, sample_live_data):
        from app.modules.digital_twin.services.site_snapshot import build_site_snapshot

        # The override changes port ge-0/0/9 to disabled
        override_device = {
            "id": "dev-1",
            "mac": "aabbccddeeff",
            "name": "SW-01",
            "type": "switch",
            "model": "EX4100-48P",
            "port_config": {
                "ge-0/0/0": {"usage": "trunk"},
                "ge-0/0/9": {"usage": "disabled"},
            },
        }

        state_overrides = {
            ("devices", "site-1", "dev-1"): override_device,
        }

        backup_device = {
            "id": "dev-1",
            "mac": "aabbccddeeff",
            "name": "SW-01",
            "type": "switch",
            "model": "EX4100-48P",
            "port_config": {"ge-0/0/0": {"usage": "trunk"}, "ge-0/0/9": {"usage": "ap"}},
        }

        async def mock_load(org_id, obj_type, site_id=None):
            if obj_type == "devices":
                return [backup_device]
            if obj_type == "settings":
                return [{"port_usages": {}}]
            if obj_type == "info":
                return [{"name": "HQ"}]
            return []

        with patch(
            "app.modules.digital_twin.services.site_snapshot._load_site_objects",
            side_effect=mock_load,
        ):
            snap = await build_site_snapshot("site-1", "org-1", sample_live_data, state_overrides=state_overrides)

        # The override should win
        assert snap.devices["dev-1"].port_config["ge-0/0/9"]["usage"] == "disabled"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_site_snapshot.py::TestBuildSiteSnapshot -v`
Expected: FAIL with `ImportError: cannot import name 'build_site_snapshot'`

- [ ] **Step 3: Implement build_site_snapshot() and _load_site_objects()**

Add to `backend/app/modules/digital_twin/services/site_snapshot.py`:

```python
async def _load_site_objects(
    org_id: str,
    object_type: str,
    site_id: str | None = None,
) -> list[dict[str, Any]]:
    """Load all latest backup objects of a type for a site (or org-level)."""
    from app.modules.digital_twin.services.state_resolver import load_all_objects_of_type

    return await load_all_objects_of_type(org_id, object_type, site_id=site_id)


def _build_device_snapshot(config: dict[str, Any]) -> DeviceSnapshot:
    """Convert a raw/compiled device config dict into a DeviceSnapshot."""
    return DeviceSnapshot(
        device_id=config.get("id", ""),
        mac=config.get("mac", ""),
        name=config.get("name", config.get("id", "")),
        type=config.get("type", "switch"),
        model=config.get("model", ""),
        port_config=config.get("port_config") or {},
        ip_config=config.get("ip_config") or config.get("ip_configs") or {},
        dhcpd_config=config.get("dhcpd_config") or {},
        oob_ip_config=config.get("oob_ip_config"),
        port_usages=config.get("port_usages"),
        ospf_config=config.get("ospf_config"),
        bgp_config=config.get("bgp_config"),
        extra_routes=config.get("extra_routes"),
        stp_config=config.get("stp_config"),
    )


async def build_site_snapshot(
    site_id: str,
    org_id: str,
    live_data: LiveSiteData,
    state_overrides: dict[StateKey, dict[str, Any]] | None = None,
) -> SiteSnapshot:
    """Build a complete SiteSnapshot from backup + live data.

    If state_overrides is provided (compiled virtual state), objects matching
    this site are used instead of their backup versions.
    """
    # Load all site objects from backup
    import asyncio

    devices_raw, networks_raw, wlans_raw, settings_raw, info_raw = await asyncio.gather(
        _load_site_objects(org_id, "devices", site_id=site_id),
        _load_site_objects(org_id, "networks", site_id=site_id),
        _load_site_objects(org_id, "wlans", site_id=site_id),
        _load_site_objects(org_id, "settings", site_id=site_id),
        _load_site_objects(org_id, "info", site_id=site_id),
    )

    # Also load org-level networks (inherited by all sites)
    org_networks_raw = await _load_site_objects(org_id, "networks")

    # Merge org + site networks (site wins on conflict by id)
    all_networks_raw = {n.get("id", ""): n for n in org_networks_raw}
    for n in networks_raw:
        all_networks_raw[n.get("id", "")] = n

    # Apply state overrides: replace backup objects with virtual state versions
    devices_by_id: dict[str, dict[str, Any]] = {d.get("id", ""): d for d in devices_raw}
    networks_by_id: dict[str, dict[str, Any]] = dict(all_networks_raw)
    wlans_by_id: dict[str, dict[str, Any]] = {w.get("id", ""): w for w in wlans_raw}
    site_setting: dict[str, Any] = settings_raw[0] if settings_raw else {}
    site_name: str = info_raw[0].get("name", site_id) if info_raw else site_id

    if state_overrides:
        for (obj_type, obj_site, obj_id), config in state_overrides.items():
            if obj_site != site_id and obj_site is not None:
                continue
            if obj_type == "devices" and obj_id:
                devices_by_id[obj_id] = config
            elif obj_type == "networks" and obj_id:
                networks_by_id[obj_id] = config
            elif obj_type == "wlans" and obj_id:
                wlans_by_id[obj_id] = config
            elif obj_type == "settings":
                site_setting = config
            elif obj_type == "info":
                site_name = config.get("name", site_name)

    # Extract port_usages from site setting
    port_usages = site_setting.get("port_usages") or {}

    # Build DeviceSnapshots
    devices: dict[str, DeviceSnapshot] = {}
    for dev_id, dev_cfg in devices_by_id.items():
        if not dev_id:
            continue
        devices[dev_id] = _build_device_snapshot(dev_cfg)

    return SiteSnapshot(
        site_id=site_id,
        site_name=site_name,
        site_setting=site_setting,
        networks=networks_by_id,
        wlans=wlans_by_id,
        devices=devices,
        port_usages=port_usages,
        lldp_neighbors=live_data.lldp_neighbors,
        port_status=live_data.port_status,
        ap_clients=live_data.ap_clients,
        port_devices=live_data.port_devices,
        ospf_peers=live_data.ospf_peers,
        bgp_peers=live_data.bgp_peers,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_site_snapshot.py -v`
Expected: PASS (all 15 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend
git add app/modules/digital_twin/services/site_snapshot.py tests/unit/test_site_snapshot.py
git commit -m "feat(digital-twin): add build_site_snapshot() with backup loading and state overrides"
```

---

### Task 4: SiteGraph + build_site_graph()

**Files:**
- Create: `backend/app/modules/digital_twin/services/site_graph.py`
- Test: `backend/tests/unit/test_site_graph.py`

Builds networkx graphs from a SiteSnapshot: L1 physical graph (LLDP links), per-VLAN L2 graphs (port membership), and gateway VLAN annotations.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_site_graph.py
"""Tests for the SiteGraph builder."""

import pytest

from app.modules.digital_twin.services.site_snapshot import DeviceSnapshot, SiteSnapshot


def _make_device(dev_id: str, mac: str, name: str, dtype: str = "switch", **kwargs) -> DeviceSnapshot:
    return DeviceSnapshot(
        device_id=dev_id, mac=mac, name=name, type=dtype,
        model="EX4100", port_config=kwargs.get("port_config", {}),
        ip_config=kwargs.get("ip_config", {}), dhcpd_config={},
        port_usages=kwargs.get("port_usages"),
        stp_config=kwargs.get("stp_config"),
    )


def _make_snapshot(
    devices: dict[str, DeviceSnapshot],
    lldp: dict[str, dict[str, str]] | None = None,
    port_usages: dict[str, dict] | None = None,
    networks: dict[str, dict] | None = None,
) -> SiteSnapshot:
    return SiteSnapshot(
        site_id="site-1", site_name="HQ",
        site_setting={}, networks=networks or {},
        wlans={}, devices=devices,
        port_usages=port_usages or {},
        lldp_neighbors=lldp or {},
        port_status={}, ap_clients={}, port_devices={},
    )


class TestBuildSiteGraph:
    def test_physical_graph_from_lldp(self):
        from app.modules.digital_twin.services.site_graph import build_site_graph

        sw1 = _make_device("sw1", "aa", "SW-1", port_config={"ge-0/0/0": {"usage": "trunk"}})
        sw2 = _make_device("sw2", "bb", "SW-2", port_config={"ge-0/0/0": {"usage": "trunk"}})
        gw = _make_device("gw1", "cc", "GW-1", dtype="gateway", port_config={"ge-0/0/0": {"usage": "Corp"}})

        lldp = {
            "aa": {"ge-0/0/0": "bb"},  # SW-1 port 0 -> SW-2
            "bb": {"ge-0/0/0": "cc"},  # SW-2 port 0 -> GW-1
        }

        snap = _make_snapshot(
            devices={"sw1": sw1, "sw2": sw2, "gw1": gw},
            lldp=lldp,
        )
        graph = build_site_graph(snap)

        assert graph.physical.number_of_nodes() == 3
        assert graph.physical.number_of_edges() == 2
        assert graph.physical.has_edge("aa", "bb")
        assert graph.physical.has_edge("bb", "cc")
        assert "cc" in graph.gateways

    def test_empty_lldp_gives_disconnected_nodes(self):
        from app.modules.digital_twin.services.site_graph import build_site_graph

        sw1 = _make_device("sw1", "aa", "SW-1")
        snap = _make_snapshot(devices={"sw1": sw1})
        graph = build_site_graph(snap)

        assert graph.physical.number_of_nodes() == 1
        assert graph.physical.number_of_edges() == 0

    def test_vlan_graph_from_port_config(self):
        from app.modules.digital_twin.services.site_graph import build_site_graph

        sw1 = _make_device("sw1", "aa", "SW-1", port_config={
            "ge-0/0/0": {"usage": "trunk"},
            "ge-0/0/9": {"usage": "Corp"},
        })
        gw = _make_device("gw1", "cc", "GW-1", dtype="gateway",
                          ip_config={"Corp": {"ip": "10.1.1.1", "netmask": "255.255.255.0"}},
                          port_config={"ge-0/0/0": {"usage": "Corp"}})

        lldp = {"aa": {"ge-0/0/0": "cc"}}
        networks = {"net-1": {"name": "Corp", "vlan_id": 100}}
        port_usages = {"Corp": {"mode": "access", "port_network": "Corp"}}

        snap = _make_snapshot(
            devices={"sw1": sw1, "gw1": gw},
            lldp=lldp, port_usages=port_usages, networks=networks,
        )
        graph = build_site_graph(snap)

        assert 100 in graph.vlan_graphs
        vlan_g = graph.vlan_graphs[100]
        # Both devices participate in VLAN 100
        assert "aa" in vlan_g.nodes
        assert "cc" in vlan_g.nodes
        # Gateway has L3 interface for this VLAN
        assert 100 in graph.gateway_vlans.get("cc", set())

    def test_no_networks_no_vlan_graphs(self):
        from app.modules.digital_twin.services.site_graph import build_site_graph

        sw1 = _make_device("sw1", "aa", "SW-1")
        snap = _make_snapshot(devices={"sw1": sw1})
        graph = build_site_graph(snap)

        assert graph.vlan_graphs == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_site_graph.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement SiteGraph and build_site_graph()**

```python
# backend/app/modules/digital_twin/services/site_graph.py
"""
Build networkx graphs from a SiteSnapshot.

L1 physical graph: devices as nodes, LLDP links as edges.
L2 per-VLAN graphs: subgraphs filtered by port VLAN membership.
Gateway VLAN annotations: which VLANs have L3 interfaces on gateways.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from app.modules.digital_twin.services.site_snapshot import SiteSnapshot


@dataclass
class SiteGraph:
    """Network graphs derived from a SiteSnapshot."""

    physical: nx.Graph  # L1: device MACs as nodes, LLDP links as edges
    vlan_graphs: dict[int, nx.Graph]  # L2: per-VLAN subgraph
    gateways: set[str]  # MACs of gateway devices
    gateway_vlans: dict[str, set[int]]  # gateway_mac -> set of VLANs with L3 interface


def _resolve_port_vlan(
    port_cfg: dict[str, Any],
    port_usages: dict[str, dict[str, Any]],
    network_name_to_vlan: dict[str, int],
) -> set[int]:
    """Resolve which VLANs a port participates in based on its usage/config.

    Returns a set of VLAN IDs this port carries.
    """
    vlans: set[int] = set()
    usage = port_cfg.get("usage", "")

    if usage == "trunk":
        # Trunk ports carry all VLANs (or a filtered set if port_vlan_id/all_networks specified)
        # For simplicity: trunk carries all VLANs known to the site
        vlans.update(network_name_to_vlan.values())
        return vlans

    if usage == "disabled":
        return vlans

    # Named usage — look up in port_usages
    profile = port_usages.get(usage, {})
    mode = profile.get("mode", "access")

    if mode == "trunk":
        vlans.update(network_name_to_vlan.values())
        return vlans

    # Access mode: single VLAN from port_network or port_vlan_id
    port_network = port_cfg.get("port_network") or profile.get("port_network", "")
    if port_network and port_network in network_name_to_vlan:
        vlans.add(network_name_to_vlan[port_network])
    elif port_network:
        # Direct VLAN ID reference (usage name = network name)
        net_vlan = network_name_to_vlan.get(usage)
        if net_vlan is not None:
            vlans.add(net_vlan)

    # vlan_id field on port config itself
    vlan_id = port_cfg.get("vlan_id") or profile.get("vlan_id")
    if vlan_id and isinstance(vlan_id, int):
        vlans.add(vlan_id)

    return vlans


def build_site_graph(snapshot: SiteSnapshot) -> SiteGraph:
    """Build physical and per-VLAN graphs from a SiteSnapshot."""
    physical = nx.Graph()
    gateways: set[str] = set()
    gateway_vlans: dict[str, set[int]] = {}

    # Build network_name -> vlan_id mapping
    network_name_to_vlan: dict[str, int] = {}
    for net_cfg in snapshot.networks.values():
        name = net_cfg.get("name", "")
        vlan_id = net_cfg.get("vlan_id")
        if name and vlan_id is not None:
            network_name_to_vlan[name] = int(vlan_id)

    # Add all devices as nodes (keyed by MAC)
    mac_to_device: dict[str, str] = {}  # mac -> device_id
    for dev_id, dev in snapshot.devices.items():
        mac = dev.mac
        if not mac:
            continue
        physical.add_node(mac, name=dev.name, type=dev.type, device_id=dev_id)
        mac_to_device[mac] = dev_id

        if dev.type == "gateway":
            gateways.add(mac)
            # Determine which VLANs this gateway has L3 interfaces for
            gw_vlans: set[int] = set()
            for net_name in dev.ip_config:
                if net_name in network_name_to_vlan:
                    gw_vlans.add(network_name_to_vlan[net_name])
            if gw_vlans:
                gateway_vlans[mac] = gw_vlans

    # Add edges from LLDP neighbor data
    for device_mac, neighbors in snapshot.lldp_neighbors.items():
        if device_mac not in physical:
            continue
        for port_id, neighbor_mac in neighbors.items():
            if neighbor_mac in physical and not physical.has_edge(device_mac, neighbor_mac):
                physical.add_edge(
                    device_mac,
                    neighbor_mac,
                    src_port=port_id,
                    src_mac=device_mac,
                )

    # Build per-VLAN graphs
    vlan_graphs: dict[int, nx.Graph] = {}

    # For each device, determine which VLANs each port participates in
    # A device participates in a VLAN if any of its ports carry that VLAN
    device_vlans: dict[str, set[int]] = {}  # mac -> set of VLANs
    for dev_id, dev in snapshot.devices.items():
        mac = dev.mac
        if not mac:
            continue
        dev_vlan_set: set[int] = set()
        dev_port_usages = dev.port_usages or snapshot.port_usages
        for port_name, port_cfg in dev.port_config.items():
            port_vlans = _resolve_port_vlan(port_cfg, dev_port_usages, network_name_to_vlan)
            dev_vlan_set |= port_vlans
        device_vlans[mac] = dev_vlan_set

    # Build a subgraph per VLAN: only devices that participate + edges between them
    all_vlans = set()
    for vlans in device_vlans.values():
        all_vlans |= vlans

    for vlan_id in all_vlans:
        vg = nx.Graph()
        for mac, vlans in device_vlans.items():
            if vlan_id in vlans:
                vg.add_node(mac)
        # Add edges from physical graph if both endpoints are in this VLAN graph
        for u, v in physical.edges:
            if u in vg and v in vg:
                vg.add_edge(u, v)
        vlan_graphs[vlan_id] = vg

    return SiteGraph(
        physical=physical,
        vlan_graphs=vlan_graphs,
        gateways=gateways,
        gateway_vlans=gateway_vlans,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_site_graph.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend
git add app/modules/digital_twin/services/site_graph.py tests/unit/test_site_graph.py
git commit -m "feat(digital-twin): add SiteGraph with physical + per-VLAN graph builders"
```

---

### Task 5: checks/connectivity.py — Physical + VLAN Reachability

**Files:**
- Create: `backend/app/modules/digital_twin/checks/__init__.py`
- Create: `backend/app/modules/digital_twin/checks/connectivity.py`
- Test: `backend/tests/unit/test_snapshot_checks.py`

Two checks: `CONN-PHYS` (physical connectivity loss via BFS) and `CONN-VLAN` (VLAN gateway reachability).

- [ ] **Step 1: Create the checks package and write failing tests**

Create empty `__init__.py`:
```python
# backend/app/modules/digital_twin/checks/__init__.py
```

```python
# backend/tests/unit/test_snapshot_checks.py
"""Tests for all snapshot-based check categories."""

import pytest

from app.modules.digital_twin.services.site_snapshot import DeviceSnapshot, SiteSnapshot


def _dev(dev_id: str, mac: str, name: str, dtype: str = "switch", **kw) -> DeviceSnapshot:
    return DeviceSnapshot(
        device_id=dev_id, mac=mac, name=name, type=dtype,
        model="EX4100", port_config=kw.get("port_config", {}),
        ip_config=kw.get("ip_config", {}), dhcpd_config=kw.get("dhcpd_config", {}),
        port_usages=kw.get("port_usages"),
        ospf_config=kw.get("ospf_config"),
        bgp_config=kw.get("bgp_config"),
        stp_config=kw.get("stp_config"),
        extra_routes=kw.get("extra_routes"),
    )


def _snap(
    devices: dict[str, DeviceSnapshot] | None = None,
    lldp: dict | None = None,
    networks: dict | None = None,
    wlans: dict | None = None,
    port_usages: dict | None = None,
    site_setting: dict | None = None,
    ap_clients: dict | None = None,
    port_devices: dict | None = None,
    ospf_peers: dict | None = None,
    bgp_peers: dict | None = None,
) -> SiteSnapshot:
    return SiteSnapshot(
        site_id="site-1", site_name="HQ",
        site_setting=site_setting or {},
        networks=networks or {},
        wlans=wlans or {},
        devices=devices or {},
        port_usages=port_usages or {},
        lldp_neighbors=lldp or {},
        port_status={},
        ap_clients=ap_clients or {},
        port_devices=port_devices or {},
        ospf_peers=ospf_peers or {},
        bgp_peers=bgp_peers or {},
    )


# ── Category 1+2: Connectivity ─────────────────────────────────────────


class TestConnPhys:
    """CONN-PHYS: Physical connectivity loss."""

    def test_detects_disconnected_device(self):
        from app.modules.digital_twin.checks.connectivity import check_connectivity

        sw = _dev("sw1", "aa", "SW-1")
        gw = _dev("gw1", "cc", "GW-1", dtype="gateway")
        ap = _dev("ap1", "dd", "AP-1", dtype="ap")

        baseline = _snap(
            devices={"sw1": sw, "gw1": gw, "ap1": ap},
            lldp={"aa": {"ge-0/0/0": "cc"}, "dd": {"eth0": "aa"}},
        )
        # Predicted: AP LLDP link removed (port disabled)
        predicted = _snap(
            devices={"sw1": sw, "gw1": gw, "ap1": ap},
            lldp={"aa": {"ge-0/0/0": "cc"}},  # AP link gone
        )
        results = check_connectivity(baseline, predicted)
        statuses = {r.check_id: r.status for r in results}
        assert statuses.get("CONN-PHYS") in ("critical", "error")

    def test_no_change_passes(self):
        from app.modules.digital_twin.checks.connectivity import check_connectivity

        sw = _dev("sw1", "aa", "SW-1")
        gw = _dev("gw1", "cc", "GW-1", dtype="gateway")
        snap = _snap(
            devices={"sw1": sw, "gw1": gw},
            lldp={"aa": {"ge-0/0/0": "cc"}},
        )
        results = check_connectivity(snap, snap)
        statuses = {r.check_id: r.status for r in results}
        assert statuses.get("CONN-PHYS") == "pass"


class TestConnVlan:
    """CONN-VLAN: VLAN reachability to gateway."""

    def test_vlan_loses_gateway(self):
        from app.modules.digital_twin.checks.connectivity import check_connectivity

        sw = _dev("sw1", "aa", "SW-1", port_config={"ge-0/0/0": {"usage": "trunk"}, "ge-0/0/9": {"usage": "Corp"}})
        gw_baseline = _dev("gw1", "cc", "GW-1", dtype="gateway",
                           ip_config={"Corp": {"ip": "10.1.1.1"}},
                           port_config={"ge-0/0/0": {"usage": "Corp"}})
        gw_predicted = _dev("gw1", "cc", "GW-1", dtype="gateway",
                            ip_config={},  # L3 interface removed
                            port_config={"ge-0/0/0": {"usage": "Corp"}})

        networks = {"n1": {"name": "Corp", "vlan_id": 100}}
        lldp = {"aa": {"ge-0/0/0": "cc"}}

        baseline = _snap(devices={"sw1": sw, "gw1": gw_baseline}, lldp=lldp, networks=networks)
        predicted = _snap(devices={"sw1": sw, "gw1": gw_predicted}, lldp=lldp, networks=networks)

        results = check_connectivity(baseline, predicted)
        conn_vlan = [r for r in results if r.check_id == "CONN-VLAN"]
        assert len(conn_vlan) == 1
        assert conn_vlan[0].status in ("error", "critical")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_snapshot_checks.py::TestConnPhys -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement connectivity checks**

```python
# backend/app/modules/digital_twin/checks/connectivity.py
"""
Category 1+2: Physical connectivity loss + VLAN reachability.

Uses networkx BFS to detect devices that lose all paths to a gateway
after a config change, and VLANs that lose L3 gateway reachability.
"""

from __future__ import annotations

import networkx as nx

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.site_graph import SiteGraph, build_site_graph
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot


def _reachable_from_gateways(graph: nx.Graph, gateways: set[str]) -> set[str]:
    """Return all nodes reachable from any gateway via BFS."""
    reachable: set[str] = set()
    for gw in gateways:
        if gw in graph:
            reachable |= set(nx.node_connected_component(graph, gw))
    return reachable


def check_connectivity(
    baseline: SiteSnapshot,
    predicted: SiteSnapshot,
) -> list[CheckResult]:
    """Run physical connectivity and VLAN reachability checks."""
    results: list[CheckResult] = []
    baseline_graph = build_site_graph(baseline)
    predicted_graph = build_site_graph(predicted)

    # ── CONN-PHYS: Physical connectivity loss ──
    baseline_reachable = _reachable_from_gateways(baseline_graph.physical, baseline_graph.gateways)
    predicted_reachable = _reachable_from_gateways(predicted_graph.physical, predicted_graph.gateways)

    newly_isolated = baseline_reachable - predicted_reachable
    # Filter to actual devices (not MACs that disappeared)
    isolated_devices = [
        mac for mac in newly_isolated
        if mac in predicted_graph.physical
    ]

    if isolated_devices:
        details = []
        affected_objects = []
        total_clients = 0
        for mac in isolated_devices:
            node_data = predicted_graph.physical.nodes.get(mac, {})
            dev_name = node_data.get("name", mac)
            dev_type = node_data.get("type", "unknown")
            dev_id = node_data.get("device_id", "")
            # Estimate client impact
            clients = baseline.ap_clients.get(dev_id, 0) if dev_type == "ap" else 0
            total_clients += clients
            client_str = f", ~{clients} clients affected" if clients else ""
            details.append(f"{dev_name} ({dev_type}, {mac}) loses gateway connectivity{client_str}")
            if dev_id:
                affected_objects.append(dev_id)

        severity = "critical" if total_clients > 0 or any(
            predicted_graph.physical.nodes.get(m, {}).get("type") == "switch" for m in isolated_devices
        ) else "error"

        results.append(CheckResult(
            check_id="CONN-PHYS",
            check_name="Physical Connectivity Loss",
            layer=2,
            status=severity,
            summary=f"{len(isolated_devices)} device(s) will lose gateway connectivity",
            details=details,
            affected_objects=affected_objects,
            affected_sites=[baseline.site_id],
            remediation_hint="Check that disabled/removed ports don't break the only path to a gateway for downstream devices.",
        ))
    else:
        results.append(CheckResult(
            check_id="CONN-PHYS",
            check_name="Physical Connectivity Loss",
            layer=2,
            status="pass",
            summary="No devices lose gateway connectivity",
            affected_sites=[baseline.site_id],
        ))

    # ── CONN-VLAN: VLAN gateway reachability ──
    # Check each VLAN that existed in baseline still has a gateway in predicted
    baseline_gateway_vlans: set[int] = set()
    for vlans in baseline_graph.gateway_vlans.values():
        baseline_gateway_vlans |= vlans

    predicted_gateway_vlans: set[int] = set()
    for vlans in predicted_graph.gateway_vlans.values():
        predicted_gateway_vlans |= vlans

    lost_vlans = baseline_gateway_vlans - predicted_gateway_vlans

    if lost_vlans:
        # Map VLAN IDs back to network names
        vlan_to_name: dict[int, str] = {}
        for net_cfg in predicted.networks.values():
            vid = net_cfg.get("vlan_id")
            if vid is not None:
                vlan_to_name[int(vid)] = net_cfg.get("name", f"VLAN {vid}")

        details = [
            f"VLAN {vid} ({vlan_to_name.get(vid, 'unnamed')}) lost L3 gateway interface"
            for vid in sorted(lost_vlans)
        ]
        results.append(CheckResult(
            check_id="CONN-VLAN",
            check_name="VLAN Gateway Reachability",
            layer=2,
            status="critical",
            summary=f"{len(lost_vlans)} VLAN(s) lost gateway connectivity",
            details=details,
            affected_sites=[baseline.site_id],
            remediation_hint="Ensure each VLAN has at least one gateway with an ip_config entry for that network.",
        ))
    else:
        results.append(CheckResult(
            check_id="CONN-VLAN",
            check_name="VLAN Gateway Reachability",
            layer=2,
            status="pass",
            summary="All VLANs retain gateway connectivity",
            affected_sites=[baseline.site_id],
        ))

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_snapshot_checks.py -v`
Expected: PASS (all 4 connectivity tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend
git add app/modules/digital_twin/checks/__init__.py app/modules/digital_twin/checks/connectivity.py tests/unit/test_snapshot_checks.py
git commit -m "feat(digital-twin): add CONN-PHYS and CONN-VLAN connectivity checks"
```

---

### Task 6: checks/config_conflicts.py — Subnet/VLAN/SSID/DHCP

**Files:**
- Create: `backend/app/modules/digital_twin/checks/config_conflicts.py`
- Modify: `backend/tests/unit/test_snapshot_checks.py`

Five checks on the predicted snapshot's full object collections: `CFG-SUBNET`, `CFG-VLAN`, `CFG-SSID`, `CFG-DHCP-RNG`, `CFG-DHCP-CFG`.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_snapshot_checks.py`:

```python
# ── Category 3: Config Conflicts ────────────────────────────────────────


class TestCfgSubnet:
    def test_detects_overlap(self):
        from app.modules.digital_twin.checks.config_conflicts import check_config_conflicts

        networks = {
            "n1": {"name": "Corp", "vlan_id": 100, "subnet": "10.1.0.0/24"},
            "n2": {"name": "IoT", "vlan_id": 200, "subnet": "10.1.0.0/16"},
        }
        snap = _snap(networks=networks)
        results = check_config_conflicts(snap)
        subnet_check = [r for r in results if r.check_id == "CFG-SUBNET"]
        assert len(subnet_check) == 1
        assert subnet_check[0].status == "critical"

    def test_no_overlap_passes(self):
        from app.modules.digital_twin.checks.config_conflicts import check_config_conflicts

        networks = {
            "n1": {"name": "Corp", "vlan_id": 100, "subnet": "10.1.0.0/24"},
            "n2": {"name": "IoT", "vlan_id": 200, "subnet": "10.2.0.0/24"},
        }
        snap = _snap(networks=networks)
        results = check_config_conflicts(snap)
        subnet_check = [r for r in results if r.check_id == "CFG-SUBNET"]
        assert subnet_check[0].status == "pass"


class TestCfgVlan:
    def test_detects_collision(self):
        from app.modules.digital_twin.checks.config_conflicts import check_config_conflicts

        networks = {
            "n1": {"name": "Corp", "vlan_id": 100, "subnet": "10.1.0.0/24"},
            "n2": {"name": "IoT", "vlan_id": 100, "subnet": "10.2.0.0/24"},
        }
        snap = _snap(networks=networks)
        results = check_config_conflicts(snap)
        vlan_check = [r for r in results if r.check_id == "CFG-VLAN"]
        assert vlan_check[0].status == "error"


class TestCfgSsid:
    def test_detects_duplicate(self):
        from app.modules.digital_twin.checks.config_conflicts import check_config_conflicts

        wlans = {
            "w1": {"ssid": "Corp-WiFi", "enabled": True},
            "w2": {"ssid": "Corp-WiFi", "enabled": True},
        }
        snap = _snap(wlans=wlans)
        results = check_config_conflicts(snap)
        ssid_check = [r for r in results if r.check_id == "CFG-SSID"]
        assert ssid_check[0].status == "error"

    def test_disabled_wlan_ignored(self):
        from app.modules.digital_twin.checks.config_conflicts import check_config_conflicts

        wlans = {
            "w1": {"ssid": "Corp-WiFi", "enabled": True},
            "w2": {"ssid": "Corp-WiFi", "enabled": False},
        }
        snap = _snap(wlans=wlans)
        results = check_config_conflicts(snap)
        ssid_check = [r for r in results if r.check_id == "CFG-SSID"]
        assert ssid_check[0].status == "pass"


class TestCfgDhcp:
    def test_detects_range_overlap(self):
        from app.modules.digital_twin.checks.config_conflicts import check_config_conflicts

        gw = _dev("gw1", "cc", "GW-1", dtype="gateway", dhcpd_config={
            "enabled": True,
            "Corp": {"type": "local", "ip_start": "10.1.1.100", "ip_end": "10.1.1.200", "gateway": "10.1.1.1"},
            "IoT": {"type": "local", "ip_start": "10.1.1.150", "ip_end": "10.1.1.250", "gateway": "10.1.1.1"},
        })
        snap = _snap(devices={"gw1": gw})
        results = check_config_conflicts(snap)
        dhcp_rng = [r for r in results if r.check_id == "CFG-DHCP-RNG"]
        assert dhcp_rng[0].status == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_snapshot_checks.py::TestCfgSubnet -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement config conflict checks**

```python
# backend/app/modules/digital_twin/checks/config_conflicts.py
"""
Category 3: Config conflict checks.

Pure functions operating on a SiteSnapshot's network, WLAN, and device collections.
Checks: CFG-SUBNET, CFG-VLAN, CFG-SSID, CFG-DHCP-RNG, CFG-DHCP-CFG.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot


def _ip_to_int(addr: str) -> int:
    return int(ipaddress.ip_address(addr))


def check_config_conflicts(predicted: SiteSnapshot) -> list[CheckResult]:
    """Run all config conflict checks against the predicted snapshot."""
    results: list[CheckResult] = []
    results.append(_check_subnet_overlap(predicted))
    results.append(_check_vlan_collision(predicted))
    results.append(_check_duplicate_ssid(predicted))
    results.append(_check_dhcp_range_overlap(predicted))
    results.append(_check_dhcp_misconfiguration(predicted))
    return results


def _check_subnet_overlap(snap: SiteSnapshot) -> CheckResult:
    """CFG-SUBNET: Detect overlapping IP subnets across networks."""
    subnets: list[tuple[str, str, ipaddress.IPv4Network | ipaddress.IPv6Network]] = []
    for net_id, net_cfg in snap.networks.items():
        subnet_str = net_cfg.get("subnet", "")
        if not subnet_str:
            continue
        try:
            net = ipaddress.ip_network(subnet_str, strict=False)
            subnets.append((net_id, net_cfg.get("name", net_id), net))
        except ValueError:
            continue

    overlaps: list[str] = []
    for i, (id_a, name_a, net_a) in enumerate(subnets):
        for id_b, name_b, net_b in subnets[i + 1 :]:
            if net_a.overlaps(net_b):
                overlaps.append(f"{name_a} ({net_a}) overlaps {name_b} ({net_b})")

    if overlaps:
        return CheckResult(
            check_id="CFG-SUBNET",
            check_name="IP Subnet Overlap",
            layer=1,
            status="critical",
            summary=f"{len(overlaps)} subnet overlap(s) detected",
            details=overlaps,
            affected_sites=[snap.site_id],
            remediation_hint="Ensure all network subnets are non-overlapping.",
        )
    return CheckResult(
        check_id="CFG-SUBNET",
        check_name="IP Subnet Overlap",
        layer=1,
        status="pass",
        summary="No subnet overlaps",
        affected_sites=[snap.site_id],
    )


def _check_vlan_collision(snap: SiteSnapshot) -> CheckResult:
    """CFG-VLAN: Detect same VLAN ID used by different networks."""
    vlan_to_names: dict[int, list[str]] = {}
    for net_cfg in snap.networks.values():
        vlan_id = net_cfg.get("vlan_id")
        name = net_cfg.get("name", "unnamed")
        if vlan_id is not None:
            vlan_to_names.setdefault(int(vlan_id), []).append(name)

    collisions = [(vid, names) for vid, names in vlan_to_names.items() if len(names) > 1]
    if collisions:
        details = [f"VLAN {vid} used by: {', '.join(names)}" for vid, names in collisions]
        return CheckResult(
            check_id="CFG-VLAN",
            check_name="VLAN ID Collision",
            layer=1,
            status="error",
            summary=f"{len(collisions)} VLAN collision(s)",
            details=details,
            affected_sites=[snap.site_id],
            remediation_hint="Each VLAN ID should be used by exactly one network.",
        )
    return CheckResult(
        check_id="CFG-VLAN", check_name="VLAN ID Collision", layer=1,
        status="pass", summary="No VLAN collisions", affected_sites=[snap.site_id],
    )


def _check_duplicate_ssid(snap: SiteSnapshot) -> CheckResult:
    """CFG-SSID: Detect duplicate SSIDs among enabled WLANs."""
    ssid_count: dict[str, int] = {}
    for wlan_cfg in snap.wlans.values():
        if not wlan_cfg.get("enabled", True):
            continue
        ssid = wlan_cfg.get("ssid", "")
        if ssid:
            ssid_count[ssid] = ssid_count.get(ssid, 0) + 1

    dupes = [(ssid, count) for ssid, count in ssid_count.items() if count > 1]
    if dupes:
        details = [f"SSID '{ssid}' appears {count} times" for ssid, count in dupes]
        return CheckResult(
            check_id="CFG-SSID", check_name="Duplicate SSID", layer=1,
            status="error", summary=f"{len(dupes)} duplicate SSID(s)",
            details=details, affected_sites=[snap.site_id],
            remediation_hint="Remove or rename duplicate SSIDs.",
        )
    return CheckResult(
        check_id="CFG-SSID", check_name="Duplicate SSID", layer=1,
        status="pass", summary="No duplicate SSIDs", affected_sites=[snap.site_id],
    )


def _collect_dhcp_ranges(snap: SiteSnapshot) -> list[tuple[str, str, int, int]]:
    """Collect all DHCP ranges from device dhcpd_config.

    Returns list of (device_name, network_name, ip_start_int, ip_end_int).
    """
    ranges: list[tuple[str, str, int, int]] = []
    for dev in snap.devices.values():
        dhcp = dev.dhcpd_config
        if not dhcp or not dhcp.get("enabled"):
            continue
        for key, cfg in dhcp.items():
            if key == "enabled" or not isinstance(cfg, dict):
                continue
            if cfg.get("type") != "local":
                continue
            ip_start = cfg.get("ip_start", "")
            ip_end = cfg.get("ip_end", "")
            if ip_start and ip_end:
                try:
                    ranges.append((dev.name, key, _ip_to_int(ip_start), _ip_to_int(ip_end)))
                except ValueError:
                    continue
    return ranges


def _check_dhcp_range_overlap(snap: SiteSnapshot) -> CheckResult:
    """CFG-DHCP-RNG: Detect overlapping DHCP ranges."""
    ranges = _collect_dhcp_ranges(snap)
    overlaps: list[str] = []
    for i, (dev_a, net_a, start_a, end_a) in enumerate(ranges):
        for dev_b, net_b, start_b, end_b in ranges[i + 1 :]:
            if start_a <= end_b and start_b <= end_a:
                overlaps.append(f"{dev_a}/{net_a} range overlaps {dev_b}/{net_b}")

    if overlaps:
        return CheckResult(
            check_id="CFG-DHCP-RNG", check_name="DHCP Scope Overlap", layer=1,
            status="error", summary=f"{len(overlaps)} DHCP range overlap(s)",
            details=overlaps, affected_sites=[snap.site_id],
            remediation_hint="Ensure DHCP ranges don't overlap across networks.",
        )
    return CheckResult(
        check_id="CFG-DHCP-RNG", check_name="DHCP Scope Overlap", layer=1,
        status="pass", summary="No DHCP range overlaps", affected_sites=[snap.site_id],
    )


def _check_dhcp_misconfiguration(snap: SiteSnapshot) -> CheckResult:
    """CFG-DHCP-CFG: Validate DHCP gateway and range within subnet."""
    issues: list[str] = []
    for dev in snap.devices.values():
        dhcp = dev.dhcpd_config
        if not dhcp or not dhcp.get("enabled"):
            continue
        for key, cfg in dhcp.items():
            if key == "enabled" or not isinstance(cfg, dict):
                continue
            if cfg.get("type") != "local":
                continue
            # Find matching network subnet
            subnet_str = ""
            for net_cfg in snap.networks.values():
                if net_cfg.get("name") == key:
                    subnet_str = net_cfg.get("subnet", "")
                    break
            if not subnet_str:
                continue
            try:
                subnet = ipaddress.ip_network(subnet_str, strict=False)
            except ValueError:
                continue

            gateway = cfg.get("gateway", "")
            ip_start = cfg.get("ip_start", "")
            ip_end = cfg.get("ip_end", "")

            if gateway:
                try:
                    if ipaddress.ip_address(gateway) not in subnet:
                        issues.append(f"{dev.name}/{key}: gateway {gateway} outside subnet {subnet}")
                except ValueError:
                    pass
            if ip_start:
                try:
                    if ipaddress.ip_address(ip_start) not in subnet:
                        issues.append(f"{dev.name}/{key}: ip_start {ip_start} outside subnet {subnet}")
                except ValueError:
                    pass
            if ip_end:
                try:
                    if ipaddress.ip_address(ip_end) not in subnet:
                        issues.append(f"{dev.name}/{key}: ip_end {ip_end} outside subnet {subnet}")
                except ValueError:
                    pass

    if issues:
        return CheckResult(
            check_id="CFG-DHCP-CFG", check_name="DHCP Server Misconfiguration", layer=1,
            status="error", summary=f"{len(issues)} DHCP misconfiguration(s)",
            details=issues, affected_sites=[snap.site_id],
            remediation_hint="Ensure DHCP gateway and IP ranges are within the network subnet.",
        )
    return CheckResult(
        check_id="CFG-DHCP-CFG", check_name="DHCP Server Misconfiguration", layer=1,
        status="pass", summary="DHCP configurations valid", affected_sites=[snap.site_id],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_snapshot_checks.py -v -k "Cfg"``
Expected: PASS (all 6 config conflict tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend
git add app/modules/digital_twin/checks/config_conflicts.py tests/unit/test_snapshot_checks.py
git commit -m "feat(digital-twin): add config conflict checks (subnet, VLAN, SSID, DHCP)"
```

---

### Task 7: checks/port_impact.py — Port Profile + Client Impact

**Files:**
- Create: `backend/app/modules/digital_twin/checks/port_impact.py`
- Modify: `backend/tests/unit/test_snapshot_checks.py`

Two checks: `PORT-DISC` (port profile changes disconnecting devices) and `PORT-CLIENT` (client impact estimation).

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_snapshot_checks.py`:

```python
# ── Category 5+6: Port Impact ──────────────────────────────────────────


class TestPortDisc:
    def test_detects_disabled_port_with_neighbor(self):
        from app.modules.digital_twin.checks.port_impact import check_port_impact

        sw_baseline = _dev("sw1", "aa", "SW-1", port_config={
            "ge-0/0/9": {"usage": "ap"},
        })
        sw_predicted = _dev("sw1", "aa", "SW-1", port_config={
            "ge-0/0/9": {"usage": "disabled"},
        })
        baseline = _snap(
            devices={"sw1": sw_baseline},
            lldp={"aa": {"ge-0/0/9": "dd"}},
            ap_clients={"ap1": 23},
        )
        predicted = _snap(
            devices={"sw1": sw_predicted},
            lldp={"aa": {"ge-0/0/9": "dd"}},
            ap_clients={"ap1": 23},
        )
        results = check_port_impact(baseline, predicted)
        port_disc = [r for r in results if r.check_id == "PORT-DISC"]
        assert port_disc[0].status == "critical"
        assert "ge-0/0/9" in port_disc[0].details[0]

    def test_no_change_passes(self):
        from app.modules.digital_twin.checks.port_impact import check_port_impact

        sw = _dev("sw1", "aa", "SW-1", port_config={"ge-0/0/9": {"usage": "ap"}})
        snap = _snap(devices={"sw1": sw}, lldp={"aa": {"ge-0/0/9": "dd"}})
        results = check_port_impact(snap, snap)
        port_disc = [r for r in results if r.check_id == "PORT-DISC"]
        assert port_disc[0].status == "pass"

    def test_port_removed_with_neighbor(self):
        from app.modules.digital_twin.checks.port_impact import check_port_impact

        sw_baseline = _dev("sw1", "aa", "SW-1", port_config={
            "ge-0/0/0": {"usage": "trunk"},
            "ge-0/0/9": {"usage": "ap"},
        })
        sw_predicted = _dev("sw1", "aa", "SW-1", port_config={
            "ge-0/0/0": {"usage": "trunk"},
            # ge-0/0/9 removed entirely
        })
        baseline = _snap(
            devices={"sw1": sw_baseline},
            lldp={"aa": {"ge-0/0/9": "dd"}},
        )
        predicted = _snap(
            devices={"sw1": sw_predicted},
            lldp={"aa": {"ge-0/0/9": "dd"}},
        )
        results = check_port_impact(baseline, predicted)
        port_disc = [r for r in results if r.check_id == "PORT-DISC"]
        assert port_disc[0].status in ("critical", "error")


class TestPortClient:
    def test_estimates_client_impact(self):
        from app.modules.digital_twin.checks.port_impact import check_port_impact

        # AP connected to disabled port — clients affected
        sw_baseline = _dev("sw1", "aa", "SW-1", port_config={"ge-0/0/9": {"usage": "ap"}})
        sw_predicted = _dev("sw1", "aa", "SW-1", port_config={"ge-0/0/9": {"usage": "disabled"}})

        # AP-1 has device_id "ap1" and MAC "dd"
        ap = _dev("ap1", "dd", "AP-1", dtype="ap")

        baseline = _snap(
            devices={"sw1": sw_baseline, "ap1": ap},
            lldp={"aa": {"ge-0/0/9": "dd"}},
            ap_clients={"ap1": 42},
        )
        predicted = _snap(
            devices={"sw1": sw_predicted, "ap1": ap},
            lldp={"aa": {"ge-0/0/9": "dd"}},
            ap_clients={"ap1": 42},
        )
        results = check_port_impact(baseline, predicted)
        client_check = [r for r in results if r.check_id == "PORT-CLIENT"]
        assert client_check[0].status in ("warning", "error", "critical")
        assert "42" in client_check[0].summary or "42" in client_check[0].details[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_snapshot_checks.py::TestPortDisc -v`
Expected: FAIL

- [ ] **Step 3: Implement port impact checks**

```python
# backend/app/modules/digital_twin/checks/port_impact.py
"""
Category 5+6: Port profile disconnect risk + client impact estimation.

Compares baseline vs predicted port_config per device, cross-references
LLDP neighbors, and estimates client impact from AP client counts.
"""

from __future__ import annotations

from typing import Any

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot


def check_port_impact(
    baseline: SiteSnapshot,
    predicted: SiteSnapshot,
) -> list[CheckResult]:
    """Run port disconnect and client impact checks."""
    results: list[CheckResult] = []

    disconnects: list[dict[str, Any]] = []  # collected for both PORT-DISC and PORT-CLIENT

    # Compare port_config per device
    for dev_id, pred_dev in predicted.devices.items():
        base_dev = baseline.devices.get(dev_id)
        if not base_dev:
            continue

        mac = pred_dev.mac
        neighbors = baseline.lldp_neighbors.get(mac, {})

        for port_name, base_port_cfg in base_dev.port_config.items():
            pred_port_cfg = pred_dev.port_config.get(port_name)
            neighbor_mac = neighbors.get(port_name)

            if not neighbor_mac:
                continue  # No device connected — no impact

            base_usage = base_port_cfg.get("usage", "")
            pred_usage = pred_port_cfg.get("usage", "") if pred_port_cfg else ""

            is_disconnect = False

            # Port removed from config
            if pred_port_cfg is None:
                is_disconnect = True

            # Port changed to disabled
            elif pred_usage == "disabled" and base_usage != "disabled":
                is_disconnect = True

            # Usage changed (could affect VLAN membership)
            elif pred_usage != base_usage and base_usage not in ("", "disabled"):
                is_disconnect = True

            if is_disconnect:
                # Find the connected device for impact assessment
                connected_dev = None
                connected_dev_id = ""
                for d_id, d in baseline.devices.items():
                    if d.mac == neighbor_mac:
                        connected_dev = d
                        connected_dev_id = d_id
                        break

                disconnects.append({
                    "device_name": pred_dev.name,
                    "device_mac": mac,
                    "port": port_name,
                    "old_usage": base_usage,
                    "new_usage": pred_usage or "(removed)",
                    "neighbor_mac": neighbor_mac,
                    "connected_device": connected_dev,
                    "connected_device_id": connected_dev_id,
                })

    # ── PORT-DISC ──
    if disconnects:
        details = []
        affected = []
        for d in disconnects:
            connected_name = d["connected_device"].name if d["connected_device"] else d["neighbor_mac"]
            connected_type = d["connected_device"].type if d["connected_device"] else "unknown"
            details.append(
                f"{d['device_name']} port {d['port']}: "
                f"'{d['old_usage']}' → '{d['new_usage']}', "
                f"disconnects {connected_name} ({connected_type})"
            )
            if d["connected_device_id"]:
                affected.append(d["connected_device_id"])

        has_critical = any(
            d.get("connected_device") and d["connected_device"].type in ("ap", "switch")
            for d in disconnects
        )
        results.append(CheckResult(
            check_id="PORT-DISC",
            check_name="Port Profile Disconnect Risk",
            layer=2,
            status="critical" if has_critical else "error",
            summary=f"{len(disconnects)} port change(s) will disconnect active device(s)",
            details=details,
            affected_objects=affected,
            affected_sites=[baseline.site_id],
            remediation_hint="Check LLDP neighbors on ports before changing usage. Active devices will lose connectivity.",
        ))
    else:
        results.append(CheckResult(
            check_id="PORT-DISC", check_name="Port Profile Disconnect Risk", layer=2,
            status="pass", summary="No port changes affect connected devices",
            affected_sites=[baseline.site_id],
        ))

    # ── PORT-CLIENT ──
    total_clients = 0
    client_details: list[str] = []
    for d in disconnects:
        if not d["connected_device"]:
            continue
        if d["connected_device"].type == "ap":
            clients = baseline.ap_clients.get(d["connected_device_id"], 0)
            if clients:
                total_clients += clients
                client_details.append(f"{d['connected_device'].name}: ~{clients} wireless clients")

    if total_clients > 0:
        severity = "critical" if total_clients >= 50 else "warning" if total_clients >= 10 else "warning"
        results.append(CheckResult(
            check_id="PORT-CLIENT",
            check_name="Client Impact Estimation",
            layer=2,
            status=severity,
            summary=f"~{total_clients} client(s) affected by port changes",
            details=client_details,
            affected_sites=[baseline.site_id],
            remediation_hint="Schedule port changes during maintenance windows to minimize client impact.",
        ))
    else:
        results.append(CheckResult(
            check_id="PORT-CLIENT", check_name="Client Impact Estimation", layer=2,
            status="pass", summary="No wireless clients affected",
            affected_sites=[baseline.site_id],
        ))

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_snapshot_checks.py -v -k "Port"``
Expected: PASS (all 4 port impact tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend
git add app/modules/digital_twin/checks/port_impact.py tests/unit/test_snapshot_checks.py
git commit -m "feat(digital-twin): add PORT-DISC and PORT-CLIENT impact checks"
```

---

### Task 8: checks/template_checks.py — Template Override + Variables

**Files:**
- Create: `backend/app/modules/digital_twin/checks/template_checks.py`
- Modify: `backend/tests/unit/test_snapshot_checks.py`

Two checks: `TMPL-CRUSH` (template override crush) and `TMPL-VAR` (unresolved template variables).

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_snapshot_checks.py`:

```python
# ── Category 4: Template Checks ────────────────────────────────────────


class TestTmplVar:
    def test_detects_unresolved_variable(self):
        from app.modules.digital_twin.checks.template_checks import check_template_variables

        snap = _snap(site_setting={
            "vars": {"dns_server": "10.1.1.1"},
            "port_usages": {"ap": {"port_network": "{{ corp_vlan }}"}},
        })
        results = check_template_variables(snap)
        tmpl_var = [r for r in results if r.check_id == "TMPL-VAR"]
        assert tmpl_var[0].status == "error"
        assert "corp_vlan" in tmpl_var[0].details[0]

    def test_all_vars_resolved_passes(self):
        from app.modules.digital_twin.checks.template_checks import check_template_variables

        snap = _snap(site_setting={
            "vars": {"corp_vlan": "Corp"},
            "port_usages": {"ap": {"port_network": "{{ corp_vlan }}"}},
        })
        results = check_template_variables(snap)
        tmpl_var = [r for r in results if r.check_id == "TMPL-VAR"]
        assert tmpl_var[0].status == "pass"

    def test_handles_null_vars(self):
        from app.modules.digital_twin.checks.template_checks import check_template_variables

        snap = _snap(site_setting={"vars": None})
        results = check_template_variables(snap)
        tmpl_var = [r for r in results if r.check_id == "TMPL-VAR"]
        assert tmpl_var[0].status == "pass"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_snapshot_checks.py::TestTmplVar -v`
Expected: FAIL

- [ ] **Step 3: Implement template checks**

```python
# backend/app/modules/digital_twin/checks/template_checks.py
"""
Category 4: Template override crush + unresolved variable detection.

Scans the site setting (which includes compiled template config) for
{{ var }} patterns not defined in site_setting.vars.
"""

from __future__ import annotations

import re
from typing import Any

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot

_VAR_RE = re.compile(r"\{\{-?\s*(\w+)")


def _extract_vars(value: Any) -> set[str]:
    """Recursively extract {{ variable }} names from a config structure."""
    found: set[str] = set()
    if isinstance(value, str):
        found.update(_VAR_RE.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            found.update(_extract_vars(v))
    elif isinstance(value, list):
        for item in value:
            found.update(_extract_vars(item))
    return found


def check_template_variables(predicted: SiteSnapshot) -> list[CheckResult]:
    """Run template variable checks against the predicted snapshot."""
    results: list[CheckResult] = []

    site_vars = predicted.site_setting.get("vars") or {}

    # Scan full site_setting for {{ var }} patterns
    # Skip the "vars" key itself (it defines variables, not uses them)
    config_to_scan = {k: v for k, v in predicted.site_setting.items() if k != "vars"}
    referenced_vars = _extract_vars(config_to_scan)

    # Also scan device configs for unresolved variables
    for dev in predicted.devices.values():
        referenced_vars.update(_extract_vars(dev.port_config))
        referenced_vars.update(_extract_vars(dev.ip_config))
        referenced_vars.update(_extract_vars(dev.dhcpd_config))

    defined_vars = set(site_vars.keys()) if isinstance(site_vars, dict) else set()
    unresolved = referenced_vars - defined_vars

    if unresolved:
        details = [f"Variable '{{{{ {var} }}}}' not defined in site vars" for var in sorted(unresolved)]
        results.append(CheckResult(
            check_id="TMPL-VAR",
            check_name="Unresolved Template Variables",
            layer=1,
            status="error",
            summary=f"{len(unresolved)} unresolved template variable(s)",
            details=details,
            affected_sites=[predicted.site_id],
            remediation_hint="Define missing variables in the site settings 'vars' section.",
        ))
    else:
        results.append(CheckResult(
            check_id="TMPL-VAR", check_name="Unresolved Template Variables", layer=1,
            status="pass", summary="All template variables resolved",
            affected_sites=[predicted.site_id],
        ))

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_snapshot_checks.py -v -k "Tmpl"``
Expected: PASS (all 3 template tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend
git add app/modules/digital_twin/checks/template_checks.py tests/unit/test_snapshot_checks.py
git commit -m "feat(digital-twin): add TMPL-VAR template variable check"
```

---

### Task 9: checks/routing.py — Gateway/OSPF/BGP/WAN

**Files:**
- Create: `backend/app/modules/digital_twin/checks/routing.py`
- Modify: `backend/tests/unit/test_snapshot_checks.py`

Four checks: `ROUTE-GW`, `ROUTE-OSPF`, `ROUTE-BGP`, `ROUTE-WAN`.

**NOTE:** OSPF and BGP config structures need confirmation from user. The checks use the field paths documented in the spec (`ospf_config.areas`, `bgp_config.neighbors`). If the real Mist API differs, the implementer should ask the user for examples.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_snapshot_checks.py`:

```python
# ── Category 7: Routing ────────────────────────────────────────────────


class TestRouteGw:
    def test_detects_network_without_gateway(self):
        from app.modules.digital_twin.checks.routing import check_routing

        sw = _dev("sw1", "aa", "SW-1", port_config={"ge-0/0/0": {"usage": "Corp"}})
        # Gateway exists but has no ip_config for Corp
        gw = _dev("gw1", "cc", "GW-1", dtype="gateway", ip_config={})
        networks = {"n1": {"name": "Corp", "vlan_id": 100, "subnet": "10.1.0.0/24"}}
        snap = _snap(devices={"sw1": sw, "gw1": gw}, networks=networks)
        results = check_routing(snap, snap)
        gw_check = [r for r in results if r.check_id == "ROUTE-GW"]
        assert gw_check[0].status in ("error", "warning")

    def test_all_networks_have_gateway(self):
        from app.modules.digital_twin.checks.routing import check_routing

        gw = _dev("gw1", "cc", "GW-1", dtype="gateway",
                   ip_config={"Corp": {"ip": "10.1.1.1", "netmask": "255.255.255.0"}})
        networks = {"n1": {"name": "Corp", "vlan_id": 100, "subnet": "10.1.0.0/24"}}
        snap = _snap(devices={"gw1": gw}, networks=networks)
        results = check_routing(snap, snap)
        gw_check = [r for r in results if r.check_id == "ROUTE-GW"]
        assert gw_check[0].status == "pass"


class TestRouteWan:
    def test_detects_wan_link_removal(self):
        from app.modules.digital_twin.checks.routing import check_routing

        gw_base = _dev("gw1", "cc", "GW-1", dtype="gateway", port_config={
            "ge-0/0/0": {"usage": "wan", "wan_type": "broadband"},
            "ge-0/0/1": {"usage": "wan", "wan_type": "lte"},
        })
        gw_pred = _dev("gw1", "cc", "GW-1", dtype="gateway", port_config={
            "ge-0/0/0": {"usage": "wan", "wan_type": "broadband"},
            # ge-0/0/1 removed
        })
        baseline = _snap(devices={"gw1": gw_base})
        predicted = _snap(devices={"gw1": gw_pred})
        results = check_routing(baseline, predicted)
        wan_check = [r for r in results if r.check_id == "ROUTE-WAN"]
        assert wan_check[0].status in ("warning", "error")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_snapshot_checks.py::TestRouteGw -v`
Expected: FAIL

- [ ] **Step 3: Implement routing checks**

```python
# backend/app/modules/digital_twin/checks/routing.py
"""
Category 7: Routing checks — gateway gap, OSPF/BGP adjacency, WAN failover.

Operates on gateway devices in the snapshot. OSPF/BGP checks verify that
peer IPs remain in a connected subnet after IP config changes.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot


def _peer_reachable(peer_ip: str, ip_configs: dict[str, dict[str, Any]]) -> bool:
    """Check if a peer IP is within any configured interface subnet."""
    try:
        peer = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    for net_name, cfg in ip_configs.items():
        ip_str = cfg.get("ip", "")
        netmask = cfg.get("netmask", "")
        if not ip_str or not netmask:
            continue
        try:
            # Build network from interface IP + netmask
            iface = ipaddress.ip_interface(f"{ip_str}/{netmask}")
            if peer in iface.network:
                return True
        except ValueError:
            continue
    return False


def check_routing(
    baseline: SiteSnapshot,
    predicted: SiteSnapshot,
) -> list[CheckResult]:
    """Run all routing checks."""
    results: list[CheckResult] = []

    # ── ROUTE-GW: Default gateway gap ──
    # Check that each network has at least one gateway with an ip_config entry
    network_names = {cfg.get("name") for cfg in predicted.networks.values() if cfg.get("name")}
    gateway_networks: set[str] = set()
    for dev in predicted.devices.values():
        if dev.type == "gateway":
            gateway_networks.update(dev.ip_config.keys())

    missing = network_names - gateway_networks
    if missing:
        details = [f"Network '{name}' has no gateway L3 interface" for name in sorted(missing)]
        results.append(CheckResult(
            check_id="ROUTE-GW", check_name="Default Gateway Gap", layer=3,
            status="error", summary=f"{len(missing)} network(s) without gateway",
            details=details, affected_sites=[predicted.site_id],
            remediation_hint="Add an ip_config entry on a gateway for each network that needs routing.",
        ))
    else:
        results.append(CheckResult(
            check_id="ROUTE-GW", check_name="Default Gateway Gap", layer=3,
            status="pass", summary="All networks have gateway interfaces",
            affected_sites=[predicted.site_id],
        ))

    # ── ROUTE-OSPF: OSPF adjacency break ──
    ospf_breaks: list[str] = []
    for dev_id in baseline.ospf_peers:
        pred_dev = predicted.devices.get(dev_id)
        if not pred_dev:
            continue
        for peer_info in baseline.ospf_peers.get(dev_id, []):
            peer_ip = peer_info.get("peer_ip", "")
            if peer_ip and not _peer_reachable(peer_ip, pred_dev.ip_config):
                ospf_breaks.append(f"{pred_dev.name}: OSPF peer {peer_ip} unreachable after change")

    if ospf_breaks:
        results.append(CheckResult(
            check_id="ROUTE-OSPF", check_name="OSPF Adjacency Break", layer=3,
            status="critical", summary=f"{len(ospf_breaks)} OSPF adjacency break(s)",
            details=ospf_breaks, affected_sites=[predicted.site_id],
            remediation_hint="Verify that OSPF peer IPs remain within configured interface subnets.",
        ))
    else:
        results.append(CheckResult(
            check_id="ROUTE-OSPF", check_name="OSPF Adjacency Break", layer=3,
            status="pass", summary="OSPF adjacencies intact",
            affected_sites=[predicted.site_id],
        ))

    # ── ROUTE-BGP: BGP adjacency break ──
    bgp_breaks: list[str] = []
    for dev_id in baseline.bgp_peers:
        pred_dev = predicted.devices.get(dev_id)
        if not pred_dev:
            continue
        for peer_info in baseline.bgp_peers.get(dev_id, []):
            peer_ip = peer_info.get("peer_ip", "")
            if peer_ip and not _peer_reachable(peer_ip, pred_dev.ip_config):
                bgp_breaks.append(f"{pred_dev.name}: BGP peer {peer_ip} unreachable after change")

    if bgp_breaks:
        results.append(CheckResult(
            check_id="ROUTE-BGP", check_name="BGP Adjacency Break", layer=3,
            status="critical", summary=f"{len(bgp_breaks)} BGP adjacency break(s)",
            details=bgp_breaks, affected_sites=[predicted.site_id],
            remediation_hint="Verify that BGP peer IPs remain within configured interface subnets.",
        ))
    else:
        results.append(CheckResult(
            check_id="ROUTE-BGP", check_name="BGP Adjacency Break", layer=3,
            status="pass", summary="BGP adjacencies intact",
            affected_sites=[predicted.site_id],
        ))

    # ── ROUTE-WAN: WAN failover impact ──
    wan_changes: list[str] = []
    for dev_id, pred_dev in predicted.devices.items():
        if pred_dev.type != "gateway":
            continue
        base_dev = baseline.devices.get(dev_id)
        if not base_dev:
            continue

        base_wan = {p: c for p, c in base_dev.port_config.items() if c.get("usage") == "wan"}
        pred_wan = {p: c for p, c in pred_dev.port_config.items() if c.get("usage") == "wan"}

        removed = set(base_wan) - set(pred_wan)
        for port in removed:
            wan_type = base_wan[port].get("wan_type", "")
            wan_changes.append(f"{pred_dev.name}: WAN link {port} ({wan_type}) removed")

    if wan_changes:
        severity = "warning" if len(wan_changes) == 1 else "error"
        results.append(CheckResult(
            check_id="ROUTE-WAN", check_name="WAN Failover Impact", layer=3,
            status=severity, summary=f"{len(wan_changes)} WAN link change(s)",
            details=wan_changes, affected_sites=[predicted.site_id],
            remediation_hint="Removing WAN links reduces failover capability. Ensure at least one WAN link remains.",
        ))
    else:
        results.append(CheckResult(
            check_id="ROUTE-WAN", check_name="WAN Failover Impact", layer=3,
            status="pass", summary="WAN links unchanged",
            affected_sites=[predicted.site_id],
        ))

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_snapshot_checks.py -v -k "Route"``
Expected: PASS (all 4 routing tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend
git add app/modules/digital_twin/checks/routing.py tests/unit/test_snapshot_checks.py
git commit -m "feat(digital-twin): add routing checks (gateway, OSPF, BGP, WAN)"
```

---

### Task 10: checks/security.py — Guest SSID + Policy Changes

**Files:**
- Create: `backend/app/modules/digital_twin/checks/security.py`
- Modify: `backend/tests/unit/test_snapshot_checks.py`

Three checks: `SEC-GUEST`, `SEC-POLICY` (change detection), `SEC-NAC` (change detection).

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_snapshot_checks.py`:

```python
# ── Category 8: Security ───────────────────────────────────────────────


class TestSecGuest:
    def test_detects_open_ssid_without_isolation(self):
        from app.modules.digital_twin.checks.security import check_security

        wlans = {
            "w1": {
                "ssid": "Guest",
                "enabled": True,
                "auth": {"type": "open"},
                "isolation": False,
                "client_isolation": False,
            }
        }
        snap = _snap(wlans=wlans)
        results = check_security(snap, snap)
        guest = [r for r in results if r.check_id == "SEC-GUEST"]
        assert guest[0].status == "warning"

    def test_isolated_guest_passes(self):
        from app.modules.digital_twin.checks.security import check_security

        wlans = {
            "w1": {
                "ssid": "Guest",
                "enabled": True,
                "auth": {"type": "open"},
                "isolation": True,
            }
        }
        snap = _snap(wlans=wlans)
        results = check_security(snap, snap)
        guest = [r for r in results if r.check_id == "SEC-GUEST"]
        assert guest[0].status == "pass"


class TestSecPolicy:
    def test_detects_changed_policy(self):
        from app.modules.digital_twin.checks.security import check_security

        baseline = _snap(site_setting={"secpolicies": [{"name": "Allow-All", "action": "allow"}]})
        predicted = _snap(site_setting={"secpolicies": [{"name": "Allow-All", "action": "deny"}]})
        results = check_security(baseline, predicted)
        pol = [r for r in results if r.check_id == "SEC-POLICY"]
        assert pol[0].status in ("warning", "error")

    def test_no_change_passes(self):
        from app.modules.digital_twin.checks.security import check_security

        snap = _snap(site_setting={"secpolicies": [{"name": "Allow-All", "action": "allow"}]})
        results = check_security(snap, snap)
        pol = [r for r in results if r.check_id == "SEC-POLICY"]
        assert pol[0].status == "pass"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_snapshot_checks.py::TestSecGuest -v`
Expected: FAIL

- [ ] **Step 3: Implement security checks**

```python
# backend/app/modules/digital_twin/checks/security.py
"""
Category 8: Security checks — guest SSID, policy change detection, NAC changes.

Guest SSID: validates open WLANs have client isolation.
Policy/NAC: change detection with diff summary (not rule simulation).
"""

from __future__ import annotations

from typing import Any

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot


def _is_open_wlan(wlan: dict[str, Any]) -> bool:
    auth = wlan.get("auth") or {}
    auth_type = auth.get("type", "")
    return auth_type in ("open", "none", "")


def _has_isolation(wlan: dict[str, Any]) -> bool:
    return bool(wlan.get("isolation")) or bool(wlan.get("client_isolation"))


def check_security(
    baseline: SiteSnapshot,
    predicted: SiteSnapshot,
) -> list[CheckResult]:
    """Run all security checks."""
    results: list[CheckResult] = []

    # ── SEC-GUEST: Open WLAN without client isolation ──
    insecure_wlans: list[str] = []
    for wlan_id, wlan_cfg in predicted.wlans.items():
        if not wlan_cfg.get("enabled", True):
            continue
        if _is_open_wlan(wlan_cfg) and not _has_isolation(wlan_cfg):
            ssid = wlan_cfg.get("ssid", wlan_id)
            insecure_wlans.append(f"SSID '{ssid}' is open without client isolation")

    if insecure_wlans:
        results.append(CheckResult(
            check_id="SEC-GUEST", check_name="Guest SSID Security", layer=4,
            status="warning", summary=f"{len(insecure_wlans)} open SSID(s) without isolation",
            details=insecure_wlans, affected_sites=[predicted.site_id],
            remediation_hint="Enable 'isolation' or 'client_isolation' on open/guest WLANs to prevent lateral movement.",
        ))
    else:
        results.append(CheckResult(
            check_id="SEC-GUEST", check_name="Guest SSID Security", layer=4,
            status="pass", summary="All open SSIDs have client isolation",
            affected_sites=[predicted.site_id],
        ))

    # ── SEC-POLICY: Security policy change detection ──
    base_policies = baseline.site_setting.get("secpolicies") or []
    pred_policies = predicted.site_setting.get("secpolicies") or []

    if base_policies != pred_policies:
        base_names = {p.get("name", i): p for i, p in enumerate(base_policies)}
        pred_names = {p.get("name", i): p for i, p in enumerate(pred_policies)}

        details: list[str] = []
        for name in set(base_names) | set(pred_names):
            if name not in base_names:
                details.append(f"Policy '{name}' added")
            elif name not in pred_names:
                details.append(f"Policy '{name}' removed")
            elif base_names[name] != pred_names[name]:
                details.append(f"Policy '{name}' modified")

        if details:
            results.append(CheckResult(
                check_id="SEC-POLICY", check_name="Security Policy Changes", layer=4,
                status="warning", summary=f"{len(details)} security policy change(s)",
                details=details, affected_sites=[predicted.site_id],
                remediation_hint="Review security policy changes carefully. Order-dependent rules may have unexpected effects.",
            ))
        else:
            results.append(CheckResult(
                check_id="SEC-POLICY", check_name="Security Policy Changes", layer=4,
                status="pass", summary="No security policy changes",
                affected_sites=[predicted.site_id],
            ))
    else:
        results.append(CheckResult(
            check_id="SEC-POLICY", check_name="Security Policy Changes", layer=4,
            status="pass", summary="No security policy changes",
            affected_sites=[predicted.site_id],
        ))

    # ── SEC-NAC: NAC rule change detection ──
    base_nac = baseline.site_setting.get("nacrules") or []
    pred_nac = predicted.site_setting.get("nacrules") or []

    if base_nac != pred_nac:
        nac_details = [f"NAC rules changed ({len(base_nac)} → {len(pred_nac)} rules)"]
        results.append(CheckResult(
            check_id="SEC-NAC", check_name="NAC Rule Changes", layer=4,
            status="warning", summary="NAC rules modified",
            details=nac_details, affected_sites=[predicted.site_id],
            remediation_hint="Review NAC rule changes. VLAN assignment conflicts can cause authentication failures.",
        ))
    else:
        results.append(CheckResult(
            check_id="SEC-NAC", check_name="NAC Rule Changes", layer=4,
            status="pass", summary="No NAC rule changes",
            affected_sites=[predicted.site_id],
        ))

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_snapshot_checks.py -v -k "Sec"``
Expected: PASS (all 4 security tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend
git add app/modules/digital_twin/checks/security.py tests/unit/test_snapshot_checks.py
git commit -m "feat(digital-twin): add security checks (guest SSID, policy, NAC)"
```

---

### Task 11: checks/stp.py — Root Bridge/BPDU/Loop

**Files:**
- Create: `backend/app/modules/digital_twin/checks/stp.py`
- Modify: `backend/tests/unit/test_snapshot_checks.py`

Three checks: `STP-ROOT`, `STP-BPDU`, `STP-LOOP`.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_snapshot_checks.py`:

```python
# ── Category 9: STP ────────────────────────────────────────────────────


class TestStpRoot:
    def test_detects_root_bridge_shift(self):
        from app.modules.digital_twin.checks.stp import check_stp

        sw1_base = _dev("sw1", "aa", "SW-1", stp_config={"bridge_priority": 4096})
        sw2_base = _dev("sw2", "bb", "SW-2", stp_config={"bridge_priority": 32768})
        sw1_pred = _dev("sw1", "aa", "SW-1", stp_config={"bridge_priority": 32768})
        sw2_pred = _dev("sw2", "bb", "SW-2", stp_config={"bridge_priority": 32768})

        lldp = {"aa": {"ge-0/0/0": "bb"}}
        baseline = _snap(devices={"sw1": sw1_base, "sw2": sw2_base}, lldp=lldp)
        predicted = _snap(devices={"sw1": sw1_pred, "sw2": sw2_pred}, lldp=lldp)

        results = check_stp(baseline, predicted)
        root_check = [r for r in results if r.check_id == "STP-ROOT"]
        assert root_check[0].status in ("warning", "error")


class TestStpBpdu:
    def test_detects_bpdu_filter_on_trunk(self):
        from app.modules.digital_twin.checks.stp import check_stp

        sw = _dev("sw1", "aa", "SW-1", port_config={
            "ge-0/0/0": {"usage": "trunk", "bpdu_filter": True},
        })
        snap = _snap(devices={"sw1": sw})
        results = check_stp(snap, snap)
        bpdu = [r for r in results if r.check_id == "STP-BPDU"]
        assert bpdu[0].status in ("warning", "error")

    def test_bpdu_filter_on_access_passes(self):
        from app.modules.digital_twin.checks.stp import check_stp

        sw = _dev("sw1", "aa", "SW-1", port_config={
            "ge-0/0/9": {"usage": "ap", "bpdu_filter": True},
        })
        snap = _snap(devices={"sw1": sw})
        results = check_stp(snap, snap)
        bpdu = [r for r in results if r.check_id == "STP-BPDU"]
        assert bpdu[0].status == "pass"


class TestStpLoop:
    def test_detects_new_cycle(self):
        from app.modules.digital_twin.checks.stp import check_stp

        sw1 = _dev("sw1", "aa", "SW-1")
        sw2 = _dev("sw2", "bb", "SW-2")
        sw3 = _dev("sw3", "cc", "SW-3")

        baseline_lldp = {"aa": {"ge-0/0/0": "bb"}, "bb": {"ge-0/0/0": "cc"}}
        # Predicted adds a link from sw3 back to sw1, creating a cycle
        predicted_lldp = {
            "aa": {"ge-0/0/0": "bb"},
            "bb": {"ge-0/0/0": "cc"},
            "cc": {"ge-0/0/0": "aa"},
        }

        baseline = _snap(devices={"sw1": sw1, "sw2": sw2, "sw3": sw3}, lldp=baseline_lldp)
        predicted = _snap(devices={"sw1": sw1, "sw2": sw2, "sw3": sw3}, lldp=predicted_lldp)

        results = check_stp(baseline, predicted)
        loop = [r for r in results if r.check_id == "STP-LOOP"]
        assert loop[0].status in ("warning", "error")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_snapshot_checks.py::TestStpRoot -v`
Expected: FAIL

- [ ] **Step 3: Implement STP checks**

```python
# backend/app/modules/digital_twin/checks/stp.py
"""
Category 9: STP risk detection — root bridge shift, BPDU filter on trunk, loop risk.

Config-based analysis using SiteGraph cycle detection.
"""

from __future__ import annotations

import networkx as nx

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.site_graph import build_site_graph
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot


def _get_stp_priority(dev) -> int | None:
    """Extract STP bridge priority from device config."""
    stp = dev.stp_config or {}
    for key in ("bridge_priority", "stp_priority", "rstp_priority"):
        val = stp.get(key)
        if val is not None:
            return int(val)
    return None


def _find_root(priorities: dict[str, int]) -> str | None:
    """Find the root bridge (lowest priority, then lowest MAC as tiebreak)."""
    if not priorities:
        return None
    return min(priorities, key=lambda mac: (priorities[mac], mac))


def check_stp(
    baseline: SiteSnapshot,
    predicted: SiteSnapshot,
) -> list[CheckResult]:
    """Run all STP checks."""
    results: list[CheckResult] = []
    baseline_graph = build_site_graph(baseline)
    predicted_graph = build_site_graph(predicted)

    # ── STP-ROOT: Root bridge shift ──
    base_priorities: dict[str, int] = {}
    pred_priorities: dict[str, int] = {}
    for dev in baseline.devices.values():
        if dev.type == "switch":
            prio = _get_stp_priority(dev)
            if prio is not None:
                base_priorities[dev.mac] = prio
    for dev in predicted.devices.values():
        if dev.type == "switch":
            prio = _get_stp_priority(dev)
            if prio is not None:
                pred_priorities[dev.mac] = prio

    base_root = _find_root(base_priorities)
    pred_root = _find_root(pred_priorities)

    if base_root and pred_root and base_root != pred_root:
        base_name = baseline.devices.get(
            next((d.device_id for d in baseline.devices.values() if d.mac == base_root), ""), None
        )
        pred_name = predicted.devices.get(
            next((d.device_id for d in predicted.devices.values() if d.mac == pred_root), ""), None
        )
        base_label = base_name.name if base_name else base_root
        pred_label = pred_name.name if pred_name else pred_root
        results.append(CheckResult(
            check_id="STP-ROOT", check_name="STP Root Bridge Shift", layer=5,
            status="warning",
            summary=f"STP root bridge will shift from {base_label} to {pred_label}",
            details=[f"Priority change causes root election: {base_label} ({base_priorities.get(base_root)}) → {pred_label} ({pred_priorities.get(pred_root)})"],
            affected_sites=[predicted.site_id],
            remediation_hint="Root bridge changes cause temporary reconvergence. Schedule during maintenance.",
        ))
    else:
        results.append(CheckResult(
            check_id="STP-ROOT", check_name="STP Root Bridge Shift", layer=5,
            status="pass", summary="STP root bridge unchanged",
            affected_sites=[predicted.site_id],
        ))

    # ── STP-BPDU: BPDU filter on trunk ──
    bpdu_issues: list[str] = []
    for dev in predicted.devices.values():
        if dev.type != "switch":
            continue
        port_usages = dev.port_usages or predicted.port_usages
        for port_name, port_cfg in dev.port_config.items():
            usage = port_cfg.get("usage", "")
            profile = port_usages.get(usage, {})

            is_trunk = usage == "trunk" or profile.get("mode") == "trunk"
            has_bpdu_filter = port_cfg.get("bpdu_filter") or port_cfg.get("stp_bpdu_filter")

            if is_trunk and has_bpdu_filter:
                bpdu_issues.append(f"{dev.name} port {port_name}: BPDU filter enabled on trunk")

    if bpdu_issues:
        results.append(CheckResult(
            check_id="STP-BPDU", check_name="BPDU Filter on Trunk", layer=5,
            status="warning", summary=f"{len(bpdu_issues)} trunk port(s) with BPDU filter",
            details=bpdu_issues, affected_sites=[predicted.site_id],
            remediation_hint="BPDU filter on trunk ports disables STP protection and risks L2 loops.",
        ))
    else:
        results.append(CheckResult(
            check_id="STP-BPDU", check_name="BPDU Filter on Trunk", layer=5,
            status="pass", summary="No BPDU filter on trunk ports",
            affected_sites=[predicted.site_id],
        ))

    # ── STP-LOOP: L2 loop risk ──
    # Check for new cycles in predicted graph not in baseline
    base_cycles = set()
    try:
        for cycle in nx.cycle_basis(baseline_graph.physical):
            base_cycles.add(frozenset(cycle))
    except nx.NetworkXError:
        pass

    new_cycles: list[list[str]] = []
    try:
        for cycle in nx.cycle_basis(predicted_graph.physical):
            if frozenset(cycle) not in base_cycles:
                new_cycles.append(cycle)
    except nx.NetworkXError:
        pass

    if new_cycles:
        details = []
        for cycle in new_cycles[:5]:  # Limit output
            names = []
            for mac in cycle:
                node_data = predicted_graph.physical.nodes.get(mac, {})
                names.append(node_data.get("name", mac))
            details.append(f"New cycle: {' → '.join(names)}")

        results.append(CheckResult(
            check_id="STP-LOOP", check_name="L2 Loop Risk", layer=5,
            status="warning", summary=f"{len(new_cycles)} new L2 cycle(s) detected",
            details=details, affected_sites=[predicted.site_id],
            remediation_hint="New physical loops require STP/RSTP protection. Verify spanning tree is active on all trunk links.",
        ))
    else:
        results.append(CheckResult(
            check_id="STP-LOOP", check_name="L2 Loop Risk", layer=5,
            status="pass", summary="No new L2 loops introduced",
            affected_sites=[predicted.site_id],
        ))

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_snapshot_checks.py -v -k "Stp"``
Expected: PASS (all 4 STP tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend
git add app/modules/digital_twin/checks/stp.py tests/unit/test_snapshot_checks.py
git commit -m "feat(digital-twin): add STP checks (root bridge, BPDU filter, loop risk)"
```

---

### Task 12: snapshot_analyzer.py — Orchestrator

**Files:**
- Create: `backend/app/modules/digital_twin/services/snapshot_analyzer.py`
- Modify: `backend/tests/unit/test_snapshot_checks.py`

Orchestrates all 9 check categories. Also includes `build_prediction_report()` moved from prediction_service.py.

- [ ] **Step 1: Write failing test for analyze_site()**

Append to `backend/tests/unit/test_snapshot_checks.py`:

```python
# ── Orchestrator ────────────────────────────────────────────────────────


class TestAnalyzeSite:
    def test_runs_all_categories(self):
        from app.modules.digital_twin.services.snapshot_analyzer import analyze_site

        sw = _dev("sw1", "aa", "SW-1", port_config={"ge-0/0/9": {"usage": "ap"}})
        gw = _dev("gw1", "cc", "GW-1", dtype="gateway",
                   ip_config={"Corp": {"ip": "10.1.1.1", "netmask": "255.255.255.0"}})
        networks = {"n1": {"name": "Corp", "vlan_id": 100, "subnet": "10.1.0.0/24"}}

        snap = _snap(
            devices={"sw1": sw, "gw1": gw},
            lldp={"aa": {"ge-0/0/0": "cc"}},
            networks=networks,
        )
        results = analyze_site(snap, snap)

        check_ids = {r.check_id for r in results}
        # Should have results from all 9 categories
        assert "CONN-PHYS" in check_ids
        assert "CONN-VLAN" in check_ids
        assert "CFG-SUBNET" in check_ids
        assert "CFG-VLAN" in check_ids
        assert "CFG-SSID" in check_ids
        assert "PORT-DISC" in check_ids
        assert "TMPL-VAR" in check_ids
        assert "ROUTE-GW" in check_ids
        assert "SEC-GUEST" in check_ids
        assert "STP-ROOT" in check_ids

    def test_build_prediction_report(self):
        from app.modules.digital_twin.models import CheckResult
        from app.modules.digital_twin.services.snapshot_analyzer import build_prediction_report

        results = [
            CheckResult(check_id="A", check_name="A", layer=1, status="pass", summary="ok"),
            CheckResult(check_id="B", check_name="B", layer=2, status="critical", summary="bad"),
            CheckResult(check_id="C", check_name="C", layer=2, status="warning", summary="meh"),
            CheckResult(check_id="D", check_name="D", layer=1, status="skipped", summary="skip"),
        ]
        report = build_prediction_report(results)
        assert report.total_checks == 3  # excludes skipped
        assert report.passed == 1
        assert report.critical == 1
        assert report.warnings == 1
        assert report.skipped == 1
        assert report.overall_severity == "critical"
        assert report.execution_safe is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_snapshot_checks.py::TestAnalyzeSite -v`
Expected: FAIL

- [ ] **Step 3: Implement snapshot_analyzer.py**

```python
# backend/app/modules/digital_twin/services/snapshot_analyzer.py
"""
Snapshot Analyzer — orchestrates all check categories.

Takes (baseline, predicted) SiteSnapshots, runs all 9 check categories,
returns aggregated list of CheckResults.
"""

from __future__ import annotations

from app.modules.digital_twin.checks.config_conflicts import check_config_conflicts
from app.modules.digital_twin.checks.connectivity import check_connectivity
from app.modules.digital_twin.checks.port_impact import check_port_impact
from app.modules.digital_twin.checks.routing import check_routing
from app.modules.digital_twin.checks.security import check_security
from app.modules.digital_twin.checks.stp import check_stp
from app.modules.digital_twin.checks.template_checks import check_template_variables
from app.modules.digital_twin.models import CheckResult, PredictionReport
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot

_SEVERITY_ORDER = {"pass": 0, "skipped": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}
_SEVERITY_LABELS = {0: "clean", 1: "info", 2: "warning", 3: "error", 4: "critical"}


def compute_overall_severity(results: list[CheckResult]) -> str:
    """Compute worst severity from a list of check results."""
    worst = 0
    for r in results:
        level = _SEVERITY_ORDER.get(r.status, 0)
        if level > worst:
            worst = level
    return _SEVERITY_LABELS[worst]


def build_prediction_report(results: list[CheckResult]) -> PredictionReport:
    """Build a PredictionReport from a list of CheckResults."""
    passed = sum(1 for r in results if r.status == "pass")
    warnings = sum(1 for r in results if r.status == "warning")
    errors = sum(1 for r in results if r.status == "error")
    critical = sum(1 for r in results if r.status == "critical")
    skipped = sum(1 for r in results if r.status == "skipped")
    severity = compute_overall_severity(results)

    parts: list[str] = []
    if critical:
        parts.append(f"{critical} critical")
    if errors:
        parts.append(f"{errors} error(s)")
    if warnings:
        parts.append(f"{warnings} warning(s)")
    summary = ", ".join(parts) if parts else "All checks passed"

    return PredictionReport(
        total_checks=len(results) - skipped,
        passed=passed,
        warnings=warnings,
        errors=errors,
        critical=critical,
        skipped=skipped,
        check_results=results,
        overall_severity=severity,
        summary=summary,
        execution_safe=(errors == 0 and critical == 0),
    )


def analyze_site(
    baseline: SiteSnapshot,
    predicted: SiteSnapshot,
) -> list[CheckResult]:
    """Run all check categories against baseline vs predicted snapshots.

    Returns a flat list of CheckResults from all 9 categories.
    """
    results: list[CheckResult] = []

    # Category 1+2: Connectivity (physical + VLAN reachability)
    results.extend(check_connectivity(baseline, predicted))

    # Category 3: Config conflicts (subnet, VLAN, SSID, DHCP)
    results.extend(check_config_conflicts(predicted))

    # Category 4: Template variables
    results.extend(check_template_variables(predicted))

    # Category 5+6: Port impact + client estimation
    results.extend(check_port_impact(baseline, predicted))

    # Category 7: Routing (gateway, OSPF, BGP, WAN)
    results.extend(check_routing(baseline, predicted))

    # Category 8: Security (guest SSID, policies, NAC)
    results.extend(check_security(baseline, predicted))

    # Category 9: STP (root bridge, BPDU, loops)
    results.extend(check_stp(baseline, predicted))

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_snapshot_checks.py -v`
Expected: PASS (all tests across all categories)

- [ ] **Step 5: Commit**

```bash
cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend
git add app/modules/digital_twin/services/snapshot_analyzer.py tests/unit/test_snapshot_checks.py
git commit -m "feat(digital-twin): add snapshot_analyzer orchestrator + build_prediction_report"
```

---

### Task 13: Wire into simulate() + Remove Old Files

**Files:**
- Modify: `backend/app/modules/digital_twin/services/twin_service.py`
- Modify: `backend/app/modules/digital_twin/CLAUDE.md`
- Remove: 6 old check files + `predicted_topology.py`

This task replaces the check dispatch in `simulate()` (lines 137-172) with the snapshot-based analysis, and removes all old check files.

- [ ] **Step 1: Modify twin_service.py imports**

Replace the imports at the top of `twin_service.py`:

Old imports (lines 22-27):
```python
from app.modules.digital_twin.services.prediction_service import (
    _build_simulation_context,
    build_prediction_report,
    compute_relevant_checks,
    run_layer1_checks,
)
```

New imports:
```python
from app.modules.digital_twin.services.snapshot_analyzer import (
    analyze_site,
    build_prediction_report,
)
from app.modules.digital_twin.services.site_snapshot import (
    build_site_snapshot,
    fetch_live_data,
)
```

- [ ] **Step 2: Replace the check dispatch in simulate()**

Replace `twin_service.py` lines 137-172 (from `# Pre-fetch shared backup data...` through `check_results.extend(l5_results)`) with:

```python
    # ── Snapshot-based analysis ──
    # For each affected site: build baseline + predicted snapshots, run all checks
    import asyncio

    async def _analyze_one_site(sid: str):
        live_data = await fetch_live_data(sid, org_id)
        baseline_snap = await build_site_snapshot(sid, org_id, live_data)
        predicted_snap = await build_site_snapshot(sid, org_id, live_data, state_overrides=virtual_state)
        return analyze_site(baseline_snap, predicted_snap)

    if affected_sites:
        site_results = await asyncio.gather(*[_analyze_one_site(sid) for sid in affected_sites])
        for site_result in site_results:
            check_results.extend(site_result)
```

- [ ] **Step 3: Run tests to verify the simulation still works**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest tests/unit/test_site_snapshot.py tests/unit/test_site_graph.py tests/unit/test_snapshot_checks.py tests/unit/test_digital_twin_schemas.py -v`
Expected: PASS (all tests)

- [ ] **Step 4: Remove old check files**

```bash
cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend
rm app/modules/digital_twin/services/config_checks.py
rm app/modules/digital_twin/services/topology_checks.py
rm app/modules/digital_twin/services/routing_checks.py
rm app/modules/digital_twin/services/security_checks.py
rm app/modules/digital_twin/services/l2_checks.py
rm app/modules/digital_twin/services/predicted_topology.py
rm app/modules/digital_twin/services/prediction_service.py
```

Also remove old test files that tested the removed check functions:

```bash
rm tests/unit/test_l2_checks.py
rm tests/unit/test_topology_checks.py
rm tests/unit/test_security_checks.py
```

- [ ] **Step 5: Update CLAUDE.md**

Update `backend/app/modules/digital_twin/CLAUDE.md` — replace the "Key Services" table and "Check Layers" section with the new architecture:

- Services table: add `site_snapshot.py`, `site_graph.py`, `snapshot_analyzer.py`; remove old check files and `prediction_service.py`
- Check table: replace L1-L5 with new 9-category system (20 checks)
- Data Model table: add `SiteSnapshot`, `DeviceSnapshot`, `LiveSiteData`, `SiteGraph`

- [ ] **Step 6: Run all tests to verify nothing is broken**

Run: `cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend && .venv/bin/pytest -v`
Expected: PASS (old tests for removed files should be deleted; new tests should pass)

- [ ] **Step 7: Commit**

```bash
cd /Users/tmunzer/4_dev/mist_automation/.worktrees/digital-twin-ui/backend
git add -A
git commit -m "feat(digital-twin): wire snapshot engine into simulate(), remove old check files

Replace the 37-check prediction_service dispatch with the snapshot-based
analysis engine. Each affected site gets baseline + predicted SiteSnapshots
built from backup + one API call, analyzed through 9 check categories
(20 focused checks).

Removed files:
- prediction_service.py (replaced by snapshot_analyzer.py)
- config_checks.py, topology_checks.py, routing_checks.py,
  security_checks.py, l2_checks.py (replaced by checks/ package)
- predicted_topology.py (replaced by site_graph.py)"
```

---

## Verification Scenarios

After all tasks are complete, test these scenarios end-to-end:

1. **Port profile change** (primary test case):
   - Simulate: PUT device, change `port_config.ge-0/0/9.usage` from `"ap"` to `"disabled"`
   - Expected: `PORT-DISC` CRITICAL ("disconnects AP-1"), `PORT-CLIENT` WARNING ("~23 clients"), `CONN-PHYS` CRITICAL if AP was the only path

2. **VLAN collision**:
   - Simulate: PUT network, change `vlan_id` to one already in use
   - Expected: `CFG-VLAN` ERROR ("VLAN 100 used by: Corp, IoT")

3. **Template variable**:
   - Simulate: PUT networktemplate, add `{{ undefined_var }}` reference
   - Expected: `TMPL-VAR` ERROR ("Variable 'undefined_var' not defined")

4. **Subnet overlap**:
   - Simulate: POST network with `subnet: 10.1.0.0/16` overlapping existing `10.1.1.0/24`
   - Expected: `CFG-SUBNET` CRITICAL ("10.1.0.0/16 overlaps 10.1.1.0/24")

5. **Guest SSID**:
   - Simulate: PUT WLAN, set `auth.type: "open"` without `isolation: true`
   - Expected: `SEC-GUEST` WARNING ("open without client isolation")

6. **WAN link removal**:
   - Simulate: PUT gateway, remove a `usage: "wan"` port
   - Expected: `ROUTE-WAN` WARNING ("WAN link ge-0/0/1 removed")
