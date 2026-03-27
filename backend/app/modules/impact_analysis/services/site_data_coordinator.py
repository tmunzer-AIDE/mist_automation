"""Site-level data coordinator for config change impact analysis.

Fetches site-level data once per poll interval and shares it across all active
monitoring sessions at the same site. Two-tier strategy: site-level by default,
org-level for non-SLE data when 3+ sites are active.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import mistapi
import structlog
from mistapi.api.v1.orgs import alarms as org_alarms
from mistapi.api.v1.orgs import devices as org_devices
from mistapi.api.v1.orgs import gatewaytemplates as org_gatewaytemplates
from mistapi.api.v1.orgs import insights
from mistapi.api.v1.orgs import networks as org_networks
from mistapi.api.v1.orgs import stats as org_stats
from mistapi.api.v1.sites import alarms, clients, devices, setting, stats

from app.modules.impact_analysis.services import topology_service
from app.modules.impact_analysis.topology.client import RawSiteData
from app.services.mist_service_factory import create_mist_service

logger = structlog.get_logger(__name__)

_CACHE_TTL = 30.0  # seconds


@dataclass
class SitePollData:
    """Aggregated site-level data from a single poll cycle."""

    topology: Any | None = None
    sle_overview: dict[str, Any] | list | None = None
    device_stats: list[dict[str, Any]] = field(default_factory=list)
    alarms: list[dict[str, Any]] = field(default_factory=list)
    client_counts: dict[str, Any] | int | None = None
    config_events: list[dict[str, Any]] = field(default_factory=list)
    port_stats: list[dict[str, Any]] = field(default_factory=list)
    device_configs: list[dict[str, Any]] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OrgPollData:
    """Org-level aggregated data (used when 3+ sites are active)."""

    device_stats: list[dict[str, Any]] = field(default_factory=list)
    alarms: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _mono_time: float = field(default_factory=time.monotonic)

    def is_fresh(self, ttl: float = 30.0) -> bool:
        """Check if the cached org data is still within TTL."""
        return (time.monotonic() - self._mono_time) < ttl

    def extract_site(self, site_id: str) -> SitePollData:
        """Filter org-level results to a specific site.

        Topology, SLE, port stats, client counts, and device configs remain
        empty — they are always fetched at site level.
        """
        site_device_stats = [d for d in self.device_stats if d.get("site_id") == site_id]
        site_alarms = [a for a in self.alarms if a.get("site_id") == site_id]
        site_events = [e for e in self.events if e.get("site_id") == site_id]

        return SitePollData(
            topology=None,
            sle_overview=None,
            device_stats=site_device_stats,
            alarms=site_alarms,
            client_counts=None,
            config_events=site_events,
            port_stats=[],
            device_configs=[],
            fetched_at=self.fetched_at,
        )


def _normalize_results(data: Any) -> list[dict[str, Any]]:
    """Unwrap Mist API {"results": [...]} wrapper if present."""
    if isinstance(data, dict) and "results" in data:
        result: list[dict[str, Any]] = data["results"]
        return result
    if isinstance(data, list):
        return data
    return []


def _safe_result(result: Any, default: Any = None) -> Any:
    """Extract a value from an asyncio.gather result, handling exceptions."""
    if isinstance(result, BaseException):
        logger.warning("site_data_fetch_partial_failure", error=str(result))
        return default if default is not None else []
    return result


async def _safe_fetch(coro: Any, default: Any = None) -> Any:
    """Execute a coroutine and return its response data, with error handling."""
    try:
        resp = await coro
        if resp.status_code == 200:
            return resp.data if resp.data is not None else (default if default is not None else [])
        return default if default is not None else []
    except Exception as e:
        logger.warning("fetch_failed", error=str(e))
        return default if default is not None else []


class SiteDataCoordinator:
    """Fetches site-level data once per poll, shares across all sessions at that site.

    Class-level registries track coordinators per site and org-level cache.
    Instance-level cache stores the last fetched SitePollData with TTL.
    """

    # Class-level registries
    _site_coordinators: dict[str, SiteDataCoordinator] = {}
    _org_data_cache: dict[str, OrgPollData] = {}

    def __init__(self, site_id: str) -> None:
        self._site_id = site_id
        self._cache: SitePollData | None = None
        self._cache_time: float = 0.0

    # ── Instance methods ────────────────────────────────────────────────────

    async def fetch_site_data(self, site_id: str, org_id: str, device_type: str = "ap") -> SitePollData:
        """Fetch site-level data with 30s TTL cache.

        Args:
            device_type: Device type filter for listSiteDevicesStats (ap, switch, gateway).
                         Defaults to 'ap' for backward compatibility.

        Checks org-level cache first (populated when 3+ sites active),
        then instance cache, then fetches fresh data.
        """
        # Check org-level cache for non-SLE data
        org_data = self._org_data_cache.get(org_id)
        if org_data and org_data.is_fresh():
            # Org cache provides device_stats, alarms, events — but we still
            # need topology, SLE, port_stats, client_counts, device_configs at site level
            org_site = org_data.extract_site(site_id)
            site_specific = await self._fetch_site_specific(site_id, org_id)
            return SitePollData(
                topology=site_specific.topology,
                sle_overview=site_specific.sle_overview,
                device_stats=org_site.device_stats or site_specific.device_stats,
                alarms=org_site.alarms or site_specific.alarms,
                client_counts=site_specific.client_counts,
                config_events=org_site.config_events or site_specific.config_events,
                port_stats=site_specific.port_stats,
                device_configs=site_specific.device_configs,
                fetched_at=datetime.now(timezone.utc),
            )

        # Check instance cache
        now = time.monotonic()
        if self._cache and (now - self._cache_time) < _CACHE_TTL:
            return self._cache

        # Fetch fresh site-level data
        data = await self._fetch_all_site_data(site_id, org_id, device_type=device_type)
        self._cache = data
        self._cache_time = time.monotonic()
        return data

    async def _fetch_all_site_data(self, site_id: str, org_id: str, device_type: str = "ap") -> SitePollData:
        """Parallel fetch of all site-level data sources.

        Fetches topology-required data (port_stats, devices, device_stats,
        site_setting, alarms, org_networks) in the same gather as other
        site-level data, then builds the topology from the shared results
        to avoid redundant API calls.

        When the telemetry LatestValueCache has fresh data for devices at this
        site, it is used in place of the listSiteDevicesStats HTTP call.
        """
        mist = await create_mist_service()
        session = mist.get_session()

        # Check telemetry cache before making the device stats API call
        cached_device_stats: list[dict[str, Any]] | None = None
        try:
            import app.modules.telemetry as telemetry_mod

            cache = getattr(telemetry_mod, "_latest_cache", None)
            if cache is not None:
                cached = cache.get_all_for_site(site_id, max_age_seconds=60)
                if cached:
                    cached_device_stats = cached
                    logger.debug("using_telemetry_cache", site_id=site_id, device_count=len(cached))
        except Exception:
            pass  # telemetry module unavailable — fall through to API

        # Indices 0-7: topology-shared + coordinator data
        # 0: SLE overview
        # 1: device_stats (typed — for coordinator) — skipped if telemetry cache hit
        # 2: alarms (shared with topology)
        # 3: client counts
        # 4: config events
        # 5: port_stats (shared with topology)
        # 6: device_configs
        # 7: listSiteDevices (topology-only)
        # 8: site_setting_derived (topology-only)
        # 9: org_networks (topology-only)

        async def _device_stats_source() -> list[dict[str, Any]]:
            if cached_device_stats is not None:
                return cached_device_stats
            return await _safe_fetch(
                mistapi.arun(stats.listSiteDevicesStats, session, site_id, type=device_type, limit=1000), []
            )

        results = await asyncio.gather(
            _safe_fetch(mistapi.arun(insights.getOrgSitesSle, session, org_id, duration="1h")),
            _device_stats_source(),
            _safe_fetch(mistapi.arun(alarms.searchSiteAlarms, session, site_id, duration="1h", limit=1000), []),
            _safe_fetch(mistapi.arun(clients.countSiteWirelessClients, session, site_id)),
            _safe_fetch(
                mistapi.arun(
                    devices.searchSiteDeviceEvents,
                    session,
                    site_id,
                    type="AP_CONFIG*,SW_CONFIG*,GW_CONFIG*",
                    duration="1h",
                    limit=1000,
                ),
                [],
            ),
            _safe_fetch(mistapi.arun(stats.searchSiteSwOrGwPorts, session, site_id, limit=1000), []),
            _safe_fetch(
                mistapi.arun(devices.searchSiteDeviceLastConfigs, session, site_id, duration="1h", limit=1000), []
            ),
            _safe_fetch(mistapi.arun(devices.listSiteDevices, session, site_id, limit=1000), []),
            _safe_fetch(mistapi.arun(setting.getSiteSettingDerived, session, site_id), {}),
            _safe_fetch(mistapi.arun(org_networks.listOrgNetworks, session, org_id, limit=1000), []),
            return_exceptions=True,
        )

        sle_overview = _safe_result(results[0])
        device_stats_raw = _safe_result(results[1], [])
        alarms_raw = _safe_result(results[2], [])
        client_counts = _safe_result(results[3])
        config_events_raw = _safe_result(results[4], [])
        port_stats_raw = _safe_result(results[5], [])
        device_configs_raw = _safe_result(results[6], [])
        devices_list_raw = _safe_result(results[7], [])
        site_setting_raw = _safe_result(results[8], {})
        org_networks_raw = _safe_result(results[9], [])

        port_stats = _normalize_results(port_stats_raw)
        alarms_list = _normalize_results(alarms_raw)
        device_stats_list = _normalize_results(device_stats_raw)

        # Build topology from the shared fetched data (avoids redundant API calls)
        gw_template_id = site_setting_raw.get("gatewaytemplate_id") if isinstance(site_setting_raw, dict) else None
        gw_template = None
        if gw_template_id:
            try:
                resp = await mistapi.arun(org_gatewaytemplates.getOrgGatewayTemplate, session, org_id, gw_template_id)
                gw_template = resp.data if resp.status_code == 200 else None
            except Exception as e:
                logger.warning("topology_gw_template_fetch_failed", error=str(e))

        raw_topo_data = RawSiteData(
            port_stats=port_stats or [],
            devices=_normalize_results(devices_list_raw) or [],
            devices_stats=device_stats_list or [],
            site_setting=site_setting_raw or {},
            alarms=alarms_list or [],
            org_networks=_normalize_results(org_networks_raw) or [],
            gateway_template=gw_template,
        )
        topo = await topology_service.build_site_topology(site_id, org_id, pre_fetched=raw_topo_data)

        return SitePollData(
            topology=topo,
            sle_overview=sle_overview,
            device_stats=device_stats_list,
            alarms=alarms_list,
            client_counts=client_counts,
            config_events=_normalize_results(config_events_raw),
            port_stats=port_stats,
            device_configs=_normalize_results(device_configs_raw),
            fetched_at=datetime.now(timezone.utc),
        )

    async def _fetch_site_specific(self, site_id: str, org_id: str) -> SitePollData:
        """Fetch only site-specific data not available from org cache.

        Used when org-level cache provides device_stats, alarms, and events.
        Only fetches: topology, SLE overview, port stats, client counts, device configs.
        """
        mist = await create_mist_service()
        session = mist.get_session()

        results = await asyncio.gather(
            topology_service.build_site_topology(site_id, org_id),
            _safe_fetch(mistapi.arun(insights.getOrgSitesSle, session, org_id, duration="1h")),
            _safe_fetch(mistapi.arun(clients.countSiteWirelessClients, session, site_id)),
            _safe_fetch(mistapi.arun(stats.searchSiteSwOrGwPorts, session, site_id, limit=1000), []),
            _safe_fetch(
                mistapi.arun(devices.searchSiteDeviceLastConfigs, session, site_id, duration="1h", limit=1000), []
            ),
            return_exceptions=True,
        )

        return SitePollData(
            topology=_safe_result(results[0]),
            sle_overview=_safe_result(results[1]),
            client_counts=_safe_result(results[2]),
            port_stats=_normalize_results(_safe_result(results[3], [])),
            device_configs=_normalize_results(_safe_result(results[4], [])),
            fetched_at=datetime.now(timezone.utc),
        )

    # ── Class methods ───────────────────────────────────────────────────────

    @classmethod
    def get_or_create(cls, site_id: str) -> SiteDataCoordinator:
        """Get existing coordinator for a site or create a new one."""
        if site_id not in cls._site_coordinators:
            cls._site_coordinators[site_id] = SiteDataCoordinator(site_id)
            logger.debug("site_coordinator_created", site_id=site_id, total=len(cls._site_coordinators))
        return cls._site_coordinators[site_id]

    @classmethod
    async def maybe_upgrade_to_org_level(cls, org_id: str) -> None:
        """When 3+ sites have active coordinators, fetch non-SLE data at org level.

        Org-level endpoints (single call covers all sites):
        - listOrgDevicesStats
        - searchOrgAlarms
        - searchOrgDeviceEvents

        NOT org-level: SLE (site-level gives better detail), topology (no org API),
        port stats, client counts (no org-level equivalent).
        """
        # Check if already fresh
        existing = cls._org_data_cache.get(org_id)
        if existing and existing.is_fresh():
            return

        active_sites = set(cls._site_coordinators.keys())
        if len(active_sites) < 3:
            return

        logger.info("upgrading_to_org_level", org_id=org_id, active_sites=len(active_sites))
        mist = await create_mist_service()
        session = mist.get_session()

        results = await asyncio.gather(
            _safe_fetch(mistapi.arun(org_stats.listOrgDevicesStats, session, org_id, limit=1000), []),
            _safe_fetch(mistapi.arun(org_alarms.searchOrgAlarms, session, org_id, duration="1h", limit=1000), []),
            _safe_fetch(
                mistapi.arun(
                    org_devices.searchOrgDeviceEvents,
                    session,
                    org_id,
                    type="AP_CONFIG*,SW_CONFIG*,GW_CONFIG*",
                    duration="1h",
                    limit=1000,
                ),
                [],
            ),
            return_exceptions=True,
        )

        cls._org_data_cache[org_id] = OrgPollData(
            device_stats=_normalize_results(_safe_result(results[0], [])),
            alarms=_normalize_results(_safe_result(results[1], [])),
            events=_normalize_results(_safe_result(results[2], [])),
            fetched_at=datetime.now(timezone.utc),
        )

    @classmethod
    def cleanup(cls, site_id: str) -> None:
        """Remove coordinator for a site when no more active sessions."""
        removed = cls._site_coordinators.pop(site_id, None)
        if removed:
            logger.debug("site_coordinator_cleaned_up", site_id=site_id, remaining=len(cls._site_coordinators))

    @classmethod
    def cleanup_all(cls) -> None:
        """Remove all coordinators and org caches. Used during shutdown."""
        cls._site_coordinators.clear()
        cls._org_data_cache.clear()
