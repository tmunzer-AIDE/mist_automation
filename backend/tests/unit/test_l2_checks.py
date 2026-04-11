"""
Unit tests for Layer 5 L2/STP prediction checks.
TDD: tests written before implementation.
"""

import pytest

from app.modules.digital_twin.services.l2_checks import (
    check_bpdu_filter_on_trunk,
    check_l2_loop_risk,
    check_stp_root_bridge_shift,
)

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------


def _dev(dev_id: str, device_type: str = "switch", **kwargs) -> dict:
    """Create a minimal device dict."""
    d = {
        "id": dev_id,
        "name": kwargs.get("name", dev_id.upper()),
        "device_type": device_type,
        "status": kwargs.get("status", "connected"),
    }
    for k, v in kwargs.items():
        if k not in d:
            d[k] = v
    return d


def _conn(local: str, remote: str, link_type: str = "STANDALONE", status: str = "UP") -> dict:
    """Create a minimal connection dict."""
    return {
        "local_device_id": local,
        "remote_device_id": remote,
        "link_type": link_type,
        "status": status,
    }


def _make_snapshot(devices: dict | None = None, connections: list | None = None) -> dict:
    """Create a minimal topology snapshot dict."""
    devs = devices or {}
    conns = connections or []
    return {
        "devices": devs,
        "connections": conns,
    }


# ---------------------------------------------------------------------------
# L5-01: L2 loop risk
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_l2_loop_risk_pass_no_cycle():
    """Linear chain A-B-C has no cycles — should pass."""
    devices = {
        "sw1": _dev("sw1"),
        "sw2": _dev("sw2"),
        "sw3": _dev("sw3"),
    }
    connections = [
        _conn("sw1", "sw2"),
        _conn("sw2", "sw3"),
    ]
    baseline = _make_snapshot(devices, [_conn("sw1", "sw2")])
    predicted = _make_snapshot(devices, connections)

    result = check_l2_loop_risk(baseline, predicted)

    assert result.check_id == "L5-01"
    assert result.layer == 5
    assert result.status == "pass"


@pytest.mark.unit
def test_l2_loop_risk_critical_triangle_cycle():
    """Triangle A-B-C-A introduces a new cycle — should be critical."""
    devices = {
        "sw1": _dev("sw1"),
        "sw2": _dev("sw2"),
        "sw3": _dev("sw3"),
    }
    baseline_conns = [
        _conn("sw1", "sw2"),
        _conn("sw2", "sw3"),
    ]
    predicted_conns = [
        _conn("sw1", "sw2"),
        _conn("sw2", "sw3"),
        _conn("sw3", "sw1"),  # closing the triangle
    ]
    baseline = _make_snapshot(devices, baseline_conns)
    predicted = _make_snapshot(devices, predicted_conns)

    result = check_l2_loop_risk(baseline, predicted)

    assert result.check_id == "L5-01"
    assert result.layer == 5
    assert result.status == "critical"
    assert len(result.affected_objects) > 0


@pytest.mark.unit
def test_l2_loop_risk_cycle_already_in_baseline_passes():
    """Cycle already present in baseline is not a new risk — should pass."""
    devices = {
        "sw1": _dev("sw1"),
        "sw2": _dev("sw2"),
        "sw3": _dev("sw3"),
    }
    triangle = [
        _conn("sw1", "sw2"),
        _conn("sw2", "sw3"),
        _conn("sw3", "sw1"),
    ]
    baseline = _make_snapshot(devices, triangle)
    predicted = _make_snapshot(devices, triangle)

    result = check_l2_loop_risk(baseline, predicted)

    assert result.check_id == "L5-01"
    assert result.status == "pass"


@pytest.mark.unit
def test_l2_loop_risk_lag_cycle_excluded():
    """Cycle through LAG connections only is STP-protected — should pass."""
    devices = {
        "sw1": _dev("sw1"),
        "sw2": _dev("sw2"),
        "sw3": _dev("sw3"),
    }
    # LAG connections between all three switches form a "cycle" but are protected
    connections = [
        _conn("sw1", "sw2", link_type="LAG"),
        _conn("sw2", "sw3", link_type="LAG"),
        _conn("sw3", "sw1", link_type="LAG"),
    ]
    baseline = _make_snapshot(devices, [])
    predicted = _make_snapshot(devices, connections)

    result = check_l2_loop_risk(baseline, predicted)

    # LAG-only cycles should not be flagged as critical
    assert result.check_id == "L5-01"
    assert result.status in ("pass", "warning")


# ---------------------------------------------------------------------------
# L5-02: BPDU filter on trunk
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bpdu_filter_on_trunk_pass_no_bpdu_filter():
    """No BPDU filter configured — should pass."""
    configs = {
        "sw1": {
            "port_config": {
                "ge-0/0/0": {"vlan_mode": "trunk"},
                "ge-0/0/1": {"vlan_mode": "access"},
            }
        }
    }

    result = check_bpdu_filter_on_trunk(configs)

    assert result.check_id == "L5-02"
    assert result.layer == 5
    assert result.status == "pass"


