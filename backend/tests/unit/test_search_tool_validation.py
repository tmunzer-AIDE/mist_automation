"""Unit tests for MCP search tool input validation."""

import pytest
from fastmcp.exceptions import ToolError

from app.modules.mcp_server.tools import search as search_tool
from app.modules.mcp_server.tools.search import _collect_duplicate_names

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
