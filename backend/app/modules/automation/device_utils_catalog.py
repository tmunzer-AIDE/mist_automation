"""
Device utilities catalog for workflow action autocomplete.

Static catalog of mistapi.device_utils functions with metadata
for autocomplete and parameter display in the workflow editor.
"""

from pydantic import BaseModel


class DeviceUtilParam(BaseModel):
    """A parameter for a device utility function."""

    name: str
    description: str = ""
    required: bool = False
    type: str = "string"


class DeviceUtilEntry(BaseModel):
    """A single device utility function in the catalog."""

    id: str
    device_type: str
    function: str
    label: str
    params: list[DeviceUtilParam] = []
    description: str


# ── Common parameter definitions ─────────────────────────────────────────────

_HOST = DeviceUtilParam(name="host", description="Target IP or hostname", required=True)
_COUNT = DeviceUtilParam(name="count", description="Packet count", type="integer")
_SIZE = DeviceUtilParam(name="size", description="Packet size in bytes", type="integer")
_VRF = DeviceUtilParam(name="vrf", description="VRF name")
_TIMEOUT = DeviceUtilParam(name="timeout", description="Command timeout in seconds", type="integer")
_PORT_ID = DeviceUtilParam(name="port_id", description="Port ID", required=True)
_PORT_IDS = DeviceUtilParam(name="port_ids", description="Comma-separated port IDs", required=True)
_NODE = DeviceUtilParam(name="node", description="Node (node0 or node1 for dual-node devices)")
_IP = DeviceUtilParam(name="ip", description="IP address filter")

