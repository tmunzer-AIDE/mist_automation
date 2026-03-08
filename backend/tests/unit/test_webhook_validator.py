"""
Unit tests for webhook validation utilities.
"""

import json
import time
import pytest
from app.utils.webhook_validator import (
    WebhookValidationError,
    MIST_WEBHOOK_TYPES,
    validate_webhook_signature,
    generate_webhook_signature,
    validate_webhook_timestamp,
    validate_mist_webhook_type,
    validate_webhook_payload,
    validate_mist_alarm_payload,
    parse_webhook_payload,
    validate_webhook_request,
    get_nested_value,
)


class TestGenerateSignature:
    """Test webhook signature generation."""

    def test_generate_signature(self):
        payload = b'{"event": "test"}'
        secret = "my_secret_key"
        signature = generate_webhook_signature(payload, secret)

        assert signature is not None
        assert len(signature) == 64  # SHA256 produces 64-character hex string

    def test_consistent_signature(self):
        payload = b'{"event": "test"}'
        secret = "my_secret_key"
        sig1 = generate_webhook_signature(payload, secret)
        sig2 = generate_webhook_signature(payload, secret)

        assert sig1 == sig2

    def test_different_payload_different_signature(self):
        secret = "my_secret_key"
        sig1 = generate_webhook_signature(b'{"event": "test1"}', secret)
        sig2 = generate_webhook_signature(b'{"event": "test2"}', secret)

        assert sig1 != sig2

    def test_different_secret_different_signature(self):
        payload = b'{"event": "test"}'
        sig1 = generate_webhook_signature(payload, "secret1")
        sig2 = generate_webhook_signature(payload, "secret2")

        assert sig1 != sig2


class TestValidateSignature:
    """Test webhook signature validation."""

    def test_valid_signature(self):
        payload = b'{"event": "test"}'
        secret = "my_secret_key"
        signature = generate_webhook_signature(payload, secret)

        valid, error = validate_webhook_signature(payload, signature, secret)
        assert valid is True
        assert error is None

    def test_invalid_signature(self):
        payload = b'{"event": "test"}'
        secret = "my_secret_key"
        signature = "invalid_signature"

        valid, error = validate_webhook_signature(payload, signature, secret)
        assert valid is False
        assert "validation failed" in error.lower()

    def test_signature_with_algorithm_prefix(self):
        payload = b'{"event": "test"}'
        secret = "my_secret_key"
        signature = generate_webhook_signature(payload, secret)
        signature_with_prefix = f"sha256={signature}"

        valid, error = validate_webhook_signature(payload, signature_with_prefix, secret)
        assert valid is True

    def test_tampered_payload(self):
        payload = b'{"event": "test"}'
        tampered_payload = b'{"event": "tampered"}'
        secret = "my_secret_key"
        signature = generate_webhook_signature(payload, secret)

        valid, error = validate_webhook_signature(tampered_payload, signature, secret)
        assert valid is False

    def test_missing_payload(self):
        valid, error = validate_webhook_signature(b'', "signature", "secret")
        assert valid is False
        assert "required" in error.lower()

    def test_missing_signature(self):
        valid, error = validate_webhook_signature(b'payload', '', "secret")
        assert valid is False
        assert "required" in error.lower()

    def test_missing_secret(self):
        valid, error = validate_webhook_signature(b'payload', "signature", '')
        assert valid is False
        assert "required" in error.lower()

    def test_unsupported_algorithm(self):
        payload = b'{"event": "test"}'
        signature = "fakealgorithm=abc123"
        secret = "my_secret_key"

        valid, error = validate_webhook_signature(payload, signature, secret)
        assert valid is False
        assert "Unsupported hash algorithm" in error


