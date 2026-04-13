import pytest

from app.modules.digital_twin.models import StagedWrite
from app.modules.digital_twin.services.label_resolver import (
    _count_by_type,
    fetch_object_names_by_type,
    fetch_site_names,
    format_object_label,
)


def test_single_object_formats_as_type_and_name():
    label = format_object_label(
        object_types=["networktemplates"],
        object_names_by_type={"networktemplates": ["default-campus"]},
    )
    assert label == "networktemplates: default-campus"


def test_multiple_same_type_formats_as_count():
    label = format_object_label(
        object_types=["networktemplates", "networktemplates", "networktemplates"],
        object_names_by_type={"networktemplates": ["a", "b", "c"]},
    )
    assert label == "3 networktemplates"


def test_multiple_mixed_types_formats_as_mixed_summary():
    label = format_object_label(
        object_types=["networktemplates", "networktemplates", "wlans"],
        object_names_by_type={"networktemplates": ["a", "b"], "wlans": ["guest"]},
    )
    assert label == "3 objects: 2 networktemplates, 1 wlans"


def test_empty_object_types_returns_none():
    assert format_object_label(object_types=[], object_names_by_type={}) is None


def test_count_by_type():
    counts = _count_by_type(["a", "a", "b", "c", "a"])
    assert counts == {"a": 3, "b": 1, "c": 1}


@pytest.mark.asyncio
async def test_fetch_object_names_by_type_uses_wlan_ssid_from_post_body(monkeypatch):
    class _FakeCursor:
        async def first_or_none(self):
            return None

    class _FakeBackupObject:
        @classmethod
        def find(cls, _query):
            return _FakeCursor()

    from app.modules.backup import models as backup_models

    monkeypatch.setattr(backup_models, "BackupObject", _FakeBackupObject)

    writes = [
        StagedWrite(
            sequence=0,
            method="POST",
            endpoint="/api/v1/sites/site-1/wlans",
            body={"ssid": "Guest-WiFi", "enabled": True},
            object_type="wlans",
            site_id="site-1",
            object_id=None,
        )
    ]

    names = await fetch_object_names_by_type(org_id="org-1", writes=writes)
    assert names == {"wlans": ["Guest-WiFi"]}


@pytest.mark.asyncio
async def test_fetch_object_names_by_type_post_does_not_query_backup(monkeypatch):
    class _FakeBackupObject:
        @classmethod
        def find(cls, _query):
            raise AssertionError("POST label resolution must not query backup source objects")

    from app.modules.backup import models as backup_models

    monkeypatch.setattr(backup_models, "BackupObject", _FakeBackupObject)

    writes = [
        StagedWrite(
            sequence=0,
            method="POST",
            endpoint="/api/v1/orgs/org-1/networks",
            body={"name": "Corp-LAN"},
            object_type="networks",
            object_id="unexpected-but-ignored",
        )
    ]

    names = await fetch_object_names_by_type(org_id="org-1", writes=writes)
    assert names == {"networks": ["Corp-LAN"]}


@pytest.mark.asyncio
async def test_fetch_site_names_resolves_legacy_site_shapes(monkeypatch):
    class _FakeCursor:
        def __init__(self, docs):
            self._docs = docs

        def sort(self, *_args, **_kwargs):
            return self

        def __aiter__(self):
            self._iter = iter(self._docs)
            return self

        async def __anext__(self):
            try:
                return next(self._iter)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class _Doc:
        def __init__(
            self,
            *,
            object_type=None,
            object_id=None,
            site_id=None,
            object_name=None,
            configuration=None,
        ):
            self.object_type = object_type
            self.object_id = object_id
            self.site_id = site_id
            self.object_name = object_name
            self.configuration = configuration or {}

    class _FakeBackupObject:
        docs = [
            _Doc(object_type="sites", object_id="site-1", site_id=None, configuration={"name": "HQ"}),
            _Doc(object_type="info", object_id="ignored", site_id="site-2", configuration={"name": "Branch"}),
        ]

        @classmethod
        def find(cls, query):
            object_type = query.get("object_type")
            if object_type == "info":
                site_ids = set(query.get("site_id", {}).get("$in", []))
                docs = [d for d in cls.docs if d.object_type == "info" and d.site_id in site_ids]
                return _FakeCursor(docs)
            object_ids = set(query.get("object_id", {}).get("$in", []))
            docs = [d for d in cls.docs if d.object_type == object_type and d.object_id in object_ids]
            return _FakeCursor(docs)

    from app.modules.backup import models as backup_models

    monkeypatch.setattr(backup_models, "BackupObject", _FakeBackupObject)

    names = await fetch_site_names(org_id="org-1", site_ids=["site-1", "site-2", "site-3"])
    assert names == ["HQ", "Branch", "site-3"]


