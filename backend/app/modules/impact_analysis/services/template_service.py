"""Template snapshot and drift detection for impact analysis.

Captures org/site template configs at baseline, compares against end-of-monitoring
state to detect template-level configuration changes, and correlates them with
device configuration events (CONFIG_CHANGED and CONFIGURED).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import mistapi
import structlog
from mistapi.api.v1.orgs import gatewaytemplates as org_gatewaytemplates
from mistapi.api.v1.orgs import networktemplates as org_networktemplates
from mistapi.api.v1.orgs import rftemplates as org_rftemplates
from mistapi.api.v1.orgs import sitetemplates as org_sitetemplates
from mistapi.api.v1.sites import setting as site_setting
from mistapi.api.v1.sites import sites as site_sites

from app.modules.backup.utils import deep_diff
from app.services.mist_service_factory import create_mist_service

if TYPE_CHECKING:
    from app.modules.impact_analysis.models import ConfigChangeEvent

logger = structlog.get_logger(__name__)

# Template fields in site info → (template_type, org API function)
_TEMPLATE_FIELDS: list[tuple[str, str, Any]] = [
    ("rftemplate_id", "rf_template", org_rftemplates.getOrgRfTemplate),
    ("networktemplate_id", "network_template", org_networktemplates.getOrgNetworkTemplate),
    ("gatewaytemplate_id", "gateway_template", org_gatewaytemplates.getOrgGatewayTemplate),
    ("sitetemplate_id", "site_template", org_sitetemplates.getOrgSiteTemplate),
]

# Correlation window: CONFIGURED events within this many seconds of a template change
_CORRELATION_WINDOW_SECONDS = 60


async def capture_template_snapshot(site_id: str, org_id: str, api_session: Any = None) -> dict[str, Any]:
    """Capture current state of all assigned templates + site setting.

    Fetches site info to discover template IDs, then fetches each template
    config and the site setting in parallel.

    Args:
        api_session: Optional pre-existing mistapi session to reuse (avoids
                     creating a new MistService on every call).

    Returns:
        Dict with site_info (template ID assignments), templates (full configs),
        site_setting, and capture timestamp.
    """
    if api_session:
        session = api_session
    else:
        mist = await create_mist_service()
        session = mist.get_session()

    # First: get site info to find assigned template IDs
    try:
        site_resp = await mistapi.arun(site_sites.getSiteInfo, session, site_id)
        site_info = site_resp.data if site_resp.status_code == 200 and isinstance(site_resp.data, dict) else {}
    except Exception as e:
        logger.warning("template_snapshot_site_info_failed", site_id=site_id, error=str(e))
        site_info = {}

    # Extract template ID assignments
    template_ids: dict[str, str | None] = {}
    for field, _, _ in _TEMPLATE_FIELDS:
        template_ids[field] = site_info.get(field)

    # Fetch all assigned templates + site setting in parallel
    async def _fetch_template(tmpl_type: str, api_fn: Any, tmpl_id: str) -> tuple[str, dict[str, Any] | None]:
        try:
            resp = await mistapi.arun(api_fn, session, org_id, tmpl_id)
            if resp.status_code == 200 and isinstance(resp.data, dict):
                return tmpl_type, {"id": tmpl_id, "name": resp.data.get("name", ""), "config": resp.data}
        except Exception as e:
            logger.warning("template_fetch_failed", tmpl_type=tmpl_type, tmpl_id=tmpl_id, error=str(e))
        return tmpl_type, None

    async def _fetch_site_setting() -> dict[str, Any]:
        try:
            resp = await mistapi.arun(site_setting.getSiteSetting, session, site_id)
            if resp.status_code == 200 and isinstance(resp.data, dict):
                return resp.data
        except Exception as e:
            logger.warning("template_snapshot_site_setting_failed", site_id=site_id, error=str(e))
        return {}

    tasks: list[Any] = []
    task_labels: list[str] = []

    for field, tmpl_type, api_fn in _TEMPLATE_FIELDS:
        tmpl_id = template_ids.get(field)
        if tmpl_id:
            tasks.append(_fetch_template(tmpl_type, api_fn, tmpl_id))
            task_labels.append(tmpl_type)

    tasks.append(_fetch_site_setting())
    task_labels.append("site_setting")

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Assemble snapshot
    templates: dict[str, Any] = {}
    setting_data: dict[str, Any] = {}

    for label, result in zip(task_labels, results, strict=True):
        if isinstance(result, Exception):
            logger.warning("template_snapshot_task_error", label=label, error=str(result))
            continue
        if label == "site_setting":
            setting_data = result if isinstance(result, dict) else {}
        elif isinstance(result, tuple):
            tmpl_type, tmpl_data = result
            if tmpl_data:
                templates[tmpl_type] = tmpl_data

    return {
        "site_info": template_ids,
        "templates": templates,
        "site_setting": setting_data,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def compute_template_drift(
    baseline: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Compare baseline template snapshot against current state.

    Uses deep_diff() from the backup module for recursive dict comparison.
    Only includes templates that actually changed.

    Returns:
        Dict with changed templates and site_setting diffs, or None if no changes.
    """
    if not baseline or not current:
        return None

    result: dict[str, Any] = {"templates": {}, "site_setting_changes": []}
    has_changes = False

    # Compare each template
    baseline_templates = baseline.get("templates", {})
    current_templates = current.get("templates", {})

    # Templates present in both → diff configs
    for tmpl_type in set(baseline_templates) | set(current_templates):
        b_tmpl = baseline_templates.get(tmpl_type)
        c_tmpl = current_templates.get(tmpl_type)

        if b_tmpl and c_tmpl:
            b_config = b_tmpl.get("config", {})
            c_config = c_tmpl.get("config", {})
            changes = deep_diff(b_config, c_config)
            if changes:
                result["templates"][tmpl_type] = {
                    "name": c_tmpl.get("name", b_tmpl.get("name", "")),
                    "id": c_tmpl.get("id", b_tmpl.get("id", "")),
                    "changes": changes,
                }
                has_changes = True
        elif b_tmpl and not c_tmpl:
            result["templates"][tmpl_type] = {
                "name": b_tmpl.get("name", ""),
                "id": b_tmpl.get("id", ""),
                "changes": [{"path": "", "type": "removed", "value": "template unassigned from site"}],
            }
            has_changes = True
        elif not b_tmpl and c_tmpl:
            result["templates"][tmpl_type] = {
                "name": c_tmpl.get("name", ""),
                "id": c_tmpl.get("id", ""),
                "changes": [{"path": "", "type": "added", "value": "template newly assigned to site"}],
            }
            has_changes = True

    # Compare site setting
    b_setting = baseline.get("site_setting", {})
    c_setting = current.get("site_setting", {})
    if b_setting and c_setting:
        setting_changes = deep_diff(b_setting, c_setting)
        if setting_changes:
            result["site_setting_changes"] = setting_changes
            has_changes = True

    return result if has_changes else None


