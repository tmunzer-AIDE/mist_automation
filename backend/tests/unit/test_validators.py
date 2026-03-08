"""
Unit tests for validation utilities.
"""

import pytest
from app.utils.validators import (
    ValidationError,
    validate_email,
    validate_password,
    validate_url,
    validate_ip_address,
    validate_cron_expression,
    validate_timezone,
    validate_json,
    validate_filter_config,
    validate_action_config,
    validate_workflow_config,
    sanitize_string,
)


class TestEmailValidation:
    """Test email validation."""

    def test_valid_email(self):
        valid, error = validate_email("user@example.com")
        assert valid is True
        assert error is None

    def test_valid_email_with_subdomain(self):
        valid, error = validate_email("user@mail.example.com")
        assert valid is True

    def test_valid_email_with_plus(self):
        valid, error = validate_email("user+tag@example.com")
        assert valid is True

    def test_invalid_email_no_at(self):
        valid, error = validate_email("userexample.com")
        assert valid is False
        assert "Invalid email" in error

    def test_invalid_email_no_domain(self):
        valid, error = validate_email("user@")
        assert valid is False

    def test_invalid_email_no_local(self):
        valid, error = validate_email("@example.com")
        assert valid is False

    def test_empty_email(self):
        valid, error = validate_email("")
        assert valid is False
        assert "required" in error.lower()

    def test_email_too_long(self):
        email = "a" * 255 + "@example.com"
        valid, error = validate_email(email)
        assert valid is False
        assert "too long" in error.lower()


class TestPasswordValidation:
    """Test password validation."""

    def test_valid_password(self):
        valid, error = validate_password("SecurePass123!")
        assert valid is True
        assert error is None

    def test_password_too_short(self):
        valid, error = validate_password("Short1!")
        assert valid is False
        assert "at least" in error.lower()

    def test_password_no_uppercase(self):
        valid, error = validate_password("securepass123!", require_uppercase=True)
        assert valid is False
        assert "uppercase" in error.lower()

    def test_password_no_lowercase(self):
        valid, error = validate_password("SECUREPASS123!", require_lowercase=True)
        assert valid is False
        assert "lowercase" in error.lower()

    def test_password_no_digit(self):
        valid, error = validate_password("SecurePass!", require_digit=True)
        assert valid is False
        assert "digit" in error.lower()

    def test_password_no_special(self):
        valid, error = validate_password("SecurePass123", require_special=True)
        assert valid is False
        assert "special" in error.lower()

    def test_password_custom_min_length(self):
        valid, error = validate_password("Short1!", min_length=12)
        assert valid is False

        valid, error = validate_password("LongerPass123!", min_length=12)
        assert valid is True

    def test_password_no_requirements(self):
        valid, error = validate_password(
            "simple",
            min_length=5,
            require_uppercase=False,
            require_lowercase=False,
            require_digit=False,
            require_special=False
        )
        assert valid is True

    def test_empty_password(self):
        valid, error = validate_password("")
        assert valid is False
        assert "required" in error.lower()


class TestURLValidation:
    """Test URL validation."""

    def test_valid_http_url(self):
        valid, error = validate_url("http://example.com")
        assert valid is True

    def test_valid_https_url(self):
        valid, error = validate_url("https://example.com")
        assert valid is True

    def test_valid_url_with_path(self):
        valid, error = validate_url("https://example.com/path/to/resource")
        assert valid is True

    def test_valid_url_with_query(self):
        valid, error = validate_url("https://example.com?param=value")
        assert valid is True

    def test_invalid_url_no_scheme(self):
        valid, error = validate_url("example.com")
        assert valid is False
        assert "scheme" in error.lower()

    def test_invalid_url_no_domain(self):
        valid, error = validate_url("https://")
        assert valid is False
        assert "domain" in error.lower()

    def test_invalid_scheme(self):
        valid, error = validate_url("ftp://example.com", allowed_schemes=["http", "https"])
        assert valid is False
        assert "scheme" in error.lower()

    def test_custom_allowed_scheme(self):
        valid, error = validate_url("ftp://example.com", allowed_schemes=["ftp"])
        assert valid is True

    def test_empty_url(self):
        valid, error = validate_url("")
        assert valid is False
        assert "required" in error.lower()


