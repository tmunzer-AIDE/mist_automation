"""Unit tests for Digital Twin preflight write-target validation."""

import pytest

import app.modules.backup.models as backup_models
from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.models import StagedWrite
from app.modules.digital_twin.services import twin_service

validate_write_targets = getattr(twin_service, "_validate_write_targets")
has_blocking_preflight_errors = getattr(twin_service, "_has_blocking_preflight_errors")


def _matches(doc: dict, query: dict) -> bool:
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(doc, branch) for branch in expected):
                return False
            continue
        if doc.get(key) != expected:
            return False
    return True


class _FakeCursor:
    def __init__(self, docs: list[dict], query: dict):
        self.docs = docs
        self.query = query

    async def first_or_none(self):
        for doc in self.docs:
            if _matches(doc, self.query):
                return doc
        return None


class _FakeBackupObject:
    docs: list[dict] = []

    @classmethod
    def find(cls, query):
        return _FakeCursor(cls.docs, query)


@pytest.mark.unit
class TestTwinServicePreflight:
    def test_blocking_preflight_detected_for_sys_error(self):
        checks = [
            CheckResult(
                check_id="SYS-02-0",
                check_name="Write Target Validation",
                layer=0,
                status="error",
                summary="x",
            )
        ]
        assert has_blocking_preflight_errors(checks) is True

    def test_non_sys_or_non_layer0_does_not_block_preflight(self):
        checks = [
            CheckResult(
                check_id="CFG-VLAN",
                check_name="Config",
                layer=1,
                status="error",
                summary="x",
            ),
            CheckResult(
                check_id="SYS-01-0",
                check_name="Endpoint Validation",
                layer=0,
                status="warning",
                summary="x",
            ),
        ]
        assert has_blocking_preflight_errors(checks) is False

    async def test_missing_org_id_emits_sys_00_context_error(self, monkeypatch):
        _FakeBackupObject.docs = []
        monkeypatch.setattr(backup_models, "BackupObject", _FakeBackupObject)

        writes = [
            StagedWrite(
                sequence=0,
                method="PUT",
                endpoint="/api/v1/sites/site-1/devices/dev-1",
                body={"name": "x"},
                object_type="devices",
                site_id="site-1",
                object_id="dev-1",
            )
        ]

        errors = await validate_write_targets("", writes)
        assert len(errors) == 1
        assert errors[0].check_id == "SYS-00"
        assert "org context" in errors[0].summary.lower()

    async def test_accepts_site_when_present_in_org_sites_backup(self, monkeypatch):
        _FakeBackupObject.docs = [
            {
                "org_id": "org-1",
                "is_deleted": False,
                "object_type": "sites",
                "object_id": "site-1",
            },
            {
                "org_id": "org-1",
                "is_deleted": False,
                "object_type": "devices",
                "site_id": "site-1",
                "object_id": "dev-1",
            },
        ]
        monkeypatch.setattr(backup_models, "BackupObject", _FakeBackupObject)

        writes = [
            StagedWrite(
                sequence=0,
                method="PUT",
                endpoint="/api/v1/sites/site-1/devices/dev-1",
                body={"name": "x"},
                object_type="devices",
                site_id="site-1",
                object_id="dev-1",
            )
        ]

        errors = await validate_write_targets("org-1", writes)
        assert errors == []

    async def test_accepts_site_when_present_in_legacy_site_backup(self, monkeypatch):
        _FakeBackupObject.docs = [
            {
                "org_id": "org-1",
                "is_deleted": False,
                "object_type": "site",
                "object_id": "site-1",
            },
            {
                "org_id": "org-1",
                "is_deleted": False,
                "object_type": "devices",
                "site_id": "site-1",
                "object_id": "dev-1",
            },
        ]
        monkeypatch.setattr(backup_models, "BackupObject", _FakeBackupObject)

        writes = [
            StagedWrite(
                sequence=0,
                method="PUT",
                endpoint="/api/v1/sites/site-1/devices/dev-1",
                body={"name": "x"},
                object_type="devices",
                site_id="site-1",
                object_id="dev-1",
            )
        ]

        errors = await validate_write_targets("org-1", writes)
        assert errors == []

    async def test_accepts_site_when_only_site_scoped_backups_exist(self, monkeypatch):
        _FakeBackupObject.docs = [
            {
                "org_id": "org-1",
                "is_deleted": False,
                "object_type": "devices",
                "site_id": "site-1",
                "object_id": "dev-1",
            }
        ]
        monkeypatch.setattr(backup_models, "BackupObject", _FakeBackupObject)

        writes = [
            StagedWrite(
                sequence=0,
                method="PUT",
                endpoint="/api/v1/sites/site-1/devices/dev-1",
                body={"name": "x"},
                object_type="devices",
                site_id="site-1",
                object_id="dev-1",
            )
        ]

        errors = await validate_write_targets("org-1", writes)
        assert errors == []

    async def test_accepts_object_with_legacy_type_label(self, monkeypatch):
        _FakeBackupObject.docs = [
            {
                "org_id": "org-1",
                "is_deleted": False,
                "object_type": "sites",
                "object_id": "site-1",
            },
            {
                "org_id": "org-1",
                "is_deleted": False,
                # Legacy backup label that does not match canonicalized 'devices'
                "object_type": "device",
                "site_id": "site-1",
                "object_id": "dev-1",
            },
        ]
        monkeypatch.setattr(backup_models, "BackupObject", _FakeBackupObject)

        writes = [
            StagedWrite(
                sequence=0,
                method="PUT",
                endpoint="/api/v1/sites/site-1/devices/dev-1",
                body={"name": "x"},
                object_type="devices",
                site_id="site-1",
                object_id="dev-1",
            )
        ]

        errors = await validate_write_targets("org-1", writes)
        assert errors == []

    async def test_missing_site_emits_sys_02_with_backup_hint(self, monkeypatch):
        _FakeBackupObject.docs = []
        monkeypatch.setattr(backup_models, "BackupObject", _FakeBackupObject)

        writes = [
            StagedWrite(
                sequence=0,
                method="PUT",
                endpoint="/api/v1/sites/site-missing/devices/dev-1",
                body={"name": "x"},
                object_type="devices",
                site_id="site-missing",
                object_id="dev-1",
            )
        ]

        errors = await validate_write_targets("org-1", writes)
        assert len(errors) == 1
        assert errors[0].check_id == "SYS-02-0"
        assert "run a backup" in (errors[0].remediation_hint or "").lower()
