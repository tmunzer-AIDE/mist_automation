"""
MCP tool: get_configuration_object_schema — payload schema guidance for Mist config objects.

The tool derives JSON schema guidance directly from Mist OpenAPI request/response
contracts to avoid backup-coverage blind spots.
"""

from __future__ import annotations

import time
from typing import Annotated, Any, cast
from uuid import UUID

import httpx
import yaml
from fastmcp.exceptions import ToolError
from mcp.server.fastmcp import Context
from pydantic import Field

from app.config import settings
from app.modules.mcp_server.helpers import to_json
from app.modules.mcp_server.server import mcp
from app.modules.mcp_server.tools.digital_twin import Object_type
from app.modules.mcp_server.tools.utils import is_placeholder

_READONLY_PAYLOAD_FIELDS: set[str] = {
    "id",
    "org_id",
    "site_id",
    "created_time",
    "modified_time",
    "created_at",
    "updated_at",
}

_OBJECT_RESOURCE_OVERRIDES: dict[Object_type, str] = {
    # Mist uses /templates for WLAN template CRUD.
    Object_type.ORG_WLANTEMPLATES: "templates",
}

_OAS_CACHE_TTL_SECONDS = 600
_OAS_CACHE_STATE: dict[str, Any] = {"spec": None, "loaded_at": 0.0}


def _scope_and_resource(object_type: Object_type) -> tuple[str, str]:
    """Translate enum object_type into endpoint scope/resource parts."""
    value = object_type.value
    if value.startswith("org_"):
        scope = "org"
        resource = value[len("org_") :]
    elif value.startswith("site_"):
        scope = "site"
        resource = value[len("site_") :]
    else:
        raise ToolError(f"Unsupported object_type '{value}'")

    return scope, _OBJECT_RESOURCE_OVERRIDES.get(object_type, resource)


def _normalize_schema_inputs(
    *,
    object_type: Object_type,
    org_id: UUID | str,
    site_id: UUID | str | None,
    object_id: UUID | str | None,
    sample_size: int,
) -> dict[str, Any]:
    """Validate and normalize tool inputs for schema discovery."""
    org_id_value = str(org_id).strip()
    if not org_id_value:
        raise ToolError("org_id is required")
    if is_placeholder(org_id_value):
        raise ToolError("org_id must be a real UUID, not a placeholder")

    site_id_value = str(site_id).strip() if site_id is not None else None
    object_id_value = str(object_id).strip() if object_id is not None else None

    scope, resource = _scope_and_resource(object_type)
    if scope == "site" and not site_id_value:
        raise ToolError(f"site_id is required when object_type='{object_type.value}'")
    if scope == "org" and site_id_value:
        raise ToolError(f"site_id is not supported when object_type='{object_type.value}'")

    if site_id_value and is_placeholder(site_id_value):
        raise ToolError("site_id must be a real UUID, not a placeholder")
    if object_id_value and is_placeholder(object_id_value):
        raise ToolError("object_id must be a real UUID, not a placeholder")

    if sample_size < 1 or sample_size > 20:
        raise ToolError("sample_size must be between 1 and 20")

    return {
        "object_type": object_type.value,
        "scope": scope,
        "resource": resource,
        "org_id": org_id_value,
        "site_id": site_id_value,
        "object_id": object_id_value,
        "sample_size": sample_size,
    }


def _is_path_param(segment: str) -> bool:
    """Return True when a path segment is an OpenAPI path parameter."""
    return segment.startswith("{") and segment.endswith("}") and len(segment) >= 3


def _split_path(path: str) -> list[str]:
    """Split a URI path into non-empty segments."""
    return [segment for segment in path.strip("/").split("/") if segment]


def _find_oas_paths(*, spec: dict[str, Any], scope: str, resource: str) -> dict[str, str | None]:
    """Find collection/detail path templates for the requested scope/resource."""
    scope_segment = "orgs" if scope == "org" else "sites"
    collection_path: str | None = None
    detail_path: str | None = None

    for path_template in spec.get("paths", {}):
        segments = _split_path(path_template)
        if len(segments) < 5:
            continue
        if segments[0] != "api" or segments[1] != "v1" or segments[2] != scope_segment:
            continue
        if not _is_path_param(segments[3]):
            continue
        if segments[4] != resource:
            continue

        if len(segments) == 5:
            collection_path = path_template
            continue

        if len(segments) == 6 and _is_path_param(segments[5]):
            detail_path = path_template

    return {"collection": collection_path, "detail": detail_path}


