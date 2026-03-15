"""
Post-deployment validation service.

Validates a Mist site by checking template variables, AP health,
switch health (including VC and cable tests), and gateway health.
"""

import asyncio
import re
from datetime import datetime, timezone

import mistapi
import structlog
from beanie import PydanticObjectId
from mistapi.api.v1.orgs import sitegroups as org_sitegroups
from mistapi.api.v1.sites import (
    devices,
    events,
    gatewaytemplates,
    networktemplates,
    setting,
    sitetemplates,
    stats,
    wlans,
)

from app.core.websocket import ws_manager
from app.modules.reports.models import ReportJob, ReportStatus
from app.services.mist_service import MistService

logger = structlog.get_logger(__name__)

# Regex to extract Jinja2 variable names from template strings
_JINJA2_VAR_RE = re.compile(r"\{\{\s*([\w][\w.]*)\s*\}\}")


async def run_post_deployment_validation(report_id: str, site_id: str) -> None:
    """Run the full post-deployment validation for a site."""
    report = await ReportJob.get(PydanticObjectId(report_id))
    if not report:
        logger.error("report_not_found", report_id=report_id)
        return

    from app.services.mist_service_factory import create_mist_service

    try:
        mist = await create_mist_service()
        session = mist.get_session()

        report.status = ReportStatus.RUNNING
        report.update_timestamp()
        await report.save()

        result: dict = {
            "site_info": {},
            "template_variables": [],
            "aps": [],
            "switches": [],
            "gateways": [],
            "summary": {"pass": 0, "fail": 0, "warn": 0},
        }

        # Step 1: Site info & settings
        await _broadcast(report_id, "running", "site_info", "Fetching site configuration...", 0, 5)
        site_setting_resp = await mistapi.arun(setting.getSiteSetting, session, site_id)
        site_vars = site_setting_resp.data.get("vars", {}) if site_setting_resp.status_code == 200 else {}

        # Get site details
        site_data = await mist.get_site(site_id)
        report.site_name = site_data.get("name", site_id)
        await report.save()

        site_address = site_data.get("address", "")
        sitegroup_ids = site_data.get("sitegroup_ids", [])
        sitegroup_names = await _resolve_sitegroup_names(session, mist.org_id, sitegroup_ids)

        # Step 2: Fetch templates + build site info
        await _broadcast(report_id, "running", "templates", "Checking templates and WLANs...", 1, 5)
        templates_raw, template_names = await _fetch_all_templates(session, site_id)
        wlan_info = await _fetch_wlan_info(session, site_id)
        result["site_info"] = {
            "site_name": report.site_name,
            "site_address": site_address,
            "site_groups": sitegroup_names,
            "templates": template_names,
            "org_wlans": wlan_info["org_wlans"],
            "site_wlans": wlan_info["site_wlans"],
        }

        # Step 3: Template variable validation (reuse fetched data)
        result["template_variables"] = _validate_template_variables(templates_raw, wlan_info["all_wlans_raw"], site_vars)

        # Step 4: Fetch config events for all device types
        await _broadcast(report_id, "running", "config_events", "Fetching device configuration events...", 2, 5)
        config_events = await _fetch_config_events(session, site_id)

        # Step 5a: AP validation
        await _broadcast(report_id, "running", "aps", "Validating access points...", 3, 5)
        result["aps"] = await _validate_aps(session, site_id, config_events)

        # Step 5b: Switch validation (with cable tests)
        await _broadcast(report_id, "running", "switches", "Validating switches...", 3, 5)
        result["switches"] = await _validate_switches(session, mist, site_id, report_id, config_events)

        # Step 5c: Gateway validation
        await _broadcast(report_id, "running", "gateways", "Validating gateways...", 4, 5)
        result["gateways"] = await _validate_gateways(session, site_id, config_events)

        # Compute summary
        result["summary"] = _compute_summary(result)

        # Save results
        report.result = result
        report.status = ReportStatus.COMPLETED
        report.completed_at = datetime.now(timezone.utc)
        report.update_timestamp()
        await report.save()

        await ws_manager.broadcast(
            f"report:{report_id}",
            {"type": "report_complete", "data": {"status": "completed", "report_id": report_id}},
        )
        logger.info("validation_report_completed", report_id=report_id, site_id=site_id)

    except Exception as e:
        logger.error("validation_report_failed", report_id=report_id, error=str(e), exc_info=True)
        report.status = ReportStatus.FAILED
        report.error = str(e)
        report.update_timestamp()
        await report.save()

        await ws_manager.broadcast(
            f"report:{report_id}",
            {"type": "report_complete", "data": {"status": "failed", "report_id": report_id, "error": str(e)}},
        )


