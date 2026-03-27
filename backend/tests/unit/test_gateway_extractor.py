"""Unit tests for Gateway metric extractor."""

from app.modules.telemetry.extractors.gateway_extractor import extract_points

# ---------------------------------------------------------------------------
# Fixtures — SRX standalone
# ---------------------------------------------------------------------------


def _srx_standalone_payload() -> dict:
    """Realistic SRX standalone gateway payload."""
    return {
        "mac": "aabb00112233",
        "name": "GW-Branch-01",
        "model": "SRX300",
        "type": "gateway",
        "cpu_stat": {"idle": 78},
        "memory_stat": {"usage": 55},
        "uptime": 604800,
        "config_status": "synced",
        "last_seen": 1774576960,
        "_time": 1774576960.7,
        "spu_stat": [
            {
                "spu_cpu": 22,
                "spu_current_session": 4500,
                "spu_max_session": 64000,
                "spu_memory": 35,
            }
        ],
        "if_stat": {
            "ge-0/0/0.0": {
                "port_id": "ge-0/0/0",
                "port_usage": "wan",
                "wan_name": "ISP-Primary",
                "up": True,
                "tx_bytes": 1000000,
                "rx_bytes": 2000000,
                "tx_pkts": 5000,
                "rx_pkts": 10000,
            },
            "ge-0/0/1.0": {
                "port_id": "ge-0/0/1",
                "port_usage": "lan",
                "up": True,
                "tx_bytes": 500000,
                "rx_bytes": 600000,
                "tx_pkts": 3000,
                "rx_pkts": 4000,
            },
            "ge-0/0/2.0": {
                "port_id": "ge-0/0/2",
                "port_usage": "wan",
                "wan_name": "ISP-Backup",
                "up": False,
                "tx_bytes": 0,
                "rx_bytes": 0,
                "tx_pkts": 0,
                "rx_pkts": 0,
            },
        },
        "dhcpd_stat": {
            "default-vlan": {
                "num_ips": 254,
                "num_leased": 42,
            },
            "guest-vlan": {
                "num_ips": 126,
                "num_leased": 10,
            },
        },
    }


# ---------------------------------------------------------------------------
# Fixtures — SRX cluster
# ---------------------------------------------------------------------------


def _srx_cluster_payload() -> dict:
    """Realistic SRX cluster gateway payload."""
    payload = _srx_standalone_payload()
    payload["cluster_config"] = {
        "status": "Green",
        "operational": "active-passive",
        "primary_node_health": "healthy",
        "secondary_node_health": "healthy",
        "control_link_info": {"status": "Up"},
        "fabric_link_info": {"Status": "Enabled"},
    }
    # Cluster may have reth interfaces for WAN
    payload["if_stat"]["reth0.0"] = {
        "port_id": "reth0",
        "port_usage": "wan",
        "wan_name": "ISP-Primary",
        "up": True,
        "tx_bytes": 3000000,
        "rx_bytes": 4000000,
        "tx_pkts": 15000,
        "rx_pkts": 20000,
    }
    return payload


# ---------------------------------------------------------------------------
# Fixtures — SSR
# ---------------------------------------------------------------------------


def _ssr_standalone_payload() -> dict:
    """Realistic SSR gateway payload."""
    return {
        "mac": "ddeeff001122",
        "name": "SSR-DC-01",
        "model": "SSR",
        "type": "gateway",
        "cpu_stat": {"idle": 90},
        "memory_stat": {"usage": 40},
        "uptime": 2592000,
        "config_status": "synced",
        "ha_state": "running",
        "ha_peer_mac": "",
        "node_name": "node0",
        "router_name": "ssr-dc-cluster",
        "last_seen": 1774576960,
        "_time": 1774576960.9,
        "if_stat": {
            "dpdk1": {
                "port_id": "dpdk1",
                "port_usage": "wan",
                "wan_name": "WAN-MPLS",
                "up": True,
                "tx_bytes": 5000000,
                "rx_bytes": 6000000,
                "tx_pkts": 25000,
                "rx_pkts": 30000,
            },
        },
        "module_stat": [
            {
                "_idx": 0,
                "network_resources": [
                    {"type": "FIB", "count": 2142, "limit": 22608},
                    {"type": "FLOW", "count": 512, "limit": 524288},
                    {"type": "ACCESS_POLICY", "count": 100, "limit": 10000},
                ],
            }
        ],
        "dhcpd_stat": {
            "corp-lan": {
                "num_ips": 500,
                "num_leased": 150,
            },
        },
    }


