"""Unit tests for backup object version consistency and summary timestamps."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from app.modules.backup.models import BackupEventType, BackupObject
from app.modules.backup.services.backup_service import BackupService


class _MistServiceStub:
    """Minimal MistService stub for BackupService unit tests."""

    def __init__(self, org_id: str):
        self.org_id = org_id
        self.session = None


class _BackupServiceStub(BackupService):
    """BackupService test double that bypasses Mist API fetches."""

    def __init__(self, mist_service, config: dict):
        super().__init__(mist_service)
        self._config = config

    async def _fetch_object_from_mist(self, object_type: str, object_id: str) -> dict:
        return self._config


@pytest.mark.unit
@pytest.mark.usefixtures("test_db")
async def test_backup_object_recreates_new_version_when_latest_is_deleted():
    """If latest version is deleted, backing up the object again must create a new active version."""
    object_id = "9a7a4c8d-8868-4715-ae43-0ebda664edfc"
    org_id = "7aaa4c8d-8868-4715-ae43-0ebda664edfc"
    config = {"id": object_id, "name": "esp-wled", "ssid": "esp-wled"}
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()

    v1 = BackupObject(
        object_type="psks",
        object_id=object_id,
        object_name="esp-wled",
        org_id=org_id,
        site_id=None,
        configuration=config,
        configuration_hash=config_hash,
        version=1,
        event_type=BackupEventType.CREATED,
        changed_fields=[],
        backed_up_at=datetime(2026, 4, 1, 6, 0, 4, tzinfo=timezone.utc),
        backed_up_by="system",
        is_deleted=False,
    )
    await v1.insert()

    v2 = BackupObject(
        object_type="psks",
        object_id=object_id,
        object_name="esp-wled",
        org_id=org_id,
        site_id=None,
        configuration=config,
        configuration_hash=config_hash,
        version=2,
        previous_version_id=v1.id,
        event_type=BackupEventType.DELETED,
        changed_fields=[],
        backed_up_at=datetime(2026, 4, 8, 6, 0, 4, tzinfo=timezone.utc),
        backed_up_by="system",
        is_deleted=True,
        deleted_at=datetime(2026, 4, 8, 6, 0, 4, tzinfo=timezone.utc),
    )
    await v2.insert()

    service = _BackupServiceStub(_MistServiceStub(org_id=org_id), config)

    result = await service.backup_single_object(
        object_type="psks",
        object_id=object_id,
        event_type=BackupEventType.CREATED,
    )

    assert result is not None

    latest = (
        await BackupObject.find(BackupObject.object_id == object_id)
        .sort([("version", -1)])
        .first_or_none()
    )
    assert latest is not None
    assert latest.version == 3
    assert latest.is_deleted is False
    assert latest.previous_version_id == v2.id


@pytest.mark.unit
@pytest.mark.usefixtures("test_db")
async def test_backup_object_summary_uses_latest_version_timestamp_for_last_backup():
    """Object summary last_backed_up_at must follow latest version, not max historical timestamp."""
    from app.api.v1.backup import list_backup_objects

    object_id = "6a7a4c8d-8868-4715-ae43-0ebda664edfc"
    org_id = "5aaa4c8d-8868-4715-ae43-0ebda664edfc"
    config = {"id": object_id, "name": "esp-wled", "ssid": "esp-wled"}
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()

    # Older version number with a newer backed_up_at (historical skew).
    v1 = BackupObject(
        object_type="psks",
        object_id=object_id,
        object_name="esp-wled",
        org_id=org_id,
        site_id=None,
        configuration=config,
        configuration_hash=config_hash,
        version=1,
        event_type=BackupEventType.CREATED,
        changed_fields=[],
        backed_up_at=datetime(2026, 4, 16, 6, 0, 4, tzinfo=timezone.utc),
        backed_up_by="system",
        is_deleted=False,
    )
    await v1.insert()

    # Latest version is deleted and older in time.
    deleted_at = datetime(2026, 4, 8, 6, 0, 4, tzinfo=timezone.utc)
    v2 = BackupObject(
        object_type="psks",
        object_id=object_id,
        object_name="esp-wled",
        org_id=org_id,
        site_id=None,
        configuration=config,
        configuration_hash=config_hash,
        version=2,
        previous_version_id=v1.id,
        event_type=BackupEventType.DELETED,
        changed_fields=[],
        backed_up_at=deleted_at,
        backed_up_by="system",
        is_deleted=True,
        deleted_at=deleted_at,
    )
    await v2.insert()

    current_user = type("UserStub", (), {"id": "u-1"})()
    response = await list_backup_objects(
        skip=0,
        limit=50,
        search=None,
        object_type=None,
        site_id=None,
        scope=None,
        status_filter="deleted",
        sort=None,
        order=None,
        _current_user=current_user,
    )

    assert response.total == 1
    assert len(response.objects) == 1
    assert response.objects[0].object_id == object_id
    assert response.objects[0].last_backed_up_at == deleted_at.replace(tzinfo=None)
    assert response.objects[0].last_backed_up_at != datetime(2026, 4, 16, 6, 0, 4)