# ── Helpers ──────────────────────────────────────────────────────────────


async def _broadcast(
    report_id: str, status: str, step: str, message: str, completed: int, total: int
) -> None:
    await ws_manager.broadcast(
        f"report:{report_id}",
        {
            "type": "report_progress",
            "data": {
                "status": status,
                "step": step,
                "message": message,
                "completed": completed,
                "total": total,
            },
        },
    )


def _extract_jinja2_vars(data: object) -> set[str]:
    """Recursively scan all string values in a data structure for Jinja2 variables."""
    found: set[str] = set()
    if isinstance(data, str):
        found.update(_JINJA2_VAR_RE.findall(data))
    elif isinstance(data, dict):
        for v in data.values():
            found.update(_extract_jinja2_vars(v))
    elif isinstance(data, list):
        for item in data:
            found.update(_extract_jinja2_vars(item))
    return found


# ── Site group resolution ────────────────────────────────────────────────


async def _resolve_sitegroup_names(session, org_id: str, sitegroup_ids: list[str]) -> list[str]:
    """Resolve site group UUIDs to names by fetching all org site groups."""
    if not sitegroup_ids:
        return []
    try:
        resp = await mistapi.arun(org_sitegroups.listOrgSiteGroups, session, org_id, limit=1000)
        if resp.status_code != 200:
            return [gid[:8] for gid in sitegroup_ids]
        id_to_name = {g["id"]: g.get("name", g["id"][:8]) for g in resp.data if isinstance(g, dict)}
        return [id_to_name.get(gid, gid[:8]) for gid in sitegroup_ids]
    except Exception as e:
        logger.warning("sitegroup_resolve_error", error=str(e))
        return [gid[:8] for gid in sitegroup_ids]


# ── Template & WLAN fetching ─────────────────────────────────────────────


_TEMPLATE_SOURCES = [
    ("site_template", sitetemplates.listSiteSiteTemplatesDerived, {"resolve": True}),
    ("network_template", networktemplates.listSiteNetworkTemplatesDerived, {}),
    ("gateway_template", gatewaytemplates.listSiteGatewayTemplatesDerived, {}),
]


async def _fetch_all_templates(session, site_id: str) -> tuple[list[tuple[str, list[dict]]], list[dict]]:
    """Fetch all derived templates and return (raw_data_per_type, template_names_list).

    Returns:
        raw: list of (template_type, [template_dicts]) for variable scanning
        names: list of {"type": ..., "name": ...} for the site_info section
    """
    raw: list[tuple[str, list[dict]]] = []
    names: list[dict] = []

    for template_type, api_fn, extra_kwargs in _TEMPLATE_SOURCES:
        try:
            resp = await mistapi.arun(api_fn, session, site_id, **extra_kwargs)
            if resp.status_code != 200:
                logger.warning("template_fetch_failed", template_type=template_type, status=resp.status_code)
                continue

            templates_data = resp.data if isinstance(resp.data, list) else [resp.data]
            valid = [t for t in templates_data if isinstance(t, dict)]
            raw.append((template_type, valid))

            for tmpl in valid:
                tmpl_name = tmpl.get("name", template_type)
                names.append({"type": template_type, "name": tmpl_name})
        except Exception as e:
            logger.warning("template_fetch_error", template_type=template_type, error=str(e))

    return raw, names


async def _fetch_wlan_info(session, site_id: str) -> dict:
    """Fetch derived WLANs and split into org WLANs (from templates) and site WLANs.

    Returns dict with keys: org_wlans, site_wlans, all_wlans_raw.
    """
    org_wlans: list[dict] = []
    site_wlans: list[dict] = []
    all_raw: list[dict] = []

    try:
        resp = await mistapi.arun(wlans.listSiteWlansDerived, session, site_id, resolve=True)
        if resp.status_code == 200:
            all_raw = resp.data if isinstance(resp.data, list) else [resp.data]
            for w in all_raw:
                if not isinstance(w, dict):
                    continue
                ssid = w.get("ssid", w.get("name", ""))
                if w.get("template_id"):
                    org_wlans.append({"ssid": ssid, "template_id": w["template_id"]})
                else:
                    site_wlans.append({"ssid": ssid})
    except Exception as e:
        logger.warning("wlan_fetch_error", error=str(e))

    return {"org_wlans": org_wlans, "site_wlans": site_wlans, "all_wlans_raw": all_raw}


