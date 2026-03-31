from __future__ import annotations

import asyncio

import structlog

from app.services.mist_service_factory import create_mist_service

log = structlog.get_logger(__name__)


def merge_rrm_responses(responses: list[dict]) -> dict[str, list[tuple[str, int]]]:
    """Merge RRM neighbor results across bands, keeping best (highest) RSSI per pair."""
    best: dict[str, dict[str, int]] = {}
    for response in responses:
        for entry in response.get("results", []):
            ap_mac: str = entry["mac"]
            ap_best = best.setdefault(ap_mac, {})
            for nbr in entry.get("neighbors", []):
                nbr_mac: str = nbr["mac"]
                rssi: int = int(nbr["rssi"])
                ap_best[nbr_mac] = max(ap_best.get(nbr_mac, -999), rssi)
    return {ap: list(nbrs.items()) for ap, nbrs in best.items()}


async def fetch_rf_neighbor_map(site_id: str) -> dict[str, list[tuple[str, int]]]:
    """Fetch RF neighbor map from Mist RRM API, merged across 2.4/5/6 GHz bands."""
    mist = await create_mist_service()
    bands = ("24", "5", "6")
    results = await asyncio.gather(
        *[mist.api_get(f"/api/v1/sites/{site_id}/rrm/neighbors/band/{band}") for band in bands],
        return_exceptions=True,
    )
    responses = []
    for band, result in zip(bands, results, strict=True):
        if isinstance(result, Exception):
            log.warning("rrm_band_fetch_failed", site_id=site_id, band=band, error=str(result))
        else:
            responses.append(result)
    return merge_rrm_responses(responses)
