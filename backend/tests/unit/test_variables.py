"""
Unit tests for variable substitution engine.
"""

import os
import pytest
from datetime import datetime, timezone
from app.utils.variables import (
    VariableSubstitutionError,
    get_nested_value,
    build_context,
    substitute_variables,
    substitute_in_dict,
    substitute_in_list,
    extract_variables,
    validate_template,
    preview_substitution,
)


class TestGetNestedValue:
    """Test nested value extraction."""

    def test_simple_field(self):
        data = {"name": "test"}
        assert get_nested_value(data, "name") == "test"

    def test_nested_field(self):
        data = {"event": {"device": {"name": "AP-01"}}}
        assert get_nested_value(data, "event.device.name") == "AP-01"

    def test_missing_field_returns_default(self):
        data = {"name": "test"}
        assert get_nested_value(data, "missing", default="default") == "default"

    def test_missing_field_returns_none(self):
        data = {"name": "test"}
        assert get_nested_value(data, "missing") is None

    def test_empty_path(self):
        data = {"name": "test"}
        assert get_nested_value(data, "") is None


class TestBuildContext:
    """Test context building."""

    def test_empty_context(self):
        context = build_context(include_env=False)
        assert "now" in context
        assert "now_iso" in context
        assert "now_timestamp" in context

    def test_webhook_data(self):
        webhook_data = {"event": {"type": "alarm"}}
        context = build_context(webhook_data=webhook_data, include_env=False)
        assert context["event"]["type"] == "alarm"

    def test_api_results(self):
        api_results = {"device_info": {"name": "AP-01"}}
        context = build_context(api_results=api_results, include_env=False)
        assert context["device_info"]["name"] == "AP-01"

    def test_workflow_context(self):
        workflow_context = {"workflow": {"name": "Test"}}
        context = build_context(workflow_context=workflow_context, include_env=False)
        assert context["workflow"]["name"] == "Test"

    def test_environment_variables(self):
        context = build_context(include_env=True)
        assert "APP_NAME" in context["env"]
        assert "ENVIRONMENT" in context["env"]
        # Must NOT expose secrets
        assert "SECRET_KEY" not in context["env"]

    def test_env_does_not_expose_secret_key(self):
        context = build_context(include_env=True)
        env = context.get("env", {})
        for key in ("SECRET_KEY", "MIST_API_TOKEN", "MONGODB_PASSWORD"):
            assert key not in env

    def test_utility_values(self):
        context = build_context(include_env=False)
        assert isinstance(context["now"], datetime)
        assert isinstance(context["now_iso"], str)
        assert isinstance(context["now_timestamp"], int)


class TestSubstituteVariables:
    """Test variable substitution."""

    def test_simple_substitution(self):
        template = "Device {{device.name}} went offline"
        webhook_data = {"device": {"name": "AP-01"}}
        result = substitute_variables(template, webhook_data=webhook_data)
        assert result == "Device AP-01 went offline"

    def test_multiple_substitutions(self):
        template = "{{type}}: {{device.name}} has {{alarm.severity}} alarm"
        webhook_data = {
            "type": "alarm",
            "device": {"name": "AP-01"},
            "alarm": {"severity": "critical"}
        }
        result = substitute_variables(template, webhook_data=webhook_data)
        assert result == "alarm: AP-01 has critical alarm"

    def test_api_results_substitution(self):
        template = "Device uptime: {{device_stats.uptime}}"
        api_results = {"device_stats": {"uptime": "24 hours"}}
        result = substitute_variables(template, api_results=api_results)
        assert result == "Device uptime: 24 hours"

    def test_workflow_context_substitution(self):
        template = "Workflow: {{workflow.name}}"
        workflow_context = {"workflow": {"name": "Test Workflow"}}
        result = substitute_variables(template, workflow_context=workflow_context)
        assert result == "Workflow: Test Workflow"

    def test_environment_variable_substitution(self):
        template = "App: {{env.APP_NAME}}"
        result = substitute_variables(template, include_env=True)
        assert "Mist" in result

    def test_secret_key_not_accessible_via_template(self):
        template = "Secret: {{env.SECRET_KEY}}"
        result = substitute_variables(template, include_env=True)
        # SECRET_KEY should not be in the env dict, so ChainableUndefined renders empty
        assert "Secret:" in result
        # Must not contain the actual secret key value
        from app.config import settings
        assert settings.secret_key not in result

    def test_empty_template(self):
        result = substitute_variables("", webhook_data={})
        assert result == ""

    def test_no_variables(self):
        template = "No variables here"
        result = substitute_variables(template, webhook_data={})
        assert result == "No variables here"

    def test_undefined_variable_non_strict(self):
        template = "Device {{device.name}} offline"
        result = substitute_variables(template, webhook_data={}, strict=False)
        # Jinja2 renders undefined variables as empty string by default
        assert "offline" in result

    def test_undefined_variable_strict(self):
        template = "Device {{device.name}} offline"
        with pytest.raises(VariableSubstitutionError, match="Undefined variable"):
            substitute_variables(template, webhook_data={}, strict=True)

    def test_template_syntax_error(self):
        template = "Device {{device.name"  # Missing closing }}
        with pytest.raises(VariableSubstitutionError, match="Template syntax error"):
            substitute_variables(template, webhook_data={})

    def test_utility_values_substitution(self):
        template = "Timestamp: {{now_timestamp}}"
        result = substitute_variables(template, webhook_data={})
        assert "Timestamp:" in result
        assert len(result) > len("Timestamp: ")