class TestValidateTimestamp:
    """Test webhook timestamp validation."""

    def test_valid_current_timestamp(self):
        timestamp = int(time.time())
        valid, error = validate_webhook_timestamp(timestamp)
        assert valid is True
        assert error is None

    def test_valid_recent_timestamp(self):
        timestamp = int(time.time()) - 60  # 1 minute ago
        valid, error = validate_webhook_timestamp(timestamp, max_age_seconds=300)
        assert valid is True

    def test_invalid_old_timestamp(self):
        timestamp = int(time.time()) - 600  # 10 minutes ago
        valid, error = validate_webhook_timestamp(timestamp, max_age_seconds=300)
        assert valid is False
        assert "too old" in error.lower()

    def test_invalid_future_timestamp(self):
        timestamp = int(time.time()) + 600  # 10 minutes in future
        valid, error = validate_webhook_timestamp(timestamp)
        assert valid is False
        assert "future" in error.lower()

    def test_missing_timestamp(self):
        valid, error = validate_webhook_timestamp(None)
        assert valid is False
        assert "required" in error.lower()

    def test_invalid_timestamp_format(self):
        valid, error = validate_webhook_timestamp(9999999999999999)
        assert valid is False
        assert "Invalid timestamp" in error

    def test_custom_max_age(self):
        timestamp = int(time.time()) - 100
        valid, error = validate_webhook_timestamp(timestamp, max_age_seconds=60)
        assert valid is False

        valid, error = validate_webhook_timestamp(timestamp, max_age_seconds=120)
        assert valid is True


class TestValidateMistWebhookType:
    """Test Mist webhook type validation."""

    def test_valid_category_alarm(self):
        valid, error = validate_mist_webhook_type("alarm")
        assert valid is True

    def test_valid_category_audit(self):
        valid, error = validate_mist_webhook_type("audit")
        assert valid is True

    def test_valid_specific_alarm_type(self):
        valid, error = validate_mist_webhook_type("ap_offline")
        assert valid is True

    def test_valid_specific_audit_type(self):
        valid, error = validate_mist_webhook_type("config_changed")
        assert valid is True

    def test_valid_device_events(self):
        valid, error = validate_mist_webhook_type("device-events")
        assert valid is True

    def test_valid_client_join(self):
        valid, error = validate_mist_webhook_type("client-join")
        assert valid is True

    def test_valid_zone(self):
        valid, error = validate_mist_webhook_type("zone")
        assert valid is True

    def test_invalid_webhook_type(self):
        valid, error = validate_mist_webhook_type("invalid_type")
        assert valid is False
        assert "Invalid Mist webhook type" in error

    def test_empty_webhook_type(self):
        valid, error = validate_mist_webhook_type("")
        assert valid is False
        assert "required" in error.lower()

    def test_all_defined_types_valid(self):
        # Test that all defined types are actually valid
        for category, events in MIST_WEBHOOK_TYPES.items():
            valid, _ = validate_mist_webhook_type(category)
            assert valid is True

            for event in events:
                valid, _ = validate_mist_webhook_type(event)
                assert valid is True


class TestValidateWebhookPayload:
    """Test webhook payload validation."""

    def test_valid_payload_all_fields(self):
        payload = {
            "event": {"type": "alarm"},
            "device": {"id": "123"}
        }
        required = ["event.type", "device.id"]
        valid, errors = validate_webhook_payload(payload, required)
        assert valid is True
        assert len(errors) == 0

    def test_invalid_payload_missing_field(self):
        payload = {
            "event": {"type": "alarm"}
        }
        required = ["event.type", "device.id"]
        valid, errors = validate_webhook_payload(payload, required)
        assert valid is False
        assert any("device.id" in error for error in errors)

    def test_valid_payload_no_required_fields(self):
        payload = {"event": "test"}
        valid, errors = validate_webhook_payload(payload, None)
        assert valid is True

    def test_invalid_payload_not_dict(self):
        payload = "not a dict"
        valid, errors = validate_webhook_payload(payload, [])
        assert valid is False
        assert any("dictionary" in error.lower() for error in errors)

    def test_nested_field_extraction(self):
        payload = {
            "level1": {
                "level2": {
                    "level3": "value"
                }
            }
        }
        required = ["level1.level2.level3"]
        valid, errors = validate_webhook_payload(payload, required)
        assert valid is True