@pytest.mark.unit
def test_bpdu_filter_on_trunk_critical_bpdu_filter_trunk():
    """BPDU filter on a trunk port — should be critical."""
    configs = {
        "sw1": {
            "port_config": {
                "ge-0/0/0": {
                    "vlan_mode": "trunk",
                    "bpdu_filter": True,
                },
            }
        }
    }

    result = check_bpdu_filter_on_trunk(configs)

    assert result.check_id == "L5-02"
    assert result.layer == 5
    assert result.status == "critical"
    assert "sw1" in result.affected_objects or any("ge-0/0/0" in d for d in result.details)


@pytest.mark.unit
def test_bpdu_filter_on_trunk_critical_stp_bpdu_filter_variant():
    """stp_bpdu_filter variant on trunk port — should also be critical."""
    configs = {
        "sw2": {
            "port_config": {
                "et-0/0/0": {
                    "vlan_mode": "trunk",
                    "stp_bpdu_filter": True,
                },
            }
        }
    }

    result = check_bpdu_filter_on_trunk(configs)

    assert result.check_id == "L5-02"
    assert result.status == "critical"


@pytest.mark.unit
def test_bpdu_filter_on_access_port_pass():
    """BPDU filter on an access port is expected and safe — should pass."""
    configs = {
        "sw1": {
            "port_config": {
                "ge-0/0/0": {
                    "vlan_mode": "access",
                    "bpdu_filter": True,
                },
            }
        }
    }

    result = check_bpdu_filter_on_trunk(configs)

    assert result.check_id == "L5-02"
    assert result.status == "pass"


@pytest.mark.unit
def test_bpdu_filter_in_port_usages():
    """BPDU filter in port_usages on a trunk profile — should be critical."""
    configs = {
        "sw1": {
            "port_usages": {
                "uplink": {
                    "mode": "trunk",
                    "bpdu_filter": True,
                }
            }
        }
    }

    result = check_bpdu_filter_on_trunk(configs)

    assert result.check_id == "L5-02"
    assert result.status == "critical"


@pytest.mark.unit
def test_bpdu_filter_empty_configs_pass():
    """Empty device configs — should pass."""
    result = check_bpdu_filter_on_trunk({})
    assert result.check_id == "L5-02"
    assert result.status == "pass"


# ---------------------------------------------------------------------------
# L5-03: STP root bridge shift
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_stp_root_bridge_shift_skipped_no_stp_config():
    """No STP priority anywhere — should be skipped."""
    baseline = {
        "sw1": {"hostname": "sw1"},
        "sw2": {"hostname": "sw2"},
    }
    predicted = {
        "sw1": {"hostname": "sw1"},
        "sw2": {"hostname": "sw2"},
    }

    result = check_stp_root_bridge_shift(baseline, predicted)

    assert result.check_id == "L5-03"
    assert result.layer == 5
    assert result.status == "skipped"


@pytest.mark.unit
def test_stp_root_bridge_shift_pass_no_change():
    """Same STP priorities in baseline and predicted — should pass."""
    baseline = {
        "sw1": {"stp_priority": 4096},
        "sw2": {"stp_priority": 32768},
    }
    predicted = {
        "sw1": {"stp_priority": 4096},
        "sw2": {"stp_priority": 32768},
    }

    result = check_stp_root_bridge_shift(baseline, predicted)

    assert result.check_id == "L5-03"
    assert result.status == "pass"


@pytest.mark.unit
def test_stp_root_bridge_shift_warning_root_changes():
    """Priority change shifts root bridge — should be warning."""
    baseline = {
        "sw1": {"stp_priority": 4096},  # root
        "sw2": {"stp_priority": 32768},
    }
    predicted = {
        "sw1": {"stp_priority": 32768},  # no longer root
        "sw2": {"stp_priority": 4096},  # becomes root
    }

    result = check_stp_root_bridge_shift(baseline, predicted)

    assert result.check_id == "L5-03"
    assert result.status == "warning"
    assert len(result.affected_objects) > 0


@pytest.mark.unit
def test_stp_root_bridge_shift_rstp_priority_variant():
    """rstp_priority variant triggers the same check."""
    baseline = {
        "sw1": {"rstp_priority": 4096},
        "sw2": {"rstp_priority": 32768},
    }
    predicted = {
        "sw1": {"rstp_priority": 32768},
        "sw2": {"rstp_priority": 4096},
    }

    result = check_stp_root_bridge_shift(baseline, predicted)

    assert result.check_id == "L5-03"
    assert result.status == "warning"


@pytest.mark.unit
def test_stp_root_bridge_shift_bridge_priority_variant():
    """bridge_priority variant triggers the same check."""
    baseline = {
        "sw1": {"bridge_priority": 8192},
        "sw2": {"bridge_priority": 32768},
    }
    predicted = {
        "sw1": {"bridge_priority": 32768},
        "sw2": {"bridge_priority": 8192},
    }

    result = check_stp_root_bridge_shift(baseline, predicted)

    assert result.check_id == "L5-03"
    assert result.status == "warning"


@pytest.mark.unit
def test_stp_root_bridge_shift_pass_priority_change_no_root_shift():
    """Priority changes but same device stays root — should pass."""
    baseline = {
        "sw1": {"stp_priority": 4096},  # root
        "sw2": {"stp_priority": 32768},
    }
    predicted = {
        "sw1": {"stp_priority": 4096},  # still root
        "sw2": {"stp_priority": 8192},  # changed but still higher than sw1
    }

    result = check_stp_root_bridge_shift(baseline, predicted)

    assert result.check_id == "L5-03"
    # sw1 is still root in both — no shift
    assert result.status == "pass"
