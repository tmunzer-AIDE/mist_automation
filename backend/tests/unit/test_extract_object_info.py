"""
Unit tests for _extract_object_info in the backup workers module.

Tests the disambiguation logic when audit events contain multiple *_id fields
(e.g. both template_id and wlan_id for a WLAN belonging to a template).
"""

from unittest.mock import patch, MagicMock

import pytest

# Minimal mock registries — only need the keys, not the ObjectDef values
_MOCK_ORG_OBJECTS = {
    "wlans": MagicMock(),
    "templates": MagicMock(),
    "networks": MagicMock(),
    "networktemplates": MagicMock(),
    "rftemplates": MagicMock(),
    "deviceprofiles": MagicMock(),
    "secpolicies": MagicMock(),
    "servicepolicies": MagicMock(),
    "mxclusters": MagicMock(),
    "mxedges": MagicMock(),
    "ssos": MagicMock(),
    "ssoroles": MagicMock(),
    "psks": MagicMock(),
}

_MOCK_SITE_OBJECTS = {
    "wlans": MagicMock(),
    "devices": MagicMock(),
    "maps": MagicMock(),
    "psks": MagicMock(),
}

_REGISTRY_PATCHES = {
    "app.modules.backup.object_registry.ORG_OBJECTS": _MOCK_ORG_OBJECTS,
    "app.modules.backup.object_registry.SITE_OBJECTS": _MOCK_SITE_OBJECTS,
}