class TestValidateMistAlarmPayload:
    """Test Mist alarm payload validation."""

    def test_valid_alarm_payload(self):
        payload = {
            "topic": "alarms",
            "events": [
                {"type": "ap_offline", "site_id": "123"}
            ]
        }
        valid, errors = validate_mist_alarm_payload(payload)
        assert valid is True
        assert len(errors) == 0

    def test_valid_audit_payload(self):
        payload = {
            "topic": "audits",
            "events": [
                {"type": "config_changed"}
            ]
        }
        valid, errors = validate_mist_alarm_payload(payload)
        assert valid is True

    def test_invalid_payload_missing_topic(self):
        payload = {
            "events": [{"type": "test"}]
        }
        valid, errors = validate_mist_alarm_payload(payload)
        assert valid is False
        assert any("topic" in error.lower() for error in errors)

    def test_invalid_payload_missing_events(self):
        payload = {
            "topic": "alarms"
        }
        valid, errors = validate_mist_alarm_payload(payload)
        assert valid is False
        assert any("events" in error.lower() for error in errors)

    def test_invalid_topic(self):
        payload = {
            "topic": "invalid_topic",
            "events": [{"type": "test"}]
        }
        valid, errors = validate_mist_alarm_payload(payload)
        assert valid is False
        assert any("topic" in error.lower() for error in errors)

    def test_invalid_events_not_list(self):
        payload = {
            "topic": "alarms",
            "events": "not a list"
        }
        valid, errors = validate_mist_alarm_payload(payload)
        assert valid is False
        assert any("list" in error.lower() for error in errors)

    def test_invalid_events_empty(self):
        payload = {
            "topic": "alarms",
            "events": []
        }
        valid, errors = validate_mist_alarm_payload(payload)
        assert valid is False
        assert any("empty" in error.lower() for error in errors)

    def test_invalid_event_not_dict(self):
        payload = {
            "topic": "alarms",
            "events": ["not a dict"]
        }
        valid, errors = validate_mist_alarm_payload(payload)
        assert valid is False
        assert any("dictionary" in error.lower() for error in errors)

    def test_event_missing_type(self):
        payload = {
            "topic": "alarms",
            "events": [{"no_type": "value"}]
        }
        valid, errors = validate_mist_alarm_payload(payload)
        assert valid is False
        assert any("type" in error.lower() for error in errors)

    def test_multiple_events(self):
        payload = {
            "topic": "alarms",
            "events": [
                {"type": "ap_offline"},
                {"type": "switch_offline"}
            ]
        }
        valid, errors = validate_mist_alarm_payload(payload)
        assert valid is True


class TestParseWebhookPayload:
    """Test webhook payload parsing."""

    def test_parse_json_payload(self):
        payload_body = b'{"event": "test", "value": 123}'
        valid, parsed, error = parse_webhook_payload(payload_body)

        assert valid is True
        assert error is None
        assert parsed["event"] == "test"
        assert parsed["value"] == 123

    def test_parse_json_array(self):
        payload_body = b'[1, 2, 3]'
        valid, parsed, error = parse_webhook_payload(payload_body)

        assert valid is True
        assert parsed == [1, 2, 3]

    def test_parse_complex_json(self):
        payload_body = b'{"nested": {"key": "value"}, "array": [1, 2, 3]}'
        valid, parsed, error = parse_webhook_payload(payload_body)

        assert valid is True
        assert parsed["nested"]["key"] == "value"
        assert parsed["array"] == [1, 2, 3]

    def test_parse_invalid_json(self):
        payload_body = b'{"invalid": json}'
        valid, parsed, error = parse_webhook_payload(payload_body)

        assert valid is False
        assert parsed is None
        assert "Invalid JSON" in error

    def test_parse_empty_payload(self):
        valid, parsed, error = parse_webhook_payload(b'')

        assert valid is False
        assert parsed is None
        assert "empty" in error.lower()

    def test_parse_with_content_type(self):
        payload_body = b'{"event": "test"}'
        valid, parsed, error = parse_webhook_payload(
            payload_body,
            content_type="application/json; charset=utf-8"
        )

        assert valid is True
        assert parsed["event"] == "test"

    def test_parse_unsupported_content_type(self):
        payload_body = b'<xml>test</xml>'
        valid, parsed, error = parse_webhook_payload(
            payload_body,
            content_type="application/xml"
        )

        assert valid is False
        assert "Unsupported content type" in error


