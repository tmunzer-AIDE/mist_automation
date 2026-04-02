"""Gateway metric extractor — parses Mist gateway WebSocket payloads into InfluxDB data points.

Handles three sub-types:
- SRX standalone: spu_stat present, no cluster_config, model != "SSR"
- SRX cluster: cluster_config present
- SSR (standalone/HA): model == "SSR", network_resources in module_stat

Produces (depending on sub-type):
- gateway_health: cpu_idle, mem_usage, uptime, ha_state, config_status (all types)
- gateway_wan: per WAN interface — up, tx/rx bytes/pkts, wan_name (all types)
- gateway_dhcp: per DHCP scope — num_ips, num_leased, utilization_pct (all types)
- gateway_spu: SPU stats — spu_cpu, sessions, memory (SRX only)
- gateway_cluster: cluster status and link health (SRX cluster only)
- gateway_resources: network resource utilization — FIB, FLOW, ACCESS_POLICY (SSR only)
"""

from __future__ import annotations

from app.modules.telemetry.extractors._helpers import get_timestamp


def _detect_subtype(payload: dict) -> str:
    """Detect gateway sub-type: 'ssr', 'srx_cluster', or 'srx_standalone'."""
    if payload.get("model") == "SSR":
        return "ssr"
    if payload.get("cluster_config"):
        return "srx_cluster"
    return "srx_standalone"


# ---------------------------------------------------------------------------
# Common measurements
# ---------------------------------------------------------------------------


def _extract_gateway_health(payload: dict, org_id: str, site_id: str, timestamp: int) -> dict:
    """Build gateway_health data point (common to all gateway types)."""
    cpu_stat = payload.get("cpu_stat", {})
    cpu_idle = int(cpu_stat.get("idle", 100))

    memory_stat = payload.get("memory_stat", {})
    mem_usage = int(memory_stat.get("usage", 0))

    tags: dict = {
        "org_id": org_id,
        "site_id": site_id,
        "mac": payload.get("mac", ""),
        "device_type": "gateway",
        "name": payload.get("name") or payload.get("hostname") or "",
        "model": payload.get("model", ""),
        "node_name": payload.get("node_name", ""),
        "router_name": payload.get("router_name", ""),
        "mist_node0_mac": payload.get("mist_node0_mac", ""),
    }

    return {
        "measurement": "gateway_health",
        "tags": tags,
        "fields": {
            "cpu_idle": cpu_idle,
            "mem_usage": mem_usage,
            "uptime": int(payload.get("uptime", 0)),
            "ha_state": payload.get("ha_state", ""),
            "config_status": payload.get("config_status", ""),
        },
        "time": timestamp,
    }


def _extract_gateway_wan(payload: dict, org_id: str, site_id: str, timestamp: int) -> list[dict]:
    """Build gateway_wan data points for WAN interfaces from if_stat."""
    if_stat = payload.get("if_stat")
    if not if_stat:
        return []

    points: list[dict] = []
    for _if_key, port_data in if_stat.items():
        if port_data.get("port_usage") != "wan":
            continue

        points.append(
            {
                "measurement": "gateway_wan",
                "tags": {
                    "org_id": org_id,
                    "site_id": site_id,
                    "mac": payload.get("mac", ""),
                    "port_id": port_data.get("port_id", _if_key),
                    "wan_name": port_data.get("wan_name", ""),
                    "port_usage": "wan",
                },
                "fields": {
                    "up": port_data.get("up", False),
                    "tx_bytes": port_data.get("tx_bytes", 0),
                    "rx_bytes": port_data.get("rx_bytes", 0),
                    "tx_pkts": port_data.get("tx_pkts", 0),
                    "rx_pkts": port_data.get("rx_pkts", 0),
                },
                "time": timestamp,
            }
        )

    return points


def _extract_gateway_dhcp(payload: dict, org_id: str, site_id: str, timestamp: int) -> list[dict]:
    """Build gateway_dhcp data points from dhcpd_stat."""
    dhcpd_stat = payload.get("dhcpd_stat")
    if not dhcpd_stat:
        return []

    points: list[dict] = []
    for network_name, scope_data in dhcpd_stat.items():
        num_ips = scope_data.get("num_ips", 0)
        num_leased = scope_data.get("num_leased", 0)
        utilization_pct = round(num_leased / num_ips * 100, 1) if num_ips > 0 else 0.0

        points.append(
            {
                "measurement": "gateway_dhcp",
                "tags": {
                    "org_id": org_id,
                    "site_id": site_id,
                    "mac": payload.get("mac", ""),
                    "network_name": network_name,
                },
                "fields": {
                    "num_ips": num_ips,
                    "num_leased": num_leased,
                    "utilization_pct": utilization_pct,
                },
                "time": timestamp,
            }
        )

    return points


