"""Tests for cascade_restore parent ordering and id_remap propagation."""

import hashlib
import json
import uuid
from typing import Any

from app.modules.backup.models import BackupEventType, BackupObject, ObjectReference
from app.modules.backup.services.restore_service import RestoreService

# ── Helpers ──────────────────────────────────────────────────────────────────


class _FakeMistService:
    """Minimal MistService stub that records POST and PUT calls."""

    def __init__(self):
        self.org_id = "org-1"
        self.post_calls: list[tuple[str, dict]] = []
        self.put_calls: list[tuple[str, dict]] = []

    async def api_post(self, endpoint: str, config: dict) -> dict:
        new_id = str(uuid.uuid4())
        self.post_calls.append((endpoint, config))
        return {**config, "id": new_id}

    async def api_put(self, endpoint: str, config: dict) -> dict:
        self.put_calls.append((endpoint, config))
        return {**config, "_via": "put"}


async def _seed_backup(
    object_type: str,
    object_id: str,
    org_id: str,
    *,
    site_id: str | None = None,
    configuration: dict | None = None,
    version: int = 1,
    is_deleted: bool = False,
    previous_version_id=None,
    object_name: str | None = None,
    references: list[dict] | None = None,
) -> BackupObject:
    """Insert a BackupObject into the test DB and return it."""
    if configuration is None:
        configuration = {}
    config_hash = hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()
    refs = [ObjectReference(**r) for r in references] if references else []
    doc = BackupObject(
        object_type=object_type,
        object_id=object_id,
        object_name=object_name or object_type,
        org_id=org_id,
        site_id=site_id,
        configuration=configuration,
        configuration_hash=config_hash,
        version=version,
        previous_version_id=previous_version_id,
        event_type=BackupEventType.DELETED if is_deleted else BackupEventType.CREATED,
        is_deleted=is_deleted,
        references=refs,
    )
    await doc.insert()
    return doc


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_cascade_restore_reorders_parents_site_first(test_db, monkeypatch):
    """
    When _validate_restore returns deleted_dependencies with a wxtag listed
    BEFORE the site, cascade_restore must still POST 'sites' first then
    'wxtags', and the wxtag endpoint must use the new site UUID from id_remap.
    """
    org_id = "org-1"
    site_id = "site-a"
    wxtag_id = "wxtag-1"
    wxrule_id = "wxrule-1"

    # --- seed: site-A (active v1, deleted v2) ---
    site_v1 = await _seed_backup(
        "sites",
        site_id,
        org_id,
        configuration={"name": "Site A"},
        version=1,
        object_name="Site A",
    )
    await _seed_backup(
        "sites",
        site_id,
        org_id,
        configuration={},
        version=2,
        is_deleted=True,
        previous_version_id=site_v1.id,
    )

    # --- seed: wxtag on site-A (active v1, deleted v2) ---
    wxtag_v1 = await _seed_backup(
        "wxtags",
        wxtag_id,
        org_id,
        site_id=site_id,
        configuration={"name": "My Tag"},
        version=1,
        object_name="My Tag",
    )
    await _seed_backup(
        "wxtags",
        wxtag_id,
        org_id,
        site_id=site_id,
        configuration={},
        version=2,
        is_deleted=True,
        previous_version_id=wxtag_v1.id,
    )

    # --- seed: wxrule on site-A referencing the wxtag (active v1, deleted v2) ---
    wxrule_v1 = await _seed_backup(
        "wxrules",
        wxrule_id,
        org_id,
        site_id=site_id,
        configuration={"name": "My Rule", "src_wxtags": [wxtag_id]},
        version=1,
        object_name="My Rule",
    )
    await _seed_backup(
        "wxrules",
        wxrule_id,
        org_id,
        site_id=site_id,
        configuration={},
        version=2,
        is_deleted=True,
        previous_version_id=wxrule_v1.id,
    )

    # --- patch _validate_restore to return wxtag BEFORE site (bad ordering) ---
    async def _fake_validate(backup: BackupObject) -> dict[str, Any]:
        return {
            "valid": True,
            "exists_in_mist": False,
            "warnings": [],
            "deleted_dependencies": [
                # wxtag listed first — simulates the current bad ordering
                {
                    "object_id": wxtag_id,
                    "object_type": "wxtags",
                    "object_name": "My Tag",
                    "field_path": "src_wxtags",
                    "relationship": "parent",
                    "org_id": org_id,
                    "site_id": site_id,
                },
                {
                    "object_id": site_id,
                    "object_type": "sites",
                    "object_name": "Site A",
                    "field_path": "site_id",
                    "relationship": "parent",
                    "org_id": org_id,
                    "site_id": None,
                },
            ],
            "deleted_children": [],
            "active_children": [],
        }

    fake_mist = _FakeMistService()
    service = RestoreService(fake_mist)
    monkeypatch.setattr(service, "_validate_restore", _fake_validate)

    # Pass the wxrule deletion version_id (v2)
    wxrule_v2 = await BackupObject.find_one(
        BackupObject.object_id == wxrule_id,
        {"is_deleted": True},
    )
    assert wxrule_v2 is not None

    result = await service.cascade_restore(
        version_id=wxrule_v2.id,
        include_parents=True,
        include_children=False,
        dry_run=False,
        restored_by="test",
    )

    assert result["status"] == "success"

    # 1. "sites" must be POST-ed before "wxtags"
    post_types = [ep.split("/")[5] for ep in [call[0] for call in fake_mist.post_calls]]
    assert post_types[0] == "sites", f"Expected first POST to 'sites', got: {post_types}"
    assert "wxtags" in post_types, f"Expected 'wxtags' in POSTs, got: {post_types}"
    sites_idx = post_types.index("sites")
    wxtags_idx = post_types.index("wxtags")
    assert sites_idx < wxtags_idx, (
        f"'sites' must be created before 'wxtags'; order was: {post_types}"
    )

    # 2. The wxtag endpoint must use the NEW site UUID (from id_remap), not site-a
    wxtag_endpoint = fake_mist.post_calls[wxtags_idx][0]
    new_site_uuid = result["id_remap"].get(site_id)
    assert new_site_uuid is not None, "id_remap must contain a new UUID for the restored site"
    assert new_site_uuid in wxtag_endpoint, (
        f"wxtag POST endpoint '{wxtag_endpoint}' should contain new site UUID '{new_site_uuid}'"
    )
    assert site_id not in wxtag_endpoint, (
        f"wxtag POST endpoint '{wxtag_endpoint}' must NOT use original site_id '{site_id}'"
    )