def _validate_template_variables(
    templates_raw: list[tuple[str, list[dict]]],
    wlans_raw: list[dict],
    site_vars: dict,
) -> list[dict]:
    """Check that Jinja2 variables found in templates are defined in site vars."""
    results: list[dict] = []
    var_keys = set(site_vars.keys()) if site_vars else set()

    # Scan non-WLAN templates
    for template_type, template_list in templates_raw:
        for tmpl in template_list:
            tmpl_name = tmpl.get("name", template_type)
            for var_name in sorted(_extract_jinja2_vars(tmpl)):
                root_var = var_name.split(".")[0]
                defined = root_var in var_keys
                results.append({
                    "template_type": template_type,
                    "template_name": tmpl_name,
                    "variable": var_name,
                    "defined": defined,
                    "status": "pass" if defined else "fail",
                })

    # Scan WLANs
    for w in wlans_raw:
        if not isinstance(w, dict):
            continue
        wlan_name = w.get("ssid", w.get("name", "wlan"))
        for var_name in sorted(_extract_jinja2_vars(w)):
            root_var = var_name.split(".")[0]
            defined = root_var in var_keys
            results.append({
                "template_type": "wlan",
                "template_name": wlan_name,
                "variable": var_name,
                "defined": defined,
                "status": "pass" if defined else "fail",
            })

    return results


# ── Config events ────────────────────────────────────────────────────────

_CONFIG_EVENT_PREFIXES = ("AP_CONFIG", "SW_CONFIG", "GW_CONFIG")


async def _fetch_config_events(session, site_id: str) -> dict[str, dict]:
    """Fetch recent system events and return the latest config event per device MAC.

    Returns:
        dict mapping device MAC → {"type": event_type, "timestamp": ..., "status": "pass"|"fail"}
    """
    latest_by_mac: dict[str, dict] = {}

    try:
        resp = await mistapi.arun(events.searchSiteSystemEvents, session, site_id, limit=1000)
        if resp.status_code != 200:
            logger.warning("config_events_fetch_failed", status=resp.status_code)
            return latest_by_mac

        all_events = resp.data.get("results", resp.data) if isinstance(resp.data, dict) else resp.data
        if not isinstance(all_events, list):
            return latest_by_mac

        for ev in all_events:
            if not isinstance(ev, dict):
                continue
            ev_type = ev.get("type", "")
            if not any(ev_type.startswith(prefix) for prefix in _CONFIG_EVENT_PREFIXES):
                continue

            mac = ev.get("mac", "")
            if not mac:
                continue

            timestamp = ev.get("timestamp", 0)
            existing = latest_by_mac.get(mac)
            if existing and existing["timestamp"] >= timestamp:
                continue

            is_success = "CONFIGURED" in ev_type and "FAILED" not in ev_type
            latest_by_mac[mac] = {
                "type": ev_type,
                "timestamp": timestamp,
                "status": "pass" if is_success else "fail",
            }
    except Exception as e:
        logger.warning("config_events_fetch_error", error=str(e))

    return latest_by_mac


def _add_config_status_check(checks: list[dict], mac: str, config_events: dict[str, dict]) -> None:
    """Append a config_status check to the checks list based on the device's latest config event."""
    event = config_events.get(mac)
    if event:
        checks.append({
            "check": "config_status",
            "status": event["status"],
            "value": event["type"],
        })
    else:
        checks.append({
            "check": "config_status",
            "status": "info",
            "value": "No config event found",
        })


# ── AP validation ────────────────────────────────────────────────────────


