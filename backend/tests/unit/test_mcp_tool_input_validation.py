"""Unit tests for MCP tool cross-field input validation helpers."""

import pytest
from fastmcp.exceptions import ToolError

from app.modules.mcp_server.tools import backup as backup_tool
from app.modules.mcp_server.tools import details as details_tool
from app.modules.mcp_server.tools import digital_twin as twin_tool
from app.modules.mcp_server.tools import impact_analysis as impact_tool
from app.modules.mcp_server.tools import workflow as workflow_tool

validate_backup = getattr(backup_tool, "_validate_backup_inputs")
validate_details = getattr(details_tool, "_validate_details_inputs")
validate_twin = getattr(twin_tool, "_validate_twin_inputs")
validate_impact = getattr(impact_tool, "_validate_session_search_inputs")
validate_workflow = getattr(workflow_tool, "_validate_workflow_inputs")


@pytest.mark.unit
class TestBackupToolValidation:
    def test_rejects_unknown_action(self):
        with pytest.raises(ToolError, match="Unknown action"):
            validate_backup(
                action="unknown",
                object_id="",
                version_id="",
                version_id_1="",
                version_id_2="",
                backup_type="",
                object_type="",
                site_id="",
                object_ids=None,
                backup_id="",
                level="",
            )

    def test_manual_site_scope_requires_site_id(self):
        with pytest.raises(ToolError, match="site_id is required"):
            validate_backup(
                action="trigger",
                object_id="",
                version_id="",
                version_id_1="",
                version_id_2="",
                backup_type="manual",
                object_type="site:devices",
                site_id="",
                object_ids=None,
                backup_id="",
                level="",
            )

    def test_full_backup_rejects_manual_fields(self):
        with pytest.raises(ToolError, match="do not pass object_type"):
            validate_backup(
                action="trigger",
                object_id="",
                version_id="",
                version_id_1="",
                version_id_2="",
                backup_type="full",
                object_type="org:wlans",
                site_id="",
                object_ids=None,
                backup_id="",
                level="",
            )

    def test_job_logs_rejects_invalid_level(self):
        with pytest.raises(ToolError, match="Invalid level"):
            validate_backup(
                action="job_logs",
                object_id="",
                version_id="",
                version_id_1="",
                version_id_2="",
                backup_type="",
                object_type="",
                site_id="",
                object_ids=None,
                backup_id="507f1f77bcf86cd799439011",
                level="debug",
            )


@pytest.mark.unit
class TestDetailsToolValidation:
    def test_dashboard_rejects_id(self):
        with pytest.raises(ToolError, match="id is not supported"):
            validate_details(detail_type="dashboard", id_value="abc", section="")

    def test_report_rejects_invalid_section(self):
        with pytest.raises(ToolError, match="Invalid section"):
            validate_details(detail_type="report", id_value="abc", section="vlans")

    def test_webhook_event_requires_id(self):
        with pytest.raises(ToolError, match="id is required"):
            validate_details(detail_type="webhook_event", id_value="", section="")


@pytest.mark.unit
class TestImpactToolValidation:
    def test_rejects_invalid_status(self):
        with pytest.raises(ToolError, match="Invalid status"):
            validate_impact(status="done", site_id="", device_type="", device_mac="")

    def test_rejects_invalid_mac(self):
        with pytest.raises(ToolError, match="Invalid device_mac"):
            validate_impact(status="", site_id="", device_type="ap", device_mac="AABBCCDDEEFF")

    def test_rejects_non_uuid_site_id(self):
        with pytest.raises(ToolError, match="must be a real UUID"):
            validate_impact(status="", site_id="my-site", device_type="", device_mac="")


@pytest.mark.unit
class TestWorkflowToolValidation:
    def test_create_requires_nodes(self):
        with pytest.raises(ToolError, match="nodes are required"):
            validate_workflow(
                action="create",
                workflow_id="",
                execution_id="",
                name="My Workflow",
                description="",
                nodes=None,
                edges=None,
                workflow_type="standard",
            )

    def test_create_rejects_invalid_workflow_type(self):
        with pytest.raises(ToolError, match="Invalid workflow_type"):
            validate_workflow(
                action="create",
                workflow_id="",
                execution_id="",
                name="My Workflow",
                description="",
                nodes=[{"id": "n1", "type": "trigger"}],
                edges=None,
                workflow_type="invalid",
            )

    def test_update_requires_changes(self):
        with pytest.raises(ToolError, match="No changes provided"):
            validate_workflow(
                action="update",
                workflow_id="507f1f77bcf86cd799439011",
                execution_id="",
                name="",
                description="",
                nodes=None,
                edges=None,
                workflow_type="standard",
            )


@pytest.mark.unit
class TestDigitalTwinValidation:
    def test_simulate_requires_writes(self):
        with pytest.raises(ToolError, match="No writes provided"):
            validate_twin(action="simulate", writes=None, session_id="")

    def test_rejects_placeholder_endpoint(self):
        with pytest.raises(ToolError, match="contains unresolved placeholders"):
            validate_twin(
                action="simulate",
                writes=[{"method": "PUT", "endpoint": "/api/v1/sites/{site_id}/devices/x", "body": {}}],
                session_id="",
            )

    def test_approve_requires_session_id(self):
        with pytest.raises(ToolError, match="session_id required"):
            validate_twin(action="approve", writes=None, session_id="")

    def test_history_rejects_writes(self):
        with pytest.raises(ToolError, match="writes is not supported"):
            validate_twin(
                action="history",
                writes=[{"method": "POST", "endpoint": "/api/v1/sites/a/wlans", "body": {}}],
                session_id="",
            )
