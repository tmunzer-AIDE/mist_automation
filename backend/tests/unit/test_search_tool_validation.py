"""Unit tests for MCP search tool input validation."""

import json

import pytest
from fastmcp.exceptions import ToolError

from app.modules.mcp_server.tools import search as search_tool
from app.modules.mcp_server.tools.search import _collect_duplicate_names, _search_backup_objects

validate_inputs = getattr(search_tool, "_validate_search_inputs")


@pytest.mark.unit
class TestSearchInputValidation:
    def test_rejects_unknown_type(self):
        with pytest.raises(ToolError, match="Unknown search_type"):
            validate_inputs(
                search_type="unknown",
                query="",
                object_type="",
                site_id="",
                status="",
                event_type="",
                hours=24,
                skip=0,
                limit=10,
                sort_by="date",
                sort_order="desc",
            )

    def test_rejects_object_type_on_non_backup_search(self):
        with pytest.raises(ToolError, match="object_type is only supported"):
            validate_inputs(
                search_type="workflows",
                query="",
                object_type="sites",
                site_id="",
                status="",
                event_type="",
                hours=24,
                skip=0,
                limit=10,
                sort_by="date",
                sort_order="desc",
            )

    def test_requires_object_type_or_site_id_for_backup_objects(self):
        with pytest.raises(ToolError, match="provide object_type or site_id"):
            validate_inputs(
                search_type="backup_objects",
                query="DNT-NRT",
                object_type="",
                site_id="",
                status="",
                event_type="",
                hours=24,
                skip=0,
                limit=10,
                sort_by="date",
                sort_order="desc",
            )

    def test_rejects_placeholder_site_id(self):
        with pytest.raises(ToolError, match="unresolved placeholders"):
            validate_inputs(
                search_type="backup_objects",
                query="",
                object_type="sites",
                site_id="{site_id}",
                status="",
                event_type="",
                hours=24,
                skip=0,
                limit=10,
                sort_by="date",
                sort_order="desc",
            )

    def test_rejects_non_uuid_site_id(self):
        with pytest.raises(ToolError, match="must be a real UUID"):
            validate_inputs(
                search_type="webhook_events",
                query="",
                object_type="",
                site_id="DNT-NRT",
                status="",
                event_type="client-connect",
                hours=24,
                skip=0,
                limit=10,
                sort_by="date",
                sort_order="desc",
            )

    def test_rejects_event_type_on_non_webhook_search(self):
        with pytest.raises(ToolError, match="event_type is only supported"):
            validate_inputs(
                search_type="executions",
                query="",
                object_type="",
                site_id="",
                status="",
                event_type="device-up",
                hours=24,
                skip=0,
                limit=10,
                sort_by="date",
                sort_order="desc",
            )

    def test_rejects_invalid_status_for_type(self):
        with pytest.raises(ToolError, match="Invalid status"):
            validate_inputs(
                search_type="backup_jobs",
                query="",
                object_type="",
                site_id="",
                status="enabled",
                event_type="",
                hours=24,
                skip=0,
                limit=10,
                sort_by="date",
                sort_order="desc",
            )

    def test_normalizes_backup_site_alias(self, monkeypatch):
        monkeypatch.setattr(search_tool, "_valid_backup_object_types", lambda: {"sites", "info", "wlans"})

        validated = validate_inputs(
            search_type="backup_objects",
            query="DNT-NRT",
            object_type="site",
            site_id="",
            status="active",
            event_type="",
            hours=24,
            skip=0,
            limit=1,
            sort_by="name",
            sort_order="asc",
        )

        assert validated["search_type"] == "backup_objects"
        assert validated["object_type"] == "sites"
        assert validated["query"] == "DNT-NRT"
        assert validated["status"] == "active"


