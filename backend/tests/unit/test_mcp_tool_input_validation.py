"""Unit tests for MCP tool cross-field input validation helpers."""

import pytest
from fastmcp.exceptions import ToolError

from app.modules.digital_twin.models import CheckResult
from app.modules.mcp_server.tools import backup as backup_tool
from app.modules.mcp_server.tools import details as details_tool
from app.modules.mcp_server.tools import digital_twin as twin_tool
from app.modules.mcp_server.tools import impact_analysis as impact_tool
from app.modules.mcp_server.tools import skills as skills_tool
from app.modules.mcp_server.tools import workflow as workflow_tool

validate_backup = getattr(backup_tool, "_validate_backup_inputs")
validate_details = getattr(details_tool, "_validate_details_inputs")
validate_twin = getattr(twin_tool, "_validate_twin_inputs")
build_report_diagnostics = getattr(twin_tool, "_build_report_diagnostics")
resolve_twin_org_id = getattr(twin_tool, "_resolve_twin_org_id")
validate_impact = getattr(impact_tool, "_validate_session_search_inputs")
validate_skill_name = getattr(skills_tool, "_validate_skill_name")
validate_workflow = getattr(workflow_tool, "_validate_workflow_inputs")


@pytest.mark.unit
class TestBackupToolValidation:
    def test_rejects_unknown_action(self):
        with pytest.raises(ToolError, match="Unknown action"):
            validate_backup(
                action="unknown",
                object_id="",
                version_id="",
                version_number=0,
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
                version_number=0,
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
                version_number=0,
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
                version_number=0,
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
class TestSkillsToolValidation:
    def test_rejects_curly_placeholder(self):
        with pytest.raises(ToolError, match="real skill name"):
            validate_skill_name("{{skill_name}}")

    def test_rejects_url_encoded_placeholder(self):
        with pytest.raises(ToolError, match="real skill name"):
            validate_skill_name("%7Bskill_name%7D")

    def test_accepts_real_skill_name(self):
        assert validate_skill_name("mist-sle") == "mist-sle"


@pytest.mark.unit
class TestDigitalTwinValidation:
    ORG_ID = "8aa21779-1178-4357-b3e0-42c02b93b870"
    SITE_ID = "2818e386-8dec-4562-9ede-5b8a0fbbdc71"
    OBJECT_ID = "3c7f19c2-4c16-4f4c-9f1b-8f5338107bd7"

    def test_resolves_explicit_org_id(self):
        resolved = resolve_twin_org_id(self.ORG_ID)
        assert resolved == self.ORG_ID

    def test_rejects_invalid_explicit_org_id(self):
        with pytest.raises(ToolError, match="must be a valid UUID"):
            resolve_twin_org_id("my-org")

    def test_rejects_missing_org_id(self):
        with pytest.raises(ToolError, match="org_id is required"):
            resolve_twin_org_id("")

    def test_falls_back_to_default_org_id_when_explicit_missing(self):
        # Single-org installs: caller omits org_id, system default fills in.
        resolved = resolve_twin_org_id("", default_org_id=self.ORG_ID)
        assert resolved == self.ORG_ID

    def test_explicit_org_id_wins_over_default(self):
        other_org = "11111111-1111-1111-1111-111111111111"
        resolved = resolve_twin_org_id(self.ORG_ID, default_org_id=other_org)
        assert resolved == self.ORG_ID

    def test_no_explicit_no_default_raises(self):
        with pytest.raises(ToolError, match="org_id is required"):
            resolve_twin_org_id(None, default_org_id=None)

    def test_simulate_uses_default_org_when_explicit_missing(self):
        # End-to-end through _validate_twin_inputs — simulate with no org_id but a default.
        validated = validate_twin(
            action="simulate",
            action_type="update",
            org_id=None,
            site_id=self.SITE_ID,
            object_type="site_info",
            payload={"name": "new"},
            object_id=None,
            session_id="",
            default_org_id=self.ORG_ID,
        )
        assert validated["org_id"] == self.ORG_ID
        assert validated["writes"][0]["endpoint"] == f"/api/v1/sites/{self.SITE_ID}"

    def test_simulate_requires_action_type(self):
        with pytest.raises(ToolError, match="action_type is required"):
            validate_twin(
                action="simulate",
                action_type=None,
                org_id=self.ORG_ID,
                site_id=None,
                object_type="org_wlans",
                payload={"ssid": "Guest"},
                object_id=None,
                session_id="",
            )

    def test_simulate_requires_object_type(self):
        with pytest.raises(ToolError, match="object_type is required"):
            validate_twin(
                action="simulate",
                action_type="create",
                org_id=self.ORG_ID,
                site_id=None,
                object_type=None,
                payload={"ssid": "Guest"},
                object_id=None,
                session_id="",
            )

    def test_simulate_requires_org_id(self):
        with pytest.raises(ToolError, match="org_id is required"):
            validate_twin(
                action="simulate",
                action_type="create",
                org_id=None,
                site_id=None,
                object_type="org_wlans",
                payload={"ssid": "Guest"},
                object_id=None,
                session_id="",
            )

    def test_site_scoped_object_requires_site_id(self):
        with pytest.raises(ToolError, match="site_id is required"):
            validate_twin(
                action="simulate",
                action_type="update",
                org_id=self.ORG_ID,
                site_id=None,
                object_type="site_wlans",
                payload={"ssid": "Guest"},
                object_id=self.OBJECT_ID,
                session_id="",
            )

    def test_org_scoped_object_rejects_site_id(self):
        with pytest.raises(ToolError, match="site_id is not supported"):
            validate_twin(
                action="simulate",
                action_type="create",
                org_id=self.ORG_ID,
                site_id=self.SITE_ID,
                object_type="org_wlans",
                payload={"ssid": "Guest"},
                object_id=None,
                session_id="",
            )

    def test_delete_rejects_payload(self):
        with pytest.raises(ToolError, match="payload is not supported"):
            validate_twin(
                action="simulate",
                action_type="delete",
                org_id=self.ORG_ID,
                site_id=None,
                object_type="org_wlans",
                payload={"name": "not-allowed"},
                object_id=self.OBJECT_ID,
                session_id="",
            )

    def test_create_rejects_object_id(self):
        with pytest.raises(ToolError, match="object_id is not supported"):
            validate_twin(
                action="simulate",
                action_type="create",
                org_id=self.ORG_ID,
                site_id=None,
                object_type="org_wlans",
                payload={"ssid": "Guest"},
                object_id=self.OBJECT_ID,
                session_id="",
            )

    def test_rejects_payload_placeholders(self):
        with pytest.raises(ToolError, match="payload contains unresolved placeholders"):
            validate_twin(
                action="simulate",
                action_type="update",
                org_id=self.ORG_ID,
                site_id=self.SITE_ID,
                object_type="site_wlans",
                payload={"ssid": "{{guest_ssid}}"},
                object_id=self.OBJECT_ID,
                session_id="",
            )

    def test_compiles_valid_update_write(self):
        validated = validate_twin(
            action="simulate",
            action_type="update",
            org_id=self.ORG_ID,
            site_id=self.SITE_ID,
            object_type="site_wlans",
            payload={"ssid": "Guest"},
            object_id=self.OBJECT_ID,
            session_id="",
        )

        assert validated["action"] == "simulate"
        assert validated["org_id"] == self.ORG_ID
        assert validated["writes"][0]["method"] == "PUT"
        assert validated["writes"][0]["endpoint"] == (
            f"/api/v1/sites/{self.SITE_ID}/wlans/{self.OBJECT_ID}"
        )

    def test_site_info_update_compiles_without_object_id(self):
        # site_info is a singleton — the site_id IS the identifier, no object_id needed.
        validated = validate_twin(
            action="simulate",
            action_type="update",
            org_id=self.ORG_ID,
            site_id=self.SITE_ID,
            object_type="site_info",
            payload={"networktemplate_id": self.OBJECT_ID},
            object_id=None,
            session_id="",
        )

        assert validated["writes"][0]["method"] == "PUT"
        assert validated["writes"][0]["endpoint"] == f"/api/v1/sites/{self.SITE_ID}"
        assert validated["writes"][0]["body"] == {"networktemplate_id": self.OBJECT_ID}

    def test_site_info_rejects_object_id(self):
        with pytest.raises(ToolError, match="object_id must not be provided"):
            validate_twin(
                action="simulate",
                action_type="update",
                org_id=self.ORG_ID,
                site_id=self.SITE_ID,
                object_type="site_info",
                payload={"networktemplate_id": "1b4d9684-8a4e-426c-beb8-3b2c352f8e1f"},
                object_id=self.OBJECT_ID,
                session_id="",
            )

    def test_site_info_rejects_create(self):
        with pytest.raises(ToolError, match="only action_type='update' is supported"):
            validate_twin(
                action="simulate",
                action_type="create",
                org_id=self.ORG_ID,
                site_id=self.SITE_ID,
                object_type="site_info",
                payload={"name": "new"},
                object_id=None,
                session_id="",
            )

    def test_site_info_rejects_delete(self):
        with pytest.raises(ToolError, match="only action_type='update' is supported"):
            validate_twin(
                action="simulate",
                action_type="delete",
                org_id=self.ORG_ID,
                site_id=self.SITE_ID,
                object_type="site_info",
                payload=None,
                object_id=None,
                session_id="",
            )

    def test_site_info_requires_site_id(self):
        with pytest.raises(ToolError, match="site_id is required"):
            validate_twin(
                action="simulate",
                action_type="update",
                org_id=self.ORG_ID,
                site_id=None,
                object_type="site_info",
                payload={"name": "new"},
                object_id=None,
                session_id="",
            )

    def test_site_setting_update_compiles_without_object_id(self):
        validated = validate_twin(
            action="simulate",
            action_type="update",
            org_id=self.ORG_ID,
            site_id=self.SITE_ID,
            object_type="site_setting",
            payload={"auto_upgrade": {"enabled": True}},
            object_id=None,
            session_id="",
        )

        assert validated["writes"][0]["method"] == "PUT"
        assert validated["writes"][0]["endpoint"] == f"/api/v1/sites/{self.SITE_ID}/setting"

    def test_approve_requires_session_id(self):
        with pytest.raises(ToolError, match="session_id required"):
            validate_twin(
                action="approve",
                action_type=None,
                org_id=None,
                site_id=None,
                object_type=None,
                payload=None,
                object_id=None,
                session_id="",
            )

    def test_session_actions_require_objectid_session_id(self):
        with pytest.raises(ToolError, match="24-character hex ObjectId"):
            validate_twin(
                action="status",
                action_type=None,
                org_id=None,
                site_id=None,
                object_type=None,
                payload=None,
                object_id=None,
                session_id=self.OBJECT_ID,
            )

    def test_simulate_existing_session_requires_objectid(self):
        with pytest.raises(ToolError, match="24-character hex ObjectId"):
            validate_twin(
                action="simulate",
                action_type="update",
                org_id=self.ORG_ID,
                site_id=self.SITE_ID,
                object_type="site_wlans",
                payload={"ssid": "Guest"},
                object_id=self.OBJECT_ID,
                session_id=self.OBJECT_ID,
            )

    def test_history_rejects_simulation_fields(self):
        with pytest.raises(ToolError, match="not supported for action='history'"):
            validate_twin(
                action="history",
                action_type="create",
                org_id=self.ORG_ID,
                site_id=None,
                object_type="org_wlans",
                payload={"ssid": "Guest"},
                object_id=None,
                session_id="",
            )

    def test_simulate_compiles_multiple_changes(self):
        validated = validate_twin(
            action="simulate",
            action_type=None,
            org_id=self.ORG_ID,
            site_id=None,
            object_type=None,
            payload=None,
            object_id=None,
            changes=[
                {
                    "action_type": "update",
                    "object_type": "site_wlans",
                    "site_id": self.SITE_ID,
                    "object_id": self.OBJECT_ID,
                    "payload": {"ssid": "Guest-1"},
                },
                {
                    "action_type": "create",
                    "object_type": "org_networks",
                    "payload": {"name": "net-new"},
                },
            ],
            session_id="",
        )

        assert validated["action"] == "simulate"
        assert len(validated["writes"]) == 2
        assert len(validated["requested_changes"]) == 2
        assert validated["writes"][0]["method"] == "PUT"
        assert validated["writes"][1]["method"] == "POST"

    def test_simulate_rejects_mixing_changes_with_single_fields(self):
        with pytest.raises(ToolError, match="changes is mutually exclusive"):
            validate_twin(
                action="simulate",
                action_type="update",
                org_id=self.ORG_ID,
                site_id=self.SITE_ID,
                object_type="site_wlans",
                payload={"ssid": "Guest"},
                object_id=self.OBJECT_ID,
                changes=[
                    {
                        "action_type": "update",
                        "object_type": "site_wlans",
                        "site_id": self.SITE_ID,
                        "object_id": self.OBJECT_ID,
                        "payload": {"ssid": "Guest-2"},
                    }
                ],
                session_id="",
            )

    def test_simulate_rejects_empty_changes_list(self):
        with pytest.raises(ToolError, match="at least one change object"):
            validate_twin(
                action="simulate",
                action_type=None,
                org_id=self.ORG_ID,
                site_id=None,
                object_type=None,
                payload=None,
                object_id=None,
                changes=[],
                session_id="",
            )


@pytest.mark.unit
class TestDigitalTwinDiagnosticsFormatting:
    def test_build_report_diagnostics_includes_full_issue_context(self):
        report = type("FakeReport", (), {})()
        report.check_results = [
            CheckResult(
                check_id="ROUTE-GW",
                check_name="Default Gateway Gap",
                layer=3,
                status="error",
                summary="1 network missing a gateway L3 interface.",
                details=["Network 'Corp' has no gateway L3 interface; network VLAN=10"],
                affected_objects=["Corp"],
                affected_sites=["site-1"],
                remediation_hint="Add gateway ip_config for routed VLANs.",
                pre_existing=False,
                description="Detects routed networks with no corresponding gateway interface.",
            ),
            CheckResult(
                check_id="CONN-PHYS",
                check_name="Physical connectivity loss",
                layer=2,
                status="pass",
                summary="All devices retain gateway reachability.",
                description="Detects devices that become isolated from gateways.",
            ),
        ]

        diagnostics = build_report_diagnostics(report)

        assert len(diagnostics["executed_checks"]) == 2
        assert len(diagnostics["check_diagnostics"]) == 2
        assert len(diagnostics["issues"]) == 1
        assert diagnostics["introduced_issue_count"] == 1
        assert diagnostics["pre_existing_issue_count"] == 0

        issue = diagnostics["issues"][0]
        assert issue["check"] == "ROUTE-GW"
        assert issue["description"] != ""
        assert issue["details"]
        assert issue["remediation_hint"]
        assert issue["affected_sites"] == ["site-1"]
        assert issue["affected_objects"] == ["Corp"]

        assert any("ROUTE-GW" in line and "error" in line for line in diagnostics["decision_log"])

    def test_build_report_diagnostics_counts_pre_existing_issues(self):
        report = type("FakeReport", (), {})()
        report.check_results = [
            CheckResult(
                check_id="SEC-GUEST",
                check_name="Guest Isolation Risk",
                layer=4,
                status="warning",
                summary="Guest SSID open without isolation.",
                details=["SSID Guest-WiFi is open without client isolation"],
                affected_sites=["site-1"],
                remediation_hint="Enable client isolation for open SSIDs.",
                pre_existing=True,
                description="Detects open WLANs that are missing isolation.",
            )
        ]

        diagnostics = build_report_diagnostics(report)

        assert diagnostics["introduced_issue_count"] == 0
        assert diagnostics["pre_existing_issue_count"] == 1
        assert diagnostics["issues"][0]["pre_existing"] is True
