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
    removed = [d for d in diff if d["change"] == "removed"]
    assert len(removed) == 1
    assert removed[0]["path"] == "description"
    assert removed[0]["before"] == "old desc"
    assert removed[0]["after"] is None
    assert summary == "1 field changed"
