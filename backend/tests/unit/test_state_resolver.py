"""Unit tests for the Digital Twin state resolver."""

from types import SimpleNamespace

import pytest

from app.modules.digital_twin.models import StagedWrite
from app.modules.digital_twin.services.state_resolver import (
    apply_staged_writes,
    collect_affected_metadata,
    load_base_state_from_backup,
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

    def test_put_replaces_nested_dict_root_key(self):
        state = {
            ("devices", "site-1", "dev-1"): {
                "port_config": {
                    "ge-0/0/1": {"usage": "ap", "description": "old"},
                    "ge-0/0/2": {"usage": "trunk"},
                },
                "name": "sw1",
            }
        }
        write = StagedWrite(
            sequence=0,
            method="PUT",
            endpoint="/api/v1/sites/site-1/devices/dev-1",
            body={"port_config": {"ge-0/0/1": {"usage": "disabled"}}},
            object_type="devices",
            site_id="site-1",
            object_id="dev-1",
        )

        merge_write_into_state(state, write)

        obj = state[("devices", "site-1", "dev-1")]
        assert obj["name"] == "sw1"
        assert obj["port_config"] == {"ge-0/0/1": {"usage": "disabled"}}


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


@pytest.mark.unit
class TestLoadBaseStateFromBackup:
    class FakeCursor:
        def __init__(self, docs, query):
            self.docs = docs
            self.query = query

        def sort(self, *_args, **_kwargs):
            return self

        async def first_or_none(self):
            for doc in self.docs:
                if all(doc.get(k) == v for k, v in self.query.items()):
                    return SimpleNamespace(**doc)
            return None

    class _FakeBackupObject:
        docs = []

        @classmethod
        def find(cls, query):
            return TestLoadBaseStateFromBackup.FakeCursor(cls.docs, query)

    async def test_site_info_put_uses_sites_fallback_shape(self, monkeypatch):
        from app.modules.backup import models as backup_models

        self._FakeBackupObject.docs = [
            {
                "object_type": "sites",
                "object_id": "site-1",
                "site_id": "site-1",
                "org_id": "org-1",
                "is_deleted": False,
                "version": 4,
                "id": "backup-doc-1",
                "configuration": {
                    "name": "Site Current",
                    "networktemplate_id": "nt-1",
                    "gatewaytemplate_id": "gt-1",
                },
            }
        ]
        monkeypatch.setattr(backup_models, "BackupObject", self._FakeBackupObject)

        writes = [
            StagedWrite(
                sequence=0,
                method="PUT",
                endpoint="/api/v1/sites/site-1",
                body={"name": "Site Renamed"},
                object_type="info",
                site_id="site-1",
                object_id=None,
            )
        ]

        base_state, _refs = await load_base_state_from_backup("org-1", writes)
        assert ("info", "site-1", None) in base_state
        assert base_state[("info", "site-1", None)]["networktemplate_id"] == "nt-1"

        predicted_state = apply_staged_writes(base_state, writes)
        predicted_info = predicted_state[("info", "site-1", None)]
        assert predicted_info["name"] == "Site Renamed"
        assert predicted_info["networktemplate_id"] == "nt-1"
        assert predicted_info["gatewaytemplate_id"] == "gt-1"


@pytest.mark.unit
class TestApplyStagedWritesIsolation:
    """Regression: apply_staged_writes must deep-copy base_state so downstream
    mutations on nested dicts don't leak back into the caller's baseline.
    """

    def test_nested_dict_mutation_does_not_affect_base_state(self):
        base_state: dict = {
            ("settings", "site-1", None): {
                "vars": {"k1": "v1"},
                "port_usages": {"uplink": {"mode": "trunk"}},
            },
        }
        write = StagedWrite(
            sequence=0,
            method="PUT",
            endpoint="/api/v1/sites/site-1/setting",
            body={"vars": {"k1": "changed", "k2": "new"}},
            object_type="settings",
            site_id="site-1",
            object_id=None,
        )

        predicted = apply_staged_writes(base_state, [write])
        predicted_obj = predicted[("settings", "site-1", None)]
        predicted_obj["port_usages"]["uplink"]["mode"] = "mutated"

        base_obj = base_state[("settings", "site-1", None)]
        # Baseline port_usages.uplink.mode must remain untouched.
        assert base_obj["port_usages"]["uplink"]["mode"] == "trunk"
        # Baseline vars must also be untouched.
        assert base_obj["vars"] == {"k1": "v1"}
