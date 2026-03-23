"""SSRF protection for outbound HTTP requests."""

import ipaddress
import socket
from urllib.parse import urlparse


def validate_outbound_url(url: str) -> None:
    """Validate that a URL is safe for outbound requests (no SSRF).

    Checks scheme, resolves hostname, and blocks private/reserved IP ranges.
    Raises ValueError if the URL is blocked.
    """
    if not url:
        raise ValueError("URL must not be empty")

    parsed = urlparse(url)

    # 1. Scheme check
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme '{parsed.scheme}': only http and https are allowed")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must contain a valid hostname")

    # 2. Resolve hostname to IP addresses
    try:
        addrinfos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"Failed to resolve hostname '{hostname}': {e}") from e

    if not addrinfos:
        raise ValueError(f"Hostname '{hostname}' resolved to no addresses")

    # 3. Check every resolved address against blocked ranges
    for _family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise ValueError(f"Could not parse resolved address '{ip_str}'") from exc

        if _is_blocked(addr):
            raise ValueError(f"URL blocked: hostname '{hostname}' resolves to private/reserved address {addr}")


def validate_outbound_host(host: str) -> str:
    """Validate that a hostname/IP is safe for outbound connections (no SSRF).

    Resolves the hostname, blocks private/reserved IP ranges, and returns the
    first safe IP address string. Use the returned IP for the actual connection
    to prevent DNS rebinding attacks.

    Raises ValueError if blocked.
    """
    if not host:
        raise ValueError("Host must not be empty")

    try:
        addrinfos = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"Failed to resolve hostname '{host}': {e}") from e

    if not addrinfos:
        raise ValueError(f"Hostname '{host}' resolved to no addresses")

    safe_ip: str | None = None
    for _family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise ValueError(f"Could not parse resolved address '{ip_str}'") from exc

        if _is_blocked(addr):
            raise ValueError(f"Host blocked: '{host}' resolves to private/reserved address {addr}")

        if safe_ip is None:
            safe_ip = ip_str

    return safe_ip  # type: ignore[return-value]


async def validate_outbound_host_async(host: str) -> str:
    """Non-blocking wrapper for validate_outbound_host (runs DNS resolution off the event loop)."""
    import asyncio

    return await asyncio.get_running_loop().run_in_executor(None, validate_outbound_host, host)


def _is_blocked(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if the address falls in a private, reserved, loopback, or link-local range."""
    return (
        addr.is_private
        or addr.is_reserved
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
    )
