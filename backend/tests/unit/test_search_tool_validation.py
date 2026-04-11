"""Unit tests for MCP search tool input validation."""

import pytest
from fastmcp.exceptions import ToolError

from app.modules.mcp_server.tools import search as search_tool

validate_inputs = getattr(search_tool, "_validate_search_inputs")


@pytest.mark.unit
class TestSearchInputValidation:
    def test_rejects_unknown_type(self):
        with pytest.raises(ToolError, match="Unknown type"):
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