@pytest.fixture(autouse=True)
def _patch_registries():
    """Patch ORG_OBJECTS and SITE_OBJECTS to avoid importing mistapi."""
    with (
        patch(
            "app.modules.backup.object_registry.ORG_OBJECTS", _MOCK_ORG_OBJECTS
        ),
        patch(
            "app.modules.backup.object_registry.SITE_OBJECTS", _MOCK_SITE_OBJECTS
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _reset_reference_index():
    """Reset the cached reference field index between tests."""
    import app.modules.backup.workers as workers_mod

    workers_mod._REFERENCE_FIELD_INDEX = None
    yield
    workers_mod._REFERENCE_FIELD_INDEX = None


def _extract(event: dict):
    from app.modules.backup.workers import _extract_object_info

    return _extract_object_info(event)


class TestSingleIdField:
    def test_org_wlan(self):
        obj_type, obj_id, site_id = _extract({"wlan_id": "abc-123"})
        assert obj_type == "wlans"
        assert obj_id == "abc-123"
        assert site_id is None

    def test_site_wlan(self):
        obj_type, obj_id, site_id = _extract(
            {"wlan_id": "abc-123", "site_id": "site-1"}
        )
        assert obj_type == "wlans"
        assert obj_id == "abc-123"
        assert site_id == "site-1"

    def test_template(self):
        obj_type, obj_id, site_id = _extract({"template_id": "tmpl-1"})
        assert obj_type == "templates"
        assert obj_id == "tmpl-1"

    def test_network(self):
        obj_type, obj_id, site_id = _extract({"network_id": "net-1"})
        assert obj_type == "networks"
        assert obj_id == "net-1"

    def test_secpolicy_y_to_ies_plural(self):
        obj_type, obj_id, site_id = _extract({"secpolicy_id": "sec-1"})
        assert obj_type == "secpolicies"
        assert obj_id == "sec-1"

    def test_servicepolicy_y_to_ies_plural(self):
        obj_type, obj_id, site_id = _extract({"servicepolicy_id": "sp-1"})
        assert obj_type == "servicepolicies"
        assert obj_id == "sp-1"


class TestDeleteEvents:
    def test_delete_value_none_string(self):
        obj_type, obj_id, site_id = _extract({"wlan_id": "None"})
        assert obj_type == "wlans"
        assert obj_id is None
        assert site_id is None

    def test_delete_with_site_id(self):
        obj_type, obj_id, site_id = _extract(
            {"wlan_id": "None", "site_id": "site-1"}
        )
        assert obj_type == "wlans"
        assert obj_id is None
        assert site_id == "site-1"


class TestMultipleIdFieldsDisambiguation:
    """Core bug fix: when multiple *_id fields are present, use REFERENCE_MAP."""

    def test_wlan_and_template_returns_wlan(self):
        """template_id is a reference field OF wlans -> wlans is the primary object."""
        obj_type, obj_id, site_id = _extract(
            {
                "template_id": "tmpl-1",
                "wlan_id": "wlan-1",
                "org_id": "org-1",
            }
        )
        assert obj_type == "wlans"
        assert obj_id == "wlan-1"

    def test_wlan_and_template_reversed_order(self):
        """Same test but with wlan_id appearing first in dict order."""
        obj_type, obj_id, site_id = _extract(
            {
                "wlan_id": "wlan-1",
                "template_id": "tmpl-1",
            }
        )
        assert obj_type == "wlans"
        assert obj_id == "wlan-1"

    def test_secpolicy_and_wlan_returns_secpolicy(self):
        """wlan_id is a reference field OF secpolicies -> secpolicies is primary."""
        obj_type, obj_id, site_id = _extract(
            {
                "wlan_id": "wlan-1",
                "secpolicy_id": "sec-1",
            }
        )
        assert obj_type == "secpolicies"
        assert obj_id == "sec-1"

    def test_ssorole_and_sso_returns_ssorole(self):
        """sso_id is a reference field OF ssoroles -> ssoroles is primary."""
        obj_type, obj_id, site_id = _extract(
            {
                "sso_id": "sso-1",
                "ssorole_id": "role-1",
            }
        )
        assert obj_type == "ssoroles"
        assert obj_id == "role-1"

    def test_device_and_deviceprofile_returns_device(self):
        """deviceprofile_id is a reference field OF devices -> devices is primary."""
        obj_type, obj_id, site_id = _extract(
            {
                "deviceprofile_id": "dp-1",
                "device_id": "dev-1",
                "site_id": "site-1",
            }
        )
        assert obj_type == "devices"
        assert obj_id == "dev-1"

    def test_device_and_map_returns_device(self):
        """map_id is a reference field OF devices -> devices is primary."""
        obj_type, obj_id, site_id = _extract(
            {
                "map_id": "map-1",
                "device_id": "dev-1",
                "site_id": "site-1",
            }
        )
        assert obj_type == "devices"
        assert obj_id == "dev-1"

    def test_mxedge_and_mxcluster_returns_mxedge(self):
        """mxcluster_id is a reference field OF mxedges -> mxedges is primary."""
        obj_type, obj_id, site_id = _extract(
            {
                "mxcluster_id": "clust-1",
                "mxedge_id": "edge-1",
            }
        )
        assert obj_type == "mxedges"
        assert obj_id == "edge-1"

    def test_full_audit_event_payload(self):
        """Reproduce the exact payload from the bug report."""
        obj_type, obj_id, site_id = _extract(
            {
                "admin_name": "Thomas Munzer tmunzer@juniper.net",
                "after": '{"enabled": false}',
                "before": '{"enabled": true}',
                "id": "3e52b39d-a8e7-4d69-abe1-158b57582bcc",
                "message": 'Update WLAN "test wlan" of Template "test wlan template"',
                "org_id": "5e1fc0cf-3920-44b7-af54-e52289ae8191",
                "src_ip": "194.9.98.201",
                "template_id": "c3a63429-8eb7-4a9f-aab6-1b1da048f9f0",
                "timestamp": 1773129791.480656,
                "user_agent": "Mozilla/5.0",
                "wlan_id": "08af0243-591a-4698-884c-ad35fd49d7ff",
            }
        )
        assert obj_type == "wlans"
        assert obj_id == "08af0243-591a-4698-884c-ad35fd49d7ff"
        assert site_id is None


class TestSkipFields:
    def test_id_field_skipped(self):
        obj_type, obj_id, site_id = _extract({"id": "some-id"})
        assert obj_type is None

    def test_org_id_skipped(self):
        obj_type, obj_id, site_id = _extract({"org_id": "org-1"})
        assert obj_type is None

    def test_admin_id_skipped(self):
        obj_type, obj_id, site_id = _extract({"admin_id": "adm-1"})
        assert obj_type is None

    def test_site_id_only_returns_none_type(self):
        obj_type, obj_id, site_id = _extract({"site_id": "site-1"})
        assert obj_type is None
        assert site_id == "site-1"


class TestFallbackBehavior:
    def test_envelope_format(self):
        obj_type, obj_id, site_id = _extract(
            {"object": "alarmtemplates", "id": "alarm-1"}
        )
        assert obj_type == "alarmtemplates"
        assert obj_id == "alarm-1"

    def test_no_matching_fields(self):
        obj_type, obj_id, site_id = _extract(
            {"foo": "bar", "timestamp": 123}
        )
        assert obj_type is None
        assert obj_id is None
        assert site_id is None

    def test_unknown_id_field_ignored(self):
        """An *_id field that doesn't match any registry key is skipped."""
        obj_type, obj_id, site_id = _extract(
            {"unknown_thing_id": "val-1"}
        )
        assert obj_type is None