@pytest.mark.unit
class TestCollectDuplicateNames:
    def test_returns_empty_when_all_names_unique(self):
        results = [
            {"id": "a", "name": "switch-01", "status": "active", "summary": "v1", "date": None},
            {"id": "b", "name": "switch-02", "status": "active", "summary": "v1", "date": None},
        ]

        assert _collect_duplicate_names(results) == {}

    def test_groups_two_entries_with_same_name(self):
        results = [
            {"id": "aaa", "name": "US-NY-SWA-01", "status": "active", "summary": "v7, 4 versions", "date": "2026-04-12"},
            {"id": "bbb", "name": "US-NY-SWA-01", "status": "active", "summary": "v1, 1 versions", "date": "2026-03-28"},
            {"id": "ccc", "name": "other", "status": "active", "summary": "v1, 1 versions", "date": None},
        ]

        duplicates = _collect_duplicate_names(results)

        assert list(duplicates.keys()) == ["US-NY-SWA-01"]
        matches = duplicates["US-NY-SWA-01"]
        assert len(matches) == 2
        assert {m["id"] for m in matches} == {"aaa", "bbb"}
        assert matches[0]["summary"].startswith("v")

    def test_ignores_empty_or_missing_names(self):
        results = [
            {"id": "a", "name": "", "status": "active", "summary": "x", "date": None},
            {"id": "b", "name": "", "status": "active", "summary": "y", "date": None},
            {"id": "c", "name": None, "status": "active", "summary": "z", "date": None},
            {"id": "d", "status": "active", "summary": "w", "date": None},
        ]

        assert _collect_duplicate_names(results) == {}

    def test_multiple_collision_groups(self):
        results = [
            {"id": "a1", "name": "alpha", "status": "active", "summary": "s", "date": None},
            {"id": "a2", "name": "alpha", "status": "active", "summary": "s", "date": None},
            {"id": "b1", "name": "beta", "status": "active", "summary": "s", "date": None},
            {"id": "b2", "name": "beta", "status": "active", "summary": "s", "date": None},
            {"id": "c1", "name": "gamma", "status": "active", "summary": "s", "date": None},
        ]

        duplicates = _collect_duplicate_names(results)

        assert set(duplicates.keys()) == {"alpha", "beta"}
        assert len(duplicates["alpha"]) == 2
        assert len(duplicates["beta"]) == 2


@pytest.mark.unit
class TestSearchBackupObjectsProjection:
    """Verify _search_backup_objects emits org_id/site_id alongside object id."""

    async def test_emits_org_id_and_site_id_per_result(self, monkeypatch):
        # Stub _paginated_query so we don't need Mongo. Emit one item that already
        # reflects the $group projection (org_id, site_id, etc.).
        async def fake_paginated_query(_model, _pipeline, _skip, _limit):
            items = [
                {
                    "_id": "d6fb4f96-3ba4-4cf5-8af2-a8d7b85087ac",
                    "object_type": "sites",
                    "object_name": "DNT-NTR",
                    "org_id": "8aa21779-1178-4357-b3e0-42c02b93b870",
                    "site_id": "d6fb4f96-3ba4-4cf5-8af2-a8d7b85087ac",
                    "is_deleted": False,
                    "version_count": 4,
                    "latest_version": 4,
                    "last_modified_at": "2026-04-11T09:00:01",
                    "config_name": None,
                }
            ]
            return 1, items

        monkeypatch.setattr(search_tool, "_paginated_query", fake_paginated_query)

        payload = await _search_backup_objects(
            query="DNT-NTR",
            object_type="sites",
            site_id="",
            status="active",
            sort={"last_modified_at": -1},
            skip=0,
            limit=10,
        )

        parsed = json.loads(payload)
        assert parsed["total"] == 1
        result = parsed["results"][0]
        assert result["id"] == "d6fb4f96-3ba4-4cf5-8af2-a8d7b85087ac"
        assert result["name"] == "DNT-NTR"
        # Critical: org_id must be present so the LLM can pass it to digital_twin
        # without guessing. site_id is additive — useful for non-site resources.
        assert result["org_id"] == "8aa21779-1178-4357-b3e0-42c02b93b870"
        assert result["site_id"] == "d6fb4f96-3ba4-4cf5-8af2-a8d7b85087ac"

    async def test_projection_handles_missing_org_id_gracefully(self, monkeypatch):
        # Legacy backup records without org_id should not break serialization.
        async def fake_paginated_query(_model, _pipeline, _skip, _limit):
            return 1, [
                {
                    "_id": "obj-1",
                    "object_type": "wlans",
                    "object_name": "Guest",
                    "org_id": None,
                    "site_id": None,
                    "is_deleted": False,
                    "version_count": 1,
                    "latest_version": 1,
                    "last_modified_at": None,
                    "config_name": None,
                }
            ]

        monkeypatch.setattr(search_tool, "_paginated_query", fake_paginated_query)

        payload = await _search_backup_objects(
            query="Guest",
            object_type="wlans",
            site_id="",
            status="",
            sort={"last_modified_at": -1},
            skip=0,
            limit=10,
        )

        parsed = json.loads(payload)
        result = parsed["results"][0]
        assert result["org_id"] is None
        assert result["site_id"] is None
