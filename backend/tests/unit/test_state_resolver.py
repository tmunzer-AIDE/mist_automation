"""Unit tests for the Digital Twin state resolver."""

import pytest

from app.modules.digital_twin.models import StagedWrite
from app.modules.digital_twin.services.state_resolver import (
    apply_staged_writes,
    collect_affected_metadata,
    merge_write_into_state,
)


@pytest.mark.unit
class TestMergeWriteIntoState:
    def test_put_merges_into_existing_object(self):
        state = {("wlans", "site-1", "wlan-1"): {"ssid": "Office", "vlan_id": "100", "enabled": True}}
        write = StagedWrite(
            sequence=0,
            method="PUT",
            endpoint="/api/v1/sites/site-1/wlans/wlan-1",
            body={"ssid": "Office-New", "band": "5"},
            object_type="wlans",
            site_id="site-1",
            object_id="wlan-1",
        )
        merge_write_into_state(state, write)
        obj = state[("wlans", "site-1", "wlan-1")]
        assert obj["ssid"] == "Office-New"
        assert obj["vlan_id"] == "100"  # preserved
        assert obj["band"] == "5"  # added

    def test_post_creates_new_object(self):
        state: dict = {}
        write = StagedWrite(
            sequence=0,
            method="POST",
            endpoint="/api/v1/sites/site-1/wlans",
            body={"ssid": "Guest", "vlan_id": "200"},
            object_type="wlans",
            site_id="site-1",
        )
        merge_write_into_state(state, write)
        keys = [k for k in state if k[0] == "wlans" and k[1] == "site-1"]
        assert len(keys) == 1
        obj = state[keys[0]]
        assert obj["ssid"] == "Guest"

    def test_delete_marks_object_tombstone(self):
        state = {("wlans", "site-1", "wlan-1"): {"ssid": "Old", "vlan_id": "100"}}
        write = StagedWrite(
            sequence=0,
            method="DELETE",
            endpoint="/api/v1/sites/site-1/wlans/wlan-1",
            object_type="wlans",
            site_id="site-1",
            object_id="wlan-1",
        )
        merge_write_into_state(state, write)
        assert state[("wlans", "site-1", "wlan-1")]["__twin_deleted__"] is True

    def test_put_creates_if_missing(self):
        state: dict = {}
        write = StagedWrite(
            sequence=0,
            method="PUT",
            endpoint="/api/v1/sites/site-1/setting",
            body={"vars": {"office_vlan": "100"}},
            object_type="setting",
            site_id="site-1",
        )
        merge_write_into_state(state, write)
        assert ("settings", "site-1", None) in state


class TestApplyStagedWrites:
    def test_applies_writes_in_sequence_order(self):
        writes = [
            StagedWrite(
                sequence=1,
                method="POST",
                endpoint="/api/v1/sites/s1/wlans",
                body={"ssid": "First"},
                object_type="wlans",
                site_id="s1",
            ),
            StagedWrite(
                sequence=0,
                method="POST",
                endpoint="/api/v1/sites/s1/networks",
                body={"name": "Net1", "subnet": "10.0.0.0/24"},
                object_type="networks",
                site_id="s1",
            ),
        ]
        state = apply_staged_writes({}, writes)
        wlan_keys = [k for k in state if k[0] == "wlans"]
        net_keys = [k for k in state if k[0] == "networks"]
        assert len(wlan_keys) == 1
        assert len(net_keys) == 1


class TestCollectAffectedMetadata:
    def test_collects_unique_sites_and_types(self):
        writes = [
            StagedWrite(sequence=0, method="PUT", endpoint="", body={}, object_type="wlans", site_id="s1"),
            StagedWrite(sequence=1, method="PUT", endpoint="", body={}, object_type="networks", site_id="s1"),
            StagedWrite(sequence=2, method="PUT", endpoint="", body={}, object_type="wlans", site_id="s2"),
        ]
        sites, types = collect_affected_metadata(writes)
        assert sorted(sites) == ["s1", "s2"]
        assert sorted(types) == ["networks", "wlans"]

    def test_skips_none_sites(self):
        writes = [
            StagedWrite(sequence=0, method="PUT", endpoint="", body={}, object_type="templates", site_id=None),
        ]
        sites, types = collect_affected_metadata(writes)
        assert sites == []
        assert types == ["templates"]