class TestSubstituteInDict:
    """Test dictionary substitution."""

    def test_simple_dict(self):
        data = {"message": "Device {{device.name}}"}
        webhook_data = {"device": {"name": "AP-01"}}
        result = substitute_in_dict(data, webhook_data=webhook_data)
        assert result["message"] == "Device AP-01"

    def test_nested_dict(self):
        data = {
            "alert": {
                "title": "{{alarm.type}}",
                "body": "Device {{device.name}}"
            }
        }
        webhook_data = {
            "alarm": {"type": "offline"},
            "device": {"name": "AP-01"}
        }
        result = substitute_in_dict(data, webhook_data=webhook_data)
        assert result["alert"]["title"] == "offline"
        assert result["alert"]["body"] == "Device AP-01"

    def test_mixed_types(self):
        data = {
            "string": "{{device.name}}",
            "number": 42,
            "bool": True,
            "null": None
        }
        webhook_data = {"device": {"name": "AP-01"}}
        result = substitute_in_dict(data, webhook_data=webhook_data)
        assert result["string"] == "AP-01"
        assert result["number"] == 42
        assert result["bool"] is True
        assert result["null"] is None

    def test_dict_with_list(self):
        data = {
            "devices": ["{{device1}}", "{{device2}}"]
        }
        webhook_data = {"device1": "AP-01", "device2": "AP-02"}
        result = substitute_in_dict(data, webhook_data=webhook_data)
        assert result["devices"] == ["AP-01", "AP-02"]


class TestSubstituteInList:
    """Test list substitution."""

    def test_simple_list(self):
        data = ["{{device1}}", "{{device2}}"]
        webhook_data = {"device1": "AP-01", "device2": "AP-02"}
        result = substitute_in_list(data, webhook_data=webhook_data)
        assert result == ["AP-01", "AP-02"]

    def test_list_with_dicts(self):
        data = [
            {"name": "{{device1}}"},
            {"name": "{{device2}}"}
        ]
        webhook_data = {"device1": "AP-01", "device2": "AP-02"}
        result = substitute_in_list(data, webhook_data=webhook_data)
        assert result[0]["name"] == "AP-01"
        assert result[1]["name"] == "AP-02"

    def test_nested_lists(self):
        data = [["{{device1}}"], ["{{device2}}"]]
        webhook_data = {"device1": "AP-01", "device2": "AP-02"}
        result = substitute_in_list(data, webhook_data=webhook_data)
        assert result[0][0] == "AP-01"
        assert result[1][0] == "AP-02"

    def test_mixed_types_in_list(self):
        data = ["{{device}}", 42, True, None]
        webhook_data = {"device": "AP-01"}
        result = substitute_in_list(data, webhook_data=webhook_data)
        assert result == ["AP-01", 42, True, None]


class TestExtractVariables:
    """Test variable extraction."""

    def test_no_variables(self):
        template = "No variables here"
        variables = extract_variables(template)
        assert variables == []

    def test_single_variable(self):
        template = "Device {{device.name}}"
        variables = extract_variables(template)
        assert variables == ["device.name"]

    def test_multiple_variables(self):
        template = "{{type}}: {{device.name}} - {{alarm.severity}}"
        variables = extract_variables(template)
        assert "type" in variables
        assert "device.name" in variables
        assert "alarm.severity" in variables

    def test_duplicate_variables(self):
        template = "{{device.name}} and {{device.name}}"
        variables = extract_variables(template)
        # Should only appear once
        assert variables.count("device.name") == 1

    def test_variables_with_whitespace(self):
        template = "{{ device.name }} and {{device.type}}"
        variables = extract_variables(template)
        assert "device.name" in variables
        assert "device.type" in variables

    def test_variables_with_filters(self):
        # Jinja2 filters (e.g., |upper) should be stripped
        template = "{{device.name | upper}}"
        variables = extract_variables(template)
        assert variables == ["device.name"]

    def test_empty_template(self):
        variables = extract_variables("")
        assert variables == []


