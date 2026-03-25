"""Raw site data container for the topology builder."""

from dataclasses import dataclass, field


@dataclass
class RawSiteData:
    """Raw payloads from the Mist API endpoints."""

    port_stats: list[dict]  # searchSiteSwOrGwPorts — LLDP + port stats
    devices: list[dict]  # listSiteDevices — port_config, VLANs, VC info
    devices_stats: list[dict]  # listSiteDevicesStats — uptime, status, IP
    alarms: list[dict] = field(default_factory=list)
    site_setting: dict = field(default_factory=dict)  # getSiteSettingDerived
    org_networks: list[dict] = field(default_factory=list)  # listOrgNetworks
    gateway_template: dict | None = None  # getOrgGatewayTemplate
