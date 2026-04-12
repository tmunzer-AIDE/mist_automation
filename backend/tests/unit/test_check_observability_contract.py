"""Cross-check observability contract tests for Digital Twin validations.

These tests enforce that every check result carries enough admin-facing
context to explain what happened, why it happened, and how to remediate.
"""

from __future__ import annotations

import pytest

from app.modules.digital_twin.checks.config_conflicts import check_config_conflicts
from app.modules.digital_twin.checks.connectivity import check_connectivity
from app.modules.digital_twin.checks.port_impact import check_port_impact
from app.modules.digital_twin.checks.routing import check_routing
from app.modules.digital_twin.checks.security import check_security
from app.modules.digital_twin.checks.stp import check_stp
from app.modules.digital_twin.checks.template_checks import check_template_variables
from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.site_snapshot import DeviceSnapshot, SiteSnapshot


def _dev(
    dev_id: str,
    mac: str,
    name: str,
    dtype: str,
    *,
    port_config: dict | None = None,
    ip_config: dict | None = None,
    stp_config: dict | None = None,
) -> DeviceSnapshot:
    return DeviceSnapshot(
        device_id=dev_id,
        mac=mac,
        name=name,
        type=dtype,
        model="test-model",
        port_config=port_config or {},
        ip_config=ip_config or {},
        dhcpd_config={},
        stp_config=stp_config,
    )


def _snap(
    *,
    site_setting: dict | None = None,
    networks: dict | None = None,
    wlans: dict | None = None,
    devices: dict[str, DeviceSnapshot] | None = None,
    port_usages: dict | None = None,
    lldp_neighbors: dict | None = None,
    ap_clients: dict | None = None,
    port_devices: dict | None = None,
) -> SiteSnapshot:
    return SiteSnapshot(
        site_id="site-1",
        site_name="Contract Site",
        site_setting=site_setting or {},
        networks=networks or {},
        wlans=wlans or {},
        devices=devices or {},
        port_usages=port_usages or {},
        lldp_neighbors=lldp_neighbors or {},
        port_status={},
        ap_clients=ap_clients or {},
        port_devices=port_devices or {},
        ospf_peers={},
        bgp_peers={},
    )


def _routing_scenario() -> tuple[SiteSnapshot, SiteSnapshot]:
    baseline = _snap()
    predicted = _snap(
        networks={"n1": {"name": "Corp", "subnet": "10.0.0.0/24", "vlan_id": 10}},
        devices={
            "gw-1": _dev(
                "gw-1",
                "aa:00:00:00:00:01",
                "GW-1",
                "gateway",
                ip_config={},
            )
        },
        wlans={"w1": {"ssid": "Corp", "enabled": True, "vlan_id": 10}},
    )
    return baseline, predicted


def _connectivity_scenario() -> tuple[SiteSnapshot, SiteSnapshot]:
    gw = _dev(
        "gw-1",
        "aa:00:00:00:00:01",
        "GW-1",
        "gateway",
        ip_config={"data": {"ip": "10.0.0.1", "netmask": "255.255.255.0"}},
    )
    sw = _dev(
        "sw-1",
        "aa:00:00:00:00:02",
        "SW-1",
        "switch",
        port_config={"ge-0/0/1": {"usage": "ap"}},
    )
    ap = _dev("ap-1", "aa:00:00:00:00:03", "AP-1", "ap")

    baseline = _snap(
        networks={"n1": {"name": "data", "vlan_id": 10}},
        devices={"gw-1": gw, "sw-1": sw, "ap-1": ap},
        lldp_neighbors={
            "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02"},
            "aa:00:00:00:00:02": {
                "ge-0/0/0": "aa:00:00:00:00:01",
                "ge-0/0/1": "aa:00:00:00:00:03",
            },
        },
        wlans={"w1": {"ssid": "Corp", "enabled": True, "vlan_id": 10}},
        ap_clients={"ap-1": 12},
    )
    predicted = _snap(
        networks={"n1": {"name": "data", "vlan_id": 10}},
        devices={"gw-1": gw, "sw-1": sw, "ap-1": ap},
        lldp_neighbors={
            "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02"},
            # AP edge removed to force CONN-PHYS impact
            "aa:00:00:00:00:02": {"ge-0/0/0": "aa:00:00:00:00:01"},
        },
        wlans={"w1": {"ssid": "Corp", "enabled": True, "vlan_id": 10}},
        ap_clients={"ap-1": 12},
    )
    return baseline, predicted


