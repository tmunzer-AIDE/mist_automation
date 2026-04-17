"""
Site snapshot: dataclasses + builders for the new check engine.

Provides:
- DeviceSnapshot / LiveSiteData / SiteSnapshot dataclasses
- fetch_live_data() — one org-level API call for LLDP, port status, client counts
- build_site_snapshot() — assemble snapshot from backup + live data + optional overrides
"""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.modules.digital_twin.services.state_resolver import (
    StateKey,
    canonicalize_object_type,
    load_all_objects_of_type,
)

logger = structlog.get_logger(__name__)

_DELETED_SENTINEL_KEY = "__twin_deleted__"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DeviceSnapshot:
    device_id: str
    mac: str
    name: str
    type: str  # "ap" | "switch" | "gateway"
    model: str
    port_config: dict[str, dict[str, Any]]  # port_name -> {usage, vlan_id, ...}
    ip_config: dict[str, dict[str, Any]]  # network_name -> {ip, netmask, type}
    dhcpd_config: dict[str, Any]
    resolved_port_config: dict[str, dict[str, Any]] | None = None
    oob_ip_config: dict[str, Any] | None = None
    port_usages: dict[str, dict[str, Any]] | None = None  # device-level overrides
    ospf_config: dict[str, Any] | None = None
    bgp_config: dict[str, Any] | None = None
    extra_routes: list[dict[str, Any]] | None = None
    stp_config: dict[str, Any] | None = None
    effective_config: dict[str, Any] | None = None


@dataclass
class LiveSiteData:
    lldp_neighbors: dict[str, dict[str, str]]  # device_mac -> {port_id -> neighbor_mac}
    port_status: dict[str, dict[str, bool]]  # device_mac -> {port_id -> up/down}
    ap_clients: dict[str, int]  # device_id -> wireless client count
    port_devices: dict[str, dict[str, str]]  # device_mac -> {port_id -> connected_mac}
    ospf_peers: dict[str, list[dict]] = field(default_factory=dict)
    bgp_peers: dict[str, list[dict]] = field(default_factory=dict)


@dataclass
class SiteSnapshot:
    site_id: str
    site_name: str
    site_setting: dict[str, Any]
    networks: dict[str, dict[str, Any]]  # network_id -> config
    wlans: dict[str, dict[str, Any]]  # wlan_id -> config
    devices: dict[str, DeviceSnapshot]  # device_id -> compiled device
    port_usages: dict[str, dict[str, Any]]  # profile_name -> profile config
    lldp_neighbors: dict[str, dict[str, str]]
    port_status: dict[str, dict[str, bool]]
    ap_clients: dict[str, int]
    port_devices: dict[str, dict[str, str]]
    ospf_peers: dict[str, list[dict]] = field(default_factory=dict)
    bgp_peers: dict[str, list[dict]] = field(default_factory=dict)


@dataclass
class SiteSnapshotSourceData:
    """Preloaded backup objects used to build one or more site snapshots."""

    site_devices: list[dict[str, Any]]
    site_networks: list[dict[str, Any]]
    org_networks: list[dict[str, Any]]
    site_wlans: list[dict[str, Any]]
    site_settings_list: list[dict[str, Any]]
    site_info_cfg: dict[str, Any]
    org_networktemplates: list[dict[str, Any]]
    org_gatewaytemplates: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Live data extraction helpers
# ---------------------------------------------------------------------------


def _extract_lldp_from_stats(device_stats: dict[str, Any]) -> dict[str, str]:
    """Extract LLDP neighbor map from a device stats payload.

    Mist ``clients[]`` entries with ``source == "lldp"`` have a ``port_ids``
    field (plural, list of port names) -- NOT ``port_id`` (singular).

    Returns:
        dict mapping port_id -> neighbor_mac
    """
    neighbors: dict[str, str] = {}
    for client in device_stats.get("clients", []):
        if client.get("source") == "lldp":
            neighbor_mac = client.get("mac", "")
            if not neighbor_mac:
                continue
            for port_id in client.get("port_ids", []):
                normalized = _normalize_port_id(port_id)
                if normalized:
                    neighbors[normalized] = neighbor_mac
    return neighbors


