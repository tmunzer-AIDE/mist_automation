"""Unit tests for SiteDataCoordinator telemetry cache integration.

Tests the three scenarios from Step 8:
1. Cache has fresh data → HTTP device stats API not called
2. Cache is empty → falls back to HTTP API
3. Telemetry disabled (_latest_cache is None) → falls back to HTTP API
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_mist_session():
    """Return a (mist_service, session) pair where all mistapi calls return empty."""
    session = MagicMock()
    mist = MagicMock()
    mist.get_session.return_value = session
    return mist, session


def _make_api_response(data, status_code=200):
    """Return a mock response object similar to mistapi responses."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.data = data
    return resp


def _make_empty_api_response():
    return _make_api_response([])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_coordinator():
    """Clear class-level state between tests."""
    from app.modules.impact_analysis.services.site_data_coordinator import SiteDataCoordinator

    SiteDataCoordinator._site_coordinators.clear()
    SiteDataCoordinator._org_data_cache.clear()
    yield
    SiteDataCoordinator._site_coordinators.clear()
    SiteDataCoordinator._org_data_cache.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSiteDataCoordinatorCacheIntegration:
    """Verify that the telemetry LatestValueCache is checked before making
    the listSiteDevicesStats HTTP call."""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_api_call(self):
        """When telemetry cache returns fresh device stats, the HTTP API is not called."""
        from app.modules.impact_analysis.services.site_data_coordinator import SiteDataCoordinator

        site_id = "site-abc"
        org_id = "org-123"

        cached_stats = [
            {"mac": "aabbccddeeff", "site_id": site_id, "status": "connected"},
            {"mac": "112233445566", "site_id": site_id, "status": "connected"},
        ]

        # Build a fake cache that returns cached_stats for the site
        fake_cache = MagicMock()
        fake_cache.get_all_for_site.return_value = cached_stats

        mist, session = _make_fake_mist_session()

        # Track whether listSiteDevicesStats was called
        api_call_tracker = MagicMock()

        async def fake_arun(func, *args, **kwargs):
            if func.__name__ == "listSiteDevicesStats":
                api_call_tracker(func.__name__)
            return _make_empty_api_response()

        # Patch _latest_cache on the actual telemetry module (already imported)
        import app.modules.telemetry as telemetry_mod

        with (
            patch(
                "app.modules.impact_analysis.services.site_data_coordinator.create_mist_service",
                return_value=mist,
            ),
            patch(
                "app.modules.impact_analysis.services.site_data_coordinator.topology_service.build_site_topology",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("mistapi.arun", side_effect=fake_arun),
            patch.object(telemetry_mod, "_latest_cache", fake_cache),
        ):
            coordinator = SiteDataCoordinator.get_or_create(site_id)
            result = await coordinator._fetch_all_site_data(site_id, org_id)

        # listSiteDevicesStats must NOT have been called
        api_call_tracker.assert_not_called()

        # device_stats in result must come from the cache
        assert result.device_stats == cached_stats
        fake_cache.get_all_for_site.assert_called_once_with(site_id, max_age_seconds=60)

    @pytest.mark.asyncio
    async def test_cache_empty_falls_back_to_api(self):
        """When telemetry cache is empty, the HTTP API is called."""
        from app.modules.impact_analysis.services.site_data_coordinator import SiteDataCoordinator

        site_id = "site-def"
        org_id = "org-456"

        api_device_stats = [{"mac": "aabbccddeeff", "site_id": site_id, "status": "connected"}]

        # Cache returns empty list → fall back to API
        fake_cache = MagicMock()
        fake_cache.get_all_for_site.return_value = []

        mist, session = _make_fake_mist_session()
        api_call_tracker = MagicMock()

        async def fake_arun(func, *args, **kwargs):
            if func.__name__ == "listSiteDevicesStats":
                api_call_tracker(func.__name__)
                return _make_api_response(api_device_stats)
            return _make_empty_api_response()

        import app.modules.telemetry as telemetry_mod

        with (
            patch(
                "app.modules.impact_analysis.services.site_data_coordinator.create_mist_service",
                return_value=mist,
            ),
            patch(
                "app.modules.impact_analysis.services.site_data_coordinator.topology_service.build_site_topology",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("mistapi.arun", side_effect=fake_arun),
            patch.object(telemetry_mod, "_latest_cache", fake_cache),
        ):
            coordinator = SiteDataCoordinator.get_or_create(site_id)
            result = await coordinator._fetch_all_site_data(site_id, org_id)

        # The API should have been called as fallback
        api_call_tracker.assert_called_once_with("listSiteDevicesStats")

        # device_stats in result must come from the API
        assert result.device_stats == api_device_stats

    @pytest.mark.asyncio
    async def test_telemetry_disabled_falls_back_to_api(self):
        """When telemetry is disabled (_latest_cache is None), the HTTP API is called."""
        from app.modules.impact_analysis.services.site_data_coordinator import SiteDataCoordinator

        site_id = "site-ghi"
        org_id = "org-789"

        api_device_stats = [{"mac": "ffeeddccbbaa", "site_id": site_id, "status": "connected"}]

        mist, session = _make_fake_mist_session()
        api_call_tracker = MagicMock()

        async def fake_arun(func, *args, **kwargs):
            if func.__name__ == "listSiteDevicesStats":
                api_call_tracker(func.__name__)
                return _make_api_response(api_device_stats)
            return _make_empty_api_response()

        # Patch _latest_cache to None (telemetry disabled)
        import app.modules.telemetry as telemetry_mod

        with (
            patch(
                "app.modules.impact_analysis.services.site_data_coordinator.create_mist_service",
                return_value=mist,
            ),
            patch(
                "app.modules.impact_analysis.services.site_data_coordinator.topology_service.build_site_topology",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("mistapi.arun", side_effect=fake_arun),
            patch.object(telemetry_mod, "_latest_cache", None),
        ):
            coordinator = SiteDataCoordinator.get_or_create(site_id)
            result = await coordinator._fetch_all_site_data(site_id, org_id)

        # The API should have been called since cache is None
        api_call_tracker.assert_called_once_with("listSiteDevicesStats")
        assert result.device_stats == api_device_stats

    @pytest.mark.asyncio
    async def test_telemetry_cache_raises_falls_back_to_api(self):
        """When the telemetry cache's get_all_for_site raises an exception, fall back to API."""
        from app.modules.impact_analysis.services.site_data_coordinator import SiteDataCoordinator

        site_id = "site-jkl"
        org_id = "org-000"

        api_device_stats = [{"mac": "001122334455", "site_id": site_id}]

        # Cache that raises on get_all_for_site
        fake_cache = MagicMock()
        fake_cache.get_all_for_site.side_effect = RuntimeError("cache exploded")

        mist, session = _make_fake_mist_session()
        api_call_tracker = MagicMock()

        async def fake_arun(func, *args, **kwargs):
            if func.__name__ == "listSiteDevicesStats":
                api_call_tracker(func.__name__)
                return _make_api_response(api_device_stats)
            return _make_empty_api_response()

        import app.modules.telemetry as telemetry_mod

        with (
            patch(
                "app.modules.impact_analysis.services.site_data_coordinator.create_mist_service",
                return_value=mist,
            ),
            patch(
                "app.modules.impact_analysis.services.site_data_coordinator.topology_service.build_site_topology",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("mistapi.arun", side_effect=fake_arun),
            patch.object(telemetry_mod, "_latest_cache", fake_cache),
        ):
            coordinator = SiteDataCoordinator.get_or_create(site_id)
            result = await coordinator._fetch_all_site_data(site_id, org_id)

        # Even with a cache exception, the API call should be made as fallback
        api_call_tracker.assert_called_once_with("listSiteDevicesStats")
        assert result.device_stats == api_device_stats

    @pytest.mark.asyncio
    async def test_cache_hit_returns_correct_device_count(self):
        """Cache hit delivers all 3 cached devices in device_stats."""
        from app.modules.impact_analysis.services.site_data_coordinator import SiteDataCoordinator

        site_id = "site-log"
        org_id = "org-log"

        cached_stats = [
            {"mac": "aabbccddeeff", "site_id": site_id},
            {"mac": "112233445566", "site_id": site_id},
            {"mac": "aabbccddee00", "site_id": site_id},
        ]

        fake_cache = MagicMock()
        fake_cache.get_all_for_site.return_value = cached_stats

        mist, session = _make_fake_mist_session()

        async def fake_arun(func, *args, **kwargs):
            return _make_empty_api_response()

        import app.modules.telemetry as telemetry_mod

        with (
            patch(
                "app.modules.impact_analysis.services.site_data_coordinator.create_mist_service",
                return_value=mist,
            ),
            patch(
                "app.modules.impact_analysis.services.site_data_coordinator.topology_service.build_site_topology",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("mistapi.arun", side_effect=fake_arun),
            patch.object(telemetry_mod, "_latest_cache", fake_cache),
        ):
            coordinator = SiteDataCoordinator.get_or_create(site_id)
            result = await coordinator._fetch_all_site_data(site_id, org_id)

        assert result.device_stats == cached_stats
        assert len(result.device_stats) == 3