async def _validate_aps(session, site_id: str, config_events: dict[str, dict]) -> list[dict]:
    """Validate all APs at the site."""
    resp = await mistapi.arun(stats.listSiteDevicesStats, session, site_id, type="ap", limit=1000)
    if resp.status_code != 200:
        logger.warning("ap_stats_fetch_failed", status=resp.status_code)
        return []

    results: list[dict] = []
    for ap in resp.data:
        checks: list[dict] = []
        mac = ap.get("mac", "")

        # Name check
        name = ap.get("name", "")
        has_name = bool(name and name.strip())
        checks.append({"check": "name_defined", "status": "pass" if has_name else "fail", "value": name or "(not set)"})

        # Firmware version
        firmware = ap.get("version", ap.get("fw_version", ""))
        checks.append({"check": "firmware_version", "status": "info", "value": firmware or "unknown"})

        # Eth0 port speed
        port_stat = ap.get("port_stat", {})
        eth0 = port_stat.get("eth0", {})
        eth0_speed = eth0.get("speed", 0)
        speed_status = "pass" if eth0_speed >= 1000 else "warn"
        checks.append({"check": "eth0_port_speed", "status": speed_status, "value": f"{eth0_speed} Mbps"})

        # Connection status
        ap_status = ap.get("status", "unknown")
        status_ok = ap_status == "connected"
        checks.append({"check": "connection_status", "status": "pass" if status_ok else "fail", "value": ap_status})

        # Config status
        _add_config_status_check(checks, mac, config_events)

        results.append(
            {
                "device_id": ap.get("id", ""),
                "name": name or "(unnamed)",
                "mac": mac,
                "model": ap.get("model", ""),
                "checks": checks,
            }
        )

    return results


# ── Switch validation ────────────────────────────────────────────────────


# Physical copper interface prefixes eligible for cable tests
_COPPER_PORT_PREFIXES = ("ge-", "mge-", "nge-")


def _is_copper_port(port_id: str) -> bool:
    """Check if a port ID is a physical copper Ethernet interface."""
    return port_id.startswith(_COPPER_PORT_PREFIXES)


async def _fetch_switch_up_ports(session, site_id: str) -> dict[str, list[str]]:
    """Fetch UP copper ports for all switches using the dedicated port search API.

    Only includes physical copper interfaces (ge-*, mge-*, nge-*) suitable for cable tests.
    Returns a dict mapping device MAC → list of UP port IDs.
    """
    ports_by_mac: dict[str, list[str]] = {}
    try:
        resp = await mistapi.arun(
            stats.searchSiteSwOrGwPorts, session, site_id,
            device_type="switch", up=True, limit=1000,
        )
        if resp.status_code != 200:
            logger.warning("switch_ports_fetch_failed", status=resp.status_code)
            return ports_by_mac

        results = resp.data.get("results", resp.data) if isinstance(resp.data, dict) else resp.data
        if not isinstance(results, list):
            return ports_by_mac

        for port in results:
            if not isinstance(port, dict):
                continue
            device_mac = port.get("mac", "")
            port_id = port.get("port_id", "")
            if device_mac and port_id and _is_copper_port(port_id):
                ports_by_mac.setdefault(device_mac, []).append(port_id)
    except Exception as e:
        logger.warning("switch_ports_fetch_error", error=str(e))

    return ports_by_mac


async def _validate_switches(
    session, mist: MistService, site_id: str, report_id: str, config_events: dict[str, dict]
) -> list[dict]:
    """Validate all switches, including VC and cable tests (parallelized per switch)."""
    resp = await mistapi.arun(stats.listSiteDevicesStats, session, site_id, type="switch", limit=1000)
    if resp.status_code != 200:
        logger.warning("switch_stats_fetch_failed", status=resp.status_code)
        return []

    switches = resp.data

    # Fetch UP ports from dedicated port search API (more reliable than port_stat)
    up_ports_by_mac = await _fetch_switch_up_ports(session, site_id)

    async def validate_one_switch(sw: dict) -> dict:
        sw_mac = sw.get("mac", "")
        sw_up_ports = up_ports_by_mac.get(sw_mac, [])
        return await _validate_single_switch(session, site_id, sw, report_id, config_events, sw_up_ports)

    results = await asyncio.gather(*[validate_one_switch(sw) for sw in switches])
    return list(results)