def _extract_port_status(device_stats: dict[str, Any]) -> dict[str, bool]:
    """Extract port up/down from ``if_stat`` field.

    Returns:
        dict mapping normalized port_id -> True (up) / False (down)
    """
    result: dict[str, bool] = {}
    if_stat = device_stats.get("if_stat")
    if not if_stat or not isinstance(if_stat, dict):
        return result
    for port_id, stat in if_stat.items():
        if isinstance(stat, dict):
            normalized = _normalize_port_id(port_id)
            if normalized:
                result[normalized] = stat.get("up", False)
    return result


def _extract_client_count(device_stats: dict[str, Any]) -> int:
    """Extract wireless client count from ``clients_stats.total`` or ``num_clients``.

    Returns:
        Client count (0 when missing).
    """
    clients_stats = device_stats.get("clients_stats")
    if isinstance(clients_stats, dict):
        total = clients_stats.get("total")
        if total is not None:
            try:
                return int(total)
            except (TypeError, ValueError):
                pass

    num_clients = device_stats.get("num_clients", 0) or 0
    try:
        return int(num_clients)
    except (TypeError, ValueError):
        return 0


def _extract_port_devices(device_stats: dict[str, Any]) -> dict[str, str]:
    """Extract connected device MACs from LLDP clients, keyed by normalized port.

    Unlike _extract_lldp_from_stats which is neighbour-centric, this maps
    every LLDP client to the port it occupies regardless of source.
    """
    result: dict[str, str] = {}
    for client in device_stats.get("clients", []):
        mac = client.get("mac", "")
        if not mac:
            continue
        for port_id in client.get("port_ids", []):
            normalized = _normalize_port_id(port_id)
            if normalized:
                result[normalized] = mac
    return result


def _extract_peer_ip(peer: dict[str, Any]) -> str:
    """Extract peer IP from heterogeneous protocol telemetry schemas."""
    for key in ("peer_ip", "neighbor_ip", "peer", "neighbor", "ip"):
        value = peer.get(key)
        if value:
            return str(value)
    return ""


def _extract_peer_entries(raw: Any) -> list[dict[str, Any]]:
    """Normalize protocol peer payloads to a list of dict entries."""
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]

    if isinstance(raw, dict):
        entries: list[dict[str, Any]] = []
        for key in ("neighbors", "peers", "sessions", "adjacencies", "results"):
            items = raw.get(key)
            if isinstance(items, list):
                entries.extend(item for item in items if isinstance(item, dict))
        return entries

    return []


def _extract_protocol_peers(device_stats: dict[str, Any], protocol: str) -> list[dict[str, Any]]:
    """Extract protocol peers from common stats payload shapes.

    Supports flat and nested forms seen in Mist telemetry payloads.
    """
    candidates: list[Any] = [
        device_stats.get(f"{protocol}_neighbors"),
        device_stats.get(f"{protocol}_peers"),
        device_stats.get(f"{protocol}_sessions"),
        device_stats.get(f"{protocol}_adjacencies"),
        device_stats.get(f"{protocol}_stats"),
    ]

    routing = device_stats.get("routing")
    if isinstance(routing, dict):
        candidates.append(routing.get(protocol))
        candidates.append(routing.get(f"{protocol}_stats"))

    peers: list[dict[str, Any]] = []
    seen_peer_ips: set[str] = set()

    for candidate in candidates:
        for entry in _extract_peer_entries(candidate):
            peer_ip = _extract_peer_ip(entry)
            if not peer_ip or peer_ip in seen_peer_ips:
                continue
            normalized = dict(entry)
            normalized["peer_ip"] = peer_ip
            peers.append(normalized)
            seen_peer_ips.add(peer_ip)

    return peers


# ---------------------------------------------------------------------------
# fetch_live_data — parallel org/site API calls
# ---------------------------------------------------------------------------


def normalize_mac(value: Any) -> str:
    """Lowercase/strip a MAC returned by the Mist API.

    Mist sometimes returns MACs as colon-separated uppercase, sometimes as
    plain lowercase — we normalize to match the form stored in backups.
    """
    if not value:
        return ""
    return str(value).replace(":", "").replace("-", "").lower()


