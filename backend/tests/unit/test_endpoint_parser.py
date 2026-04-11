"""Unit tests for Mist API endpoint parser."""

import pytest

from app.modules.digital_twin.services.endpoint_parser import parse_endpoint


@pytest.mark.unit
class TestParseEndpoint:
    def test_org_wlans_list(self):
        result = parse_endpoint("POST", "/api/v1/orgs/org-123/wlans")
        assert result.object_type == "wlans"
        assert result.org_id == "org-123"
        assert result.site_id is None
        assert result.object_id is None
        assert result.scope == "org"
        assert result.error is None

    def test_org_wlan_update(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/wlans/wlan-456")
        assert result.object_type == "wlans"
        assert result.org_id == "org-123"
        assert result.object_id == "wlan-456"
        assert result.site_id is None
        assert result.error is None

    def test_site_wlans_create(self):
        result = parse_endpoint("POST", "/api/v1/sites/site-789/wlans")
        assert result.object_type == "wlans"
        assert result.site_id == "site-789"
        assert result.object_id is None
        assert result.scope == "site"
        assert result.error is None

    def test_site_wlan_update(self):
        result = parse_endpoint("PUT", "/api/v1/sites/site-789/wlans/wlan-abc")
        assert result.object_type == "wlans"
        assert result.site_id == "site-789"
        assert result.object_id == "wlan-abc"
        assert result.error is None

    def test_site_wlan_delete(self):
        result = parse_endpoint("DELETE", "/api/v1/sites/site-789/wlans/wlan-abc")
        assert result.object_type == "wlans"
        assert result.site_id == "site-789"
        assert result.object_id == "wlan-abc"
        assert result.error is None

    def test_site_setting(self):
        result = parse_endpoint("PUT", "/api/v1/sites/site-789/setting")
        assert result.object_type == "settings"
        assert result.site_id == "site-789"
        assert result.object_id is None
        assert result.is_singleton is True
        assert result.error is None

    def test_org_setting(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/setting")
        assert result.object_type == "settings"
        assert result.org_id == "org-123"
        assert result.is_singleton is True
        assert result.error is None

    def test_org_root_data(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123")
        assert result.object_type == "data"
        assert result.org_id == "org-123"
        assert result.object_id is None
        assert result.is_singleton is True
        assert result.error is None

    def test_site_info(self):
        result = parse_endpoint("PUT", "/api/v1/sites/site-789")
        assert result.object_type == "info"
        assert result.site_id == "site-789"
        assert result.is_singleton is True
        assert result.error is None

    def test_networks(self):
        result = parse_endpoint("POST", "/api/v1/orgs/org-123/networks")
        assert result.object_type == "networks"
        assert result.org_id == "org-123"
        assert result.error is None

    def test_sitetemplates(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/sitetemplates/tmpl-1")
        assert result.object_type == "sitetemplates"
        assert result.object_id == "tmpl-1"
        assert result.error is None

    def test_rftemplates(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/rftemplates/rf-1")
        assert result.object_type == "rftemplates"
        assert result.object_id == "rf-1"
        assert result.error is None

    def test_devices(self):
        result = parse_endpoint("PUT", "/api/v1/sites/site-789/devices/dev-1")
        assert result.object_type == "devices"
        assert result.site_id == "site-789"
        assert result.object_id == "dev-1"
        assert result.error is None

    def test_unknown_endpoint_sets_error(self):
        result = parse_endpoint("POST", "/api/v1/some/unknown/path")
        assert result.object_type is None
        assert result.error is not None
        assert "does not match Mist API pattern" in result.error

    def test_nacportals(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/nacportals/nac-1")
        assert result.object_type == "nacportals"
        assert result.error is None

    def test_nacrules(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/nacrules/rule-1")
        assert result.object_type == "nacrules"
        assert result.object_id == "rule-1"
        assert result.error is None

    def test_secpolicies(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/secpolicies/sec-1")
        assert result.object_type == "secpolicies"
        assert result.error is None

    def test_services(self):
        result = parse_endpoint("POST", "/api/v1/orgs/org-123/services")
        assert result.object_type == "services"
        assert result.error is None

    def test_servicepolicies(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/servicepolicies/sp-1")
        assert result.object_type == "servicepolicies"
        assert result.error is None

    # --- Normalization tests (singular → plural) ---

    def test_normalize_wlan_to_wlans(self):
        result = parse_endpoint("POST", "/api/v1/sites/site-789/wlan")
        assert result.object_type == "wlans"
        assert result.error is None

    def test_normalize_wlan_with_id(self):
        result = parse_endpoint("PUT", "/api/v1/sites/site-789/wlan/wlan-abc")
        assert result.object_type == "wlans"
        assert result.object_id == "wlan-abc"
        assert result.error is None

    def test_normalize_network_to_networks(self):
        result = parse_endpoint("POST", "/api/v1/orgs/org-123/network")
        assert result.object_type == "networks"
        assert result.error is None

    def test_normalize_device_to_devices(self):
        result = parse_endpoint("PUT", "/api/v1/sites/site-789/device/dev-1")
        assert result.object_type == "devices"
        assert result.object_id == "dev-1"
        assert result.error is None

    def test_normalize_rftemplate_to_rftemplates(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/rftemplate/rf-1")
        assert result.object_type == "rftemplates"
        assert result.error is None

    def test_normalize_gatewaytemplate_to_gatewaytemplates(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/gatewaytemplate/gt-1")
        assert result.object_type == "gatewaytemplates"
        assert result.error is None

    # --- Validation error tests ---

    def test_invalid_site_resource_sets_error(self):
        result = parse_endpoint("POST", "/api/v1/sites/site-789/wlan/MlN/vlan")
        # The regex won't match a 4-segment path — no site_id populated
        assert result.error is not None

    def test_invalid_site_resource_name(self):
        result = parse_endpoint("POST", "/api/v1/sites/site-789/badresource")
        assert result.object_type is None
        assert result.site_id == "site-789"
        assert result.scope == "site"
        assert result.error is not None
        assert "badresource" in result.error

    def test_invalid_org_resource_name(self):
        result = parse_endpoint("POST", "/api/v1/orgs/org-123/unknownstuff")
        assert result.object_type is None
        assert result.org_id == "org-123"
        assert result.scope == "org"
        assert result.error is not None
        assert "unknownstuff" in result.error

    def test_invalid_resource_still_populates_ids(self):
        """error field set but site_id/org_id still extracted."""
        result = parse_endpoint("PUT", "/api/v1/sites/site-abc/nonexistent/obj-1")
        assert result.site_id == "site-abc"
        assert result.scope == "site"
        assert result.error is not None

    def test_put_collection_requires_object_id(self):
        result = parse_endpoint("PUT", "/api/v1/sites/site-789/wlans")
        assert result.object_type == "wlans"
        assert result.object_id is None
        assert result.error is not None
        assert "requires object_id" in result.error

    def test_delete_org_collection_requires_object_id(self):
        result = parse_endpoint("DELETE", "/api/v1/orgs/org-123/networks")
        assert result.object_type == "networks"
        assert result.object_id is None
        assert result.error is not None
        assert "requires object_id" in result.error

    def test_post_collection_with_object_id_rejected(self):
        result = parse_endpoint("POST", "/api/v1/sites/site-789/wlans/wlan-abc")
        assert result.object_type == "wlans"
        assert result.object_id == "wlan-abc"
        assert result.error is not None
        assert "must target a collection endpoint without object_id" in result.error

    def test_singleton_with_object_id_rejected(self):
        result = parse_endpoint("PUT", "/api/v1/sites/site-789/setting/extra")
        assert result.object_type == "settings"
        assert result.error is not None
        assert "does not accept object_id" in result.error

    # --- Placeholder validation tests ---

    def test_rejects_placeholder_site_id(self):
        result = parse_endpoint("PUT", "/api/v1/sites/{site_id}/devices/dev-1")
        assert result.error is not None
        assert "Unresolved path placeholder" in result.error

    def test_rejects_placeholder_object_id(self):
        result = parse_endpoint("PUT", "/api/v1/sites/site-1/devices/{device_id}")
        assert result.error is not None
        assert "Unresolved path placeholder" in result.error

    def test_rejects_placeholder_org_id(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/{org_id}/networktemplates/nt-1")
        assert result.error is not None
        assert "Unresolved path placeholder" in result.error

    def test_rejects_angle_bracket_placeholder(self):
        result = parse_endpoint("PUT", "/api/v1/sites/<site_id>/devices/dev-1")
        assert result.error is not None
        assert "Unresolved path placeholder" in result.error

    # --- Trailing slash stripping ---

    def test_trailing_slash_site_wlans(self):
        result = parse_endpoint("GET", "/api/v1/sites/site-789/wlans/")
        assert result.object_type == "wlans"
        assert result.site_id == "site-789"
        assert result.error is None

    def test_trailing_slash_org_setting(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/setting/")
        assert result.object_type == "settings"
        assert result.is_singleton is True
        assert result.error is None

    def test_trailing_slash_unknown(self):
        result = parse_endpoint("POST", "/api/v1/some/unknown/path/")
        assert result.error is not None
        assert "does not match Mist API pattern" in result.error