async def test_validate_restore_batches_deleted_children(test_db, monkeypatch):
    """
    Characterization test: _validate_restore collects deleted children that
    reference the target via the BackupObject.references index.

    Scenario:
      - target: wxtag "tag-1" on site-A
      - rule-1: 3 versions (v1 active, v2 active, v3 deleted) — references tag-1
      - rule-2: 2 versions (v1 active, v2 deleted)            — references tag-1
      - rule-3: 1 version  (v1 active, NOT deleted)           — decoy, must be excluded
    """
    org_id = "org-1"
    site_id = "site-A"
    tag_id = "tag-1"

    # --- target: wxtag tag-1 (active v1) ---
    tag_v1 = await _seed_backup(
        "wxtags",
        tag_id,
        org_id,
        site_id=site_id,
        configuration={"name": "My Tag"},
        version=1,
        object_name="My Tag",
    )

    # --- rule-1: 3 versions, v3 deleted ---
    rule1_v1 = await _seed_backup(
        "wxrules",
        "rule-1",
        org_id,
        site_id=site_id,
        configuration={"src_wxtags": [tag_id]},
        version=1,
        object_name="Rule 1",
        references=[{"target_type": "wxtags", "target_id": tag_id, "field_path": "src_wxtags"}],
    )
    rule1_v2 = await _seed_backup(
        "wxrules",
        "rule-1",
        org_id,
        site_id=site_id,
        configuration={"src_wxtags": [tag_id]},
        version=2,
        object_name="Rule 1",
        previous_version_id=rule1_v1.id,
        references=[{"target_type": "wxtags", "target_id": tag_id, "field_path": "src_wxtags"}],
    )
    await _seed_backup(
        "wxrules",
        "rule-1",
        org_id,
        site_id=site_id,
        configuration={},
        version=3,
        is_deleted=True,
        object_name="Rule 1",
        previous_version_id=rule1_v2.id,
        references=[{"target_type": "wxtags", "target_id": tag_id, "field_path": "src_wxtags"}],
    )

    # --- rule-2: 2 versions, v2 deleted ---
    rule2_v1 = await _seed_backup(
        "wxrules",
        "rule-2",
        org_id,
        site_id=site_id,
        configuration={"src_wxtags": [tag_id]},
        version=1,
        object_name="Rule 2",
        references=[{"target_type": "wxtags", "target_id": tag_id, "field_path": "src_wxtags"}],
    )
    await _seed_backup(
        "wxrules",
        "rule-2",
        org_id,
        site_id=site_id,
        configuration={},
        version=2,
        is_deleted=True,
        object_name="Rule 2",
        previous_version_id=rule2_v1.id,
        references=[{"target_type": "wxtags", "target_id": tag_id, "field_path": "src_wxtags"}],
    )

    # --- rule-3: decoy — active v1, NOT deleted, references tag-1 ---
    await _seed_backup(
        "wxrules",
        "rule-3",
        org_id,
        site_id=site_id,
        configuration={"src_wxtags": [tag_id]},
        version=1,
        object_name="Rule 3",
        references=[{"target_type": "wxtags", "target_id": tag_id, "field_path": "src_wxtags"}],
    )

    # --- patch _fetch_current_config to return {} (exists_in_mist=True) ---
    async def _fake_fetch(object_type, object_id, site_id=None):
        return {}

    fake_mist = _FakeMistService()
    service = RestoreService(fake_mist)
    monkeypatch.setattr(service, "_fetch_current_config", _fake_fetch)

    result = await service._validate_restore(tag_v1)

    child_ids = [c["object_id"] for c in result["deleted_children"]]
    assert "rule-1" in child_ids, f"rule-1 should be a deleted child; got: {child_ids}"
    assert "rule-2" in child_ids, f"rule-2 should be a deleted child; got: {child_ids}"
    assert "rule-3" not in child_ids, f"rule-3 is active and must NOT appear; got: {child_ids}"
    # Each rule should appear exactly once (deduplication)
    assert child_ids.count("rule-1") == 1, f"rule-1 appears more than once: {child_ids}"
    assert child_ids.count("rule-2") == 1, f"rule-2 appears more than once: {child_ids}"


