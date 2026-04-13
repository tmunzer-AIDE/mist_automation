"""Unit tests for MCP get_configuration_object_schema helper logic."""

import pytest
from fastmcp.exceptions import ToolError

from app.modules.mcp_server.tools.configuration_schema import (
    _build_field_index,
    _compact_schema,
    _example_from_schema,
    _find_oas_paths,
    _flatten_schema_fields,
    _normalize_schema_inputs,
    _pick_operation_schema,
    _sanitize_payload_example,
    _score_entry,
    _tokenize_query,
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
            )

    def test_org_object_rejects_site_id(self):
        with pytest.raises(ToolError, match="site_id is not supported"):
            _normalize_schema_inputs(
                object_type=Object_type.ORG_WLANS,
                org_id="8aa21779-1178-4357-b3e0-42c02b93b870",
                site_id="2818e386-8dec-4562-9ede-5b8a0fbbdc71",
                object_id=None,
            )

    def test_wlan_template_maps_to_templates_resource(self):
        validated = _normalize_schema_inputs(
            object_type=Object_type.ORG_WLANTEMPLATES,
            org_id="8aa21779-1178-4357-b3e0-42c02b93b870",
            site_id=None,
            object_id=None,
        )
        assert validated["resource"] == "templates"

    def test_site_info_singleton_accepts_no_object_id(self):
        # site_info is a singleton — must accept calls with no object_id.
        validated = _normalize_schema_inputs(
            object_type=Object_type.SITE_INFO,
            org_id="8aa21779-1178-4357-b3e0-42c02b93b870",
            site_id="2818e386-8dec-4562-9ede-5b8a0fbbdc71",
            object_id=None,
        )
        assert validated["object_type"] == "site_info"
        assert validated["scope"] == "site"

    def test_site_info_singleton_rejects_object_id(self):
        with pytest.raises(ToolError, match="object_id must not be provided"):
            _normalize_schema_inputs(
                object_type=Object_type.SITE_INFO,
                org_id="8aa21779-1178-4357-b3e0-42c02b93b870",
                site_id="2818e386-8dec-4562-9ede-5b8a0fbbdc71",
                object_id="3c7f19c2-4c16-4f4c-9f1b-8f5338107bd7",
            )

    def test_site_setting_singleton_rejects_object_id(self):
        with pytest.raises(ToolError, match="object_id must not be provided"):
            _normalize_schema_inputs(
                object_type=Object_type.SITE_SETTING,
                org_id="8aa21779-1178-4357-b3e0-42c02b93b870",
                site_id="2818e386-8dec-4562-9ede-5b8a0fbbdc71",
                object_id="3c7f19c2-4c16-4f4c-9f1b-8f5338107bd7",
            )


@pytest.mark.unit
class TestConfigurationSchemaInference:
    def test_finds_collection_and_detail_paths(self):
        paths = _find_oas_paths(spec=_MOCK_OAS_SPEC, scope="org", resource="wlans")

        assert paths["collection"] == "/api/v1/orgs/{org_id}/wlans"
        assert paths["detail"] == "/api/v1/orgs/{org_id}/wlans/{wlan_id}"

    def test_find_oas_paths_singleton_override_site_info(self):
        # Singleton shortcut returns the explicit URL template without walking the spec.
        # For site_info the 4-segment path is invisible to the generic walker.
        result = _find_oas_paths(
            spec={"paths": {}},
            scope="site",
            resource="info",
            object_type=Object_type.SITE_INFO,
        )
        assert result == {"collection": "/api/v1/sites/{site_id}", "detail": None}

    def test_find_oas_paths_singleton_override_site_setting(self):
        result = _find_oas_paths(
            spec={"paths": {}},
            scope="site",
            resource="setting",
            object_type=Object_type.SITE_SETTING,
        )
        assert result == {"collection": "/api/v1/sites/{site_id}/setting", "detail": None}

    def test_find_oas_paths_generic_walker_unaffected_for_non_singletons(self):
        # Non-singleton object_type still hits the walker and finds collection/detail.
        paths = _find_oas_paths(
            spec=_MOCK_OAS_SPEC,
            scope="org",
            resource="wlans",
            object_type=Object_type.ORG_WLANS,
        )
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