async def _validate_single_switch(
    session, site_id: str, sw: dict, report_id: str,
    config_events: dict[str, dict], up_ports: list[str],
) -> dict:
    """Validate a single switch: name, firmware, status, VC, cable tests."""
    checks: list[dict] = []
    device_id = sw.get("id", "")
    name = sw.get("name", "")
    mac = sw.get("mac", "")

    # Name check
    has_name = bool(name and name.strip())
    checks.append({"check": "name_defined", "status": "pass" if has_name else "fail", "value": name or "(not set)"})

    # Firmware version
    firmware = sw.get("version", sw.get("fw_version", ""))
    checks.append({"check": "firmware_version", "status": "info", "value": firmware or "unknown"})

    # Connection status
    sw_status = sw.get("status", "unknown")
    status_ok = sw_status == "connected"
    checks.append({"check": "connection_status", "status": "pass" if status_ok else "fail", "value": sw_status})

    # Config status
    _add_config_status_check(checks, mac, config_events)

    # Virtual chassis check
    vc_result = None
    if sw.get("vc_mac") or sw.get("module_stat"):
        vc_result = await _check_virtual_chassis(session, site_id, device_id, firmware)

    # Cable tests on UP ports (from searchSiteSwOrGwPorts API)
    cable_tests: list[dict] = []
    total_ports = len(up_ports)
    for idx, port_id in enumerate(up_ports):
        await _broadcast(
            report_id,
            "running",
            "switches",
            f"Switch {name or device_id[:8]}: testing port {port_id} ({idx + 1}/{total_ports})",
            idx + 1,
            total_ports,
        )
        test_result = await _run_cable_test(session, site_id, device_id, port_id)
        cable_tests.append(test_result)

    return {
        "device_id": device_id,
        "name": name or "(unnamed)",
        "mac": mac,
        "model": sw.get("model", ""),
        "checks": checks,
        "virtual_chassis": vc_result,
        "cable_tests": cable_tests,
    }


async def _check_virtual_chassis(session, site_id: str, device_id: str, expected_firmware: str) -> dict:
    """Check virtual chassis members for firmware consistency, VC ports, and presence.

    The Mist VC API returns a dict with a ``members`` list. Each member has:
    - ``mac``: device MAC
    - ``model``: device model
    - ``vc_role``: "master" / "backup" / "linecard"
    - ``vc_ports``: list of VC port dicts, each with ``up`` (bool)
    - ``version`` or ``fw_version``: firmware version
    - ``status``: "not-present" / "present" / etc. (may be absent if device is connected)
    - ``serial``: serial number
    - ``member``: member index (0, 1, 2, ...)
    """
    try:
        resp = await mistapi.arun(devices.getSiteDeviceVirtualChassis, session, site_id, device_id)
        if resp.status_code != 200:
            return {"status": "error", "message": f"Failed to fetch VC info: {resp.status_code}", "members": []}

        vc_data = resp.data
        logger.debug("vc_raw_data", device_id=device_id, data=vc_data)

        # The VC response can be a dict with "members" key, or the data might be nested differently
        if isinstance(vc_data, dict):
            members_raw = vc_data.get("members", [])
        elif isinstance(vc_data, list):
            members_raw = vc_data
        else:
            return {"status": "error", "message": "Unexpected VC data format", "members": []}

        members: list[dict] = []
        for member in members_raw:
            if not isinstance(member, dict):
                continue

            member_fw = member.get("version", member.get("fw_version", ""))

            # VC ports: list of dicts with "up" boolean
            vc_ports = member.get("vc_ports", [])
            if isinstance(vc_ports, list):
                vc_ports_up = sum(
                    1 for p in vc_ports
                    if isinstance(p, dict) and (p.get("up") is True or p.get("status") == "up")
                )
            else:
                vc_ports_up = 0

            # Member status: "not-present", "present", or absent (means connected)
            member_status = member.get("status", "")
            vc_role = member.get("vc_role", "")
            # A member is present if status is NOT "not-present",
            # or if it has a vc_role assigned (master/backup/linecard)
            is_present = member_status != "not-present" and (member_status or vc_role)

            # Display status: prefer vc_role if available, fall back to status field
            display_status = vc_role or member_status or "unknown"

            member_checks: list[dict] = []
            # Firmware consistency
            fw_match = bool(member_fw and member_fw == expected_firmware)
            member_checks.append({
                "check": "firmware_match",
                "status": "pass" if fw_match else ("fail" if member_fw else "info"),
                "value": member_fw or "unknown",
                "expected": expected_firmware,
            })
            # VC ports UP (need 2)
            member_checks.append({
                "check": "vc_ports_up",
                "status": "pass" if vc_ports_up >= 2 else "fail",
                "value": vc_ports_up,
                "expected": 2,
            })
            # Presence
            member_checks.append({
                "check": "member_present",
                "status": "pass" if is_present else "fail",
                "value": display_status,
            })

            members.append({
                "member_id": member.get("member", member.get("member_id", "")),
                "mac": member.get("mac", ""),
                "serial": member.get("serial", ""),
                "model": member.get("model", ""),
                "firmware": member_fw,
                "status": display_status,
                "vc_ports_up": vc_ports_up,
                "checks": member_checks,
            })

        return {"status": "checked", "members": members}

    except Exception as e:
        logger.warning("vc_check_failed", device_id=device_id, error=str(e))
        return {"status": "error", "message": str(e), "members": []}