# ---------------------------------------------------------------------------
# SRX-specific measurements
# ---------------------------------------------------------------------------


def _extract_gateway_spu(payload: dict, org_id: str, site_id: str, timestamp: int) -> list[dict]:
    """Build gateway_spu data point from spu_stat (SRX only). Returns empty list if no SPU data."""
    spu_stat = payload.get("spu_stat")
    if not spu_stat:
        return []

    spu = spu_stat[0]

    return [
        {
            "measurement": "gateway_spu",
            "tags": {
                "org_id": org_id,
                "site_id": site_id,
                "mac": payload.get("mac", ""),
            },
            "fields": {
                "spu_cpu": spu.get("spu_cpu", 0),
                "spu_sessions": spu.get("spu_current_session", 0),
                "spu_max_sessions": spu.get("spu_max_session", 0),
                "spu_memory": spu.get("spu_memory", 0),
            },
            "time": timestamp,
        }
    ]


def _extract_gateway_cluster(payload: dict, org_id: str, site_id: str, timestamp: int) -> list[dict]:
    """Build gateway_cluster data point from cluster_config (SRX cluster only)."""
    cluster_config = payload.get("cluster_config")
    if not cluster_config:
        return []

    control_link_info = cluster_config.get("control_link_info", {})
    control_link_up = control_link_info.get("status", "").lower() == "up"

    # Note: Mist uses capital-S "Status" for fabric_link_info
    fabric_link_info = cluster_config.get("fabric_link_info", {})
    fabric_status = fabric_link_info.get("Status", fabric_link_info.get("status", ""))
    fabric_link_up = fabric_status.lower() in ("up", "enabled")

    return [
        {
            "measurement": "gateway_cluster",
            "tags": {
                "org_id": org_id,
                "site_id": site_id,
                "mac": payload.get("mac", ""),
            },
            "fields": {
                "status": cluster_config.get("status", ""),
                "operational": cluster_config.get("operational", ""),
                "primary_health": cluster_config.get("primary_node_health", ""),
                "secondary_health": cluster_config.get("secondary_node_health", ""),
                "control_link_up": control_link_up,
                "fabric_link_up": fabric_link_up,
            },
            "time": timestamp,
        }
    ]


# ---------------------------------------------------------------------------
# SSR-specific measurements
# ---------------------------------------------------------------------------


def _extract_gateway_resources(payload: dict, org_id: str, site_id: str, timestamp: int) -> list[dict]:
    """Build gateway_resources data points from module_stat network_resources (SSR only)."""
    module_stat = payload.get("module_stat")
    if not module_stat:
        return []

    first_module = module_stat[0]
    network_resources = first_module.get("network_resources")
    if not network_resources:
        return []

    points: list[dict] = []
    for resource in network_resources:
        count = resource.get("count", 0)
        limit = resource.get("limit", 0)
        utilization_pct = round(count / limit * 100, 1) if limit > 0 else 0.0

        points.append(
            {
                "measurement": "gateway_resources",
                "tags": {
                    "org_id": org_id,
                    "site_id": site_id,
                    "mac": payload.get("mac", ""),
                    "node_name": payload.get("node_name", ""),
                    "mist_node0_mac": payload.get("mist_node0_mac", ""),
                    "resource_type": resource.get("type", ""),
                },
                "fields": {
                    "count": count,
                    "limit": limit,
                    "utilization_pct": utilization_pct,
                },
                "time": timestamp,
            }
        )

    return points


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_points(payload: dict, org_id: str, site_id: str) -> list[dict]:
    """Extract InfluxDB data points from a raw gateway WebSocket payload.

    Detects gateway sub-type (SSR, SRX cluster, SRX standalone) and produces
    the appropriate set of measurements. All types emit gateway_health,
    gateway_wan, and gateway_dhcp. SRX types additionally emit gateway_spu.
    SRX clusters emit gateway_cluster. SSR emits gateway_resources.
    """
    timestamp = get_timestamp(payload)
    subtype = _detect_subtype(payload)
    points: list[dict] = []

    # Common measurements (all gateway types)
    points.append(_extract_gateway_health(payload, org_id, site_id, timestamp))
    points.extend(_extract_gateway_wan(payload, org_id, site_id, timestamp))
    points.extend(_extract_gateway_dhcp(payload, org_id, site_id, timestamp))

    # Sub-type-specific measurements
    if subtype == "ssr":
        points.extend(_extract_gateway_resources(payload, org_id, site_id, timestamp))
    elif subtype == "srx_cluster":
        points.extend(_extract_gateway_spu(payload, org_id, site_id, timestamp))
        points.extend(_extract_gateway_cluster(payload, org_id, site_id, timestamp))
    else:
        # srx_standalone
        points.extend(_extract_gateway_spu(payload, org_id, site_id, timestamp))

    return points