@pytest.mark.asyncio
async def test_fetch_site_names_uses_latest_version_per_site(monkeypatch):
    class _FakeCursor:
        def __init__(self, docs):
            self._docs = docs

        def sort(self, *_args, **_kwargs):
            self._docs = sorted(self._docs, key=lambda d: d.version, reverse=True)
            return self

        def __aiter__(self):
            self._iter = iter(self._docs)
            return self

        async def __anext__(self):
            try:
                return next(self._iter)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class _Doc:
        def __init__(self, *, site_id, version, object_name=None, configuration=None):
            self.site_id = site_id
            self.version = version
            self.object_id = None
            self.object_name = object_name
            self.configuration = configuration or {}

    class _FakeBackupObject:
        @classmethod
        def find(cls, query):
            if query.get("object_type") != "info":
                return _FakeCursor([])
            return _FakeCursor(
                [
                    _Doc(site_id="site-1", version=1, configuration={"name": "Old HQ"}),
                    _Doc(site_id="site-1", version=3, configuration={"name": "HQ"}),
                    _Doc(site_id="site-1", version=2, configuration={"name": "Mid HQ"}),
                ]
            )

    from app.modules.backup import models as backup_models

    monkeypatch.setattr(backup_models, "BackupObject", _FakeBackupObject)

    names = await fetch_site_names(org_id="org-1", site_ids=["site-1"])
    assert names == ["HQ"]


@pytest.mark.asyncio
async def test_fetch_object_names_by_type_site_singletons_use_site_name(monkeypatch):
    class _FakeCursor:
        def __init__(self, query):
            self.query = query

        def sort(self, *_args, **_kwargs):
            return self

        async def first_or_none(self):
            if self.query.get("org_id") != "org-1":
                return None
            if self.query.get("object_type") == "info" and self.query.get("site_id") == "site-1":
                class _Doc:
                    object_name = None
                    configuration = {"name": "HQ"}

                return _Doc()
            return None

    class _FakeBackupObject:
        @classmethod
        def find(cls, query):
            return _FakeCursor(query)

    from app.modules.backup import models as backup_models

    monkeypatch.setattr(backup_models, "BackupObject", _FakeBackupObject)

    writes = [
        StagedWrite(
            sequence=0,
            method="PUT",
            endpoint="/api/v1/sites/site-1",
            body={},
            object_type="info",
            site_id="site-1",
            object_id=None,
        ),
        StagedWrite(
            sequence=1,
            method="PUT",
            endpoint="/api/v1/sites/site-1/setting",
            body={"auto_upgrade": {"enabled": True}},
            object_type="setting",
            site_id="site-1",
            object_id=None,
        ),
    ]

    names = await fetch_object_names_by_type(org_id="org-1", writes=writes)
    assert names == {"info": ["HQ"], "settings": ["HQ"]}


@pytest.mark.asyncio
async def test_fetch_site_names_prefers_info_over_sites(monkeypatch):
    class _FakeCursor:
        def __init__(self, docs):
            self._docs = docs

        def sort(self, *_args, **_kwargs):
            self._docs = sorted(self._docs, key=lambda d: d.version, reverse=True)
            return self

        def __aiter__(self):
            self._iter = iter(self._docs)
            return self

        async def __anext__(self):
            try:
                return next(self._iter)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class _Doc:
        def __init__(self, *, object_type, site_id=None, object_id=None, version=1, configuration=None):
            self.object_type = object_type
            self.site_id = site_id
            self.object_id = object_id
            self.version = version
            self.object_name = None
            self.configuration = configuration or {}

    class _FakeBackupObject:
        docs = [
            _Doc(object_type="sites", object_id="site-1", version=99, configuration={"name": "Stale Sites Name"}),
            _Doc(object_type="info", site_id="site-1", version=1, configuration={"name": "Authoritative Info Name"}),
        ]

        @classmethod
        def find(cls, query):
            object_type = query.get("object_type")
            if object_type == "info":
                site_ids = set(query.get("site_id", {}).get("$in", []))
                docs = [d for d in cls.docs if d.object_type == "info" and d.site_id in site_ids]
                return _FakeCursor(docs)
            object_ids = set(query.get("object_id", {}).get("$in", []))
            docs = [d for d in cls.docs if d.object_type == object_type and d.object_id in object_ids]
            return _FakeCursor(docs)

    from app.modules.backup import models as backup_models

    monkeypatch.setattr(backup_models, "BackupObject", _FakeBackupObject)

    names = await fetch_site_names(org_id="org-1", site_ids=["site-1"])
    assert names == ["Authoritative Info Name"]
