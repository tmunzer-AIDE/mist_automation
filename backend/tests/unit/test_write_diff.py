from app.modules.digital_twin.models import StagedWrite
from app.modules.digital_twin.services.write_diff import build_write_diff


def test_diff_for_put_modifies_existing():
    base = {"name": "default", "port_usages": {"trunk": {"vlan_id": 10}}}
    write = StagedWrite(
        sequence=0,
        method="PUT",
        endpoint="/api/v1/orgs/org-id/networktemplates/t1",
        body={"name": "default", "port_usages": {"trunk": {"vlan_id": 20}}},
        object_type="networktemplates",
        object_id="t1",
    )
    diff, summary = build_write_diff(write, base)
    assert summary == "1 field changed"
    assert len(diff) == 1
    assert diff[0]["path"] == "port_usages.trunk.vlan_id"
    assert diff[0]["change"] == "modified"
    assert diff[0]["before"] == 10
    assert diff[0]["after"] == 20


def test_diff_for_post_marks_all_fields_added():
    write = StagedWrite(
        sequence=0,
        method="POST",
        endpoint="/api/v1/orgs/org-id/networktemplates",
        body={"name": "new-template", "enabled": True},
        object_type="networktemplates",
    )
    diff, summary = build_write_diff(write, None)
    assert summary == "new object"
    paths = {d["path"] for d in diff}
    assert paths == {"name", "enabled"}
    assert all(d["change"] == "added" for d in diff)


def test_diff_for_delete_has_no_fields():
    write = StagedWrite(
        sequence=0,
        method="DELETE",
        endpoint="/api/v1/orgs/org-id/networktemplates/t1",
        body=None,
        object_type="networktemplates",
        object_id="t1",
    )
    diff, summary = build_write_diff(write, {"name": "doomed"})
    assert summary == "deleted"
    assert diff == []


def test_diff_for_put_against_missing_base_treats_all_as_added():
    write = StagedWrite(
        sequence=0,
        method="PUT",
        endpoint="/api/v1/orgs/org-id/networktemplates/t1",
        body={"name": "x"},
        object_type="networktemplates",
        object_id="t1",
    )
    diff, summary = build_write_diff(write, None)
    assert summary == "1 field changed"
    assert diff[0]["change"] == "added"
    assert diff[0]["path"] == "name"


def test_diff_for_put_with_removed_field():
    base = {"name": "t", "description": "old desc", "enabled": True}
    write = StagedWrite(
        sequence=0,
        method="PUT",
        endpoint="/api/v1/orgs/org-id/networktemplates/t1",
        body={"name": "t", "enabled": True},  # description dropped
        object_type="networktemplates",
        object_id="t1",
    )
    diff, summary = build_write_diff(write, base)
    assert diff == []
    assert summary == "0 fields changed"


def test_diff_for_put_empty_body_has_no_changes():
    base = {"name": "default", "enabled": True}
    write = StagedWrite(
        sequence=0,
        method="PUT",
        endpoint="/api/v1/orgs/org-id/networktemplates/t1",
        body={},
        object_type="networktemplates",
        object_id="t1",
    )
    diff, summary = build_write_diff(write, base)
    assert diff == []
    assert summary == "0 fields changed"


def test_diff_for_put_replaces_specified_dict_root_key():
    base = {
        "name": "default",
        "key1": {"nested_a": 1, "nested_b": 2},
        "key2": "preserved",
    }
    write = StagedWrite(
        sequence=0,
        method="PUT",
        endpoint="/api/v1/orgs/org-id/networktemplates/t1",
        body={"key1": {"nested_a": 9}},
        object_type="networktemplates",
        object_id="t1",
    )
    diff, summary = build_write_diff(write, base)

    by_path = {d["path"]: d for d in diff}
    assert "key2" not in by_path
    assert by_path["key1.nested_a"]["change"] == "modified"
    assert by_path["key1.nested_a"]["before"] == 1
    assert by_path["key1.nested_a"]["after"] == 9
    assert by_path["key1.nested_b"]["change"] == "removed"
    assert by_path["key1.nested_b"]["before"] == 2
    assert by_path["key1.nested_b"]["after"] is None
    assert summary == "2 fields changed"


def test_diff_for_put_port_config_replaces_specified_dict_root_key():
    base = {
        "port_config": {
            "ge-0/0/1": {"usage": "access", "description": "uplink"},
            "ge-0/0/2": {"usage": "ap"},
        }
    }
    write = StagedWrite(
        sequence=0,
        method="PUT",
        endpoint="/api/v1/sites/site-1/devices/dev-1",
        body={"port_config": {"ge-0/0/1": {"usage": "trunk"}}},
        object_type="devices",
        site_id="site-1",
        object_id="dev-1",
    )

    diff, summary = build_write_diff(write, base)
    by_path = {d["path"]: d for d in diff}

    assert by_path["port_config.ge-0/0/1.usage"]["change"] == "modified"
    assert by_path["port_config.ge-0/0/1.usage"]["before"] == "access"
    assert by_path["port_config.ge-0/0/1.usage"]["after"] == "trunk"
    assert by_path["port_config.ge-0/0/1.description"]["change"] == "removed"
    assert by_path["port_config.ge-0/0/1.description"]["before"] == "uplink"
    assert by_path["port_config.ge-0/0/1.description"]["after"] is None
    assert by_path["port_config.ge-0/0/2"]["change"] == "removed"
    assert by_path["port_config.ge-0/0/2"]["before"] == {"usage": "ap"}
    assert by_path["port_config.ge-0/0/2"]["after"] is None
    assert summary == "3 fields changed"
