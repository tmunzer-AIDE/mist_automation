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

    def test_org_wlan_update(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/wlans/wlan-456")
        assert result.object_type == "wlans"
        assert result.org_id == "org-123"
        assert result.object_id == "wlan-456"
        assert result.site_id is None

    def test_site_wlans_create(self):
        result = parse_endpoint("POST", "/api/v1/sites/site-789/wlans")
        assert result.object_type == "wlans"
        assert result.site_id == "site-789"
        assert result.object_id is None
        assert result.scope == "site"

    def test_site_wlan_update(self):
        result = parse_endpoint("PUT", "/api/v1/sites/site-789/wlans/wlan-abc")
        assert result.object_type == "wlans"
        assert result.site_id == "site-789"
        assert result.object_id == "wlan-abc"

    def test_site_wlan_delete(self):
        result = parse_endpoint("DELETE", "/api/v1/sites/site-789/wlans/wlan-abc")
        assert result.object_type == "wlans"
        assert result.site_id == "site-789"
        assert result.object_id == "wlan-abc"

    def test_site_setting(self):
        result = parse_endpoint("PUT", "/api/v1/sites/site-789/setting")
        assert result.object_type == "setting"
        assert result.site_id == "site-789"
        assert result.object_id is None
        assert result.is_singleton is True

    def test_org_setting(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/setting")
        assert result.object_type == "setting"
        assert result.org_id == "org-123"
        assert result.is_singleton is True

    def test_site_info(self):
        result = parse_endpoint("PUT", "/api/v1/sites/site-789")
        assert result.object_type == "info"
        assert result.site_id == "site-789"
        assert result.is_singleton is True

    def test_networks(self):
        result = parse_endpoint("POST", "/api/v1/orgs/org-123/networks")
        assert result.object_type == "networks"
        assert result.org_id == "org-123"

    def test_sitetemplates(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/sitetemplates/tmpl-1")
        assert result.object_type == "sitetemplates"
        assert result.object_id == "tmpl-1"

    def test_rftemplates(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/rftemplates/rf-1")
        assert result.object_type == "rftemplates"
        assert result.object_id == "rf-1"

    def test_devices(self):
        result = parse_endpoint("PUT", "/api/v1/sites/site-789/devices/dev-1")
        assert result.object_type == "devices"
        assert result.site_id == "site-789"
        assert result.object_id == "dev-1"

    def test_unknown_endpoint_returns_none_type(self):
        result = parse_endpoint("POST", "/api/v1/some/unknown/path")
        assert result.object_type is None

    def test_nacportals(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/nacportals/nac-1")
        assert result.object_type == "nacportals"

    def test_nacrules(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/nacrules/rule-1")
        assert result.object_type == "nacrules"
        assert result.object_id == "rule-1"

    def test_secpolicies(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/secpolicies/sec-1")
        assert result.object_type == "secpolicies"

    def test_services(self):
        result = parse_endpoint("POST", "/api/v1/orgs/org-123/services")
        assert result.object_type == "services"

    def test_servicepolicies(self):
        result = parse_endpoint("PUT", "/api/v1/orgs/org-123/servicepolicies/sp-1")
        assert result.object_type == "servicepolicies"