@pytest.mark.unit
class TestFieldIndexHelpers:
    """Unit tests for the reverse-field-index helpers backing find_configuration_field."""

    def test_tokenize_query_splits_on_non_alpha(self):
        assert _tokenize_query("port usage profile") == ["port", "usage", "profile"]
        assert _tokenize_query("port-config.ge-0/0/9") == ["port", "config", "ge", "0", "9"]
        assert _tokenize_query("  ") == []
        # de-dup preserves order
        assert _tokenize_query("vlan vlan id") == ["vlan", "id"]

    def test_tokenize_query_rejects_empty_via_caller(self):
        # The tool itself raises ToolError on empty query; the tokenizer just returns [].
        assert _tokenize_query("") == []

    def test_tokenize_query_splits_compound_suffix(self):
        # Long compound tokens ending in a known root split into head + root while
        # keeping the original token so exact-name matches still score.
        assert _tokenize_query("networktemplate") == ["networktemplate", "network", "template"]
        assert _tokenize_query("rftemplate") == ["rftemplate", "rf", "template"]
        assert _tokenize_query("deviceprofile") == ["deviceprofile", "device", "profile"]

    def test_tokenize_query_short_tokens_unchanged(self):
        # Under 8 chars is too short to reliably split — 'ssid' / 'dns' stay intact.
        assert _tokenize_query("ssid dns") == ["ssid", "dns"]
        # 'rftemplate' is long enough, but the raw 'rf' alone is kept as-is.
        assert _tokenize_query("rf") == ["rf"]

    def test_tokenize_query_handles_mixed_multi_compound(self):
        # Multiple compound tokens in one query should each expand.
        result = _tokenize_query("rftemplate deviceprofile")
        assert "rftemplate" in result
        assert "rf" in result
        assert "template" in result
        assert "deviceprofile" in result
        assert "device" in result
        assert "profile" in result

    def test_tokenize_query_compound_preserves_dedup(self):
        # When the query already contains both compound and head, the order is preserved
        # and the duplicate is dropped.
        result = _tokenize_query("network networktemplate")
        assert result[0] == "network"
        assert "networktemplate" in result
        assert "template" in result
        # 'network' must not appear twice.
        assert result.count("network") == 1

    def test_flatten_schema_fields_walks_properties(self):
        schema = {
            "type": "object",
            "properties": {
                "ssid": {"type": "string", "description": "Network name"},
                "enabled": {"type": "boolean"},
            },
        }

        entries = _flatten_schema_fields(schema, object_type_value="org_wlans")
        paths = {e["path"] for e in entries}

        assert paths == {"ssid", "enabled"}
        assert next(e for e in entries if e["path"] == "ssid")["description"] == "Network name"
        assert next(e for e in entries if e["path"] == "ssid")["object_type"] == "org_wlans"

    def test_flatten_schema_fields_handles_additional_properties(self):
        schema = {
            "type": "object",
            "properties": {
                "port_config": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "usage": {
                                "type": "string",
                                "enum": ["ap", "disabled", "uplink"],
                                "description": "Port usage profile reference",
                            },
                        },
                    },
                },
            },
        }

        entries = _flatten_schema_fields(schema, object_type_value="site_devices")
        paths = {e["path"] for e in entries}

        assert "port_config" in paths
        assert "port_config.*.usage" in paths
        usage_entry = next(e for e in entries if e["path"] == "port_config.*.usage")
        assert usage_entry["enum"] == ["ap", "disabled", "uplink"]
        assert usage_entry["type"] == "string"

    def test_flatten_schema_fields_handles_array_items(self):
        schema = {
            "type": "object",
            "properties": {
                "servers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ip": {"type": "string"},
                        },
                    },
                }
            },
        }

        entries = _flatten_schema_fields(schema, object_type_value="site_settings")
        paths = {e["path"] for e in entries}

        assert "servers" in paths
        assert "servers[].ip" in paths

    def test_score_entry_exact_field_name_beats_substring(self):
        usage_entry = {
            "object_type": "site_devices",
            "path": "port_config.*.usage",
            "field_name": "usage",
            "description": "Port usage profile reference",
            "type": "string",
            "enum": ["ap", "disabled"],
        }
        name_entry = {
            "object_type": "site_devices",
            "path": "port_config.*.name",
            "field_name": "name",
            "description": "Port name",
            "type": "string",
            "enum": None,
        }

        terms = _tokenize_query("port usage")

        usage_score, usage_hits = _score_entry(usage_entry, terms)
        name_score, name_hits = _score_entry(name_entry, terms)

        # Usage entry hits both terms (port in path/desc, usage exact on field) — full AND bonus.
        assert usage_hits == 2
        assert usage_score > name_score

    def test_score_entry_all_terms_bonus_dominates(self):
        # Entry hit by ALL query terms should beat a generic entry with only one exact hit.
        usage_entry = {
            "object_type": "site_devices",
            "path": "port_config.*.usage",
            "field_name": "usage",
            "description": "Port usage profile reference",
            "type": "string",
            "enum": ["ap", "disabled"],
        }
        generic_port_entry = {
            "object_type": "org_networktemplates",
            "path": "switch_matching.rules[].radius.acct_servers[].port",
            "field_name": "port",
            "description": "Radius Auth Port, value from 1 to 65535, default is 1813",
            "type": "integer",
            "enum": None,
        }

        terms = _tokenize_query("port profile switch")

        usage_score, usage_hits = _score_entry(usage_entry, terms)
        generic_score, generic_hits = _score_entry(generic_port_entry, terms)

        # 'port' and 'profile' both appear in usage entry description; 'switch' doesn't.
        # 'port' matches field_name exactly for generic, 'switch' matches path; 'profile' doesn't.
        # Both hit 2 terms, but usage has the more specific match on the description level.
        assert usage_hits == 2
        assert generic_hits == 2
        # Usage wins because it has multiple hits on the port token (field+path+desc) plus profile in desc.
        assert usage_score > generic_score

    def test_score_entry_matches_enum_values(self):
        entry = {
            "object_type": "site_devices",
            "path": "port_config.*.usage",
            "field_name": "usage",
            "description": "",
            "type": "string",
            "enum": ["ap", "disabled", "uplink"],
        }

        score, hits = _score_entry(entry, _tokenize_query("disabled"))
        assert score > 0
        assert hits == 1

        score_miss, hits_miss = _score_entry(entry, _tokenize_query("completely_unrelated"))
        assert score_miss == 0
        assert hits_miss == 0

    def test_score_entry_dampens_short_exact_matches(self):
        # A 4-char exact match ('name') should get a dampened bonus compared to a longer one.
        short_entry = {
            "object_type": "org_wlans",
            "path": "name",
            "field_name": "name",
            "description": "",
            "type": "string",
            "enum": None,
        }
        long_entry = {
            "object_type": "org_wlans",
            "path": "deviceprofile_id",
            "field_name": "deviceprofile_id",
            "description": "",
            "type": "string",
            "enum": None,
        }

        short_score, _ = _score_entry(short_entry, ["name"])
        long_score, _ = _score_entry(long_entry, ["deviceprofile_id"])

        # Short exact gets 12, long exact gets 18.
        assert short_score < long_score

    def test_build_field_index_uses_mock_oas(self, monkeypatch):
        """Exercise _build_field_index end-to-end against a minimal OAS spec."""
        # Narrow the enum universe so the build stays fast and deterministic.
        from app.modules.mcp_server.tools import configuration_schema as mod
        from app.modules.mcp_server.tools.digital_twin import Object_type as real_object_type

        class _FakeObjectType:
            def __init__(self, value: str):
                self.value = value

        fake_enum = [_FakeObjectType("org_wlans")]

        # Iterating Object_type in the real module should be patchable — the module
        # references Object_type via `for object_type in Object_type:`.
        monkeypatch.setattr(mod, "Object_type", fake_enum)

        spec = {
            "paths": {
                "/api/v1/orgs/{org_id}/wlans": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "ssid": {"type": "string", "description": "Network name"},
                                            "vlan_id": {"type": "integer"},
                                            "enabled": {"type": "boolean"},
                                        },
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        # Monkeypatch the _scope_and_resource helper to map our fake enum to the mock path.
        original_scope_fn = mod._scope_and_resource

        def fake_scope_and_resource(object_type):
            if getattr(object_type, "value", None) == "org_wlans":
                return ("org", "wlans")
            return original_scope_fn(object_type)

        monkeypatch.setattr(mod, "_scope_and_resource", fake_scope_and_resource)

        # Also patch Object_type reference inside the enum value lookups (not needed — we
        # don't touch the real enum from _build_field_index except iteration).
        # Restore the real enum after the test runs (monkeypatch.setattr handles teardown).
        del real_object_type  # silence unused warning

        index = _build_field_index(spec)
        paths = {e["path"] for e in index if e["object_type"] == "org_wlans"}
        assert {"ssid", "vlan_id", "enabled"} <= paths
