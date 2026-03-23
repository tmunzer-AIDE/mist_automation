"""Unit tests for IP allowlist checking in the webhook gateway."""

import pytest

from app.api.v1.webhooks import _ip_in_allowlist


@pytest.mark.unit
class TestIpAllowlist:
    def test_exact_ip_match(self):
        assert _ip_in_allowlist("192.168.1.1", ["192.168.1.1/32"]) is True

    def test_exact_ip_no_match(self):
        assert _ip_in_allowlist("10.0.0.1", ["192.168.1.1/32"]) is False

    def test_cidr_match(self):
        assert _ip_in_allowlist("10.0.0.5", ["10.0.0.0/24"]) is True

    def test_cidr_no_match(self):
        assert _ip_in_allowlist("10.1.0.1", ["10.0.0.0/24"]) is False

    def test_ipv6_cidr(self):
        assert _ip_in_allowlist("fe80::1", ["fe80::/10"]) is True

    def test_empty_allowlist(self):
        assert _ip_in_allowlist("192.168.1.1", []) is False

    def test_invalid_client_ip(self):
        assert _ip_in_allowlist("not-an-ip", ["10.0.0.0/24"]) is False

    def test_invalid_cidr_entry(self):
        assert _ip_in_allowlist("10.0.0.1", ["not-a-cidr"]) is False

    def test_multiple_entries_match_second(self):
        assert _ip_in_allowlist("172.16.0.5", ["10.0.0.0/8", "172.16.0.0/16"]) is True

    def test_single_host_cidr(self):
        assert _ip_in_allowlist("192.168.1.1", ["192.168.1.1/32"]) is True

    def test_ipv4_mapped_ipv6_does_not_match_v4_entry(self):
        # ::ffff:10.0.0.1 is IPv6 mapped — should not match plain v4 CIDR
        assert _ip_in_allowlist("::ffff:10.0.0.1", ["10.0.0.0/24"]) is False
