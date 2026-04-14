"""Unit tests for impact-analysis chat context construction."""

from datetime import datetime, timezone

import pytest

from app.api.v1.impact_analysis import _build_session_context
from app.modules.impact_analysis.models import ConfigChangeEvent, DeviceType, MonitoringSession, SessionStatus

pytestmark = pytest.mark.unit


def _make_session() -> MonitoringSession:
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

    return MonitoringSession(
        site_id="site-123",
        site_name="HQ",
        org_id="org-123",
        device_mac="aa:bb:cc:dd:ee:ff",
        device_name="core-sw1",
        device_type=DeviceType.SWITCH,
        status=SessionStatus.MONITORING,
        config_changes=[old_change, latest_change],
    )


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
    session = MonitoringSession(
        site_id="site-123",
        site_name="HQ",
        org_id="org-123",
        device_mac="aa:bb:cc:dd:ee:ff",
        device_name="core-sw1",
        device_type=DeviceType.SWITCH,
        status=SessionStatus.PENDING,
        config_changes=[],
    )

    context = _build_session_context(session)

    assert "Config changes: 0" in context
    assert "Most recent config changes" not in context