class TestValidateTemplate:
    """Test template validation."""

    def test_valid_template(self):
        template = "Device {{device.name}}"
        valid, error = validate_template(template)
        assert valid is True
        assert error is None

    def test_empty_template(self):
        valid, error = validate_template("")
        assert valid is True
        assert error is None

    def test_no_variables(self):
        template = "No variables"
        valid, error = validate_template(template)
        assert valid is True
        assert error is None

    def test_invalid_template_missing_closing(self):
        template = "Device {{device.name"
        valid, error = validate_template(template)
        assert valid is False
        assert error is not None
        assert "Syntax error" in error or "syntax" in error.lower()

    def test_invalid_template_missing_opening(self):
        template = "Device device.name}}"
        valid, error = validate_template(template)
        # This actually parses fine in Jinja2, the closing }} is treated as text
        assert valid is True

    def test_complex_valid_template(self):
        template = "{% if device %}{{device.name}}{% endif %}"
        valid, error = validate_template(template)
        assert valid is True


class TestPreviewSubstitution:
    """Test substitution preview."""

    def test_successful_preview(self):
        template = "Device {{device.name}}"
        context = {"device": {"name": "AP-01"}}
        preview = preview_substitution(template, context)

        assert preview["valid"] is True
        assert preview["result"] == "Device AP-01"
        assert "device.name" in preview["variables"]
        assert preview["variable_values"]["device.name"] == "AP-01"

    def test_preview_with_undefined_variable(self):
        template = "Device {{device.name}}"
        context = {"other": "value"}
        preview = preview_substitution(template, context)

        assert preview["valid"] is True
        assert "device.name" in preview["variables"]
        assert preview["variable_values"]["device.name"] == "<undefined>"

    def test_preview_with_invalid_template(self):
        template = "Device {{device.name"
        context = {"device": {"name": "AP-01"}}
        preview = preview_substitution(template, context)

        assert preview["valid"] is False
        assert "error" in preview
        assert "variables" in preview

    def test_preview_multiple_variables(self):
        template = "{{type}}: {{device.name}}"
        context = {"type": "alarm", "device": {"name": "AP-01"}}
        preview = preview_substitution(template, context)

        assert preview["valid"] is True
        assert len(preview["variables"]) == 2
        assert preview["variable_values"]["type"] == "alarm"
        assert preview["variable_values"]["device.name"] == "AP-01"


class TestComplexScenarios:
    """Test complex real-world scenarios."""

    def test_slack_message_template(self):
        template = """
        :warning: *{{alarm.type}}* Alert
        *Device:* {{device.name}}
        *Site:* {{site.name}}
        *Severity:* {{alarm.severity}}
        *Time:* {{now_iso}}
        """
        webhook_data = {
            "alarm": {"type": "Device Offline", "severity": "critical"},
            "device": {"name": "AP-01"},
            "site": {"name": "Building A"}
        }
        result = substitute_variables(template, webhook_data=webhook_data)

        assert "Device Offline" in result
        assert "AP-01" in result
        assert "Building A" in result
        assert "critical" in result

    def test_servicenow_payload(self):
        data = {
            "short_description": "{{alarm.type}} - {{device.name}}",
            "description": "Device {{device.name}} at {{site.name}} has {{alarm.severity}} alarm",
            "severity": "{{alarm.severity}}",
            "assignment_group": "Network Team"
        }
        webhook_data = {
            "alarm": {"type": "offline", "severity": "critical"},
            "device": {"name": "AP-01"},
            "site": {"name": "Building A"}
        }
        result = substitute_in_dict(data, webhook_data=webhook_data)

        assert result["short_description"] == "offline - AP-01"
        assert "Building A" in result["description"]
        assert result["severity"] == "critical"
        assert result["assignment_group"] == "Network Team"

    def test_conditional_template(self):
        template = "{% if alarm.severity == 'critical' %}URGENT: {% endif %}{{alarm.type}}"
        webhook_data = {"alarm": {"type": "Device Offline", "severity": "critical"}}
        result = substitute_variables(template, webhook_data=webhook_data)
        assert result == "URGENT: Device Offline"

        webhook_data = {"alarm": {"type": "Device Offline", "severity": "minor"}}
        result = substitute_variables(template, webhook_data=webhook_data)
        assert result == "Device Offline"

    def test_api_action_parameters(self):
        data = {
            "device_id": "{{device.id}}",
            "command": "reboot",
            "reason": "Offline for {{device.offline_duration}} minutes"
        }
        webhook_data = {
            "device": {"id": "abc123", "offline_duration": 30}
        }
        result = substitute_in_dict(data, webhook_data=webhook_data)

        assert result["device_id"] == "abc123"
        assert result["command"] == "reboot"
        assert "30 minutes" in result["reason"]

    def test_combined_context_sources(self):
        template = "{{workflow.name}}: {{event.type}} on {{device_info.name}} ({{device_info.model}})"
        webhook_data = {"event": {"type": "alarm"}}
        api_results = {"device_info": {"name": "AP-01", "model": "AP43"}}
        workflow_context = {"workflow": {"name": "Auto-Reboot"}}

        result = substitute_variables(
            template,
            webhook_data=webhook_data,
            api_results=api_results,
            workflow_context=workflow_context
        )

        assert "Auto-Reboot" in result
        assert "alarm" in result
        assert "AP-01" in result
        assert "AP43" in result