class TestIPAddressValidation:
    """Test IP address validation."""

    def test_valid_ipv4(self):
        valid, error = validate_ip_address("192.168.1.1")
        assert valid is True

    def test_valid_ipv6(self):
        valid, error = validate_ip_address("2001:0db8:85a3:0000:0000:8a2e:0370:7334")
        assert valid is True

    def test_valid_ipv6_compressed(self):
        valid, error = validate_ip_address("2001:db8::1")
        assert valid is True

    def test_invalid_ipv4(self):
        valid, error = validate_ip_address("256.1.1.1")
        assert valid is False

    def test_invalid_ip_format(self):
        valid, error = validate_ip_address("not.an.ip.address")
        assert valid is False

    def test_ipv4_version_check(self):
        valid, error = validate_ip_address("192.168.1.1", version=4)
        assert valid is True

        valid, error = validate_ip_address("2001:db8::1", version=4)
        assert valid is False
        assert "IPv4" in error

    def test_ipv6_version_check(self):
        valid, error = validate_ip_address("2001:db8::1", version=6)
        assert valid is True

        valid, error = validate_ip_address("192.168.1.1", version=6)
        assert valid is False
        assert "IPv6" in error

    def test_empty_ip(self):
        valid, error = validate_ip_address("")
        assert valid is False
        assert "required" in error.lower()


class TestCronExpressionValidation:
    """Test cron expression validation."""

    def test_valid_cron_expression(self):
        valid, error = validate_cron_expression("0 0 * * *")
        assert valid is True

    def test_valid_cron_every_minute(self):
        valid, error = validate_cron_expression("* * * * *")
        assert valid is True

    def test_valid_cron_specific_time(self):
        valid, error = validate_cron_expression("30 14 * * 1")
        assert valid is True

    def test_valid_cron_with_ranges(self):
        valid, error = validate_cron_expression("0 9-17 * * 1-5")
        assert valid is True

    def test_valid_cron_with_steps(self):
        valid, error = validate_cron_expression("*/15 * * * *")
        assert valid is True

    def test_invalid_cron_too_few_fields(self):
        valid, error = validate_cron_expression("0 0 * *")
        assert valid is False
        assert "field" in error or "column" in error

    def test_invalid_cron_too_many_fields(self):
        valid, error = validate_cron_expression("0 0 * * * * *", allow_seconds=False)
        assert valid is False

    def test_invalid_cron_bad_syntax(self):
        valid, error = validate_cron_expression("invalid cron")
        assert valid is False

    def test_cron_with_seconds_allowed(self):
        valid, error = validate_cron_expression("0 0 0 * * *", allow_seconds=True)
        assert valid is True

    def test_empty_cron(self):
        valid, error = validate_cron_expression("")
        assert valid is False
        assert "required" in error.lower()


class TestTimezoneValidation:
    """Test timezone validation."""

    def test_valid_timezone_us(self):
        valid, error = validate_timezone("America/New_York")
        assert valid is True

    def test_valid_timezone_europe(self):
        valid, error = validate_timezone("Europe/London")
        assert valid is True

    def test_valid_timezone_utc(self):
        valid, error = validate_timezone("UTC")
        assert valid is True

    def test_invalid_timezone(self):
        valid, error = validate_timezone("Invalid/Timezone")
        assert valid is False
        assert "Invalid timezone" in error

    def test_empty_timezone(self):
        valid, error = validate_timezone("")
        assert valid is False
        assert "required" in error.lower()


class TestJSONValidation:
    """Test JSON validation."""

    def test_valid_json_object(self):
        valid, error, parsed = validate_json('{"key": "value"}')
        assert valid is True
        assert error is None
        assert parsed == {"key": "value"}

    def test_valid_json_array(self):
        valid, error, parsed = validate_json('[1, 2, 3]')
        assert valid is True
        assert parsed == [1, 2, 3]

    def test_valid_json_nested(self):
        valid, error, parsed = validate_json('{"nested": {"key": "value"}}')
        assert valid is True
        assert parsed["nested"]["key"] == "value"

    def test_invalid_json_syntax(self):
        valid, error, parsed = validate_json('{"key": invalid}')
        assert valid is False
        assert "Invalid JSON" in error
        assert parsed is None

    def test_invalid_json_trailing_comma(self):
        valid, error, parsed = validate_json('{"key": "value",}')
        assert valid is False

    def test_empty_json(self):
        valid, error, parsed = validate_json('')
        assert valid is False
        assert "required" in error.lower()