async def _run_cable_test(session, site_id: str, device_id: str, port_id: str) -> dict:
    """Run a cable test on a single switch port using mistapi device_utils.

    Uses mistapi.device_utils.ex.cableTest which triggers the test and
    listens on a WebSocket for the results.
    """
    try:
        from mistapi.device_utils.ex import cableTest

        # cableTest is synchronous/threaded — run in a thread to avoid blocking the event loop
        util_response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: cableTest(session, site_id, device_id, port_id, timeout=15).wait(timeout=20),
        )

        # Check trigger response
        trigger_resp = util_response.trigger_api_response
        if trigger_resp and trigger_resp.status_code not in (200, 201):
            return {
                "port": port_id,
                "status": "error",
                "message": f"Trigger API returned {trigger_resp.status_code}",
                "pairs": [],
            }

        # Use ws_raw_events (unprocessed) instead of ws_data (VT100-processed)
        # to avoid data loss from screen buffer rendering
        raw_events = util_response.ws_raw_events or []
        raw_texts = _extract_raw_texts(raw_events)
        logger.info("cable_test_raw", device_id=device_id, port=port_id, message_count=len(raw_texts))

        result = _parse_cable_test_results(port_id, raw_texts)
        logger.info("cable_test_parsed", device_id=device_id, port=port_id, status=result["status"], pairs=result["pairs"])
        return result

    except Exception as e:
        logger.warning("cable_test_failed", device_id=device_id, port=port_id, error=str(e))
        return {"port": port_id, "status": "error", "message": str(e), "pairs": []}


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[()][A-B0-2]")


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _extract_raw_texts(raw_events: list) -> list[str]:
    """Extract raw text from WebSocket raw events, stripping ANSI escape sequences.

    Raw events can be dicts (with nested 'data' and 'raw' keys) or strings.
    """
    texts: list[str] = []
    for event in raw_events:
        raw_str = _dig_raw(event)
        if raw_str and isinstance(raw_str, str):
            cleaned = _ANSI_RE.sub("", raw_str)
            cleaned = _CONTROL_CHAR_RE.sub("", cleaned)  # strip backspace, null, etc.
            cleaned = cleaned.replace("\r", "")
            if cleaned:
                texts.append(cleaned)
    return texts


def _dig_raw(obj) -> str | None:
    """Recursively dig into a WS event to find the 'raw' text field."""
    import json as _json

    if isinstance(obj, str):
        try:
            obj = _json.loads(obj)
        except (ValueError, TypeError):
            return obj  # plain text message

    if isinstance(obj, dict):
        if "raw" in obj:
            return obj["raw"]
        if "data" in obj:
            return _dig_raw(obj["data"])
    return None


def _parse_cable_test_results(port_id: str, raw_messages: list) -> dict:
    """Parse cable test results from WebSocket raw messages.

    The raw messages are already-extracted terminal text strings from
    _extract_raw_texts. They are NOT line-aligned — each message is an
    arbitrary chunk of the terminal output stream. We concatenate them
    directly (NO separator) since the text already contains newlines.
    """
    # Direct concatenation — the terminal output already has \n at line boundaries.
    # Adding extra \n between chunks would SPLIT logical lines that span chunk boundaries.
    full_text = "".join(msg for msg in raw_messages if isinstance(msg, str))

    if not full_text.strip():
        return {"port": port_id, "status": "info", "pairs": [], "raw": [str(m) for m in raw_messages]}

    return _parse_junos_tdr_output(port_id, full_text, raw_messages)


