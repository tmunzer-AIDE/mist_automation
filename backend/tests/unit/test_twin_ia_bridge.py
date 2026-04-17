"""Unit tests for twin_ia_bridge._get_devices_at_site — MAC normalization and
UUID-fallback regression guards.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.digital_twin.services import twin_ia_bridge


class _FakeTwinSession:
    """Minimal stand-in for TwinSession — we never touch IA in these tests."""

    def __init__(self):
        self.id = "session-id"
        self.org_id = "org-1"
        self.affected_sites: list[str] = []
        self.staged_writes: list[Any] = []
        self.updated_at = None
        self.created_at = None
        self.overall_severity = "clean"
        self.prediction_report = None


def _make_backup(object_id: str, configuration: dict[str, Any]):
    """Create a BackupObject stand-in."""
    return SimpleNamespace(object_id=object_id, configuration=configuration)


class _FakeBackupFind:
    """Minimal chainable stand-in for ``BackupObject.find(...).sort(...).to_list()``."""

    def __init__(self, docs):
        self._docs = docs

    def sort(self, *_args, **_kwargs):
        return self

    async def to_list(self):
        return self._docs


@pytest.mark.unit
class TestGetDevicesAtSiteBackupFallback:
    async def test_mixed_case_mac_is_normalized_on_ingest(self, monkeypatch):
        """Colon-uppercase MACs from backup must come out lowercase-stripped."""

        def fake_find(cls, query):  # noqa: ARG001
            return _FakeBackupFind(
                [
                    _make_backup(
                        object_id="uuid-aaaa",
                        configuration={"mac": "AA:BB:CC:00:11:22", "name": "sw-1", "type": "switch"},
                    )
                ]
            )

        # Disable telemetry cache path — force backup fallback.
        monkeypatch.setattr(twin_ia_bridge, "_latest_cache", None, raising=False)
        from app.modules.backup import models as backup_models

        monkeypatch.setattr(backup_models.BackupObject, "find", classmethod(fake_find))

        devices = await twin_ia_bridge._get_devices_at_site("site-1", _FakeTwinSession())
        assert len(devices) == 1
        assert devices[0]["mac"] == "aabbcc001122"

    async def test_device_without_mac_is_skipped_not_substituted_with_uuid(self, monkeypatch):
        """Regression: ``cfg.get("mac") or b.object_id`` used to feed a UUID
        into normalize_mac(), producing garbage. Devices without a MAC must
        be skipped instead.
        """

        def fake_find(cls, query):  # noqa: ARG001
            return _FakeBackupFind(
                [
                    _make_backup(
                        object_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                        configuration={"name": "no-mac-device", "type": "switch"},
                    ),
                    _make_backup(
                        object_id="uuid-bbbb",
                        configuration={"mac": "11:22:33:44:55:66", "name": "sw-2", "type": "switch"},
                    ),
                ]
            )

        monkeypatch.setattr(twin_ia_bridge, "_latest_cache", None, raising=False)
        from app.modules.backup import models as backup_models

        monkeypatch.setattr(backup_models.BackupObject, "find", classmethod(fake_find))

        devices = await twin_ia_bridge._get_devices_at_site("site-1", _FakeTwinSession())
        # Only the device with a real MAC should be emitted.
        assert len(devices) == 1
        assert devices[0]["mac"] == "112233445566"
        assert devices[0]["name"] == "sw-2"

    async def test_dash_separated_mac_normalized(self, monkeypatch):
        def fake_find(cls, query):  # noqa: ARG001
            return _FakeBackupFind(
                [
                    _make_backup(
                        object_id="uuid-cccc",
                        configuration={"mac": "AA-BB-CC-DD-EE-FF", "name": "sw-3", "type": "gateway"},
                    )
                ]
            )

        monkeypatch.setattr(twin_ia_bridge, "_latest_cache", None, raising=False)
        from app.modules.backup import models as backup_models

        monkeypatch.setattr(backup_models.BackupObject, "find", classmethod(fake_find))

        devices = await twin_ia_bridge._get_devices_at_site("site-1", _FakeTwinSession())
        assert len(devices) == 1
        assert devices[0]["mac"] == "aabbccddeeff"