# ---------------------------------------------------------------------------
# Tests: gateway_health (common to all types)
# ---------------------------------------------------------------------------


class TestGatewayHealth:
    """All gateway types produce a gateway_health point."""

    def test_srx_standalone_health(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        healths = [p for p in points if p["measurement"] == "gateway_health"]
        assert len(healths) == 1
        h = healths[0]
        assert h["tags"]["org_id"] == "org-1"
        assert h["tags"]["site_id"] == "site-1"
        assert h["tags"]["mac"] == "aabb00112233"
        assert h["tags"]["device_type"] == "gateway"
        assert h["tags"]["name"] == "GW-Branch-01"
        assert h["tags"]["model"] == "SRX300"
        assert h["fields"]["cpu_idle"] == 78
        assert h["fields"]["mem_usage"] == 55
        assert h["fields"]["uptime"] == 604800
        assert h["fields"]["config_status"] == "synced"
        assert h["time"] == 1774576960

    def test_srx_cluster_health(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        healths = [p for p in points if p["measurement"] == "gateway_health"]
        assert len(healths) == 1

    def test_ssr_health_with_ha_fields(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        healths = [p for p in points if p["measurement"] == "gateway_health"]
        assert len(healths) == 1
        h = healths[0]
        assert h["tags"]["model"] == "SSR"
        assert h["tags"]["node_name"] == "node0"
        assert h["tags"]["router_name"] == "ssr-dc-cluster"
        assert h["fields"]["ha_state"] == "running"
        assert h["fields"]["cpu_idle"] == 90

    def test_health_time_falls_back_to_last_seen(self):
        payload = _srx_standalone_payload()
        del payload["_time"]
        points = extract_points(payload, "org-1", "site-1")
        h = next(p for p in points if p["measurement"] == "gateway_health")
        assert h["time"] == 1774576960

    def test_empty_payload_returns_health_with_defaults(self):
        points = extract_points({"mac": "000000000000", "model": "SRX320"}, "org-1", "site-1")
        healths = [p for p in points if p["measurement"] == "gateway_health"]
        assert len(healths) == 1
        assert healths[0]["fields"]["cpu_idle"] == 100


# ---------------------------------------------------------------------------
# Tests: gateway_wan (common to all types)
# ---------------------------------------------------------------------------


class TestGatewayWan:
    """All gateway types produce gateway_wan points for WAN ports."""

    def test_srx_standalone_wan_ports_only(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        wans = [p for p in points if p["measurement"] == "gateway_wan"]
        # ge-0/0/0 is wan+up, ge-0/0/1 is lan (excluded), ge-0/0/2 is wan+down (included)
        assert len(wans) == 2
        port_ids = {p["tags"]["port_id"] for p in wans}
        assert port_ids == {"ge-0/0/0", "ge-0/0/2"}

    def test_wan_point_tags(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        wan = next(p for p in points if p["measurement"] == "gateway_wan" and p["tags"]["port_id"] == "ge-0/0/0")
        assert wan["tags"]["org_id"] == "org-1"
        assert wan["tags"]["site_id"] == "site-1"
        assert wan["tags"]["mac"] == "aabb00112233"
        assert wan["tags"]["wan_name"] == "ISP-Primary"
        assert wan["tags"]["port_usage"] == "wan"

    def test_wan_point_fields(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        wan = next(p for p in points if p["measurement"] == "gateway_wan" and p["tags"]["port_id"] == "ge-0/0/0")
        fields = wan["fields"]
        assert fields["up"] is True
        assert fields["tx_bytes"] == 1000000
        assert fields["rx_bytes"] == 2000000
        assert fields["tx_pkts"] == 5000
        assert fields["rx_pkts"] == 10000

    def test_wan_time(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        wans = [p for p in points if p["measurement"] == "gateway_wan"]
        for wan in wans:
            assert wan["time"] == 1774576960

    def test_cluster_reth_wan_included(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        wans = [p for p in points if p["measurement"] == "gateway_wan"]
        port_ids = {p["tags"]["port_id"] for p in wans}
        assert "reth0" in port_ids

    def test_ssr_wan_port(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        wans = [p for p in points if p["measurement"] == "gateway_wan"]
        assert len(wans) == 1
        assert wans[0]["tags"]["port_id"] == "dpdk1"
        assert wans[0]["tags"]["wan_name"] == "WAN-MPLS"

    def test_no_if_stat_produces_no_wan_points(self):
        payload = _srx_standalone_payload()
        del payload["if_stat"]
        points = extract_points(payload, "org-1", "site-1")
        wans = [p for p in points if p["measurement"] == "gateway_wan"]
        assert wans == []


# ---------------------------------------------------------------------------
# Tests: gateway_dhcp (common to SRX and SSR)
# ---------------------------------------------------------------------------


class TestGatewayDhcp:
    """Gateway payloads with dhcpd_stat produce gateway_dhcp points."""

    def test_srx_dhcp_points(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        dhcps = [p for p in points if p["measurement"] == "gateway_dhcp"]
        assert len(dhcps) == 2
        networks = {p["tags"]["network_name"] for p in dhcps}
        assert networks == {"default-vlan", "guest-vlan"}

    def test_dhcp_tags(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        dhcp = next(
            p for p in points if p["measurement"] == "gateway_dhcp" and p["tags"]["network_name"] == "default-vlan"
        )
        assert dhcp["tags"]["org_id"] == "org-1"
        assert dhcp["tags"]["site_id"] == "site-1"
        assert dhcp["tags"]["mac"] == "aabb00112233"

    def test_dhcp_fields(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        dhcp = next(
            p for p in points if p["measurement"] == "gateway_dhcp" and p["tags"]["network_name"] == "default-vlan"
        )
        fields = dhcp["fields"]
        assert fields["num_ips"] == 254
        assert fields["num_leased"] == 42
        # utilization_pct = 42 / 254 * 100 ~= 16.5
        assert 16.4 < fields["utilization_pct"] < 16.6

    def test_dhcp_utilization_zero_when_no_ips(self):
        payload = _srx_standalone_payload()
        payload["dhcpd_stat"]["empty-scope"] = {"num_ips": 0, "num_leased": 0}
        points = extract_points(payload, "org-1", "site-1")
        dhcp = next(
            p for p in points if p["measurement"] == "gateway_dhcp" and p["tags"]["network_name"] == "empty-scope"
        )
        assert dhcp["fields"]["utilization_pct"] == 0

    def test_no_dhcpd_stat_produces_no_dhcp_points(self):
        payload = _srx_standalone_payload()
        del payload["dhcpd_stat"]
        points = extract_points(payload, "org-1", "site-1")
        dhcps = [p for p in points if p["measurement"] == "gateway_dhcp"]
        assert dhcps == []

    def test_ssr_dhcp_points(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        dhcps = [p for p in points if p["measurement"] == "gateway_dhcp"]
        assert len(dhcps) == 1
        assert dhcps[0]["tags"]["network_name"] == "corp-lan"

    def test_dhcp_time(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        dhcps = [p for p in points if p["measurement"] == "gateway_dhcp"]
        for dhcp in dhcps:
            assert dhcp["time"] == 1774576960


# ---------------------------------------------------------------------------
# Tests: gateway_spu (SRX only)
# ---------------------------------------------------------------------------


class TestGatewaySpu:
    """SRX gateways produce gateway_spu point from spu_stat."""

    def test_srx_standalone_spu(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        spus = [p for p in points if p["measurement"] == "gateway_spu"]
        assert len(spus) == 1

    def test_spu_tags(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        spu = next(p for p in points if p["measurement"] == "gateway_spu")
        assert spu["tags"]["org_id"] == "org-1"
        assert spu["tags"]["site_id"] == "site-1"
        assert spu["tags"]["mac"] == "aabb00112233"

    def test_spu_fields(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        spu = next(p for p in points if p["measurement"] == "gateway_spu")
        fields = spu["fields"]
        assert fields["spu_cpu"] == 22
        assert fields["spu_sessions"] == 4500
        assert fields["spu_max_sessions"] == 64000
        assert fields["spu_memory"] == 35

    def test_spu_time(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        spu = next(p for p in points if p["measurement"] == "gateway_spu")
        assert spu["time"] == 1774576960

    def test_srx_cluster_spu(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        spus = [p for p in points if p["measurement"] == "gateway_spu"]
        assert len(spus) == 1

    def test_empty_spu_stat_produces_no_spu(self):
        payload = _srx_standalone_payload()
        payload["spu_stat"] = []
        points = extract_points(payload, "org-1", "site-1")
        spus = [p for p in points if p["measurement"] == "gateway_spu"]
        assert spus == []

    def test_no_spu_stat_key_produces_no_spu(self):
        payload = _srx_standalone_payload()
        del payload["spu_stat"]
        points = extract_points(payload, "org-1", "site-1")
        spus = [p for p in points if p["measurement"] == "gateway_spu"]
        assert spus == []

    def test_ssr_has_no_spu(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        spus = [p for p in points if p["measurement"] == "gateway_spu"]
        assert spus == []


# ---------------------------------------------------------------------------
# Tests: gateway_cluster (SRX cluster only)
# ---------------------------------------------------------------------------


class TestGatewayCluster:
    """SRX cluster gateways produce gateway_cluster point."""

    def test_cluster_point_present(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        clusters = [p for p in points if p["measurement"] == "gateway_cluster"]
        assert len(clusters) == 1

    def test_cluster_tags(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        cluster = next(p for p in points if p["measurement"] == "gateway_cluster")
        assert cluster["tags"]["org_id"] == "org-1"
        assert cluster["tags"]["site_id"] == "site-1"
        assert cluster["tags"]["mac"] == "aabb00112233"

    def test_cluster_fields(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        cluster = next(p for p in points if p["measurement"] == "gateway_cluster")
        fields = cluster["fields"]
        assert fields["status"] == "Green"
        assert fields["operational"] == "active-passive"
        assert fields["primary_health"] == "healthy"
        assert fields["secondary_health"] == "healthy"
        assert fields["control_link_up"] is True
        assert fields["fabric_link_up"] is True

    def test_cluster_control_link_down(self):
        payload = _srx_cluster_payload()
        payload["cluster_config"]["control_link_info"]["status"] = "Down"
        points = extract_points(payload, "org-1", "site-1")
        cluster = next(p for p in points if p["measurement"] == "gateway_cluster")
        assert cluster["fields"]["control_link_up"] is False

    def test_cluster_fabric_link_down(self):
        payload = _srx_cluster_payload()
        payload["cluster_config"]["fabric_link_info"]["Status"] = "Down"
        points = extract_points(payload, "org-1", "site-1")
        cluster = next(p for p in points if p["measurement"] == "gateway_cluster")
        assert cluster["fields"]["fabric_link_up"] is False

    def test_cluster_time(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        cluster = next(p for p in points if p["measurement"] == "gateway_cluster")
        assert cluster["time"] == 1774576960

    def test_standalone_has_no_cluster_point(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        clusters = [p for p in points if p["measurement"] == "gateway_cluster"]
        assert clusters == []

    def test_ssr_has_no_cluster_point(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        clusters = [p for p in points if p["measurement"] == "gateway_cluster"]
        assert clusters == []


# ---------------------------------------------------------------------------
# Tests: gateway_resources (SSR only)
# ---------------------------------------------------------------------------


class TestGatewayResources:
    """SSR gateways produce gateway_resources points from network_resources."""

    def test_ssr_resources_present(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        resources = [p for p in points if p["measurement"] == "gateway_resources"]
        assert len(resources) == 3

    def test_resource_tags(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        fib = next(p for p in points if p["measurement"] == "gateway_resources" and p["tags"]["resource_type"] == "FIB")
        assert fib["tags"]["org_id"] == "org-1"
        assert fib["tags"]["site_id"] == "site-1"
        assert fib["tags"]["mac"] == "ddeeff001122"
        assert fib["tags"]["node_name"] == "node0"

    def test_resource_fields_fib(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        fib = next(p for p in points if p["measurement"] == "gateway_resources" and p["tags"]["resource_type"] == "FIB")
        fields = fib["fields"]
        assert fields["count"] == 2142
        assert fields["limit"] == 22608
        # utilization_pct = 2142 / 22608 * 100 ~= 9.47, rounds to 9.5
        assert 9.4 < fields["utilization_pct"] <= 9.5

    def test_resource_fields_flow(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        flow = next(
            p for p in points if p["measurement"] == "gateway_resources" and p["tags"]["resource_type"] == "FLOW"
        )
        assert flow["fields"]["count"] == 512
        assert flow["fields"]["limit"] == 524288

    def test_resource_fields_access_policy(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        ap = next(
            p
            for p in points
            if p["measurement"] == "gateway_resources" and p["tags"]["resource_type"] == "ACCESS_POLICY"
        )
        assert ap["fields"]["count"] == 100
        assert ap["fields"]["limit"] == 10000
        # utilization_pct = 100 / 10000 * 100 = 1.0
        assert ap["fields"]["utilization_pct"] == 1.0

    def test_resource_utilization_zero_when_limit_zero(self):
        payload = _ssr_standalone_payload()
        payload["module_stat"][0]["network_resources"][0]["limit"] = 0
        points = extract_points(payload, "org-1", "site-1")
        fib = next(p for p in points if p["measurement"] == "gateway_resources" and p["tags"]["resource_type"] == "FIB")
        assert fib["fields"]["utilization_pct"] == 0

    def test_resource_time(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        resources = [p for p in points if p["measurement"] == "gateway_resources"]
        for r in resources:
            assert r["time"] == 1774576960

    def test_srx_standalone_has_no_resources(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        resources = [p for p in points if p["measurement"] == "gateway_resources"]
        assert resources == []

    def test_srx_cluster_has_no_resources(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        resources = [p for p in points if p["measurement"] == "gateway_resources"]
        assert resources == []

    def test_ssr_no_module_stat_produces_no_resources(self):
        payload = _ssr_standalone_payload()
        del payload["module_stat"]
        points = extract_points(payload, "org-1", "site-1")
        resources = [p for p in points if p["measurement"] == "gateway_resources"]
        assert resources == []

    def test_ssr_empty_network_resources_produces_no_resources(self):
        payload = _ssr_standalone_payload()
        payload["module_stat"][0]["network_resources"] = []
        points = extract_points(payload, "org-1", "site-1")
        resources = [p for p in points if p["measurement"] == "gateway_resources"]
        assert resources == []


# ---------------------------------------------------------------------------
# Tests: device type detection
# ---------------------------------------------------------------------------


class TestGatewayTypeDetection:
    """Verify correct sub-type detection determines which measurements appear."""

    def test_srx_standalone_measurements(self):
        points = extract_points(_srx_standalone_payload(), "org-1", "site-1")
        measurements = {p["measurement"] for p in points}
        assert "gateway_health" in measurements
        assert "gateway_wan" in measurements
        assert "gateway_dhcp" in measurements
        assert "gateway_spu" in measurements
        assert "gateway_cluster" not in measurements
        assert "gateway_resources" not in measurements

    def test_srx_cluster_measurements(self):
        points = extract_points(_srx_cluster_payload(), "org-1", "site-1")
        measurements = {p["measurement"] for p in points}
        assert "gateway_health" in measurements
        assert "gateway_wan" in measurements
        assert "gateway_dhcp" in measurements
        assert "gateway_spu" in measurements
        assert "gateway_cluster" in measurements
        assert "gateway_resources" not in measurements

    def test_ssr_measurements(self):
        points = extract_points(_ssr_standalone_payload(), "org-1", "site-1")
        measurements = {p["measurement"] for p in points}
        assert "gateway_health" in measurements
        assert "gateway_wan" in measurements
        assert "gateway_dhcp" in measurements
        assert "gateway_resources" in measurements
        assert "gateway_spu" not in measurements
        assert "gateway_cluster" not in measurements
