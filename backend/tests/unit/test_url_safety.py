"""Unit tests for SSRF protection in validate_outbound_url."""

import socket
from unittest.mock import patch

import pytest

from app.utils.url_safety import validate_outbound_url


def _make_addrinfo(ip: str, family=socket.AF_INET):
    """Build a fake getaddrinfo result tuple for the given IP."""
    return [(family, socket.SOCK_STREAM, 6, "", (ip, 0))]


def _make_addrinfo_v6(ip: str):
    """Build a fake getaddrinfo result tuple for an IPv6 address."""
    return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0))]


# ---------------------------------------------------------------------------
# Public-IP helper: all "valid URL" tests patch getaddrinfo to return a
# well-known public IP so DNS resolution never touches the network.
# ---------------------------------------------------------------------------
PUBLIC_IP = "93.184.216.34"  # example.com


@pytest.mark.unit
class TestValidUrls:
    """Public URLs with safe IPs should pass validation."""

    @patch("app.utils.url_safety.socket.getaddrinfo", return_value=_make_addrinfo(PUBLIC_IP))
    def test_https_url(self, mock_dns):
        validate_outbound_url("https://example.com")

    @patch("app.utils.url_safety.socket.getaddrinfo", return_value=_make_addrinfo(PUBLIC_IP))
    def test_http_url(self, mock_dns):
        validate_outbound_url("http://api.mist.com/v1/test")

    @patch("app.utils.url_safety.socket.getaddrinfo", return_value=_make_addrinfo(PUBLIC_IP))
    def test_url_with_port(self, mock_dns):
        validate_outbound_url("https://example.com:8443/webhook")

    @patch("app.utils.url_safety.socket.getaddrinfo", return_value=_make_addrinfo(PUBLIC_IP))
    def test_url_with_path_and_query(self, mock_dns):
        validate_outbound_url("https://example.com/path?key=value&other=1")


@pytest.mark.unit
class TestInvalidSchemes:
    """Non-http(s) schemes must be rejected."""

    def test_ftp_scheme_rejected(self):
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            validate_outbound_url("ftp://example.com/file")

    def test_file_scheme_rejected(self):
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            validate_outbound_url("file:///etc/passwd")

    def test_javascript_scheme_rejected(self):
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            validate_outbound_url("javascript:alert(1)")

    def test_missing_scheme_rejected(self):
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            validate_outbound_url("example.com/path")


@pytest.mark.unit
class TestLoopbackBlocked:
    """Loopback addresses must be blocked."""

    @patch(
        "app.utils.url_safety.socket.getaddrinfo",
        return_value=_make_addrinfo("127.0.0.1"),
    )
    def test_127_0_0_1(self, mock_dns):
        with pytest.raises(ValueError, match="private/reserved"):
            validate_outbound_url("http://127.0.0.1")

    @patch(
        "app.utils.url_safety.socket.getaddrinfo",
        return_value=_make_addrinfo_v6("::1"),
    )
    def test_ipv6_loopback(self, mock_dns):
        with pytest.raises(ValueError, match="private/reserved"):
            validate_outbound_url("http://[::1]")

    @patch(
        "app.utils.url_safety.socket.getaddrinfo",
        return_value=_make_addrinfo("127.0.0.1"),
    )
    def test_localhost(self, mock_dns):
        with pytest.raises(ValueError, match="private/reserved"):
            validate_outbound_url("http://localhost")


@pytest.mark.unit
class TestPrivateRangesBlocked:
    """RFC 1918 private ranges must be blocked."""

    @patch(
        "app.utils.url_safety.socket.getaddrinfo",
        return_value=_make_addrinfo("10.0.0.1"),
    )
    def test_10_network(self, mock_dns):
        with pytest.raises(ValueError, match="private/reserved"):
            validate_outbound_url("http://10.0.0.1")

    @patch(
        "app.utils.url_safety.socket.getaddrinfo",
        return_value=_make_addrinfo("172.16.0.1"),
    )
    def test_172_16_network(self, mock_dns):
        with pytest.raises(ValueError, match="private/reserved"):
            validate_outbound_url("http://172.16.0.1")

    @patch(
        "app.utils.url_safety.socket.getaddrinfo",
        return_value=_make_addrinfo("192.168.1.1"),
    )
    def test_192_168_network(self, mock_dns):
        with pytest.raises(ValueError, match="private/reserved"):
            validate_outbound_url("http://192.168.1.1")


@pytest.mark.unit
class TestLinkLocalBlocked:
    """Link-local addresses (169.254.x.x) must be blocked."""

    @patch(
        "app.utils.url_safety.socket.getaddrinfo",
        return_value=_make_addrinfo("169.254.1.1"),
    )
    def test_link_local_ipv4(self, mock_dns):
        with pytest.raises(ValueError, match="private/reserved"):
            validate_outbound_url("http://169.254.1.1")

    @patch(
        "app.utils.url_safety.socket.getaddrinfo",
        return_value=_make_addrinfo_v6("fe80::1"),
    )
    def test_link_local_ipv6(self, mock_dns):
        with pytest.raises(ValueError, match="private/reserved"):
            validate_outbound_url("http://[fe80::1]")


@pytest.mark.unit
class TestEmptyAndMissingHost:
    """Edge cases for empty/missing URL components."""

    def test_empty_url(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_outbound_url("")

    def test_url_with_no_host(self):
        with pytest.raises(ValueError, match="(hostname|scheme)"):
            validate_outbound_url("http://")

    def test_none_like_empty(self):
        """Empty string is explicitly rejected."""
        with pytest.raises(ValueError):
            validate_outbound_url("")


@pytest.mark.unit
class TestDnsResolutionFailure:
    """DNS resolution failures should raise ValueError."""

    @patch(
        "app.utils.url_safety.socket.getaddrinfo",
        side_effect=socket.gaierror("Name or service not known"),
    )
    def test_unresolvable_hostname(self, mock_dns):
        with pytest.raises(ValueError, match="Failed to resolve"):
            validate_outbound_url("https://this-does-not-exist.invalid")

    @patch(
        "app.utils.url_safety.socket.getaddrinfo",
        return_value=[],
    )
    def test_hostname_resolves_to_nothing(self, mock_dns):
        with pytest.raises(ValueError, match="resolved to no addresses"):
            validate_outbound_url("https://empty-resolve.example.com")


@pytest.mark.unit
class TestMultipleResolvedAddresses:
    """When a hostname resolves to multiple IPs, all must be safe."""

    @patch(
        "app.utils.url_safety.socket.getaddrinfo",
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0)),
        ],
    )
    def test_one_public_one_private_blocked(self, mock_dns):
        with pytest.raises(ValueError, match="private/reserved"):
            validate_outbound_url("https://dual-homed.example.com")

    @patch(
        "app.utils.url_safety.socket.getaddrinfo",
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
        ],
    )
    def test_all_public_passes(self, mock_dns):
        validate_outbound_url("https://multi-ip.example.com")