class TestValidateWebhookRequest:
    """Test complete webhook request validation."""

    def test_valid_request_no_signature(self):
        payload_body = b'{"topic": "alarms", "events": [{"type": "test"}]}'
        valid, parsed, errors = validate_webhook_request(
            payload_body,
            validate_signature=False
        )

        assert valid is True
        assert len(errors) == 0
        assert parsed is not None
        assert parsed["topic"] == "alarms"

    def test_valid_request_with_signature(self):
        payload_body = b'{"topic": "alarms", "events": [{"type": "test"}]}'
        secret = "my_secret"
        signature = generate_webhook_signature(payload_body, secret)

        valid, parsed, errors = validate_webhook_request(
            payload_body,
            signature=signature,
            secret=secret,
            validate_signature=True
        )

        assert valid is True
        assert len(errors) == 0

    def test_valid_request_with_timestamp(self):
        payload_body = b'{"topic": "alarms", "events": [{"type": "test"}]}'
        timestamp = int(time.time())

        valid, parsed, errors = validate_webhook_request(
            payload_body,
            timestamp=timestamp,
            validate_signature=False
        )

        assert valid is True
        assert len(errors) == 0

    def test_invalid_request_bad_signature(self):
        payload_body = b'{"topic": "alarms", "events": [{"type": "test"}]}'
        secret = "my_secret"
        signature = "invalid_signature"

        valid, parsed, errors = validate_webhook_request(
            payload_body,
            signature=signature,
            secret=secret,
            validate_signature=True
        )

        assert valid is False
        assert len(errors) > 0
        assert any("signature" in error.lower() for error in errors)

    def test_invalid_request_old_timestamp(self):
        payload_body = b'{"topic": "alarms", "events": [{"type": "test"}]}'
        timestamp = int(time.time()) - 600  # 10 minutes ago

        valid, parsed, errors = validate_webhook_request(
            payload_body,
            timestamp=timestamp,
            max_age_seconds=300,
            validate_signature=False
        )

        assert valid is False
        assert any("timestamp" in error.lower() for error in errors)

    def test_invalid_request_bad_json(self):
        payload_body = b'invalid json'

        valid, parsed, errors = validate_webhook_request(
            payload_body,
            validate_signature=False
        )

        assert valid is False
        assert parsed is None
        assert len(errors) > 0

    def test_signature_validation_missing_secret(self):
        payload_body = b'{"topic": "alarms", "events": [{"type": "test"}]}'

        valid, parsed, errors = validate_webhook_request(
            payload_body,
            signature="some_signature",
            validate_signature=True
        )

        assert valid is False
        assert any("secret" in error.lower() for error in errors)

    def test_complete_validation(self):
        payload_body = b'{"topic": "alarms", "events": [{"type": "ap_offline"}]}'
        secret = "my_secret"
        signature = generate_webhook_signature(payload_body, secret)
        timestamp = int(time.time())

        valid, parsed, errors = validate_webhook_request(
            payload_body,
            signature=signature,
            secret=secret,
            timestamp=timestamp,
            validate_signature=True
        )

        assert valid is True
        assert len(errors) == 0
        assert parsed is not None
        assert parsed["topic"] == "alarms"
        assert parsed["events"][0]["type"] == "ap_offline"


class TestGetNestedValue:
    """Test get_nested_value helper."""

    def test_simple_field(self):
        data = {"name": "test"}
        assert get_nested_value(data, "name") == "test"

    def test_nested_field(self):
        data = {"event": {"device": {"name": "AP-01"}}}
        assert get_nested_value(data, "event.device.name") == "AP-01"

    def test_missing_field(self):
        data = {"name": "test"}
        assert get_nested_value(data, "missing") is None

    def test_empty_path(self):
        data = {"name": "test"}
        assert get_nested_value(data, "") is None


class TestMistWebhookTypes:
    """Test MIST_WEBHOOK_TYPES constant."""

    def test_has_alarm_category(self):
        assert "alarm" in MIST_WEBHOOK_TYPES

    def test_has_audit_category(self):
        assert "audit" in MIST_WEBHOOK_TYPES

    def test_has_device_events_category(self):
        assert "device-events" in MIST_WEBHOOK_TYPES

    def test_alarm_types_not_empty(self):
        assert len(MIST_WEBHOOK_TYPES["alarm"]) > 0

    def test_common_alarm_types_exist(self):
        alarm_types = MIST_WEBHOOK_TYPES["alarm"]
        assert "ap_offline" in alarm_types
        assert "switch_offline" in alarm_types
        assert "gateway_offline" in alarm_types

    def test_no_duplicate_types_in_category(self):
        for category, types in MIST_WEBHOOK_TYPES.items():
            assert len(types) == len(set(types)), f"Duplicates found in {category}"