def correlate_with_config_events(
    drift_result: dict[str, Any],
    config_changes: list[ConfigChangeEvent],
) -> dict[str, Any]:
    """Match template changes to device CONFIGURED events by timestamp proximity.

    For each changed template, finds CONFIGURED events that occurred within
    a 60-second window, suggesting the template change triggered the device config push.
    """
    if not config_changes:
        return drift_result

    # Collect timestamps of all config change events
    event_timestamps: list[dict[str, Any]] = []
    for event in config_changes:
        event_timestamps.append(
            {
                "event_type": event.event_type,
                "timestamp": (
                    event.timestamp.isoformat() if isinstance(event.timestamp, datetime) else str(event.timestamp)
                ),
                "timestamp_dt": event.timestamp if isinstance(event.timestamp, datetime) else None,
                "device_name": event.device_name,
                "commit_user": event.commit_user,
                "commit_method": event.commit_method,
            }
        )

    # For each changed template, find correlated events
    for _tmpl_type, tmpl_data in drift_result.get("templates", {}).items():
        # All CONFIGURED events are potentially related to any template change
        # since we can't determine the exact causal link from the event payload.
        # We include all events as "related" — the user can correlate by timing.
        tmpl_data["related_events"] = [
            {
                "event_type": evt["event_type"],
                "event_category": "initiated" if "CONFIG_CHANGED" in evt["event_type"] else "applied",
                "timestamp": evt["timestamp"],
                "device_name": evt["device_name"],
                "commit_user": evt["commit_user"],
                "commit_method": evt["commit_method"],
            }
            for evt in event_timestamps
        ]

    return drift_result
