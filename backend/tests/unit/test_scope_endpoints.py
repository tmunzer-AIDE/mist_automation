"""Tests for GET /telemetry/scope/summary and /telemetry/scope/devices.

Uses the shared httpx AsyncClient fixture with a patched LatestValueCache.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.modules.telemetry.services.latest_value_cache import LatestValueCache

SITE_1 = "00000000-0000-0000-0000-000000000001"
SITE_2 = "00000000-0000-0000-0000-000000000002"


def _build_test_cache() -> LatestValueCache:
    """Build a cache with one AP and one switch at SITE_1."""
    cache = LatestValueCache()

    # AP device
    cache.update(
        "aabbccdd0001",
        {
            "mac": "aabbccdd0001",
            "site_id": SITE_1,
            "type": "ap",
            "name": "AP-Lobby",
            "model": "AP45",
            "num_clients": 12,
            "cpu_stat": {"idle": 65.5},
            "radio_stat": {
                "band_24": {"util_all": 30.0, "noise_floor": -85},
                "band_5": {"util_all": 20.0, "noise_floor": -90},
            },
        },
    )

    # Switch device
    cache.update(
        "aabbccdd0002",
        {
            "mac": "aabbccdd0002",
            "site_id": SITE_1,
            "type": "switch",
            "name": "SW-Core",
            "model": "EX4400",
            "clients_stats": {"total": {"num_wired_clients": 8}},
            "cpu_stat": {"idle": 80.0},
            "module_stat": [{"poe": {"power_draw": 120.5, "max_power": 740.0}}],
            "dhcpd_stat": {"vlan10": {"num_leased": 25}},
        },
    )

    return cache


class TestScopeSummaryAPFields:
    """Verify AP summary has correct avg_cpu, total_clients, reporting counts."""

    async def test_scope_summary_ap_fields(self, client):
        cache = _build_test_cache()
        with patch("app.modules.telemetry._latest_cache", cache):
            resp = await client.get("/api/v1/telemetry/scope/summary")

        assert resp.status_code == 200
        data = resp.json()
        ap = data["ap"]
        assert ap is not None
        assert ap["reporting_total"] == 1
        assert ap["reporting_active"] == 1
        # cpu_util = 100 - 65.5 = 34.5
        assert ap["avg_cpu_util"] == 34.5
        assert ap["max_cpu_util"] == 34.5
        assert ap["total_clients"] == 12
        # Band data
        assert "band_24" in ap["bands"]
        assert ap["bands"]["band_24"]["avg_util_all"] == 30.0
        assert ap["bands"]["band_24"]["avg_noise_floor"] == -85.0
        assert ap["bands"]["band_5"]["avg_util_all"] == 20.0


class TestScopeSummarySwitchFields:
    """Verify switch summary has correct fields."""

    async def test_scope_summary_switch_fields(self, client):
        cache = _build_test_cache()
        with patch("app.modules.telemetry._latest_cache", cache):
            resp = await client.get("/api/v1/telemetry/scope/summary")

        assert resp.status_code == 200
        data = resp.json()
        sw = data["switch"]
        assert sw is not None
        assert sw["reporting_total"] == 1
        assert sw["reporting_active"] == 1
        # cpu_util = 100 - 80 = 20
        assert sw["avg_cpu_util"] == 20.0
        assert sw["total_clients"] == 8
        assert sw["poe_draw_total"] == 120.5
        assert sw["poe_max_total"] == 740.0
        assert sw["total_dhcp_leases"] == 25


class TestScopeDevicesFlatList:
    """Verify device list has both devices."""

    async def test_scope_devices_returns_flat_list(self, client):
        cache = _build_test_cache()
        with patch("app.modules.telemetry._latest_cache", cache):
            resp = await client.get("/api/v1/telemetry/scope/devices")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["devices"]) == 2
        # All devices have required fields
        for dev in data["devices"]:
            assert "mac" in dev
            assert "device_type" in dev
            assert "fresh" in dev
            assert "cpu_util" in dev


class TestScopeSummaryNoCacheReturns503:
    """Patch cache to None and verify 503."""

    async def test_scope_summary_no_cache_returns_503(self, client):
        with patch("app.modules.telemetry._latest_cache", None):
            resp = await client.get("/api/v1/telemetry/scope/summary")

        assert resp.status_code == 503

    async def test_scope_devices_no_cache_returns_503(self, client):
        with patch("app.modules.telemetry._latest_cache", None):
            resp = await client.get("/api/v1/telemetry/scope/devices")

        assert resp.status_code == 503


class TestScopeDevicesFiltersBySite:
    """With two different site_ids, verify filtering works."""

    async def test_scope_devices_filters_by_site(self, client):
        cache = _build_test_cache()

        # Add a device at a different site
        cache.update(
            "aabbccdd0003",
            {
                "mac": "aabbccdd0003",
                "site_id": SITE_2,
                "type": "gateway",
                "name": "GW-Branch",
                "model": "SRX320",
                "cpu_stat": {"idle": 70.0},
                "if_stat": {
                    "ge-0/0/0": {"port_usage": "wan", "up": True},
                    "ge-0/0/1": {"port_usage": "wan", "up": False},
                },
                "dhcpd_stat": {"default": {"num_leased": 10}},
            },
        )

        with patch("app.modules.telemetry._latest_cache", cache):
            # Filter to SITE_1 — should get AP + switch only
            resp = await client.get(
                "/api/v1/telemetry/scope/devices",
                params={"site_id": SITE_1},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 2
            macs = {d["mac"] for d in data["devices"]}
            assert "aabbccdd0001" in macs
            assert "aabbccdd0002" in macs
            assert "aabbccdd0003" not in macs

            # Filter to SITE_2 — should get gateway only
            resp = await client.get(
                "/api/v1/telemetry/scope/devices",
                params={"site_id": SITE_2},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 1
            assert data["devices"][0]["mac"] == "aabbccdd0003"

    async def test_scope_summary_filters_by_site(self, client):
        """Summary endpoint also respects site_id filter."""
        cache = _build_test_cache()

        # Add a gateway at a different site
        cache.update(
            "aabbccdd0003",
            {
                "mac": "aabbccdd0003",
                "site_id": SITE_2,
                "type": "gateway",
                "name": "GW-Branch",
                "model": "SRX320",
                "cpu_stat": {"idle": 70.0},
                "if_stat": {
                    "ge-0/0/0": {"port_usage": "wan", "up": True},
                    "ge-0/0/1": {"port_usage": "wan", "up": False},
                },
                "dhcpd_stat": {"default": {"num_leased": 10}},
            },
        )

        with patch("app.modules.telemetry._latest_cache", cache):
            # SITE_1 should have AP + switch, no gateway
            resp = await client.get(
                "/api/v1/telemetry/scope/summary",
                params={"site_id": SITE_1},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["ap"] is not None
            assert data["switch"] is not None
            assert data["gateway"] is None

            # SITE_2 should have gateway only
            resp = await client.get(
                "/api/v1/telemetry/scope/summary",
                params={"site_id": SITE_2},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["ap"] is None
            assert data["switch"] is None
            assert data["gateway"] is not None
            gw = data["gateway"]
            assert gw["reporting_total"] == 1
            assert gw["wan_links_total"] == 2
            assert gw["wan_links_up"] == 1
            assert gw["total_dhcp_leases"] == 10


class TestScopeSummaryStaleDevices:
    """Verify stale devices are counted in total but not in active."""

    async def test_stale_device_counted_correctly(self, client):
        cache = _build_test_cache()
        # Make the AP stale
        cache._entries["aabbccdd0001"]["updated_at"] = time.time() - 120

        with patch("app.modules.telemetry._latest_cache", cache):
            resp = await client.get("/api/v1/telemetry/scope/summary")

        assert resp.status_code == 200
        data = resp.json()
        ap = data["ap"]
        assert ap["reporting_total"] == 1
        assert ap["reporting_active"] == 0  # stale

    async def test_stale_device_in_devices_list(self, client):
        cache = _build_test_cache()
        cache._entries["aabbccdd0001"]["updated_at"] = time.time() - 120

        with patch("app.modules.telemetry._latest_cache", cache):
            resp = await client.get("/api/v1/telemetry/scope/devices")

        assert resp.status_code == 200
        devices = {d["mac"]: d for d in resp.json()["devices"]}
        assert devices["aabbccdd0001"]["fresh"] is False
        assert devices["aabbccdd0002"]["fresh"] is True


class TestScopeSummaryInvalidSiteId:
    """Verify invalid site_id returns 400."""

    async def test_invalid_site_id_returns_400_summary(self, client):
        cache = _build_test_cache()
        with patch("app.modules.telemetry._latest_cache", cache):
            resp = await client.get(
                "/api/v1/telemetry/scope/summary",
                params={"site_id": "not-a-uuid"},
            )
        assert resp.status_code == 400

    async def test_invalid_site_id_returns_400_devices(self, client):
        cache = _build_test_cache()
        with patch("app.modules.telemetry._latest_cache", cache):
            resp = await client.get(
                "/api/v1/telemetry/scope/devices",
                params={"site_id": "not-a-uuid"},
            )
        assert resp.status_code == 400
