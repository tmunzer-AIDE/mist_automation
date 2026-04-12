#!/usr/bin/env python3
"""Seed Digital Twin simulation sessions for UI table population.

This script creates simulation-only sessions (no approve/execute) with a mix of
single-change and multi-change writes.

The script connects to the app MCP server over streamable HTTP using FastMCP.
Pass the MCP URL and an Authorization bearer token via flags or env vars.

Run from backend directory:
    .venv/bin/python scripts/seed_digital_twin_simulations.py --mcp-url http://localhost:8000/mcp/ --auth-token <TOKEN>

Examples:
  .venv/bin/python scripts/seed_digital_twin_simulations.py --list-scenarios
        .venv/bin/python scripts/seed_digital_twin_simulations.py --mcp-url http://localhost:8000/mcp/ --auth-token <TOKEN>
        .venv/bin/python scripts/seed_digital_twin_simulations.py --only single-switch-safe,multi-risky --mcp-url http://localhost:8000/mcp/ --auth-token <TOKEN>

Environment variable alternatives:
    MCP_SERVER_URL
    MCP_AUTH_TOKEN
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _ensure_python_runtime() -> None:
    """Relaunch with backend .venv Python when available.

    This keeps the script easy to run via `python3 ...` while still using the
    project's pinned dependencies.
    """
    candidates = [
        BACKEND_ROOT / ".venv" / "bin" / "python",
        BACKEND_ROOT.parent / ".venv" / "bin" / "python",
    ]

    for venv_python in candidates:
        if not venv_python.exists():
            continue

        venv_root = venv_python.parent.parent.resolve()
        in_target_venv = Path(sys.prefix).resolve() == venv_root

        if not in_target_venv:
            print(f"[INFO] Re-running with virtualenv interpreter: {venv_python}")
            os.execv(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]])


def _resolve_required_value(cli_value: str | None, env_var: str, cli_flag: str) -> str:
    value = (cli_value or os.environ.get(env_var) or "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required value. Provide {cli_flag} or set {env_var}."
        )
    return value


def _normalize_mcp_url(raw_url: str) -> str:
    """Normalize MCP URL so mounted /mcp endpoint resolves to streamable /mcp/."""
    parts = urlsplit(raw_url.strip())
    path = parts.path or "/"
    if path.endswith("/mcp"):
        path = f"{path}/"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


DEFAULT_ORG_ID = "8aa21779-1178-4357-b3e0-42c02b93b870"
DEFAULT_SITE_ID = "173aca52-a2c2-4416-8c34-21570e01c458"

# Known current objects from this environment
DEFAULT_SWITCH_A_ID = "00000000-0000-0000-1000-485a0dea2e00"  # US-NY-SWA-01
DEFAULT_SWITCH_B_ID = "00000000-0000-0000-1000-02000368871b"  # US-NY-SWC-01
DEFAULT_GATEWAY_ID = "00000000-0000-0000-1000-409ea4d5afdc"  # SRX320


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    tool_args: dict[str, Any]
    suite: str = "seed"


def _switch_update_payload(usage: str) -> dict[str, Any]:
    return {
        "type": "switch",
        "port_config": {
            "ge-0/0/8": {
                "usage": usage,
                "dynamic_usage": None,
                "critical": False,
                "description": "",
                "no_local_overwrite": True,
            }
        },
    }


def _single_site_device_update_args(
    org_id: str,
    site_id: str,
    switch_id: str,
    usage: str,
) -> dict[str, Any]:
    return {
        "action": "simulate",
        "action_type": "update",
        "org_id": org_id,
        "site_id": site_id,
        "object_type": "site_devices",
        "object_id": switch_id,
        "payload": _switch_update_payload(usage),
    }


def _single_site_info_rename_args(org_id: str, site_id: str, suffix: str) -> dict[str, Any]:
    return {
        "action": "simulate",
        "action_type": "update",
        "org_id": org_id,
        "site_id": site_id,
        "object_type": "site_info",
        "payload": {
            "name": f"DT-Seed-{suffix}",
        },
    }


def _single_site_info_template_bind_args(org_id: str, site_id: str) -> dict[str, Any]:
    # Mirrors the valid singleton site_info update from MCP input validation tests.
    return {
        "action": "simulate",
        "action_type": "update",
        "org_id": org_id,
        "site_id": site_id,
        "object_type": "site_info",
        "payload": {
            "networktemplate_id": "1b4d9684-8a4e-426c-beb8-3b2c352f8e1f",
        },
    }


def _site_setting_payload() -> dict[str, Any]:
    return {
        "auto_upgrade": {
            "enabled": True,
        }
    }


def _single_site_setting_args(org_id: str, site_id: str) -> dict[str, Any]:
    return {
        "action": "simulate",
        "action_type": "update",
        "org_id": org_id,
        "site_id": site_id,
        "object_type": "site_setting",
        "payload": _site_setting_payload(),
    }


def _org_wlan_create_payload(suffix: str) -> dict[str, Any]:
    return {
        "ssid": f"DT-SEED-{suffix}",
        "enabled": True,
        "auth": {"type": "open"},
        "vlan_id": 10,
    }


def _single_org_wlan_create_args(org_id: str, suffix: str) -> dict[str, Any]:
    return {
        "action": "simulate",
        "action_type": "create",
        "org_id": org_id,
        "object_type": "org_wlans",
        "payload": _org_wlan_create_payload(suffix),
    }


def _single_org_network_create_args(org_id: str, suffix: str) -> dict[str, Any]:
    return {
        "action": "simulate",
        "action_type": "create",
        "org_id": org_id,
        "object_type": "org_networks",
        "payload": {
            "name": f"DT-Conflict-Net-{suffix}",
            "subnet": "10.0.0.0/24",
            "gateway": "10.0.0.1",
            "vlan_id": 10,
        },
    }


def _single_site_device_delete_args(org_id: str, site_id: str, object_id: str) -> dict[str, Any]:
    return {
        "action": "simulate",
        "action_type": "delete",
        "org_id": org_id,
        "site_id": site_id,
        "object_type": "site_devices",
        "object_id": object_id,
    }


def _single_site_wlan_open_guest_args(org_id: str, site_id: str, suffix: str) -> dict[str, Any]:
    return {
        "action": "simulate",
        "action_type": "create",
        "org_id": org_id,
        "site_id": site_id,
        "object_type": "site_wlans",
        "payload": {
            "ssid": f"Guest-Open-Failure-{suffix}",
            "enabled": True,
            "auth": {"type": "open"},
            "vlan_id": "10",
            "isolation": False,
        },
    }


def _single_switch_bpdu_filter_args(org_id: str, site_id: str, switch_id: str) -> dict[str, Any]:
    return {
        "action": "simulate",
        "action_type": "update",
        "org_id": org_id,
        "site_id": site_id,
        "object_type": "site_devices",
        "object_id": switch_id,
        "payload": {
            "type": "switch",
            "port_config": {
                "ge-0/0/8": {
                    "usage": "trunk",
                    "bpdu_filter": True,
                    "critical": False,
                    "description": "",
                    "no_local_overwrite": True,
                }
            },
        },
    }


def _single_switch_port_disable_args(org_id: str, site_id: str, switch_id: str) -> dict[str, Any]:
    # Mirrors a previously run clean simulation from history: disable a specific switch port.
    return {
        "action": "simulate",
        "action_type": "update",
        "org_id": org_id,
        "site_id": site_id,
        "object_type": "site_devices",
        "object_id": switch_id,
        "payload": {
            "type": "switch",
            "port_config": {
                "ge-0/0/0": {
                    "usage": "disabled",
                    "critical": False,
                    "description": "history-replay-clean",
                    "no_local_overwrite": True,
                }
            },
        },
    }


def _single_gateway_ip_clear_args(org_id: str, site_id: str, gateway_id: str) -> dict[str, Any]:
    # Inspired by routing tests where removing L3 gateway interfaces can trigger ROUTE-GW impacts.
    return {
        "action": "simulate",
        "action_type": "update",
        "org_id": org_id,
        "site_id": site_id,
        "object_type": "site_devices",
        "object_id": gateway_id,
        "payload": {
            "type": "gateway",
            "ip_config": {},
        },
    }


def _multi_switch_update_args(
    org_id: str,
    site_id: str,
    switch_a_id: str,
    switch_b_id: str,
    usage: str,
) -> dict[str, Any]:
    return {
        "action": "simulate",
        "org_id": org_id,
        "changes": [
            {
                "action_type": "update",
                "object_type": "site_devices",
                "site_id": site_id,
                "object_id": switch_a_id,
                "payload": _switch_update_payload(usage),
            },
            {
                "action_type": "update",
                "object_type": "site_devices",
                "site_id": site_id,
                "object_id": switch_b_id,
                "payload": _switch_update_payload(usage),
            },
        ],
    }


def _multi_mixed_args(
    org_id: str,
    site_id: str,
    switch_a_id: str,
) -> dict[str, Any]:
    return {
        "action": "simulate",
        "org_id": org_id,
        "changes": [
            {
                "action_type": "update",
                "object_type": "site_setting",
                "site_id": site_id,
                "payload": _site_setting_payload(),
            },
            {
                "action_type": "update",
                "object_type": "site_devices",
                "site_id": site_id,
                "object_id": switch_a_id,
                "payload": _switch_update_payload("trunk"),
            },
        ],
    }


def build_scenarios(
    *,
    org_id: str,
    site_id: str,
    switch_a_id: str,
    switch_b_id: str,
    gateway_id: str,
) -> list[Scenario]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = datetime.now(timezone.utc).strftime("%H%M%S")
    compact_suffix = datetime.now(timezone.utc).strftime("%m%d%H%M%S")

    return [
        Scenario(
            name="single-switch-safe",
            description="Single update on switch A (likely clean).",
            tool_args=_single_site_device_update_args(org_id, site_id, switch_a_id, usage="trunk"),
            suite="seed",
        ),
        Scenario(
            name="single-switch-risky",
            description="Single update on switch A to disabled usage (may raise impacts).",
            tool_args=_single_site_device_update_args(org_id, site_id, switch_a_id, usage="disabled"),
            suite="seed",
        ),
        Scenario(
            name="single-site-info",
            description="Single site_info rename update.",
            tool_args=_single_site_info_rename_args(org_id, site_id, suffix=stamp),
            suite="seed",
        ),
        Scenario(
            name="single-site-setting",
            description="Single site_setting update (auto-upgrade enabled).",
            tool_args=_single_site_setting_args(org_id, site_id),
            suite="seed",
        ),
        Scenario(
            name="single-org-wlan-create",
            description="Single org WLAN create simulation.",
            tool_args=_single_org_wlan_create_args(org_id, suffix=stamp),
            suite="seed",
        ),
        Scenario(
            name="single-device-delete",
            description="Single gateway delete simulation (destructive scenario, simulate only).",
            tool_args=_single_site_device_delete_args(org_id, site_id, gateway_id),
            suite="seed",
        ),
        Scenario(
            name="multi-safe",
            description="Two switch updates (likely clean).",
            tool_args=_multi_switch_update_args(org_id, site_id, switch_a_id, switch_b_id, usage="trunk"),
            suite="seed",
        ),
        Scenario(
            name="multi-risky",
            description="Two switch updates to disabled usage (likely warnings/errors).",
            tool_args=_multi_switch_update_args(org_id, site_id, switch_a_id, switch_b_id, usage="disabled"),
            suite="seed",
        ),
        Scenario(
            name="multi-mixed",
            description="Mixed site setting + switch update.",
            tool_args=_multi_mixed_args(org_id, site_id, switch_a_id),
            suite="seed",
        ),
        Scenario(
            name="test-site-info-singleton-update",
            description="Test-derived: valid site_info singleton update without object_id.",
            tool_args=_single_site_info_rename_args(org_id, site_id, suffix=stamp),
            suite="tests",
        ),
        Scenario(
            name="test-site-info-template-binding",
            description="Test-derived: site_info template-binding payload compile path.",
            tool_args=_single_site_info_template_bind_args(org_id, site_id),
            suite="tests",
        ),
        Scenario(
            name="test-site-setting-singleton-update",
            description="Test-derived: site_setting singleton update.",
            tool_args=_single_site_setting_args(org_id, site_id),
            suite="tests",
        ),
        Scenario(
            name="test-switch-update-write-compile",
            description="Test-derived: valid site_devices update write compilation.",
            tool_args=_single_site_device_update_args(org_id, site_id, switch_a_id, usage="trunk"),
            suite="tests",
        ),
        Scenario(
            name="test-multi-switch-update-compile",
            description="Test-derived: valid multi-change site_devices update compilation.",
            tool_args=_multi_switch_update_args(org_id, site_id, switch_a_id, switch_b_id, usage="trunk"),
            suite="tests",
        ),
        Scenario(
            name="test-route-gw-ip-interface-removal",
            description="Test-derived: gateway ip_config clear to exercise ROUTE-GW behavior.",
            tool_args=_single_gateway_ip_clear_args(org_id, site_id, gateway_id),
            suite="tests",
        ),
        Scenario(
            name="failure-connectivity-delete-gateway",
            description="Failure: delete gateway device to trigger critical connectivity impacts.",
            tool_args=_single_site_device_delete_args(org_id, site_id, gateway_id),
            suite="failures",
        ),
        Scenario(
            name="failure-connectivity-delete-switch-b",
            description="Failure: delete switch B to trigger connectivity critical issue(s).",
            tool_args=_single_site_device_delete_args(org_id, site_id, switch_b_id),
            suite="failures",
        ),
        Scenario(
            name="failure-security-open-guest-wlan",
            description="Failure: create open guest WLAN without isolation to trigger SEC-GUEST warning.",
            tool_args=_single_site_wlan_open_guest_args(org_id, site_id, suffix=suffix),
            suite="failures",
        ),
        Scenario(
            name="failure-stp-bpdu-filter-on-trunk",
            description="Failure: enable BPDU filter on trunk port to trigger STP-BPDU warning.",
            tool_args=_single_switch_bpdu_filter_args(org_id, site_id, switch_a_id),
            suite="failures",
        ),
        Scenario(
            name="history-multi-two-switch-trunk-clean",
            description="History replay: multi-change clean run with two switch trunk updates.",
            tool_args=_multi_switch_update_args(org_id, site_id, switch_a_id, switch_b_id, usage="trunk"),
            suite="history",
        ),
        Scenario(
            name="history-single-org-network-create-clean",
            description="History replay: org network create simulation (clean).",
            tool_args=_single_org_network_create_args(org_id, compact_suffix),
            suite="history",
        ),
        Scenario(
            name="history-single-org-wlan-create-clean",
            description="History replay: org WLAN create simulation (clean).",
            tool_args=_single_org_wlan_create_args(org_id, compact_suffix),
            suite="history",
        ),
        Scenario(
            name="history-single-switch-port-disable-clean",
            description="History replay: switch port disable simulation (clean).",
            tool_args=_single_switch_port_disable_args(org_id, site_id, switch_a_id),
            suite="history",
        ),
        Scenario(
            name="history-single-delete-gateway-critical",
            description="History replay: gateway delete simulation (critical).",
            tool_args=_single_site_device_delete_args(org_id, site_id, gateway_id),
            suite="history",
        ),
        Scenario(
            name="history-single-delete-switch-b-critical",
            description="History replay: switch B delete simulation (critical).",
            tool_args=_single_site_device_delete_args(org_id, site_id, switch_b_id),
            suite="history",
        ),
        Scenario(
            name="history-single-open-guest-wlan-warning",
            description="History replay: open guest WLAN simulation (SEC-GUEST warning).",
            tool_args=_single_site_wlan_open_guest_args(org_id, site_id, suffix=suffix),
            suite="history",
        ),
        Scenario(
            name="history-single-stp-bpdu-warning",
            description="History replay: BPDU filter on trunk simulation (STP warning).",
            tool_args=_single_switch_bpdu_filter_args(org_id, site_id, switch_a_id),
            suite="history",
        ),
        Scenario(
            name="chat-single-switch-safe",
            description="Chat replay: single switch trunk update (clean in prior run).",
            tool_args=_single_site_device_update_args(org_id, site_id, switch_a_id, usage="trunk"),
            suite="chat",
        ),
        Scenario(
            name="chat-single-switch-risky",
            description="Chat replay: single switch disabled usage update.",
            tool_args=_single_site_device_update_args(org_id, site_id, switch_a_id, usage="disabled"),
            suite="chat",
        ),
        Scenario(
            name="chat-multi-switch-trunk-clean",
            description="Chat replay: multi-change trunk updates on both switches.",
            tool_args=_multi_switch_update_args(org_id, site_id, switch_a_id, switch_b_id, usage="trunk"),
            suite="chat",
        ),
        Scenario(
            name="chat-multi-switch-disabled-risky",
            description="Chat replay: multi-change disabled usage updates on both switches.",
            tool_args=_multi_switch_update_args(org_id, site_id, switch_a_id, switch_b_id, usage="disabled"),
            suite="chat",
        ),
        Scenario(
            name="chat-multi-mixed-site-setting-switch",
            description="Chat replay: mixed site setting update plus switch update.",
            tool_args=_multi_mixed_args(org_id, site_id, switch_a_id),
            suite="chat",
        ),
        Scenario(
            name="chat-single-site-info-rename",
            description="Chat replay: site_info rename update.",
            tool_args=_single_site_info_rename_args(org_id, site_id, suffix=stamp),
            suite="chat",
        ),
        Scenario(
            name="chat-single-org-wlan-create",
            description="Chat replay: org WLAN create simulation.",
            tool_args=_single_org_wlan_create_args(org_id, compact_suffix),
            suite="chat",
        ),
        Scenario(
            name="chat-single-org-network-create",
            description="Chat replay: org network create simulation.",
            tool_args=_single_org_network_create_args(org_id, compact_suffix),
            suite="chat",
        ),
        Scenario(
            name="chat-single-switch-port-disable-clean",
            description="Chat replay: switch port disable simulation that previously passed.",
            tool_args=_single_switch_port_disable_args(org_id, site_id, switch_a_id),
            suite="chat",
        ),
        Scenario(
            name="chat-failure-delete-gateway-critical",
            description="Chat replay: gateway delete critical failure simulation.",
            tool_args=_single_site_device_delete_args(org_id, site_id, gateway_id),
            suite="chat",
        ),
        Scenario(
            name="chat-failure-delete-switch-b-critical",
            description="Chat replay: switch B delete critical failure simulation.",
            tool_args=_single_site_device_delete_args(org_id, site_id, switch_b_id),
            suite="chat",
        ),
        Scenario(
            name="chat-warning-open-guest-wlan",
            description="Chat replay: open guest WLAN warning simulation.",
            tool_args=_single_site_wlan_open_guest_args(org_id, site_id, suffix=suffix),
            suite="chat",
        ),
        Scenario(
            name="chat-warning-stp-bpdu-trunk",
            description="Chat replay: STP BPDU filter warning simulation.",
            tool_args=_single_switch_bpdu_filter_args(org_id, site_id, switch_a_id),
            suite="chat",
        ),
    ]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed Digital Twin simulation sessions")
    parser.add_argument("--org-id", default=DEFAULT_ORG_ID)
    parser.add_argument("--site-id", default=DEFAULT_SITE_ID)
    parser.add_argument("--switch-a-id", default=DEFAULT_SWITCH_A_ID)
    parser.add_argument("--switch-b-id", default=DEFAULT_SWITCH_B_ID)
    parser.add_argument("--gateway-id", default=DEFAULT_GATEWAY_ID)
    parser.add_argument("--mcp-url", default=os.environ.get("MCP_SERVER_URL"))
    parser.add_argument("--auth-token", default=os.environ.get("MCP_AUTH_TOKEN"))
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS cert verification for MCP HTTPS connections",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="MCP request timeout in seconds",
    )
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated scenario names to run (default: run all)",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List scenario names/descriptions and exit",
    )
    parser.add_argument(
        "--scenario-suite",
        choices=["all", "seed", "tests", "failures", "history", "chat"],
        default="all",
        help="Filter scenarios by suite before applying --only",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()

    scenarios = build_scenarios(
        org_id=args.org_id,
        site_id=args.site_id,
        switch_a_id=args.switch_a_id,
        switch_b_id=args.switch_b_id,
        gateway_id=args.gateway_id,
    )
    suite_filtered = [s for s in scenarios if args.scenario_suite == "all" or s.suite == args.scenario_suite]
    by_name = {s.name: s for s in suite_filtered}

    if args.list_scenarios:
        print("Available scenarios:")
        for scenario in suite_filtered:
            print(f"- {scenario.name} [{scenario.suite}]: {scenario.description}")
        return

    raw_mcp_url = _resolve_required_value(args.mcp_url, "MCP_SERVER_URL", "--mcp-url")
    mcp_url = _normalize_mcp_url(raw_mcp_url)
    if mcp_url != raw_mcp_url:
        print(f"[INFO] Normalized MCP URL to streamable endpoint: {mcp_url}")
    auth_token = _resolve_required_value(args.auth_token, "MCP_AUTH_TOKEN", "--auth-token")

    try:
        from fastmcp import Client
        from fastmcp.exceptions import ClientError, ToolError
        from mcp import McpError
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing FastMCP dependency. Run with backend virtualenv Python: "
            "'.venv/bin/python scripts/seed_digital_twin_simulations.py'"
        ) from exc

    selected: list[Scenario]
    if args.only.strip():
        requested = [name.strip() for name in args.only.split(",") if name.strip()]
        missing = [name for name in requested if name not in by_name]
        if missing:
            raise RuntimeError(f"Unknown scenario name(s): {', '.join(missing)}")
        selected = [by_name[name] for name in requested]
    else:
        selected = suite_filtered

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    print(f"Connecting to MCP server: {mcp_url}")
    print(f"Running {len(selected)} scenario(s)...")

    created_session_ids: list[str] = []

    async with Client(
        mcp_url,
        auth=auth_token,
        verify=not args.insecure,
        timeout=args.timeout,
    ) as mcp_client:
        for index, scenario in enumerate(selected, start=1):
            tool_args = dict(scenario.tool_args)
            tool_args.setdefault("session_id", "")

            source_ref = f"seed-script:{stamp}:{index}:{scenario.name}"
            try:
                tool_result = await mcp_client.call_tool(
                    "digital_twin",
                    tool_args,
                    raise_on_error=False,
                )
            except (RuntimeError, ValueError, TimeoutError, OSError, ClientError, ToolError, McpError) as exc:
                print(f"[FAIL] {scenario.name}: {exc}")
                continue

            if tool_result.is_error:
                error_text = "\n".join(
                    block.text for block in tool_result.content if hasattr(block, "text")
                )
                print(f"[FAIL] {scenario.name}: MCP tool returned error: {error_text or 'unknown error'}")
                continue

            parsed: dict[str, Any] | None = None
            if isinstance(tool_result.data, dict):
                parsed = tool_result.data

            if parsed is None:
                text_blocks = [block.text for block in tool_result.content if hasattr(block, "text")]
                joined_text = "\n".join(text_blocks).strip()
                if joined_text:
                    try:
                        parsed_value = json.loads(joined_text)
                        if isinstance(parsed_value, dict):
                            parsed = parsed_value
                    except json.JSONDecodeError:
                        parsed = None

            if parsed is None:
                print(f"[FAIL] {scenario.name}: Unexpected non-JSON response: {tool_result}")
                continue

            session_id = str(parsed.get("session_id") or "")
            status = str(parsed.get("status") or "unknown")
            severity = str(parsed.get("overall_severity") or parsed.get("severity") or "unknown")
            execution_safe = bool(parsed.get("execution_safe", False))
            counts = parsed.get("counts") or {}
            checks = int(counts.get("total", 0)) if isinstance(counts, dict) else 0
            summary = str(parsed.get("summary") or "No summary")

            if not session_id:
                print(f"[FAIL] {scenario.name}: No session_id returned. Response={parsed}")
                continue

            created_session_ids.append(session_id)

            print(
                "[OK] "
                f"{scenario.name}: session_id={session_id}, status={status}, "
                f"severity={severity}, execution_safe={execution_safe}, checks={checks}"
            )
            print(f"     summary={summary}")
            print(f"     source_ref={source_ref}")

    print("\nDone.")
    if created_session_ids:
        print("Created sessions:")
        for sid in created_session_ids:
            print(f"- {sid}")


if __name__ == "__main__":
    _ensure_python_runtime()
    asyncio.run(main())