DEVICE_UTILS_CATALOG: list[DeviceUtilEntry] = [
    # ── AP ────────────────────────────────────────────────────────────────────
    DeviceUtilEntry(
        id="ap_ping",
        device_type="ap",
        function="ping",
        label="Ping",
        params=[_HOST, _COUNT, _SIZE, _VRF, _TIMEOUT],
        description="Send ICMP ping from an Access Point",
    ),
    DeviceUtilEntry(
        id="ap_traceroute",
        device_type="ap",
        function="traceroute",
        label="Traceroute",
        params=[_HOST, _TIMEOUT],
        description="Traceroute from an Access Point",
    ),
    DeviceUtilEntry(
        id="ap_arp",
        device_type="ap",
        function="retrieveArpTable",
        label="Retrieve ARP Table",
        params=[_TIMEOUT],
        description="Retrieve the ARP table from an Access Point",
    ),
    # ── EX ────────────────────────────────────────────────────────────────────
    DeviceUtilEntry(
        id="ex_ping",
        device_type="ex",
        function="ping",
        label="Ping",
        params=[_HOST, _COUNT, _SIZE, _VRF, _TIMEOUT],
        description="Send ICMP ping from an EX switch",
    ),
    DeviceUtilEntry(
        id="ex_monitor_traffic",
        device_type="ex",
        function="monitorTraffic",
        label="Monitor Traffic",
        params=[
            DeviceUtilParam(name="port_id", description="Port ID to monitor (all ports if empty)"),
            _TIMEOUT,
        ],
        description="Monitor traffic on an EX switch port",
    ),
    DeviceUtilEntry(
        id="ex_top",
        device_type="ex",
        function="topCommand",
        label="Top Command",
        params=[_TIMEOUT],
        description="Run top command on an EX switch",
    ),
    DeviceUtilEntry(
        id="ex_arp",
        device_type="ex",
        function="retrieveArpTable",
        label="Retrieve ARP Table",
        params=[_IP, DeviceUtilParam(name="port_id", description="Port ID filter"), _VRF, _TIMEOUT],
        description="Retrieve the ARP table from an EX switch",
    ),
    DeviceUtilEntry(
        id="ex_bgp",
        device_type="ex",
        function="retrieveBgpSummary",
        label="Retrieve BGP Summary",
        params=[_TIMEOUT],
        description="Retrieve BGP neighbor summary from an EX switch",
    ),
    DeviceUtilEntry(
        id="ex_dhcp_leases",
        device_type="ex",
        function="retrieveDhcpLeases",
        label="Retrieve DHCP Leases",
        params=[_TIMEOUT],
        description="Retrieve DHCP leases from an EX switch",
    ),
    DeviceUtilEntry(
        id="ex_release_dhcp",
        device_type="ex",
        function="releaseDhcpLeases",
        label="Release DHCP Leases",
        params=[_TIMEOUT],
        description="Release DHCP leases on an EX switch",
    ),
    DeviceUtilEntry(
        id="ex_mac_table",
        device_type="ex",
        function="retrieveMacTable",
        label="Retrieve MAC Table",
        params=[_TIMEOUT],
        description="Retrieve the MAC address table from an EX switch",
    ),
    DeviceUtilEntry(
        id="ex_clear_mac",
        device_type="ex",
        function="clearMacTable",
        label="Clear MAC Table",
        params=[_TIMEOUT],
        description="Clear the MAC address table on an EX switch",
    ),
    DeviceUtilEntry(
        id="ex_clear_learned_mac",
        device_type="ex",
        function="clearLearnedMac",
        label="Clear Learned MAC",
        params=[_TIMEOUT],
        description="Clear learned MAC addresses on an EX switch",
    ),
    DeviceUtilEntry(
        id="ex_clear_bpdu",
        device_type="ex",
        function="clearBpduError",
        label="Clear BPDU Error",
        params=[_TIMEOUT],
        description="Clear BPDU error on an EX switch port",
    ),
    DeviceUtilEntry(
        id="ex_clear_dot1x",
        device_type="ex",
        function="clearDot1xSessions",
        label="Clear 802.1X Sessions",
        params=[_TIMEOUT],
        description="Clear 802.1X sessions on an EX switch",
    ),
    DeviceUtilEntry(
        id="ex_clear_hit_count",
        device_type="ex",
        function="clearHitCount",
        label="Clear Policy Hit Count",
        params=[_TIMEOUT],
        description="Clear firewall policy hit counters on an EX switch",
    ),
    DeviceUtilEntry(
        id="ex_bounce_port",
        device_type="ex",
        function="bouncePort",
        label="Bounce Port",
        params=[_PORT_IDS, _TIMEOUT],
        description="Bounce (disable/enable) ports on an EX switch",
    ),
    DeviceUtilEntry(
        id="ex_cable_test",
        device_type="ex",
        function="cableTest",
        label="Cable Test",
        params=[_PORT_ID, _TIMEOUT],
        description="Run cable diagnostics on an EX switch port",
    ),
    # ── SRX ───────────────────────────────────────────────────────────────────
    DeviceUtilEntry(
        id="srx_ping",
        device_type="srx",
        function="ping",
        label="Ping",
        params=[_HOST, _COUNT, _SIZE, _VRF, _NODE, _TIMEOUT],
        description="Send ICMP ping from an SRX firewall",
    ),
    DeviceUtilEntry(
        id="srx_monitor_traffic",
        device_type="srx",
        function="monitorTraffic",
        label="Monitor Traffic",
        params=[
            DeviceUtilParam(name="port_id", description="Port ID to monitor (all ports if empty)"),
            _TIMEOUT,
        ],
        description="Monitor traffic on an SRX firewall port",
    ),
    DeviceUtilEntry(
        id="srx_top",
        device_type="srx",
        function="topCommand",
        label="Top Command",
        params=[_TIMEOUT],
        description="Run top command on an SRX firewall",
    ),
    DeviceUtilEntry(
        id="srx_arp",
        device_type="srx",
        function="retrieveArpTable",
        label="Retrieve ARP Table",
        params=[_IP, DeviceUtilParam(name="port_id", description="Port ID filter"), _VRF, _TIMEOUT],
        description="Retrieve the ARP table from an SRX firewall",
    ),
    DeviceUtilEntry(
        id="srx_bgp",
        device_type="srx",
        function="retrieveBgpSummary",
        label="Retrieve BGP Summary",
        params=[_NODE, _TIMEOUT],
        description="Retrieve BGP neighbor summary from an SRX firewall",
    ),
    DeviceUtilEntry(
        id="srx_dhcp_leases",
        device_type="srx",
        function="retrieveDhcpLeases",
        label="Retrieve DHCP Leases",
        params=[_NODE, _TIMEOUT],
        description="Retrieve DHCP leases from an SRX firewall",
    ),
    DeviceUtilEntry(
        id="srx_release_dhcp",
        device_type="srx",
        function="releaseDhcpLeases",
        label="Release DHCP Leases",
        params=[_NODE, _TIMEOUT],
        description="Release DHCP leases on an SRX firewall",
    ),
    DeviceUtilEntry(
        id="srx_ospf_db",
        device_type="srx",
        function="retrieveOspfDatabase",
        label="OSPF Database",
        params=[_NODE, _TIMEOUT],
        description="Retrieve OSPF database from an SRX firewall",
    ),
    DeviceUtilEntry(
        id="srx_ospf_neighbors",
        device_type="srx",
        function="retrieveOspfNeighbors",
        label="OSPF Neighbors",
        params=[_NODE, _TIMEOUT],
        description="Retrieve OSPF neighbors from an SRX firewall",
    ),
    DeviceUtilEntry(
        id="srx_ospf_interfaces",
        device_type="srx",
        function="retrieveOspfInterfaces",
        label="OSPF Interfaces",
        params=[_NODE, _TIMEOUT],
        description="Retrieve OSPF interfaces from an SRX firewall",
    ),
    DeviceUtilEntry(
        id="srx_ospf_summary",
        device_type="srx",
        function="retrieveOspfSummary",
        label="OSPF Summary",
        params=[_NODE, _TIMEOUT],
        description="Retrieve OSPF summary from an SRX firewall",
    ),
    DeviceUtilEntry(
        id="srx_bounce_port",
        device_type="srx",
        function="bouncePort",
        label="Bounce Port",
        params=[_PORT_IDS, _TIMEOUT],
        description="Bounce (disable/enable) ports on an SRX firewall",
    ),
    DeviceUtilEntry(
        id="srx_routes",
        device_type="srx",
        function="retrieveRoutes",
        label="Retrieve Routes",
        params=[_NODE, _TIMEOUT],
        description="Retrieve routing table from an SRX firewall",
    ),
    DeviceUtilEntry(
        id="srx_sessions",
        device_type="srx",
        function="retrieveSessions",
        label="Retrieve Sessions",
        params=[_NODE, _TIMEOUT],
        description="Retrieve active sessions from an SRX firewall",
    ),
    DeviceUtilEntry(
        id="srx_clear_sessions",
        device_type="srx",
        function="clearSessions",
        label="Clear Sessions",
        params=[_NODE, _TIMEOUT],
        description="Clear active sessions on an SRX firewall",
    ),
    # ── SSR ───────────────────────────────────────────────────────────────────
    DeviceUtilEntry(
        id="ssr_ping",
        device_type="ssr",
        function="ping",
        label="Ping",
        params=[_HOST, _COUNT, _SIZE, _VRF, _NODE, _TIMEOUT],
        description="Send ICMP ping from an SSR router",
    ),
    DeviceUtilEntry(
        id="ssr_arp",
        device_type="ssr",
        function="retrieveArpTable",
        label="Retrieve ARP Table",
        params=[_NODE, _TIMEOUT],
        description="Retrieve the ARP table from an SSR router",
    ),
    DeviceUtilEntry(
        id="ssr_bgp",
        device_type="ssr",
        function="retrieveBgpSummary",
        label="Retrieve BGP Summary",
        params=[_NODE, _TIMEOUT],
        description="Retrieve BGP neighbor summary from an SSR router",
    ),
    DeviceUtilEntry(
        id="ssr_dhcp_leases",
        device_type="ssr",
        function="retrieveDhcpLeases",
        label="Retrieve DHCP Leases",
        params=[_NODE, _TIMEOUT],
        description="Retrieve DHCP leases from an SSR router",
    ),
    DeviceUtilEntry(
        id="ssr_release_dhcp",
        device_type="ssr",
        function="releaseDhcpLeases",
        label="Release DHCP Leases",
        params=[_NODE, _TIMEOUT],
        description="Release DHCP leases on an SSR router",
    ),
    DeviceUtilEntry(
        id="ssr_ospf_db",
        device_type="ssr",
        function="retrieveOspfDatabase",
        label="OSPF Database",
        params=[_NODE, _TIMEOUT],
        description="Retrieve OSPF database from an SSR router",
    ),
    DeviceUtilEntry(
        id="ssr_ospf_neighbors",
        device_type="ssr",
        function="retrieveOspfNeighbors",
        label="OSPF Neighbors",
        params=[_NODE, _TIMEOUT],
        description="Retrieve OSPF neighbors from an SSR router",
    ),
    DeviceUtilEntry(
        id="ssr_ospf_interfaces",
        device_type="ssr",
        function="retrieveOspfInterfaces",
        label="OSPF Interfaces",
        params=[_NODE, _TIMEOUT],
        description="Retrieve OSPF interfaces from an SSR router",
    ),
    DeviceUtilEntry(
        id="ssr_ospf_summary",
        device_type="ssr",
        function="retrieveOspfSummary",
        label="OSPF Summary",
        params=[_NODE, _TIMEOUT],
        description="Retrieve OSPF summary from an SSR router",
    ),
    DeviceUtilEntry(
        id="ssr_bounce_port",
        device_type="ssr",
        function="bouncePort",
        label="Bounce Port",
        params=[_PORT_IDS, _TIMEOUT],
        description="Bounce (disable/enable) ports on an SSR router",
    ),
    DeviceUtilEntry(
        id="ssr_routes",
        device_type="ssr",
        function="retrieveRoutes",
        label="Retrieve Routes",
        params=[_NODE, _TIMEOUT],
        description="Retrieve routing table from an SSR router",
    ),
    DeviceUtilEntry(
        id="ssr_service_path",
        device_type="ssr",
        function="showServicePath",
        label="Show Service Path",
        params=[_TIMEOUT],
        description="Show service path from an SSR router",
    ),
    DeviceUtilEntry(
        id="ssr_sessions",
        device_type="ssr",
        function="retrieveSessions",
        label="Retrieve Sessions",
        params=[_NODE, _TIMEOUT],
        description="Retrieve active sessions from an SSR router",
    ),
    DeviceUtilEntry(
        id="ssr_clear_sessions",
        device_type="ssr",
        function="clearSessions",
        label="Clear Sessions",
        params=[_NODE, _TIMEOUT],
        description="Clear active sessions on an SSR router",
    ),
]

# Security: allowlist of valid (device_type, function) pairs.
# The executor validates against this BEFORE calling getattr().
_ALLOWED_CALLS: frozenset[tuple[str, str]] = frozenset(
    (e.device_type, e.function) for e in DEVICE_UTILS_CATALOG
)


def is_allowed(device_type: str, function: str) -> bool:
    """Check if a (device_type, function) pair is in the allowlist."""
    return (device_type, function) in _ALLOWED_CALLS
