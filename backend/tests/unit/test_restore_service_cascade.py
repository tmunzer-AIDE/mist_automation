"""Tests for cascade_restore parent ordering and id_remap propagation."""

import hashlib
import json
import uuid
from typing import Any

from app.modules.backup.models import BackupEventType, BackupObject
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
) -> BackupObject:
    """Insert a BackupObject into the test DB and return it."""
    if configuration is None:
        configuration = {}
    config_hash = hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()
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