def _build_cable_result_from_pairs(port_id: str, pairs: list) -> dict:
    """Build cable test result from structured JSON pairs data."""
    _PASS_STATUSES = {"ok", "pass", "normal", "OK", "Normal", "Passed"}
    pair_results: list[dict] = []
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        pair_status = pair.get("status", "unknown")
        pair_results.append({
            "pair": pair.get("pair", pair.get("index", pair.get("name", ""))),
            "status": pair_status,
            "length": pair.get("length", ""),
        })
    overall = "pass" if all(p["status"] in _PASS_STATUSES for p in pair_results) else "fail"
    return {"port": port_id, "status": overall, "pairs": pair_results}


# Regexes for Junos TDR output parsing
_TDR_TEST_STATUS_RE = re.compile(r"Test\s+status\s*:\s*(.+)", re.IGNORECASE)
_TDR_MDI_PAIR_RE = re.compile(r"MDI\s+pair\s*:\s*(\S+)", re.IGNORECASE)
_TDR_CABLE_STATUS_RE = re.compile(r"Cable\s+status\s*:\s*(.+)", re.IGNORECASE)
_TDR_CABLE_LENGTH_RE = re.compile(r"Cable\s+length.*?:\s*(\d+)\s*[Mm]eters?", re.IGNORECASE)

_TDR_PASS_STATUSES = {"Normal", "normal", "OK", "ok", "Passed", "passed"}


def _parse_junos_tdr_output(port_id: str, text: str, raw_messages: list) -> dict:
    """Parse Junos TDR (Time Domain Reflectometry) cable test output.

    The WebSocket delivers multiple messages for the same port. The first
    message typically has just ``Test status : Test successfully executed``
    and the second contains the full ``Interface TDR detail`` block with
    MDI pair data. We split by ``Interface name`` and pick the **richest**
    block for our port (the one with MDI pair data).

    Example format::

        Interface TDR detail:
        Interface name                  : ge-0/0/6
        Test status                     : Passed
        Link status                     :  UP
        MDI pair                        : 1-2
          Cable status                  : Normal
          Cable length/Distance To Fault: 0 Meters
        MDI pair                        : 3-6
          Cable status                  : Normal
          Cable length/Distance To Fault: 0 Meters
    """
    # Split by "Interface name" to isolate per-interface blocks.
    # Pick the LAST block for our port — it's the one with detailed results.
    blocks = re.split(r"(?=Interface name\s*:)", text)
    target_block = ""
    for block in blocks:
        if port_id in block:
            target_block = block  # keep overwriting — last match wins

    # If no specific block found, use the full text
    if not target_block:
        target_block = text

    # Parse test status
    test_status_match = _TDR_TEST_STATUS_RE.search(target_block)
    test_status = test_status_match.group(1).strip() if test_status_match else ""

    # Strip any remaining ANSI escape sequences
    target_block = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", target_block)

    # Parse MDI pairs — each pair is followed by Cable status and Cable length lines
    pair_results: list[dict] = []
    current_pair = ""
    current_status = ""
    current_length = ""

    for line in target_block.splitlines():
        line_stripped = line.strip().strip("\r\x00")

        pair_match = _TDR_MDI_PAIR_RE.search(line_stripped)
        if pair_match:
            # Save previous pair if any
            if current_pair:
                pair_results.append({"pair": current_pair, "status": current_status, "length": current_length})
            current_pair = pair_match.group(1)
            current_status = ""
            current_length = ""
            continue

        status_match = _TDR_CABLE_STATUS_RE.search(line_stripped)
        if status_match and current_pair:
            current_status = status_match.group(1).strip()
            continue

        length_match = _TDR_CABLE_LENGTH_RE.search(line_stripped)
        if length_match and current_pair:
            current_length = f"{length_match.group(1)}m"
            continue

    # Don't forget the last pair
    if current_pair:
        pair_results.append({"pair": current_pair, "status": current_status, "length": current_length})

    # Determine overall status
    if pair_results:
        overall = "pass" if all(p["status"] in _TDR_PASS_STATUSES for p in pair_results) else "fail"
    elif test_status:
        overall = "pass" if test_status.startswith("Test successfully") or test_status == "Passed" else "fail"
    else:
        overall = "info"

    return {
        "port": port_id,
        "status": overall,
        "pairs": pair_results,
        "raw": [str(m) for m in raw_messages] if not pair_results else [],
    }


# ── Gateway validation ───────────────────────────────────────────────────


