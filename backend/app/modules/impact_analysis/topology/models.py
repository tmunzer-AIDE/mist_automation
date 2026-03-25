"""All data models for the Mist topology MCP server."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


@dataclass
class VCMember:
    fpc_idx: int
    mac: str
    model: str
    role: str  # "master" | "backup" | "linecard"
    status: str


@dataclass
class Device:
    id: str
    name: str
    mac: str
    model: str
    site_id: str

    ip: str = ""
    serial: str = ""

    status: str = "unknown"  # "connected" | "disconnected" | "unknown"
    uptime: int = 0
    firmware: str = ""
    last_seen: int = 0
    alarm_count: int = 0

    is_virtual_chassis: bool = False
    vc_members: list[VCMember] = field(default_factory=list)
    vc_mac: str = ""

    mclag_peer_id: str = ""
    mclag_domain_id: str = ""

    device_type: str = ""  # "switch" | "gateway" | "ap"

    port_config: dict = field(default_factory=dict)
    port_usages: dict = field(default_factory=dict)
    networks: dict = field(default_factory=dict)
    dhcpd_config: dict = field(default_factory=dict)
    raw_stats: dict = field(default_factory=dict)

    def matches(self, identifier: str) -> bool:
        identifier = identifier.strip().lower()
        return identifier in (
            self.id.lower(),
            self.name.lower(),
            self.mac.lower(),
            self.ip.lower(),
        )


class LinkType(str, Enum):
    STANDALONE = "STANDALONE"
    LAG = "LAG"
    MCLAG = "MCLAG"
    VC_ICL = "VC_ICL"
    MCLAG_ICL = "MCLAG_ICL"
    FABRIC = "FABRIC"


class LinkStatus(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


@dataclass
class PhysicalLink:
    local_port: str
    remote_port: str
    status: LinkStatus = LinkStatus.UNKNOWN


@dataclass
class LogicalGroup:
    group_type: str  # "VC" | "MCLAG" | "FABRIC"
    group_id: str
    member_ids: list[str] = field(default_factory=list)


@dataclass
class Connection:
    local_device_id: str
    remote_device_id: str
    link_type: LinkType = LinkType.STANDALONE
    local_ae: str | None = None
    remote_ae: str | None = None
    physical_links: list[PhysicalLink] = field(default_factory=list)
    port_profile: str | None = None
    vlan_mode: str | None = None
    access_vlan: str | None = None
    trunk_vlans: list[str] = field(default_factory=list)
    native_vlan: str | None = None
    status: LinkStatus = LinkStatus.UNKNOWN
    esi: str | None = None
    mclag_domain_id: str | None = None

    @property
    def local_ae_display(self) -> str:
        if not self.local_ae:
            return self.physical_links[0].local_port if self.physical_links else ""
        members = ",".join(pl.local_port for pl in self.physical_links)
        return f"{self.local_ae} ({members})" if members else self.local_ae

    @property
    def remote_ae_display(self) -> str:
        if not self.remote_ae:
            return self.physical_links[0].remote_port if self.physical_links else ""
        members = ",".join(pl.remote_port for pl in self.physical_links)
        return f"{self.remote_ae} ({members})" if members else self.remote_ae

    def vlan_summary(self) -> str:
        if self.vlan_mode == "access" and self.access_vlan:
            return f"access:{self.access_vlan}"
        parts = []
        if self.trunk_vlans:
            parts.append(f"trunk:{','.join(self.trunk_vlans)}")
        if self.native_vlan:
            parts.append(f"native:{self.native_vlan}")
        return " ".join(parts) if parts else ""


@dataclass
class SiteTopology:
    site_id: str
    site_name: str = ""
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))

    devices: dict[str, Device] = field(default_factory=dict)
    connections: list[Connection] = field(default_factory=list)
    logical_groups: list[LogicalGroup] = field(default_factory=list)
    vlan_map: dict[str, str] = field(default_factory=dict)
    subnet_map: dict[str, str] = field(default_factory=dict)

    _adj: dict[str, list[Connection]] = field(default_factory=dict, repr=False)

    def build_adj(self) -> None:
        self._adj = {}
        for conn in self.connections:
            self._adj.setdefault(conn.local_device_id, []).append(conn)
            self._adj.setdefault(conn.remote_device_id, []).append(conn)

    def neighbors(self, device_id: str) -> list[Connection]:
        return self._adj.get(device_id, [])

    def resolve_device(self, identifier: str) -> Device | None:
        identifier = identifier.strip().lower()
        if identifier in self.devices:
            return self.devices[identifier]
        for device in self.devices.values():
            if device.matches(identifier):
                return device
        return None

    @property
    def device_count(self) -> int:
        return len(self.devices)

    @property
    def connection_count(self) -> int:
        return len(self.connections)
