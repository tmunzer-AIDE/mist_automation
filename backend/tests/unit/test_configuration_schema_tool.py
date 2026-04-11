"""Unit tests for MCP get_configuration_object_schema helper logic."""

import pytest
from fastmcp.exceptions import ToolError

from app.modules.mcp_server.tools.configuration_schema import (
    _compact_schema,
    _example_from_schema,
    _find_oas_paths,
    _normalize_schema_inputs,
    _pick_operation_schema,
    _sanitize_payload_example,
)
from app.modules.mcp_server.tools.digital_twin import Object_type


_MOCK_OAS_SPEC = {
    "paths": {
        "/api/v1/orgs/{org_id}/wlans": {
            "post": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name"],
                                "properties": {
                                    "name": {"type": "string"},
                                    "enabled": {"type": "boolean"},
                                },
                                "example": {"name": "Guest", "enabled": True},
                            }
                        }
                    }
                }
            },
            "get": {
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                        },
                                    },
                                }
                            }
                        }
                    }
                }
            },
        },
        "/api/v1/orgs/{org_id}/wlans/{wlan_id}": {
            "put": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name"],
                                "properties": {
                                    "name": {"type": "string"},
                                    "vlan_id": {"type": "integer"},
                                },
                            }
                        }
                    }
                }
            }
        },
    }
}


@pytest.mark.unit
class TestConfigurationSchemaToolValidation:
    def test_site_object_requires_site_id(self):
        with pytest.raises(ToolError, match="site_id is required"):
            _normalize_schema_inputs(
                object_type=Object_type.SITE_WLANS,
                org_id="8aa21779-1178-4357-b3e0-42c02b93b870",
                site_id=None,
                object_id=None,
                sample_size=5,
            )

    def test_org_object_rejects_site_id(self):
        with pytest.raises(ToolError, match="site_id is not supported"):
            _normalize_schema_inputs(
                object_type=Object_type.ORG_WLANS,
                org_id="8aa21779-1178-4357-b3e0-42c02b93b870",
                site_id="2818e386-8dec-4562-9ede-5b8a0fbbdc71",
                object_id=None,
                sample_size=5,
            )

    def test_wlan_template_maps_to_templates_resource(self):
        validated = _normalize_schema_inputs(
            object_type=Object_type.ORG_WLANTEMPLATES,
            org_id="8aa21779-1178-4357-b3e0-42c02b93b870",
            site_id=None,
            object_id=None,
            sample_size=5,
        )
        assert validated["resource"] == "templates"


@pytest.mark.unit
class TestConfigurationSchemaInference:
    def test_finds_collection_and_detail_paths(self):
        paths = _find_oas_paths(spec=_MOCK_OAS_SPEC, scope="org", resource="wlans")

        assert paths["collection"] == "/api/v1/orgs/{org_id}/wlans"
        assert paths["detail"] == "/api/v1/orgs/{org_id}/wlans/{wlan_id}"

    def test_pick_operation_schema_prefers_collection_post_without_object_id(self):
        schema, path_template, method, source, example = _pick_operation_schema(
            spec=_MOCK_OAS_SPEC,
            collection_path="/api/v1/orgs/{org_id}/wlans",
            detail_path="/api/v1/orgs/{org_id}/wlans/{wlan_id}",
            object_id_present=False,
        )

        assert path_template == "/api/v1/orgs/{org_id}/wlans"
        assert method == "POST"
        assert source == "request"
        assert schema["type"] == "object"
        assert "name" in schema["required"]
        assert isinstance(example, dict)
        assert example["name"] == "Guest"

    def test_pick_operation_schema_prefers_detail_put_with_object_id(self):
        schema, path_template, method, source, _ = _pick_operation_schema(
            spec=_MOCK_OAS_SPEC,
            collection_path="/api/v1/orgs/{org_id}/wlans",
            detail_path="/api/v1/orgs/{org_id}/wlans/{wlan_id}",
            object_id_present=True,
        )

        assert path_template == "/api/v1/orgs/{org_id}/wlans/{wlan_id}"
        assert method == "PUT"
        assert source == "request"
        assert "vlan_id" in schema["properties"]

    def test_compact_schema_preserves_required_optional_compacted(self):
        full = {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "examples": ["Guest"]},
                "enabled": {"type": "boolean", "examples": [True]},
            },
        }

        compact = _compact_schema(full)

        assert compact["properties"]["name"]["examples"] == ["Guest"]
        assert compact["properties"]["enabled"] == {"type": "boolean", "examples": [True]}
        assert "x-hint" in compact

    def test_example_from_schema_includes_required_fields(self):
        schema = {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "enabled": {"type": "boolean"},
            },
        }

        example = _example_from_schema(schema)

        assert isinstance(example, dict)
        assert "name" in example

    def test_sanitize_payload_example_removes_readonly_fields(self):
        payload = _sanitize_payload_example(
            {
                "id": "abc",
                "org_id": "org",
                "site_id": "site",
                "name": "Guest",
                "enabled": True,
            }
        )

        assert "id" not in payload
        assert "org_id" not in payload
        assert "site_id" not in payload
        assert payload["name"] == "Guest"