async def _validate_gateways(session, site_id: str, config_events: dict[str, dict]) -> list[dict]:
    """Validate all gateways at the site."""
    resp = await mistapi.arun(stats.listSiteDevicesStats, session, site_id, type="gateway", limit=1000)
    if resp.status_code != 200:
        logger.warning("gateway_stats_fetch_failed", status=resp.status_code)
        return []

    results: list[dict] = []
    for gw in resp.data:
        checks: list[dict] = []

        # Name check
        name = gw.get("name", "")
        has_name = bool(name and name.strip())
        checks.append({"check": "name_defined", "status": "pass" if has_name else "fail", "value": name or "(not set)"})

        # Firmware version
        firmware = gw.get("version", gw.get("fw_version", ""))
        checks.append({"check": "firmware_version", "status": "info", "value": firmware or "unknown"})

        # Connection status
        gw_status = gw.get("status", "unknown")
        status_ok = gw_status == "connected"
        checks.append({"check": "connection_status", "status": "pass" if status_ok else "fail", "value": gw_status})

        # Config status
        mac = gw.get("mac", "")
        _add_config_status_check(checks, mac, config_events)

        # Port status — report all ports from gateway stats
        # Gateway port_stat may be absent from device stats; use port search API as fallback
        all_ports: list[dict] = []
        port_stat = gw.get("port_stat", {})
        logger.debug("gateway_port_stat", device_id=gw.get("id", ""), port_stat_keys=list(port_stat.keys()) if isinstance(port_stat, dict) else "not_a_dict")

        if isinstance(port_stat, dict) and port_stat:
            for port_id, pdata in port_stat.items():
                if not isinstance(pdata, dict):
                    continue
                port_up = pdata.get("up", False)
                port_usage = pdata.get("port_usage", "")
                all_ports.append({
                    "port": port_id,
                    "up": port_up,
                    "speed": pdata.get("speed", 0),
                    "full_duplex": pdata.get("full_duplex", False),
                    "port_usage": port_usage,
                })
        else:
            # Fallback: fetch ports from the port search API
            try:
                port_resp = await mistapi.arun(
                    stats.searchSiteSwOrGwPorts, session, site_id,
                    device_type="gateway", mac=mac, limit=100,
                )
                if port_resp.status_code == 200:
                    port_results = port_resp.data.get("results", port_resp.data) if isinstance(port_resp.data, dict) else port_resp.data
                    if isinstance(port_results, list):
                        for p in port_results:
                            if not isinstance(p, dict):
                                continue
                            all_ports.append({
                                "port": p.get("port_id", ""),
                                "up": p.get("up", False),
                                "speed": p.get("speed", 0),
                                "full_duplex": p.get("full_duplex", False),
                                "port_usage": p.get("port_usage", ""),
                            })
            except Exception as e:
                logger.warning("gateway_port_search_failed", mac=mac, error=str(e))

        port_count_up = sum(1 for p in all_ports if p["up"])
        port_status = "pass" if all_ports and all(p["up"] for p in all_ports) else "fail" if all_ports else "info"
        checks.append({
            "check": "wan_port_status",
            "status": port_status,
            "value": f"{port_count_up}/{len(all_ports)} UP",
            "ports": all_ports,
        })

        results.append(
            {
                "device_id": gw.get("id", ""),
                "name": name or "(unnamed)",
                "mac": gw.get("mac", ""),
                "model": gw.get("model", ""),
                "checks": checks,
            }
        )

    return results


# ── Summary ──────────────────────────────────────────────────────────────


def _compute_summary(result: dict) -> dict:
    """Compute pass/fail/warn counts from all checks."""
    counts = {"pass": 0, "fail": 0, "warn": 0, "info": 0}

    # Template variables
    for item in result.get("template_variables", []):
        s = item.get("status", "info")
        if s in counts:
            counts[s] += 1

    # Device checks (APs, switches, gateways)
    for device_type in ("aps", "switches", "gateways"):
        for device in result.get(device_type, []):
            for check in device.get("checks", []):
                s = check.get("status", "info")
                if s in counts:
                    counts[s] += 1
            # VC member checks
            vc = device.get("virtual_chassis")
            if vc and isinstance(vc, dict):
                for member in vc.get("members", []):
                    for check in member.get("checks", []):
                        s = check.get("status", "info")
                        if s in counts:
                            counts[s] += 1
            # Cable test results
            for ct in device.get("cable_tests", []):
                s = ct.get("status", "info")
                if s in counts:
                    counts[s] += 1

    return counts