def _resolve_oas_ref(ref: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Resolve a local OpenAPI $ref path into a concrete object."""
    if not ref.startswith("#/"):
        return {}

    resolved: Any = spec
    for part in ref.lstrip("#/").split("/"):
        if not isinstance(resolved, dict):
            return {}
        resolved = resolved.get(part)

    return resolved if isinstance(resolved, dict) else {}


def _resolve_schema_refs(schema: Any, spec: dict[str, Any], *, depth: int = 0) -> Any:
    """Resolve nested OpenAPI $ref references in request/response schemas."""
    if depth > 20:
        return schema
    if not isinstance(schema, dict):
        return schema

    if "$ref" in schema:
        resolved = _resolve_oas_ref(str(schema["$ref"]), spec)
        return _resolve_schema_refs(resolved, spec, depth=depth + 1)

    result = dict(schema)

    if isinstance(result.get("properties"), dict):
        result["properties"] = {
            key: _resolve_schema_refs(value, spec, depth=depth + 1)
            for key, value in result["properties"].items()
        }

    if "items" in result:
        result["items"] = _resolve_schema_refs(result["items"], spec, depth=depth + 1)

    for keyword in ("allOf", "anyOf", "oneOf"):
        if isinstance(result.get(keyword), list):
            result[keyword] = [_resolve_schema_refs(item, spec, depth=depth + 1) for item in result[keyword]]

    if isinstance(result.get("additionalProperties"), dict):
        result["additionalProperties"] = _resolve_schema_refs(
            result["additionalProperties"], spec, depth=depth + 1
        )

    return result


def _merge_allof_object_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Flatten object-like allOf composition into a single object schema when safe."""
    all_of = schema.get("allOf")
    if not isinstance(all_of, list) or not all_of:
        return schema

    merged_properties: dict[str, Any] = {}
    merged_required: list[str] = []
    non_object_parts: list[Any] = []

    for part in all_of:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type in (None, "object") or "properties" in part:
            if isinstance(part.get("properties"), dict):
                merged_properties.update(part["properties"])
            if isinstance(part.get("required"), list):
                merged_required.extend(str(item) for item in part["required"])
        else:
            non_object_parts.append(part)

    flattened = {k: v for k, v in schema.items() if k != "allOf"}

    if merged_properties:
        existing = flattened.get("properties", {}) if isinstance(flattened.get("properties"), dict) else {}
        flattened["type"] = "object"
        flattened["properties"] = {**merged_properties, **existing}

    existing_required = flattened.get("required", []) if isinstance(flattened.get("required"), list) else []
    if merged_required or existing_required:
        flattened["required"] = list(dict.fromkeys([*merged_required, *existing_required]))

    if non_object_parts:
        flattened["anyOf"] = non_object_parts

    return flattened


def _select_json_media(content: dict[str, Any]) -> dict[str, Any] | None:
    """Choose the most appropriate JSON media definition from content entries."""
    if not isinstance(content, dict):
        return None

    if isinstance(content.get("application/json"), dict):
        return content["application/json"]

    for media_type, media_schema in content.items():
        if "json" in str(media_type).lower() and isinstance(media_schema, dict):
            return media_schema

    return None


def _extract_media_schema_and_example(
    operation: dict[str, Any],
    spec: dict[str, Any],
    *,
    request: bool,
) -> tuple[dict[str, Any] | None, Any | None]:
    """Extract resolved schema/example from requestBody or response content."""
    target: dict[str, Any] | None = None

    if request:
        raw_request = operation.get("requestBody")
        if not raw_request:
            return None, None
        resolved_request = _resolve_schema_refs(raw_request, spec)
        if isinstance(resolved_request, dict):
            target = resolved_request
    else:
        responses = operation.get("responses", {})
        for code in ("200", "201", "202"):
            candidate = responses.get(code)
            if not isinstance(candidate, dict):
                continue
            resolved_response = _resolve_schema_refs(candidate, spec)
            if isinstance(resolved_response, dict):
                target = resolved_response
                break

    if not isinstance(target, dict):
        return None, None

    media = _select_json_media(target.get("content", {}))
    if not isinstance(media, dict):
        return None, None

    schema = media.get("schema")
    resolved_schema = _resolve_schema_refs(schema, spec) if isinstance(schema, dict) else None
    if isinstance(resolved_schema, dict):
        resolved_schema = _merge_allof_object_schema(resolved_schema)

    example: Any | None = None
    if media.get("example") is not None:
        example = media.get("example")
    elif isinstance(media.get("examples"), dict):
        for candidate in media["examples"].values():
            if isinstance(candidate, dict) and candidate.get("value") is not None:
                example = candidate.get("value")
                break

    if example is None and isinstance(resolved_schema, dict):
        if resolved_schema.get("example") is not None:
            example = resolved_schema.get("example")
        elif isinstance(resolved_schema.get("examples"), list) and resolved_schema["examples"]:
            example = resolved_schema["examples"][0]

    return resolved_schema, example


def _pick_operation_schema(
    *,
    spec: dict[str, Any],
    collection_path: str | None,
    detail_path: str | None,
    object_id_present: bool,
) -> tuple[dict[str, Any], str, str, str, Any | None]:
    """Select the best matching OAS operation schema for payload guidance."""
    paths = spec.get("paths", {})

    preference: list[tuple[str | None, str, str]]
    if object_id_present:
        preference = [
            (detail_path, "put", "request"),
            (detail_path, "patch", "request"),
            (collection_path, "post", "request"),
            (detail_path, "get", "response"),
            (collection_path, "get", "response"),
        ]
    else:
        preference = [
            (collection_path, "post", "request"),
            (collection_path, "put", "request"),
            (collection_path, "patch", "request"),
            (detail_path, "put", "request"),
            (detail_path, "patch", "request"),
            (collection_path, "get", "response"),
            (detail_path, "get", "response"),
        ]

    for path_template, method, source in preference:
        if not path_template:
            continue

        path_item = paths.get(path_template)
        if not isinstance(path_item, dict):
            continue

        operation = path_item.get(method)
        if not isinstance(operation, dict):
            continue

        schema, example = _extract_media_schema_and_example(operation, spec, request=(source == "request"))
        if isinstance(schema, dict):
            return schema, path_template, method.upper(), source, example

    raise ToolError(
        "No matching Mist OAS schema was found for this object type. "
        "The endpoint may be unsupported or missing request/response schema definitions in OAS."
    )


def _choose_primary_type(type_value: Any) -> str:
    """Select a concrete JSON schema type from string or union type entries."""
    if isinstance(type_value, str):
        return type_value
    if isinstance(type_value, list):
        for item in type_value:
            if item != "null":
                return str(item)
        if type_value:
            return str(type_value[0])
    return "object"


def _example_from_schema(schema: dict[str, Any], *, depth: int = 0) -> Any:
    """Generate a lightweight sample payload from a JSON schema."""
    if depth > 8 or not isinstance(schema, dict):
        return None

    if schema.get("example") is not None:
        return schema["example"]
    if isinstance(schema.get("examples"), list) and schema["examples"]:
        return schema["examples"][0]
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        return schema["enum"][0]

    schema_type = _choose_primary_type(schema.get("type"))

    if schema_type == "object":
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return {}

        required = schema.get("required", []) if isinstance(schema.get("required"), list) else []
        required_set = set(required)

        result: dict[str, Any] = {}

        for key in required:
            value = _example_from_schema(properties.get(key, {}), depth=depth + 1)
            if value is not None:
                result[key] = value

        for key, value_schema in properties.items():
            if key in required_set:
                continue
            if len(result) >= max(len(required), 3):
                break
            value = _example_from_schema(value_schema, depth=depth + 1)
            if value is not None:
                result[key] = value

        return result

    if schema_type == "array":
        items_schema = schema.get("items", {})
        example_item = _example_from_schema(items_schema, depth=depth + 1)
        return [example_item] if example_item is not None else []

    if schema_type == "string":
        fmt = str(schema.get("format", "")).lower()
        if fmt == "uuid":
            return "00000000-0000-0000-0000-000000000000"
        if fmt == "date-time":
            return "2024-01-01T00:00:00Z"
        if fmt == "email":
            return "user@example.com"
        return "example"

    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 1.0
    if schema_type == "boolean":
        return True

    return None


def _compact_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a token-efficient summary of an object JSON schema."""
    required_fields = set(schema.get("required", []))
    properties = schema.get("properties", {})

    compact_required: dict[str, Any] = {}
    compact_optional: dict[str, Any] = {}

    for field_name, field_schema in properties.items():
        if field_name in required_fields:
            compact_required[field_name] = field_schema
            continue

        compact_entry: dict[str, Any] = {}
        if isinstance(field_schema, dict):
            if field_schema.get("type") is not None:
                compact_entry["type"] = field_schema["type"]
            if field_schema.get("examples"):
                compact_entry["examples"] = field_schema["examples"][:1]
        compact_optional[field_name] = compact_entry or {"type": "object"}

    compact = {k: v for k, v in schema.items() if k != "properties"}
    compact["properties"] = {**compact_required, **compact_optional}

    optional_count = len(compact_optional)
    if optional_count:
        compact["x-hint"] = (
            f"{optional_count} optional field(s) shown in compact form "
            "(type + optional example only). Pass verbose=True for full inferred schema."
        )

    return compact


def _sanitize_payload_example(example: dict[str, Any] | None) -> dict[str, Any]:
    """Remove common read-only fields from payload examples."""
    if not example:
        return {}
    return {k: v for k, v in example.items() if k not in _READONLY_PAYLOAD_FIELDS}


async def _load_mist_oas_spec() -> dict[str, Any]:
    """Load and cache the Mist OpenAPI document configured for this backend."""
    now = time.time()
    cached_spec = _OAS_CACHE_STATE.get("spec")
    cached_at = _OAS_CACHE_STATE.get("loaded_at")
    if isinstance(cached_spec, dict) and isinstance(cached_at, (int, float)):
        if now - float(cached_at) < _OAS_CACHE_TTL_SECONDS:
            return cast(dict[str, Any], cached_spec)

    oas_url = (settings.mist_oas_url or "").strip()
    if not oas_url:
        raise ToolError("Mist OAS URL is not configured (settings.mist_oas_url)")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(oas_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ToolError("Failed to fetch Mist OAS document from configured URL") from exc

    try:
        spec = yaml.safe_load(response.text)
    except Exception as exc:
        raise ToolError("Failed to parse Mist OAS document") from exc

    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        raise ToolError("Mist OAS document is invalid: missing 'paths' object")

    _OAS_CACHE_STATE["spec"] = spec
    _OAS_CACHE_STATE["loaded_at"] = now
    return spec


@mcp.tool()
async def get_configuration_object_schema(
    ctx: Context,
    object_type: Annotated[
        Object_type,
        Field(
            description=(
                "Configuration object type to model. Use the same enum values expected by digital_twin "
                "simulate flows (org_* and site_*)."
            )
        ),
    ],
    org_id: Annotated[
        UUID,
        Field(description="Mist organization UUID."),
    ],
    site_id: Annotated[
        UUID | None,
        Field(
            default=None,
            description=(
                "Site UUID for site-scoped object types. Required when object_type starts with 'site_'."
            ),
        ),
    ] = None,
    object_id: Annotated[
        UUID | None,
        Field(
            default=None,
            description=(
                "Optional object UUID to focus schema guidance on one specific object instance."
            ),
        ),
    ] = None,
    verbose: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "When false (default), optional fields are compacted to reduce token usage. "
                "Set true to return the full resolved schema tree."
            ),
        ),
    ] = False,
    sample_size: Annotated[
        int,
        Field(
            default=5,
            ge=1,
            le=20,
            description=(
                "Reserved for backward compatibility with older sample-based behavior. "
                "Ignored when using OAS-derived schemas."
            ),
        ),
    ] = 5,
) -> str:
    """Infer payload schema for a Mist configuration object type.

    This tool helps LLMs build safer create/update payloads before calling
    digital_twin(action='simulate'). It returns:
    - OAS-derived JSON schema (compact by default)
    - sanitized example payload (read-only keys removed)
    - source metadata (request/response operation and path template)
    """
    _ = ctx

    validated = _normalize_schema_inputs(
        object_type=object_type,
        org_id=org_id,
        site_id=site_id,
        object_id=object_id,
        sample_size=sample_size,
    )

    spec = await _load_mist_oas_spec()
    oas_paths = _find_oas_paths(spec=spec, scope=validated["scope"], resource=validated["resource"])

    if not oas_paths["collection"] and not oas_paths["detail"]:
        raise ToolError(
            "No matching endpoint path was found in Mist OAS for this object_type. "
            "Verify the object_type mapping or Mist OAS coverage."
        )

    schema, path_template, method, schema_source, schema_example = _pick_operation_schema(
        spec=spec,
        collection_path=oas_paths["collection"],
        detail_path=oas_paths["detail"],
        object_id_present=bool(validated["object_id"]),
    )

    if schema.get("type") != "object":
        schema = {"type": "object", "properties": {"value": schema}}

    response_schema = schema if verbose else _compact_schema(schema)
    generated_example = schema_example if schema_example is not None else _example_from_schema(schema)
    example_payload = _sanitize_payload_example(generated_example if isinstance(generated_example, dict) else None)

    return to_json(
        {
            "object_type": validated["object_type"],
            "scope": validated["scope"],
            "resource": validated["resource"],
            "org_id": validated["org_id"],
            "site_id": validated["site_id"],
            "object_id": validated["object_id"],
            "source": "oas",
            "schema_source": schema_source,
            "operation": {"method": method, "path_template": path_template},
            "schema": response_schema,
            "example_payload": example_payload,
            "usage_notes": [
                "Schema is derived from Mist OAS contracts for the matched endpoint operation.",
                "Use example_payload as a starting point for create/update payloads.",
                "Keep required fields from schema.required when crafting payloads.",
                "After editing payload, run digital_twin(action='simulate', ...) before approve.",
            ],
        }
    )