async def test_validate_restore_collects_site_scoped_children_when_restoring_site(test_db, monkeypatch):
    """
    Characterization test: _validate_restore collects deleted site-scoped
    children (via site_id membership) when the target is a site.

    Scenario:
      - site-A: v1 active, v2 deleted
      - children of site-A (all with v1 active, v2 deleted):
          map-1 (maps), wlan-1 (wlans), settings singleton (settings)
      - decoy: settings on site-B — active v1 only, must be excluded
      - excluded: info record for site-A — must be excluded by object_type != "info"
    """
    org_id = "org-1"

    # --- site-A: v1 active, v2 deleted ---
    site_v1 = await _seed_backup(
        "sites",
        "site-A",
        org_id,
        configuration={"name": "Site A"},
        version=1,
        object_name="Site A",
    )
    site_v2 = await _seed_backup(
        "sites",
        "site-A",
        org_id,
        configuration={},
        version=2,
        is_deleted=True,
        object_name="Site A",
        previous_version_id=site_v1.id,
    )

    # --- map-1 on site-A ---
    map_v1 = await _seed_backup(
        "maps",
        "map-1",
        org_id,
        site_id="site-A",
        configuration={"name": "Floor 1"},
        version=1,
        object_name="Floor 1",
    )
    await _seed_backup(
        "maps",
        "map-1",
        org_id,
        site_id="site-A",
        configuration={},
        version=2,
        is_deleted=True,
        object_name="Floor 1",
        previous_version_id=map_v1.id,
    )

    # --- wlan-1 on site-A ---
    wlan_v1 = await _seed_backup(
        "wlans",
        "wlan-1",
        org_id,
        site_id="site-A",
        configuration={"ssid": "Corp"},
        version=1,
        object_name="Corp",
    )
    await _seed_backup(
        "wlans",
        "wlan-1",
        org_id,
        site_id="site-A",
        configuration={},
        version=2,
        is_deleted=True,
        object_name="Corp",
        previous_version_id=wlan_v1.id,
    )

    # --- settings singleton on site-A ---
    settings_v1 = await _seed_backup(
        "settings",
        "settings",
        org_id,
        site_id="site-A",
        configuration={"rf_template_id": None},
        version=1,
        object_name="settings",
    )
    await _seed_backup(
        "settings",
        "settings",
        org_id,
        site_id="site-A",
        configuration={},
        version=2,
        is_deleted=True,
        object_name="settings",
        previous_version_id=settings_v1.id,
    )

    # --- decoy: settings on site-B — active only, must NOT appear ---
    # Note: unique_object_version index is on (object_id, version) globally,
    # so we use version=3 to avoid colliding with site-A settings v1/v2.
    await _seed_backup(
        "settings",
        "settings",
        org_id,
        site_id="site-B",
        configuration={"rf_template_id": None},
        version=3,
        object_name="settings",
    )

    # --- excluded: info record for site-A — excluded by object_type != "info" filter ---
    # Use version=3 and version=4 to avoid colliding with the sites records (v1, v2).
    # The unique index is on (object_id, version) globally.
    info_v1 = await _seed_backup(
        "info",
        "site-A",
        org_id,
        site_id="site-A",
        configuration={"name": "Site A"},
        version=3,
        object_name="Site A",
    )
    await _seed_backup(
        "info",
        "site-A",
        org_id,
        site_id="site-A",
        configuration={},
        version=4,
        is_deleted=True,
        object_name="Site A",
        previous_version_id=info_v1.id,
    )

    # --- patch _fetch_current_config to raise (exists_in_mist=False) ---
    async def _fake_fetch_raises(object_type, object_id, site_id=None):
        raise Exception("not found")

    fake_mist = _FakeMistService()
    service = RestoreService(fake_mist)
    monkeypatch.setattr(service, "_fetch_current_config", _fake_fetch_raises)

    # Pass the active version (v1) of the site — the code checks object_type == "sites"
    result = await service._validate_restore(site_v1)

    child_ids = [c["object_id"] for c in result["deleted_children"]]
    child_types = {c["object_id"]: c["object_type"] for c in result["deleted_children"]}

    assert "map-1" in child_ids, f"map-1 should be a site-scoped child; got: {child_ids}"
    assert "wlan-1" in child_ids, f"wlan-1 should be a site-scoped child; got: {child_ids}"

    # settings from site-A must be present; identify by (object_id, site_id) pair
    settings_children = [c for c in result["deleted_children"] if c["object_id"] == "settings"]
    assert len(settings_children) >= 1, f"settings (site-A) should be a child; got: {result['deleted_children']}"
    assert all(c["site_id"] == "site-A" for c in settings_children), (
        f"settings child must be from site-A only; got: {settings_children}"
    )

    # info must be excluded
    assert "info" not in child_types.values(), f"info type must be excluded; got: {child_ids}"

    # site-B settings must not appear
    site_b_settings = [c for c in result["deleted_children"] if c["object_id"] == "settings" and c.get("site_id") == "site-B"]
    assert len(site_b_settings) == 0, f"site-B settings must not appear; got: {site_b_settings}"