# Backwards-compat alias (module-private name still referenced elsewhere).
_normalize_mac = normalize_mac


def _normalize_port_id(port_id: Any) -> str:
    """Normalize a live-data port id using the shared topology helper.

    Lazy import to avoid a module-level circular dependency: ``topology_utils``
    imports ``SiteSnapshot`` from this module at load time. Calling the
    helper at runtime — after both modules have finished loading — is safe.
    """
    from app.modules.digital_twin.services.topology_utils import normalize_port_id

    return normalize_port_id(port_id)


def _deep_merge_singleton(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` on top of ``base``.

    Nested dicts are merged key-wise so partial PUTs (e.g. updating only
    ``settings.vars.foo``) don't erase sibling keys at any nesting level.
    Scalars and lists are replaced wholesale, matching Mist partial-PUT
    semantics for leaf values. Used by :func:`build_site_snapshot`'s
    singleton-override pipeline.
    """
    result = dict(base)
    for key, value in override.items():
        existing_value = result.get(key)
        if isinstance(existing_value, dict) and isinstance(value, dict):
            result[key] = _deep_merge_singleton(existing_value, value)
        else:
            result[key] = value
    return result


def _extract_lldp_from_ap_stat(device_stats: dict[str, Any]) -> tuple[str, str] | None:
    """Extract switch MAC and port from an AP's ``lldp_stat`` field.

    Returns:
        (switch_mac, switch_port) or None.
    """
    lldp_stat = device_stats.get("lldp_stat")
    if not isinstance(lldp_stat, dict):
        return None

    chassis_id = _normalize_mac(lldp_stat.get("chassis_id"))
    port_id = lldp_stat.get("port_id")

    if chassis_id and port_id:
        return chassis_id, str(port_id)
    return None


async def fetch_live_data(site_id: str, org_id: str) -> LiveSiteData:
    """Fetch live device stats and port/LLDP data for a site.

    Runs two Mist API calls in parallel:
    - ``listOrgDevicesStats(fields="*")`` — AP client counts and AP-side LLDP
      neighbours (``clients[]`` with ``source="lldp"`` AND ``lldp_stat``)
    - ``searchSiteSwOrGwPorts(limit=1000)`` — switch/gateway port records
      including ``neighbor_mac`` / ``up`` / ``port_id``, which is the
      authoritative LLDP source for switches and gateways

    Falls back to an empty field whenever a call fails; both sources are
    merged so APs and switches each contribute their best data.
    """
    lldp_neighbors: dict[str, dict[str, str]] = {}
    port_status: dict[str, dict[str, bool]] = {}
    ap_clients: dict[str, int] = {}
    port_devices: dict[str, dict[str, str]] = {}
    ospf_peers: dict[str, list[dict[str, Any]]] = {}
    bgp_peers: dict[str, list[dict[str, Any]]] = {}

    try:
        import mistapi
        from mistapi.api.v1.orgs import stats as org_stats
        from mistapi.api.v1.sites import stats as site_stats

        from app.services.mist_service_factory import create_mist_service

        mist = await create_mist_service()
        session = mist.get_session()

        stats_resp, ports_resp = await asyncio.gather(
            mistapi.arun(
                org_stats.listOrgDevicesStats,
                session,
                org_id,
                site_id=site_id,
                fields="*",
            ),
            mistapi.arun(
                site_stats.searchSiteSwOrGwPorts,
                session,
                site_id,
                limit=1000,
            ),
            return_exceptions=True,
        )

        # ── listOrgDevicesStats: AP client counts + AP-side LLDP ──
        devices_list: list[dict[str, Any]] = []
        has_l2_device = False
        if isinstance(stats_resp, BaseException):
            logger.warning("live_data_org_stats_failed", site_id=site_id, error=str(stats_resp))
        elif stats_resp.status_code != 200:
            logger.warning("live_data_org_stats_error", site_id=site_id, status=stats_resp.status_code)
        else:
            if stats_resp.data:
                devices_list = (
                    stats_resp.data if isinstance(stats_resp.data, list) else stats_resp.data.get("results", [])
                )
            for device_stats in devices_list:
                mac = _normalize_mac(device_stats.get("mac", ""))
                device_id = device_stats.get("id", "")
                dtype = device_stats.get("type")

                if dtype in ("switch", "gateway"):
                    has_l2_device = True

                if mac:
                    neighbors = _extract_lldp_from_stats(device_stats)
                    if neighbors:
                        lldp_neighbors.setdefault(mac, {}).update(
                            {p: _normalize_mac(n) for p, n in neighbors.items() if n}
                        )

                    # AP-side LLDP: use lldp_stat to find the upstream switch and port.
                    # This allows us to "symmetrize" the link even when the switch
                    # side LLDP is missing or disabled, ensuring PORT-DISC on the
                    # switch side correctly identifies the connected AP.
                    if dtype == "ap":
                        upstream = _extract_lldp_from_ap_stat(device_stats)
                        if upstream:
                            sw_mac, sw_port = upstream
                            # Add reverse edge: Switch MAC -> {Port -> AP MAC}
                            sw_port_norm = _normalize_port_id(sw_port)
                            if sw_port_norm:
                                lldp_neighbors.setdefault(sw_mac, {})[sw_port_norm] = mac
                                port_devices.setdefault(sw_mac, {})[sw_port_norm] = mac

                    ports = _extract_port_status(device_stats)
                    if ports:
                        port_status.setdefault(mac, {}).update(ports)

                    pd = _extract_port_devices(device_stats)
                    if pd:
                        port_devices.setdefault(mac, {}).update({p: _normalize_mac(n) for p, n in pd.items() if n})

                if device_id:
                    count = _extract_client_count(device_stats)
                    if count > 0:
                        ap_clients[device_id] = count

                    ospf = _extract_protocol_peers(device_stats, "ospf")
                    if ospf:
                        ospf_peers[device_id] = ospf

                    bgp = _extract_protocol_peers(device_stats, "bgp")
                    if bgp:
                        bgp_peers[device_id] = bgp

        # ── searchSiteSwOrGwPorts: authoritative switch/gateway LLDP + port state ──
        port_stats_list: list[dict[str, Any]] = []
        if isinstance(ports_resp, BaseException):
            logger.warning("live_data_port_stats_failed", site_id=site_id, error=str(ports_resp))
        elif ports_resp.status_code != 200:
            logger.warning("live_data_port_stats_error", site_id=site_id, status=ports_resp.status_code)
        else:
            if ports_resp.data:
                port_stats_list = (
                    ports_resp.data if isinstance(ports_resp.data, list) else ports_resp.data.get("results", [])
                )
            port_lldp_added = 0
            for ps in port_stats_list:
                dev_mac = _normalize_mac(ps.get("mac"))
                port_id = _normalize_port_id(ps.get("port_id"))
                if not dev_mac or not port_id:
                    continue

                up = ps.get("up")
                if up is not None:
                    port_status.setdefault(dev_mac, {})[port_id] = bool(up)

                neighbor_mac = _normalize_mac(ps.get("neighbor_mac"))
                if neighbor_mac:
                    lldp_neighbors.setdefault(dev_mac, {})[port_id] = neighbor_mac
                    port_devices.setdefault(dev_mac, {})[port_id] = neighbor_mac
                    port_lldp_added += 1

            logger.info(
                "live_data_port_stats",
                site_id=site_id,
                port_records=len(port_stats_list),
                lldp_edges=port_lldp_added,
            )

        # Surface missing LLDP so port-impact checks that rely on it aren't silently
        # downgraded to "skipped" without operators knowing why.
        if has_l2_device and not lldp_neighbors:
            logger.warning(
                "live_data_no_lldp",
                site_id=site_id,
                device_count=len(devices_list),
                port_record_count=len(port_stats_list),
                hint=(
                    "Neither listOrgDevicesStats clients[].source='lldp' nor "
                    "searchSiteSwOrGwPorts returned LLDP neighbours for this site; "
                    "port_impact checks will be skipped"
                ),
            )

    except Exception:
        logger.exception("live_data_fetch_failed", site_id=site_id)

    return LiveSiteData(
        lldp_neighbors=lldp_neighbors,
        port_status=port_status,
        ap_clients=ap_clients,
        port_devices=port_devices,
        ospf_peers=ospf_peers,
        bgp_peers=bgp_peers,
    )


# ---------------------------------------------------------------------------
# Snapshot builder helpers
# ---------------------------------------------------------------------------


async def _load_site_objects(
    org_id: str,
    object_type: str,
    site_id: str | None = None,
) -> list[dict[str, Any]]:
    """Thin wrapper around state_resolver.load_all_objects_of_type()."""
    canonical_type = canonicalize_object_type(object_type) or object_type

    # For inherited networks, only include org-scoped networks. Without this
    # filter, site-scoped network backups from other sites pollute the snapshot.
    org_level_only = canonical_type == "networks" and site_id is None
    return await load_all_objects_of_type(
        org_id,
        canonical_type,
        site_id=site_id,
        org_level_only=org_level_only,
    )


async def _load_site_info_config(org_id: str, site_id: str) -> dict[str, Any]:
    """Resolve the site info config from whichever backup shape carries it.

    Mist site identity/template assignments can land in three different
    backup shapes depending on how the backup tool captured them:

    - ``object_type="info"`` at site scope (site-level singleton, newer format)
    - ``object_type="site"`` at site scope (legacy site-level singleton)
    - ``object_type="sites"`` at org level (entry in the org-wide sites list)

    The first two paths go through :func:`_load_site_objects` so tests that
    patch that helper still work; the third queries ``BackupObject`` directly
    because it's an org-level collection whose records are identified by
    ``object_id`` rather than ``site_id``. Returns the first non-empty match or
    an empty dict.
    """
    # Path 1: new site-level singleton
    info_docs = await _load_site_objects(org_id, "info", site_id=site_id)
    if info_docs:
        return dict(info_docs[0])

    # Path 2: legacy alias — state_resolver canonicalizes "site" -> "info", so
    # _load_site_objects already covers this under the "info" query above.

    # Path 3: org-level "sites" list. Query BackupObject directly because the
    # record is keyed by object_id, not site_id — outside the _load_site_objects
    # shape. Tests that don't populate this path simply get an empty dict.
    try:
        from app.modules.backup.models import BackupObject

        doc = (
            await BackupObject.find(
                {
                    "object_type": "sites",
                    "object_id": site_id,
                    "org_id": org_id,
                    "is_deleted": False,
                }
            )
            .sort([("version", -1)])
            .first_or_none()
        )
        if doc and doc.configuration:
            return dict(doc.configuration)
    except Exception:
        logger.debug("site_info_sites_lookup_failed", site_id=site_id, exc_info=True)
    return {}


async def load_site_snapshot_source_data(site_id: str, org_id: str) -> SiteSnapshotSourceData:
    """Load backup objects required by build_site_snapshot for one site.

    This allows callers to reuse the same preloaded data for baseline and
    predicted snapshot builds in a simulation pass.
    """
    gathered = await asyncio.gather(
        _load_site_objects(org_id, "devices", site_id=site_id),
        _load_site_objects(org_id, "networks", site_id=site_id),
        _load_site_objects(org_id, "networks"),
        _load_site_objects(org_id, "wlans", site_id=site_id),
        _load_site_objects(org_id, "settings", site_id=site_id),
        _load_site_info_config(org_id, site_id),
        _load_site_objects(org_id, "networktemplates"),
        _load_site_objects(org_id, "gatewaytemplates"),
    )

    return SiteSnapshotSourceData(
        site_devices=gathered[0],
        site_networks=gathered[1],
        org_networks=gathered[2],
        site_wlans=gathered[3],
        site_settings_list=gathered[4],
        site_info_cfg=gathered[5],
        org_networktemplates=gathered[6],
        org_gatewaytemplates=gathered[7],
    )


def _build_device_snapshot(config: dict[str, Any]) -> DeviceSnapshot:
    """Convert a raw/compiled device config dict into a DeviceSnapshot.

    Handles both ``ip_config`` and ``ip_configs`` field names (Mist uses both).
    """
    # Mist uses ip_configs (plural) on gateways, ip_config on others
    ip_config = config.get("ip_config") or config.get("ip_configs") or {}

    return DeviceSnapshot(
        device_id=config.get("id", ""),
        mac=_normalize_mac(config.get("mac", "")),
        name=config.get("name", ""),
        type=config.get("type", ""),
        model=config.get("model", ""),
        port_config=config.get("port_config") or {},
        resolved_port_config=config.get("resolved_port_config"),
        ip_config=ip_config,
        dhcpd_config=config.get("dhcpd_config") or {},
        oob_ip_config=config.get("oob_ip_config"),
        port_usages=config.get("port_usages"),
        ospf_config=config.get("ospf_config"),
        bgp_config=config.get("bgp_config"),
        extra_routes=config.get("extra_routes"),
        stp_config=config.get("stp_config"),
        effective_config=config,
    )


# ---------------------------------------------------------------------------
# build_site_snapshot
# ---------------------------------------------------------------------------


async def build_site_snapshot(
    site_id: str,
    org_id: str,
    live_data: LiveSiteData,
    state_overrides: dict[StateKey, dict[str, Any]] | None = None,
    source_data: SiteSnapshotSourceData | None = None,
) -> SiteSnapshot:
    """Assemble a full SiteSnapshot from backup data, live data, and optional overrides.

    Args:
        site_id: Mist site ID.
        org_id: Mist org ID.
        live_data: Pre-fetched live data from fetch_live_data().
        state_overrides: Optional dict of (object_type, site_id, object_id) -> config
            to replace backup values (e.g. from staged writes).
        source_data: Optional preloaded backup object set for this site.
    """
    overrides = state_overrides or {}

    if source_data is None:
        source_data = await load_site_snapshot_source_data(site_id, org_id)

    # Build from deep-copied source_data so baseline/predicted builds can reuse
    # one loaded source object safely without cross-mutation.
    site_devices: list[dict[str, Any]] = copy.deepcopy(source_data.site_devices)
    site_networks: list[dict[str, Any]] = copy.deepcopy(source_data.site_networks)
    org_networks: list[dict[str, Any]] = copy.deepcopy(source_data.org_networks)
    site_wlans: list[dict[str, Any]] = copy.deepcopy(source_data.site_wlans)
    site_settings_list: list[dict[str, Any]] = copy.deepcopy(source_data.site_settings_list)
    site_info_cfg: dict[str, Any] = copy.deepcopy(source_data.site_info_cfg)
    org_networktemplates: list[dict[str, Any]] = copy.deepcopy(source_data.org_networktemplates)
    org_gatewaytemplates: list[dict[str, Any]] = copy.deepcopy(source_data.org_gatewaytemplates)

    # Normalize site info to the list-wrapped shape the singleton-override helper expects.
    site_info_list: list[dict[str, Any]] = [site_info_cfg] if site_info_cfg else []

    def _iter_overrides(
        object_type: str,
        scope_site_id: str | None,
    ) -> list[tuple[str | None, dict[str, Any]]]:
        canonical_target = canonicalize_object_type(object_type) or object_type
        matched: list[tuple[str | None, dict[str, Any]]] = []

        for (ov_type, ov_site_id, ov_object_id), ov_config in overrides.items():
            canonical_override = canonicalize_object_type(ov_type) or ov_type
            if canonical_override != canonical_target:
                continue
            if ov_site_id != scope_site_id:
                continue
            matched.append((ov_object_id, ov_config))

        return matched

    # Apply state overrides to collection objects (devices/networks/wlans):
    # replace changed objects, append new ones (POST), and remove deleted ones.
    def _apply_overrides(
        objects: list[dict[str, Any]],
        object_type: str,
        scope_site_id: str | None,
    ) -> list[dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}
        for obj in objects:
            obj_id = obj.get("id")
            if obj_id:
                by_id[obj_id] = obj

        for ov_object_id, ov_config in _iter_overrides(object_type, scope_site_id):
            if not ov_object_id:
                continue
            if ov_config.get(_DELETED_SENTINEL_KEY):
                by_id.pop(ov_object_id, None)
            else:
                by_id[ov_object_id] = ov_config

        return list(by_id.values())

    # Apply state override to singleton objects (settings/info).
    def _apply_singleton_override(
        objects: list[dict[str, Any]],
        object_type: str,
        scope_site_id: str | None,
    ) -> list[dict[str, Any]]:
        singleton_override: dict[str, Any] | None = None

        for ov_object_id, ov_config in _iter_overrides(object_type, scope_site_id):
            if ov_object_id is None:
                singleton_override = ov_config

        if singleton_override is None:
            return objects
        if singleton_override.get(_DELETED_SENTINEL_KEY):
            return []
        # Deep-merge the staged write on top of the existing singleton so a
        # partial PUT (e.g. updating only `vars.foo`) doesn't wipe sibling
        # keys at any nesting level. Mirrors the merge done in
        # config_compiler._compile_site_devices.
        existing = objects[0] if objects else {}
        return [_deep_merge_singleton(existing, singleton_override)]

    site_devices = _apply_overrides(site_devices, "devices", site_id)
    site_networks = _apply_overrides(site_networks, "networks", site_id)
    org_networks = _apply_overrides(org_networks, "networks", None)
    site_wlans = _apply_overrides(site_wlans, "wlans", site_id)
    org_networktemplates = _apply_overrides(org_networktemplates, "networktemplates", None)
    org_gatewaytemplates = _apply_overrides(org_gatewaytemplates, "gatewaytemplates", None)
    site_settings_list = _apply_singleton_override(site_settings_list, "settings", site_id)
    site_info_list = _apply_singleton_override(site_info_list, "info", site_id)

    # Extract site info
    site_info = site_info_list[0] if site_info_list else {}
    site_name = site_info.get("name", "")
    networktemplate_id = site_info.get("networktemplate_id")
    gatewaytemplate_id = site_info.get("gatewaytemplate_id")

    # Extract site setting
    site_setting = site_settings_list[0] if site_settings_list else {}

    # Extract port_usages from site_setting
    port_usages: dict[str, dict[str, Any]] = site_setting.get("port_usages") or {}

    # ── Network scoping ──
    # Org-level networks are filtered to only those referenced by the templates
    # actually assigned to this site (plus inline site-setting networks). Without
    # this filter, org_networks carries every network from every template in the
    # org, producing false CFG-SUBNET overlaps between networks that never
    # co-exist on any real site.
    #
    # When no template or site-info hint is available (e.g. a partially-backed-up
    # org or an isolated unit test), we fall back to including every org network
    # so that the old behaviour and existing tests still work.
    referenced_names: set[str] = set()
    template_overrides: dict[str, dict[str, Any]] = {}

    def _collect_template_networks(tmpl_list: list[dict[str, Any]], tmpl_id: str | None) -> None:
        if not tmpl_id:
            return
        for tmpl in tmpl_list:
            if tmpl.get("id") != tmpl_id:
                continue
            tmpl_networks = tmpl.get("networks") or {}
            if not isinstance(tmpl_networks, dict):
                break
            for net_name, net_override in tmpl_networks.items():
                referenced_names.add(net_name)
                if isinstance(net_override, dict):
                    merged = template_overrides.get(net_name, {})
                    template_overrides[net_name] = {**merged, **net_override}
            break

    _collect_template_networks(org_networktemplates, networktemplate_id)
    _collect_template_networks(org_gatewaytemplates, gatewaytemplate_id)

    # Site-setting can also define/override networks inline (keyed by name).
    site_setting_networks = site_setting.get("networks") or {}
    if isinstance(site_setting_networks, dict):
        for net_name in site_setting_networks:
            referenced_names.add(net_name)

    filtering_active = bool(referenced_names)
    if site_info and not filtering_active:
        logger.info(
            "site_snapshot_no_template_refs",
            site_id=site_id,
            hint=(
                "Site info present but no networktemplate/gatewaytemplate references — "
                "no org-level network filtering will be applied"
            ),
        )

    # Build network map from the org-network pool. Keys are the network IDs so
    # the existing override-by-id semantics and external assertions keep working.
    networks: dict[str, dict[str, Any]] = {}
    for net in org_networks:
        name = net.get("name", "") or ""
        if filtering_active and name not in referenced_names:
            continue
        net_id = net.get("id", "") or name
        if not net_id:
            continue
        merged = dict(net)
        if name and name in template_overrides:
            merged.update(template_overrides[name])
        if name and isinstance(site_setting_networks, dict) and isinstance(site_setting_networks.get(name), dict):
            merged.update(site_setting_networks[name])
        networks[net_id] = merged

    # Site-scoped standalone network backups override org-level ones by id.
    for net in site_networks:
        net_id = net.get("id", "") or net.get("name", "") or ""
        if net_id:
            networks[net_id] = net

    # Seed template-only and site-setting-only networks. In templated Mist orgs,
    # network definitions frequently live *only* inline inside the network /
    # gateway template's ``networks`` dict (keyed by name), and there are zero
    # standalone ``BackupObject(type="networks")`` records. The loop above then
    # produces nothing and ``snapshot.networks`` ends up empty — every
    # VLAN-aware check (CONN-VLAN, CONN-VLAN-PATH, ROUTE-GW, CFG-SUBNET,
    # CFG-DHCP-*) silently degrades to "not applicable". The passes below add
    # entries for names that have no existing backing, preserving the existing
    # merge semantics for names that *do* have standalone backups.
    existing_names = {cfg.get("name") for cfg in networks.values() if cfg.get("name")}
    for name, tmpl_frag in template_overrides.items():
        if not name or name in existing_names:
            continue
        entry: dict[str, Any] = {"name": name, **tmpl_frag}
        if isinstance(site_setting_networks, dict) and isinstance(site_setting_networks.get(name), dict):
            entry = {**entry, **site_setting_networks[name]}
        net_id = entry.get("id") or name
        networks[net_id] = entry
        existing_names.add(name)

    if isinstance(site_setting_networks, dict):
        for name, site_frag in site_setting_networks.items():
            if not name or not isinstance(site_frag, dict) or name in existing_names:
                continue
            entry = {"name": name, **site_frag}
            net_id = entry.get("id") or name
            networks[net_id] = entry
            existing_names.add(name)

    # Deterministic iteration order — MongoDB's $group stage does not guarantee
    # output order, so consecutive base-state loads of the same collection can
    # arrive in different orders. Without a sort here, CFG-SUBNET detail strings
    # (which depend on iteration order) would differ between the baseline and
    # predicted analyses, defeating pre_existing classification.
    networks = dict(sorted(networks.items()))

    # Build WLAN map
    wlans: dict[str, dict[str, Any]] = {}
    for wlan in site_wlans:
        wlan_id = wlan.get("id", "")
        if wlan_id:
            wlans[wlan_id] = wlan

    # Build device snapshots
    devices: dict[str, DeviceSnapshot] = {}
    for dev_config in site_devices:
        dev_id = dev_config.get("id", "")
        if dev_id:
            devices[dev_id] = _build_device_snapshot(dev_config)

    # Materialize per-interface profile attributes and explicit VLAN lists once
    # so all downstream checks/graphs share the same fully-resolved interface view.
    site_vars = site_setting.get("vars") or {}
    if devices:
        from app.modules.digital_twin.services.topology_utils import (
            build_network_name_to_vlan,
            materialize_device_port_config,
        )

        network_name_to_vlan = build_network_name_to_vlan(networks, site_vars)
        for device in devices.values():
            device.resolved_port_config = materialize_device_port_config(
                device.port_config,
                port_usages,
                device.port_usages,
                network_name_to_vlan,
                site_vars,
            )

    return SiteSnapshot(
        site_id=site_id,
        site_name=site_name,
        site_setting=site_setting,
        networks=networks,
        wlans=wlans,
        devices=devices,
        port_usages=port_usages,
        lldp_neighbors=live_data.lldp_neighbors,
        port_status=live_data.port_status,
        ap_clients=live_data.ap_clients,
        port_devices=live_data.port_devices,
        ospf_peers=live_data.ospf_peers,
        bgp_peers=live_data.bgp_peers,
    )
