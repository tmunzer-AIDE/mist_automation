"""SLE (Service Level Experience) service for impact analysis.

Two-tier strategy:
1. Site-level SLE at every poll (per-metric getSiteSleSummaryTrend calls)
2. Device-level drill-down only when degradation detected
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any

import mistapi
import structlog
from mistapi.api.v1.sites import sle

from app.services.mist_service_factory import create_mist_service

logger = structlog.get_logger(__name__)

# SLE metrics by device type — site scope for site-wide queries, device scope for per-device queries
SLE_METRICS: dict[str, dict[str, Any]] = {
    "ap": {
        "scope": "site",
        "device_scope": "ap",
        "metrics": [
            "time-to-connect",
            "successful-connect",
            "throughput",
            "roaming",
            "capacity",
            "coverage",
            "ap-health",
        ],
    },
    "switch": {
        "scope": "site",
        "device_scope": "switch",
        "metrics": [
            "switch-throughput",
            "switch-health",
            "switch-stc",
            "switch-stc-new",
        ],
    },
    "gateway": {
        "scope": "site",
        "device_scope": "gateway",
        "metrics": ["gateway-health", "wan-link-health"],
    },
}

# Drill-down functions by device type (actual mistapi callables)
_DRILL_DOWN_FUNCTIONS: dict[str, list[tuple[Callable, str]]] = {
    "ap": [
        (sle.listSiteSleImpactedAps, "impacted-aps"),
        (sle.listSiteSleImpactedWirelessClients, "impacted-clients"),
    ],
    "switch": [
        (sle.listSiteSleImpactedSwitches, "impacted-switches"),
        (sle.listSiteSleImpactedInterfaces, "impacted-interfaces"),
        (sle.listSiteSleImpactedWiredClients, "impacted-wired-clients"),
    ],
    "gateway": [
        (sle.listSiteSleImpactedGateways, "impacted-gateways"),
        (sle.listSiteSleImpactedInterfaces, "impacted-interfaces"),
    ],
}


async def capture_baseline(
    site_id: str,
    org_id: str,
    device_type: str,
    device_id: str | None,
    before_timestamp: datetime,
    api_session: Any = None,
) -> dict[str, Any]:
    """Capture SLE baseline with 60-min history (site-level + per-device trends).

    Fetches two data points per metric, all in parallel:
    1. Site-level trend (time-series for delta comparison + chart)
    2. Per-device trend (time-series for the changed device's chart)

    This is the only SLE call that fetches independently (not via coordinator),
    because it needs historical data from before the change.
    """
    sle_config = SLE_METRICS.get(device_type)
    if not sle_config:
        logger.warning("sle_unknown_device_type", device_type=device_type)
        return {}

    if not api_session:
        mist = await create_mist_service()
        api_session = mist.get_session()
    site_scope = sle_config["scope"]
    device_scope = sle_config["device_scope"]
    metrics = sle_config["metrics"]
    end_epoch = str(int(before_timestamp.timestamp()))

    results: dict[str, Any] = {
        "scope": site_scope,
        "captured_at": before_timestamp.isoformat(),
        "device_id": device_id,
        "metrics": {},
    }

    async def _safe_sle_call(func: Any, scope: str, scope_id: str, metric: str) -> Any:
        try:
            resp = await mistapi.arun(
                func,
                api_session,
                site_id,
                scope=scope,
                scope_id=scope_id,
                metric=metric,
                duration="1h",
                end=end_epoch,
            )
            return resp.data if resp.status_code == 200 else None
        except Exception as e:
            logger.warning("sle_baseline_fetch_failed", metric=metric, scope=scope, error=str(e))
            return None

    # Build all tasks: 2 per metric (site trend + device trend)
    # getSiteSleSummary is deprecated — use getSiteSleSummaryTrend for everything
    tasks: list[tuple[str, str, Any]] = []  # (metric, label, coroutine)
    for metric in metrics:
        tasks.append((metric, "site_trend", _safe_sle_call(sle.getSiteSleSummaryTrend, site_scope, site_id, metric)))
        if device_id:
            tasks.append(
                (metric, "device_trend", _safe_sle_call(sle.getSiteSleSummaryTrend, device_scope, device_id, metric))
            )

    # Execute all in parallel
    coros = [t[2] for t in tasks]
    fetched = await asyncio.gather(*coros)

    # Assemble results by metric
    for (metric, label, _), data in zip(tasks, fetched, strict=True):
        if metric not in results["metrics"]:
            results["metrics"][metric] = {}
        if data is not None:
            results["metrics"][metric][label] = data

    # Pre-compute baseline SLE values for frontend display
    for _metric_name, metric_data in results["metrics"].items():
        val = _extract_sle_value(metric_data)
        if val is not None:
            metric_data["baseline_value"] = round(val, 1)

    return results


async def capture_snapshot(
    site_id: str,
    org_id: str,
    device_type: str,
    api_session: Any = None,
) -> dict[str, Any]:
    """Capture a single SLE snapshot during monitoring polls.

    Makes per-metric getSiteSleSummaryTrend calls (site scope only, 1h duration)
    to get current SLE data. Returns same format as baseline for consistent delta
    computation: {"metrics": {"metric_name": <trend_response>}}.
    """
    sle_config = SLE_METRICS.get(device_type)
    if not sle_config:
        return {"metrics": {}}

    if not api_session:
        mist = await create_mist_service()
        api_session = mist.get_session()
    site_scope = sle_config["scope"]
    metrics = sle_config["metrics"]

    async def _safe_call(metric: str) -> tuple[str, Any]:
        try:
            resp = await mistapi.arun(
                sle.getSiteSleSummaryTrend,
                api_session,
                site_id,
                scope=site_scope,
                scope_id=site_id,
                metric=metric,
                duration="1h",
            )
            return metric, resp.data if resp.status_code == 200 else None
        except Exception as e:
            logger.warning("sle_snapshot_fetch_failed", metric=metric, error=str(e))
            return metric, None

    fetched = await asyncio.gather(*[_safe_call(m) for m in metrics])

    result_metrics: dict[str, Any] = {}
    for metric_name, data in fetched:
        if data is not None:
            result_metrics[metric_name] = {"site_trend": data}

    return {"metrics": result_metrics}


async def drill_down_device_sle(
    site_id: str,
    org_id: str,
    degraded_metrics: list[str],
    device_type: str,
    api_session: Any = None,
) -> dict[str, Any]:
    """Drill down to device-level SLE for degraded metrics.

    Called only when compute_delta() detects degradation. Fetches impacted
    devices/clients/interfaces for each degraded metric.
    """
    sle_config = SLE_METRICS.get(device_type)
    if not sle_config:
        return {}

    scope = sle_config["scope"]
    drill_funcs = _DRILL_DOWN_FUNCTIONS.get(device_type, [])
    if not api_session:
        mist = await create_mist_service()
        api_session = mist.get_session()
    session = api_session

    results: dict[str, Any] = {}

    async def _fetch_drill_down(metric: str, func: Callable, label: str) -> tuple[str, str, Any]:
        try:
            resp = await mistapi.arun(
                func,
                session,
                site_id,
                scope=scope,
                scope_id=site_id,
                metric=metric,
                duration="1h",
            )
            return metric, label, resp.data if resp.status_code == 200 else None
        except Exception as e:
            logger.warning("sle_drill_down_failed", metric=metric, label=label, error=str(e))
            return metric, label, None

    tasks = []
    for metric in degraded_metrics:
        for func, label in drill_funcs:
            tasks.append(_fetch_drill_down(metric, func, label))

    if tasks:
        fetched = await asyncio.gather(*tasks)
        for metric_name, endpoint_name, data in fetched:
            if data is not None:
                results.setdefault(metric_name, {})[endpoint_name] = data

    return results


def compute_delta(
    baseline: dict[str, Any],
    snapshots: list[dict[str, Any]],
    threshold_percent: float = 10.0,
) -> dict[str, Any]:
    """Compare baseline SLE averages against post-change averages.

    Returns degradation summary with per-metric analysis.
    """
    empty_result: dict[str, Any] = {"metrics": [], "overall_degraded": False, "degraded_metric_names": []}

    if not baseline or not snapshots:
        return empty_result

    baseline_metrics = baseline.get("metrics", {})
    if not baseline_metrics:
        return empty_result

    metric_results: list[dict[str, Any]] = []
    degraded_names: list[str] = []

    for metric_name, baseline_data in baseline_metrics.items():
        baseline_value = _extract_sle_value(baseline_data)
        if baseline_value is None:
            continue

        # Average the metric across all post-change snapshots
        post_values: list[float] = []
        for snapshot in snapshots:
            snapshot_metrics = snapshot.get("metrics", {})
            snap_data = snapshot_metrics.get(metric_name)
            if snap_data is not None:
                val = _extract_sle_value(snap_data)
                if val is not None:
                    post_values.append(val)

        if not post_values:
            metric_results.append(
                {
                    "name": metric_name,
                    "baseline_value": baseline_value,
                    "current_value": None,
                    "change_percent": None,
                    "degraded": False,
                    "status": "no_data",
                }
            )
            continue

        current_value = sum(post_values) / len(post_values)

        # Calculate change (negative = degradation for SLE metrics where higher is better)
        if baseline_value > 0:
            change_percent = ((current_value - baseline_value) / baseline_value) * 100
        else:
            change_percent = 0.0

        degraded = change_percent < -threshold_percent

        if degraded:
            degraded_names.append(metric_name)

        metric_results.append(
            {
                "name": metric_name,
                "baseline_value": round(baseline_value, 2),
                "current_value": round(current_value, 2),
                "change_percent": round(change_percent, 2),
                "degraded": degraded,
                "status": "degraded" if degraded else "stable",
            }
        )

    return {
        "metrics": metric_results,
        "overall_degraded": len(degraded_names) > 0,
        "degraded_metric_names": degraded_names,
    }


def _extract_sle_value(data: Any) -> float | None:
    """Extract SLE success rate from API response data.

    Computes success rate as (total - degraded) / total * 100 from the
    getSiteSleSummaryTrend response. Null buckets (no data for that period)
    are skipped. Returns None if no valid data points exist.

    Handles:
    - Baseline metric dict: {"site_trend": <trend_response>, ...}
    - getSiteSleSummaryTrend response: {"sle": {"samples": {"total": [...], "degraded": [...]}}}
    """
    if data is None or not isinstance(data, dict):
        return None

    # Baseline metric structure — dig into site_trend
    if "site_trend" in data:
        return _extract_sle_value(data["site_trend"])

    # getSiteSleSummaryTrend response — compute from total/degraded
    sle_obj = data.get("sle")
    if not isinstance(sle_obj, dict):
        return None
    samples = sle_obj.get("samples")
    if not isinstance(samples, dict):
        return None

    total_arr = samples.get("total", [])
    degraded_arr = samples.get("degraded", [])

    # Pair buckets, skip where either is null/non-numeric or total is 0
    success_rates: list[float] = []
    for i in range(min(len(total_arr), len(degraded_arr))):
        t = total_arr[i]
        d = degraded_arr[i]
        if not isinstance(t, (int, float)) or not isinstance(d, (int, float)):
            continue
        if t <= 0:
            continue
        success_rates.append((t - d) / t * 100)

    if not success_rates:
        return None

    return round(sum(success_rates) / len(success_rates), 2)