def _port_impact_scenario() -> tuple[SiteSnapshot, SiteSnapshot]:
    ap = _dev("ap-1", "aa:bb:cc:00:00:01", "AP-Lobby", "ap")
    sw_base = _dev(
        "sw-1",
        "aa:bb:cc:00:00:10",
        "SW-Core",
        "switch",
        port_config={"ge-0/0/5": {"usage": "ap"}},
    )
    sw_pred = _dev(
        "sw-1",
        "aa:bb:cc:00:00:10",
        "SW-Core",
        "switch",
        port_config={"ge-0/0/5": {"usage": "disabled"}},
    )
    baseline = _snap(
        devices={"sw-1": sw_base, "ap-1": ap},
        lldp_neighbors={"aa:bb:cc:00:00:10": {"ge-0/0/5": "aa:bb:cc:00:00:01"}},
        ap_clients={"ap-1": 25},
    )
    predicted = _snap(
        devices={"sw-1": sw_pred, "ap-1": ap},
        lldp_neighbors=baseline.lldp_neighbors,
        ap_clients=baseline.ap_clients,
    )
    return baseline, predicted


def _security_scenario() -> tuple[SiteSnapshot, SiteSnapshot]:
    baseline = _snap()
    predicted = _snap(
        wlans={
            "w1": {
                "ssid": "Guest-WiFi",
                "enabled": True,
                "auth": {"type": "open"},
            }
        }
    )
    return baseline, predicted


def _stp_scenario() -> tuple[SiteSnapshot, SiteSnapshot]:
    baseline = _snap(
        devices={
            "sw-1": _dev(
                "sw-1",
                "aa:bb:cc:00:00:11",
                "SW-Core",
                "switch",
                stp_config={"bridge_priority": 4096},
            ),
            "sw-2": _dev(
                "sw-2",
                "aa:bb:cc:00:00:12",
                "SW-Access",
                "switch",
                stp_config={"bridge_priority": 32768},
            ),
        }
    )
    predicted = _snap(
        devices={
            "sw-1": _dev(
                "sw-1",
                "aa:bb:cc:00:00:11",
                "SW-Core",
                "switch",
                stp_config={"bridge_priority": 32768},
            ),
            "sw-2": _dev(
                "sw-2",
                "aa:bb:cc:00:00:12",
                "SW-Access",
                "switch",
                stp_config={"bridge_priority": 4096},
            ),
        }
    )
    return baseline, predicted


def _assert_admin_observability(result: CheckResult, family: str) -> None:
    context = f"family={family}, check={result.check_id}, status={result.status}, dump={result.model_dump()}"

    assert result.check_id.strip(), f"Missing check_id: {context}"
    assert result.check_name.strip(), f"Missing check_name: {context}"
    assert result.summary.strip(), f"Missing summary: {context}"
    assert result.description.strip(), f"Missing description: {context}"

    if result.status in {"warning", "error", "critical"}:
        assert result.details, f"Issue checks must include detail lines: {context}"
        assert result.affected_sites, f"Issue checks must include affected_sites: {context}"
        assert result.remediation_hint, f"Issue checks must include remediation_hint: {context}"
        assert all(d.strip() for d in result.details), f"Empty detail line found: {context}"


@pytest.mark.unit
class TestCheckObservabilityContract:
    def test_all_check_families_expose_admin_diagnostics(self):
        config_results = check_config_conflicts(
            _snap(
                networks={
                    "n1": {"name": "Corp", "subnet": "10.0.0.0/24", "vlan_id": 10},
                    "n2": {"name": "Guest", "subnet": "10.0.0.128/25", "vlan_id": 20},
                }
            )
        )

        template_results = check_template_variables(
            _snap(site_setting={"vars": {}, "dns": ["{{ missing_dns_var }}"]})
        )

        routing_baseline, routing_predicted = _routing_scenario()
        routing_results = check_routing(routing_baseline, routing_predicted)

        conn_baseline, conn_predicted = _connectivity_scenario()
        connectivity_results = check_connectivity(conn_baseline, conn_predicted)

        port_baseline, port_predicted = _port_impact_scenario()
        port_results = check_port_impact(port_baseline, port_predicted)

        sec_baseline, sec_predicted = _security_scenario()
        security_results = check_security(sec_baseline, sec_predicted)

        stp_baseline, stp_predicted = _stp_scenario()
        stp_results = check_stp(stp_baseline, stp_predicted)

        all_results = {
            "config": config_results,
            "template": template_results,
            "routing": routing_results,
            "connectivity": connectivity_results,
            "port_impact": port_results,
            "security": security_results,
            "stp": stp_results,
        }

        # Contract: every emitted check result must be administratively useful.
        for family, results in all_results.items():
            assert results, f"{family} returned no check results"
            for result in results:
                _assert_admin_observability(result, family)

        issue_count = sum(
            1
            for results in all_results.values()
            for result in results
            if result.status in {"warning", "error", "critical"}
        )
        assert issue_count > 0, "contract fixture must include issue results"
