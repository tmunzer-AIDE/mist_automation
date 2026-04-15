"""Unit tests for impact-analysis chat context construction."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api.v1.impact_analysis import _build_session_context
from app.modules.impact_analysis.models import ConfigChangeEvent, DeviceType, SessionStatus

pytestmark = pytest.mark.unit


def _make_session(**overrides):
    now = datetime.now(timezone.utc)
    old_change = ConfigChangeEvent(
        event_type="SW_CONFIG_CHANGED_BY_USER",
        device_mac="aa:bb:cc:dd:ee:ff",
        device_name="core-sw1",
        timestamp=now,
        payload_summary={"topic": "audits", "id": "audit-1"},
        change_message="Old change message",
    )
    latest_change = ConfigChangeEvent(
        event_type="SW_CONFIGURED",
        device_mac="aa:bb:cc:dd:ee:ff",
        device_name="core-sw1",
        timestamp=now,
        payload_summary={"topic": "device-events", "id": "evt-2", "method": "netconf"},
        config_diff="set interfaces ge-0/0/1 disable\ndelete protocols ospf area 0.0.0.0",
        config_before={"interfaces": {"ge-0/0/1": {"disable": False}}},
        config_after={"interfaces": {"ge-0/0/1": {"disable": True}}},
        change_message="Disable uplink for maintenance",
        device_model="EX4400-48P",
        firmware_version="22.4R3",
        commit_user="ops@example.com",
        commit_method="netconf",
    )

    defaults = {
        "site_id": "site-123",
        "site_name": "HQ",
        "org_id": "org-123",
        "device_mac": "aa:bb:cc:dd:ee:ff",
        "device_name": "core-sw1",
        "device_type": DeviceType.SWITCH,
        "status": SessionStatus.MONITORING,
        "impact_severity": "none",
        "config_changes": [old_change, latest_change],
        "incidents": [],
        "validation_results": {},
        "sle_delta": {},
        "ai_assessment": {},
        "timeline": [],
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_build_session_context_includes_identifiers_and_latest_change_details():
    session = _make_session()

    context = _build_session_context(session)

    assert "Org ID: org-123" in context
    assert "Site ID: site-123 (HQ)" in context
    assert "Most recent config changes (newest first):" in context
    assert "1. SW_CONFIGURED" in context
    assert "Committed by: ops@example.com via netconf" in context
    assert "model=EX4400-48P, firmware=22.4R3" in context
    assert "Audit message: Disable uplink for maintenance" in context
    assert "Config diff (Junos):" in context
    assert "Config before/after (audit):" in context
    assert "Default reference: if the user says 'this change'" in context


def test_build_session_context_still_works_without_config_changes():
    session = _make_session(status=SessionStatus.PENDING, config_changes=[])

    context = _build_session_context(session)

    assert "Config changes: 0" in context
    assert "Most recent config changes" not in context


def test_build_session_context_truncates_long_sections():
    now = datetime.now(timezone.utc)
    long_diff = "set interfaces ge-0/0/1 description test\n" * 120
    long_payload = {"note": "x" * 2000}
    long_before = {"radius_secret": "super-secret-value" * 200}

    session = _make_session(
        config_changes=[
            ConfigChangeEvent(
                event_type="SW_CONFIGURED",
                device_mac="aa:bb:cc:dd:ee:ff",
                device_name="core-sw1",
                timestamp=now,
                payload_summary=long_payload,
                config_diff=long_diff,
                config_before=long_before,
                config_after={"api_key": "top-secret"},
            )
        ]
    )

    context = _build_session_context(session)

    assert "truncated, full length" in context
    assert "[REDACTED]" in context
    assert "super-secret-value" not in context
    assert "top-secret" not in context


def test_build_session_context_only_includes_latest_three_changes():
    now = datetime.now(timezone.utc)
    changes = []
    for idx in range(5):
        changes.append(
            ConfigChangeEvent(
                event_type=f"CHANGE_{idx}",
                device_mac="aa:bb:cc:dd:ee:ff",
                device_name="core-sw1",
                timestamp=now.replace(microsecond=idx),
                payload_summary={"id": idx},
            )
        )

    session = _make_session(config_changes=changes)

    context = _build_session_context(session)

    assert "CHANGE_4" in context
    assert "CHANGE_3" in context
    assert "CHANGE_2" in context
    assert "CHANGE_1" not in context
    assert "CHANGE_0" not in context