class TestFilterConfigValidation:
    """Test filter configuration validation."""

    def test_valid_simple_filter(self):
        config = {
            "field": "type",
            "operator": "equals",
            "value": "alarm"
        }
        valid, error = validate_filter_config(config)
        assert valid is True

    def test_valid_filter_with_source(self):
        config = {
            "field": "type",
            "operator": "equals",
            "value": "alarm",
            "source": "webhook"
        }
        valid, error = validate_filter_config(config)
        assert valid is True

    def test_valid_filter_group(self):
        config = {
            "logic": "or",
            "filters": [
                {"field": "type", "operator": "equals", "value": "alarm"},
                {"field": "type", "operator": "equals", "value": "audit"}
            ]
        }
        valid, error = validate_filter_config(config)
        assert valid is True

    def test_invalid_filter_missing_field(self):
        config = {
            "operator": "equals",
            "value": "alarm"
        }
        valid, error = validate_filter_config(config)
        assert valid is False
        assert "field" in error.lower()

    def test_invalid_filter_missing_operator(self):
        config = {
            "field": "type",
            "value": "alarm"
        }
        valid, error = validate_filter_config(config)
        assert valid is False
        assert "operator" in error.lower()

    def test_invalid_operator(self):
        config = {
            "field": "type",
            "operator": "invalid_op",
            "value": "alarm"
        }
        valid, error = validate_filter_config(config)
        assert valid is False
        assert "Invalid operator" in error

    def test_between_operator_needs_list(self):
        config = {
            "field": "count",
            "operator": "between",
            "value": 5  # Should be a list
        }
        valid, error = validate_filter_config(config)
        assert valid is False
        assert "list" in error.lower()

    def test_in_list_operator_needs_list(self):
        config = {
            "field": "severity",
            "operator": "in_list",
            "value": "critical"  # Should be a list
        }
        valid, error = validate_filter_config(config)
        assert valid is False
        assert "list" in error.lower()

    def test_is_true_no_value_needed(self):
        config = {
            "field": "active",
            "operator": "is_true"
        }
        valid, error = validate_filter_config(config)
        assert valid is True

    def test_invalid_source(self):
        config = {
            "field": "type",
            "operator": "equals",
            "value": "alarm",
            "source": "invalid_source"
        }
        valid, error = validate_filter_config(config)
        assert valid is False
        assert "source" in error.lower()


class TestActionConfigValidation:
    """Test action configuration validation."""

    def test_valid_api_action(self):
        config = {
            "type": "api_get",
            "endpoint": "devices"
        }
        valid, error = validate_action_config(config)
        assert valid is True

    def test_valid_notification_action(self):
        config = {
            "type": "slack",
            "config": {"webhook_url": "https://hooks.slack.com/..."}
        }
        valid, error = validate_action_config(config)
        assert valid is True

    def test_invalid_action_missing_type(self):
        config = {
            "endpoint": "devices"
        }
        valid, error = validate_action_config(config)
        assert valid is False
        assert "type" in error.lower()

    def test_invalid_action_type(self):
        config = {
            "type": "invalid_type",
            "endpoint": "devices"
        }
        valid, error = validate_action_config(config)
        assert valid is False
        assert "Invalid action type" in error

    def test_api_action_missing_endpoint(self):
        config = {
            "type": "api_get"
        }
        valid, error = validate_action_config(config)
        assert valid is False
        assert "endpoint" in error.lower()

    def test_notification_action_missing_config(self):
        config = {
            "type": "slack"
        }
        valid, error = validate_action_config(config)
        assert valid is False
        assert "config" in error.lower()

    def test_invalid_on_failure(self):
        config = {
            "type": "api_get",
            "endpoint": "devices",
            "on_failure": "invalid"
        }
        valid, error = validate_action_config(config)
        assert valid is False
        assert "on_failure" in error.lower()

    def test_valid_on_failure_stop(self):
        config = {
            "type": "api_get",
            "endpoint": "devices",
            "on_failure": "stop"
        }
        valid, error = validate_action_config(config)
        assert valid is True

    def test_valid_on_failure_continue(self):
        config = {
            "type": "api_get",
            "endpoint": "devices",
            "on_failure": "continue"
        }
        valid, error = validate_action_config(config)
        assert valid is True


