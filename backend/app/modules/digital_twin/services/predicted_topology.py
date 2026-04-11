"""
Build a predicted SiteTopology from virtual state.

Constructs synthetic RawSiteData from the Digital Twin's resolved
virtual state, then feeds it to the existing topology builder.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.modules.impact_analysis.topology.client import RawSiteData

logger = structlog.get_logger(__name__)

StateKey = tuple[str, str | None, str | None]


def build_synthetic_raw_data(
    site_id: str,
    virtual_state: dict[StateKey, dict[str, Any]],
) -> RawSiteData:
    """Build RawSiteData from virtual state for the topology builder."""
    devices: list[dict[str, Any]] = []
    devices_stats: list[dict[str, Any]] = []
    site_setting: dict[str, Any] = {}
    org_networks: list[dict[str, Any]] = []

    for (obj_type, obj_site, _obj_id), config in virtual_state.items():
        if obj_type == "devices" and obj_site == site_id:
            devices.append(dict(config))
            devices_stats.append(dict(config))
        elif obj_type == "setting" and obj_site == site_id:
            site_setting = dict(config)
        elif obj_type == "networks":
            if obj_site == site_id or obj_site is None:
                org_networks.append(dict(config))

    return RawSiteData(
        port_stats=[],
        devices=devices,
        devices_stats=devices_stats,
        site_setting=site_setting,
        org_networks=org_networks,
    )


async def build_predicted_topology(
    site_id: str,
    org_id: str,
    virtual_state: dict[StateKey, dict[str, Any]],
):
    """Build a predicted SiteTopology from virtual state.

    Uses the existing topology builder with synthetic RawSiteData.
    Falls back to live topology if synthetic data is insufficient.
    """
    from app.modules.impact_analysis.services.topology_service import build_site_topology

    raw_data = build_synthetic_raw_data(site_id, virtual_state)

    if not raw_data.devices:
        return await build_site_topology(site_id, org_id)

    try:
        return await build_site_topology(site_id, org_id, pre_fetched=raw_data)
    except Exception as e:
        logger.warning("predicted_topology_fallback", site_id=site_id, error=str(e))
        return await build_site_topology(site_id, org_id)