class TestWorkflowConfigValidation:
    """Test workflow configuration validation."""

    def test_valid_webhook_workflow(self):
        config = {
            "name": "Test Workflow",
            "trigger": {
                "type": "webhook",
                "webhook_type": "alarm"
            },
            "filters": [],
            "actions": []
        }
        valid, errors = validate_workflow_config(config)
        assert valid is True
        assert len(errors) == 0

    def test_valid_cron_workflow(self):
        config = {
            "name": "Test Workflow",
            "trigger": {
                "type": "cron",
                "cron_expression": "0 0 * * *",
                "timezone": "America/New_York"
            },
            "filters": [],
            "actions": []
        }
        valid, errors = validate_workflow_config(config)
        assert valid is True

    def test_invalid_workflow_missing_name(self):
        config = {
            "trigger": {"type": "webhook", "webhook_type": "alarm"}
        }
        valid, errors = validate_workflow_config(config)
        assert valid is False
        assert any("name" in error.lower() for error in errors)

    def test_invalid_workflow_missing_trigger(self):
        config = {
            "name": "Test Workflow"
        }
        valid, errors = validate_workflow_config(config)
        assert valid is False
        assert any("trigger" in error.lower() for error in errors)

    def test_invalid_trigger_type(self):
        config = {
            "name": "Test Workflow",
            "trigger": {"type": "invalid"}
        }
        valid, errors = validate_workflow_config(config)
        assert valid is False
        assert any("trigger type" in error.lower() for error in errors)

    def test_webhook_trigger_missing_webhook_type(self):
        config = {
            "name": "Test Workflow",
            "trigger": {"type": "webhook"}
        }
        valid, errors = validate_workflow_config(config)
        assert valid is False
        assert any("webhook_type" in error.lower() for error in errors)

    def test_cron_trigger_missing_expression(self):
        config = {
            "name": "Test Workflow",
            "trigger": {"type": "cron"}
        }
        valid, errors = validate_workflow_config(config)
        assert valid is False
        assert any("cron_expression" in error.lower() for error in errors)

    def test_invalid_cron_expression(self):
        config = {
            "name": "Test Workflow",
            "trigger": {
                "type": "cron",
                "cron_expression": "invalid cron"
            }
        }
        valid, errors = validate_workflow_config(config)
        assert valid is False
        assert any("cron" in error.lower() for error in errors)

    def test_invalid_timezone(self):
        config = {
            "name": "Test Workflow",
            "trigger": {
                "type": "cron",
                "cron_expression": "0 0 * * *",
                "timezone": "Invalid/TimeZone"
            }
        }
        valid, errors = validate_workflow_config(config)
        assert valid is False
        assert any("timezone" in error.lower() for error in errors)

    def test_invalid_status(self):
        config = {
            "name": "Test Workflow",
            "trigger": {"type": "webhook", "webhook_type": "alarm"},
            "status": "invalid"
        }
        valid, errors = validate_workflow_config(config)
        assert valid is False
        assert any("status" in error.lower() for error in errors)

    def test_invalid_sharing(self):
        config = {
            "name": "Test Workflow",
            "trigger": {"type": "webhook", "webhook_type": "alarm"},
            "sharing": "invalid"
        }
        valid, errors = validate_workflow_config(config)
        assert valid is False
        assert any("sharing" in error.lower() for error in errors)

    def test_invalid_timeout(self):
        config = {
            "name": "Test Workflow",
            "trigger": {"type": "webhook", "webhook_type": "alarm"},
            "timeout_seconds": -10
        }
        valid, errors = validate_workflow_config(config)
        assert valid is False
        assert any("timeout" in error.lower() for error in errors)

    def test_timeout_too_large(self):
        config = {
            "name": "Test Workflow",
            "trigger": {"type": "webhook", "webhook_type": "alarm"},
            "timeout_seconds": 5000
        }
        valid, errors = validate_workflow_config(config)
        assert valid is False
        assert any("timeout" in error.lower() for error in errors)


class TestSanitizeString:
    """Test string sanitization."""

    def test_strip_whitespace(self):
        result = sanitize_string("  test  ")
        assert result == "test"

    def test_no_strip(self):
        result = sanitize_string("  test  ", strip=False)
        assert result == "  test  "

    def test_max_length(self):
        result = sanitize_string("very long string", max_length=10)
        assert result == "very long "
        assert len(result) == 10

    def test_allowed_chars_alphanumeric(self):
        result = sanitize_string("test123!@#", allowed_chars="a-zA-Z0-9")
        assert result == "test123"

    def test_empty_string(self):
        result = sanitize_string("")
        assert result == ""

    def test_combined_sanitization(self):
        result = sanitize_string(
            "  Hello World!  ",
            max_length=10,
            allowed_chars="a-zA-Z ",
            strip=True
        )
        assert result == "Hello Worl"
        assert "!" not in result
