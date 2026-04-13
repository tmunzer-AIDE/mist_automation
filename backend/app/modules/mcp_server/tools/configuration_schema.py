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
from pydantic import Field

from app.config import settings
from app.modules.mcp_server.helpers import to_json
from app.modules.mcp_server.server import mcp
from app.modules.mcp_server.tools.digital_twin import (
    _ORG_OBJECT_TYPE_VALUES,
    _SINGLETON_OAS_PATHS,
    _SITE_OBJECT_TYPE_VALUES,
    Object_type,
)
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

# Reverse-field index cache, tied to the OAS spec identity.
_FIELD_INDEX_CACHE: dict[str, Any] = {"spec_id": None, "entries": []}


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

    if object_type in _SINGLETON_OAS_PATHS and object_id_value:
        raise ToolError(
            f"object_id must not be provided for singleton object_type='{object_type.value}' — "
            "the site_id is the identifier"
        )

    if site_id_value and is_placeholder(site_id_value):
        raise ToolError("site_id must be a real UUID, not a placeholder")
    if object_id_value and is_placeholder(object_id_value):
        raise ToolError("object_id must be a real UUID, not a placeholder")

    return {
        "object_type": object_type.value,
        "scope": scope,
        "resource": resource,
        "org_id": org_id_value,
        "site_id": site_id_value,
        "object_id": object_id_value,
    }


def _is_path_param(segment: str) -> bool:
    """Return True when a path segment is an OpenAPI path parameter."""
    return segment.startswith("{") and segment.endswith("}") and len(segment) >= 3


def _split_path(path: str) -> list[str]:
    """Split a URI path into non-empty segments."""
    return [segment for segment in path.strip("/").split("/") if segment]


def _find_oas_paths(
    *,
    spec: dict[str, Any],
    scope: str,
    resource: str,
    object_type: Object_type | None = None,
) -> dict[str, str | None]:
    """Find collection/detail path templates for the requested scope/resource.

    Singleton object_types (site_info, site_setting) short-circuit the generic
    walker via `_SINGLETON_OAS_PATHS`. For site_info the 4-segment path
    `/api/v1/sites/{site_id}` is invisible to the walker (which requires 5+
    segments), so the override is the only way to reach it.
    """
    if object_type is not None and object_type in _SINGLETON_OAS_PATHS:
        return {"collection": _SINGLETON_OAS_PATHS[object_type], "detail": None}

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


def _extract_discriminator_info(schema: dict[str, Any]) -> dict[str, Any] | None:
    """Return discriminator info for a schema that uses oneOf + discriminator, else None.

    The returned dict has:
    - property_name: the discriminator property (e.g. 'type')
    - variants: dict of {variant_name: variant_schema} resolved from mapping or inferred from oneOf
    """
    if not isinstance(schema, dict):
        return None

    discriminator = schema.get("discriminator")
    one_of = schema.get("oneOf")
    if not isinstance(discriminator, dict) or not isinstance(one_of, list):
        return None

    property_name = str(discriminator.get("propertyName") or "")
    mapping = discriminator.get("mapping") if isinstance(discriminator.get("mapping"), dict) else {}

    variants: dict[str, Any] = {}

    # If mapping is present, use the ref-based ordering — but we only have the already-resolved
    # oneOf entries, not the raw $refs. Walk oneOf and try to associate each entry with a mapping
    # key by matching the discriminator property's constant/enum.
    for variant_schema in one_of:
        if not isinstance(variant_schema, dict):
            continue
        merged = _merge_allof_object_schema(variant_schema)
        key = _guess_variant_key(merged, property_name)
        if not key:
            continue
        variants[key] = merged

    # Fallback: if we couldn't infer any keys but mapping is present, use mapping keys positionally.
    if not variants and mapping:
        mapping_keys = list(mapping.keys())
        for idx, variant_schema in enumerate(one_of):
            if idx >= len(mapping_keys):
                break
            if isinstance(variant_schema, dict):
                variants[mapping_keys[idx]] = _merge_allof_object_schema(variant_schema)

    if not variants:
        return None

    return {
        "property_name": property_name,
        "variants": variants,
    }


def _guess_variant_key(schema: dict[str, Any], property_name: str) -> str | None:
    """Infer the discriminator value for a oneOf variant by inspecting its properties.

    Looks for a `const` or single-value `enum` on the discriminator property, then falls back
    to the variant's `title` or `description` if still unknown.
    """
    if not isinstance(schema, dict):
        return None

    properties = schema.get("properties")
    if isinstance(properties, dict) and property_name:
        prop = properties.get(property_name)
        if isinstance(prop, dict):
            const_val = prop.get("const")
            if isinstance(const_val, str) and const_val:
                return const_val
            enum_vals = prop.get("enum")
            if isinstance(enum_vals, list) and len(enum_vals) == 1 and isinstance(enum_vals[0], str):
                return enum_vals[0]

    title = schema.get("title")
    if isinstance(title, str) and title:
        return title.strip().lower()

    description = schema.get("description")
    if isinstance(description, str) and description:
        return description.strip().lower().split()[0] if description.strip() else None

    return None


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


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def get_configuration_object_schema(
    object_type: Annotated[
        Object_type,
        Field(
            description=(
                "Configuration object type to model. Must be one of the explicit enum values "
                "(org_* for org-scoped, site_* for site-scoped). "
                f"Org-scoped values: {_ORG_OBJECT_TYPE_VALUES}. "
                f"Site-scoped values: {_SITE_OBJECT_TYPE_VALUES}. "
                "Singletons (no object_id, update only): 'site_info' for Site document writes "
                "— use this for template bindings (networktemplate_id, rftemplate_id, "
                "gatewaytemplate_id, aptemplate_id, alarmtemplate_id, sitetemplate_id, "
                "secpolicy_id, sitegroup_ids) and site identity (name, timezone, latlng). "
                "'site_setting' for site-level runtime settings — wireless defaults, DNS/NTP, "
                "auto_upgrade, wids/rogue, switch_mgmt. Do NOT use site_setting for template bindings. "
                "Use the same value you plan to pass to digital_twin(action='simulate')."
            ),
            examples=['org_wlans', 'site_wlans', 'site_devices', 'site_info', 'site_setting'],
        ),
    ],
    org_id: Annotated[
        UUID,
        Field(
            description="Mist organization UUID.",
            examples=['8aa21779-1178-4357-b3e0-42c02b93b870'],
        ),
    ],
    site_id: Annotated[
        UUID | None,
        Field(
            default=None,
            description=(
                "Site UUID. Required when object_type is site-scoped (starts with 'site_'). "
                "Forbidden when object_type is org-scoped (starts with 'org_')."
            ),
            examples=['2818e386-8dec-4562-9ede-5b8a0fbbdc71'],
        ),
    ] = None,
    object_id: Annotated[
        UUID | None,
        Field(
            default=None,
            description=(
                "Optional object UUID. When provided, the tool prefers the detail endpoint "
                "(PUT/PATCH on a specific instance) to shape the schema toward update payloads. "
                "Must NOT be provided for singleton object_types (site_info, site_setting)."
            ),
        ),
    ] = None,
    verbose: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "When false (default), optional fields are compacted to reduce token usage. "
                "Set true to return the full resolved schema tree (much larger)."
            ),
        ),
    ] = False,
    variant: Annotated[
        str,
        Field(
            default="",
            description=(
                "Discriminator value for object_types whose OAS schema is a oneOf union. "
                "For object_type='site_devices', use 'ap' | 'switch' | 'gateway' — the device type "
                "of the target instance. If omitted and the schema has a oneOf discriminator, the "
                "response lists available_variants and you must retry with a variant value."
            ),
            examples=['switch', 'ap', 'gateway'],
        ),
    ] = "",
) -> str:
    """Infer payload schema for a Mist configuration object type from the Mist OpenAPI spec.

    CALL THIS BEFORE digital_twin(action='simulate') to discover required fields and build a valid payload.
    Use the returned example_payload as a starting point, then edit only the fields the user wants to change.
    For an even cheaper pre-flight check, follow up with validate_configuration_payload(...) to dry-validate
    a draft payload against this schema before hitting the twin.

    Discriminated object_types: some Mist objects (most notably site_devices) use a discriminator +
    oneOf in the OAS to pick between variants (ap / switch / gateway). Pass `variant` to select one.
    When `variant` is omitted and the schema has a discriminator, the response contains
    `available_variants` — retry the call with one of those values.

    Returns:
    - schema: OAS-derived JSON schema (compacted unless verbose=True)
    - example_payload: sanitized example (read-only keys like id/org_id/created_time removed)
    - source metadata: OAS operation (method, path_template, request-vs-response source)
    - available_variants (only when a discriminator is present and variant was empty)

    This tool is read-only. It does NOT modify Mist configuration or create any sessions.
    """
    validated = _normalize_schema_inputs(
        object_type=object_type,
        org_id=org_id,
        site_id=site_id,
        object_id=object_id,
    )

    spec = await _load_mist_oas_spec()
    oas_paths = _find_oas_paths(
        spec=spec,
        scope=validated["scope"],
        resource=validated["resource"],
        object_type=object_type,
    )

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

    # Handle discriminated oneOf (e.g. site_devices: ap | switch | gateway).
    discriminator_info = _extract_discriminator_info(schema)
    selected_variant: str | None = None

    if discriminator_info:
        variants = discriminator_info["variants"]
        normalized_variant = (variant or "").strip().lower()

        if not normalized_variant:
            # Ask the LLM to retry with a specific variant.
            return to_json(
                {
                    "object_type": validated["object_type"],
                    "scope": validated["scope"],
                    "resource": validated["resource"],
                    "org_id": validated["org_id"],
                    "site_id": validated["site_id"],
                    "object_id": validated["object_id"],
                    "source": "oas",
                    "operation": {"method": method, "path_template": path_template},
                    "discriminator": discriminator_info["property_name"],
                    "available_variants": sorted(variants.keys()),
                    "next_action": (
                        f"retry with variant=<one of {sorted(variants.keys())}> — "
                        f"pick based on the target {discriminator_info['property_name']}"
                    ),
                }
            )

        if normalized_variant not in variants:
            raise ToolError(
                f"variant '{variant}' not in available variants {sorted(variants.keys())} "
                f"for object_type='{validated['object_type']}'"
            )

        selected_variant = normalized_variant
        schema = variants[normalized_variant]
        # When the OAS supplies a bare example, it won't match the selected variant — fall back
        # to generating one from the variant schema.
        schema_example = _example_from_schema(schema) if not isinstance(schema_example, dict) else schema_example

    if schema.get("type") != "object":
        schema = {"type": "object", "properties": {"value": schema}}

    response_schema = schema if verbose else _compact_schema(schema)
    generated_example = schema_example if schema_example is not None else _example_from_schema(schema)
    example_payload = _sanitize_payload_example(generated_example if isinstance(generated_example, dict) else None)

    result: dict[str, Any] = {
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
            "Dry-validate your draft payload with validate_configuration_payload(...) before calling digital_twin(simulate).",
        ],
    }
    if selected_variant:
        result["variant"] = selected_variant
        result["discriminator"] = discriminator_info["property_name"] if discriminator_info else None
    return to_json(result)


# ---------------------------------------------------------------------------
# validate_configuration_payload — cheap dry-validator for simulate payloads.
# ---------------------------------------------------------------------------

_JSON_TYPE_CHECKS: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
}


def _type_matches(value: Any, schema_type: Any) -> bool:
    """Return True when `value` satisfies the JSON-schema `type` declaration."""
    if schema_type is None:
        return True
    if isinstance(schema_type, list):
        return any(_type_matches(value, t) for t in schema_type)
    if not isinstance(schema_type, str):
        return True
    if schema_type == "null":
        return value is None
    # `bool` is a subclass of `int` — treat integer/number strictly.
    if schema_type in ("integer", "number"):
        return isinstance(value, _JSON_TYPE_CHECKS[schema_type]) and not isinstance(value, bool)
    checks = _JSON_TYPE_CHECKS.get(schema_type)
    return True if checks is None else isinstance(value, checks)


def _validate_against_schema(
    payload: Any,
    schema: dict[str, Any],
    path: str,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
    missing_required: list[str],
) -> None:
    """Walk a JSON-schema/payload pair and collect structured validation findings."""
    if not isinstance(schema, dict):
        return

    schema_type = schema.get("type")
    if schema_type and not _type_matches(payload, schema_type):
        errors.append(
            {
                "path": path,
                "message": f"Expected {schema_type}, got {type(payload).__name__}.",
            }
        )
        return

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values and payload not in enum_values:
        errors.append(
            {
                "path": path,
                "message": f"Value '{payload}' is not in allowed enum {enum_values}.",
            }
        )

    if isinstance(payload, dict):
        properties = schema.get("properties", {}) if isinstance(schema.get("properties"), dict) else {}
        required = schema.get("required", []) if isinstance(schema.get("required"), list) else []

        for required_field in required:
            if required_field not in payload:
                full_path = f"{path}.{required_field}" if path else required_field
                missing_required.append(full_path)

        additional = schema.get("additionalProperties", True)
        for key, value in payload.items():
            key_path = f"{path}.{key}" if path else key
            if key in properties:
                _validate_against_schema(
                    value,
                    properties[key],
                    key_path,
                    errors,
                    warnings,
                    missing_required,
                )
            elif additional is False:
                errors.append(
                    {
                        "path": key_path,
                        "message": "Unknown field (schema forbids additional properties).",
                    }
                )
            else:
                warnings.append(
                    {
                        "path": key_path,
                        "message": "Field not listed in OAS schema; Mist may ignore it.",
                    }
                )
        return

    if isinstance(payload, list):
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for index, item in enumerate(payload):
                _validate_against_schema(
                    item,
                    items_schema,
                    f"{path}[{index}]",
                    errors,
                    warnings,
                    missing_required,
                )


def _collect_payload_placeholders(value: Any, path: str = "payload") -> list[str]:
    """Return payload paths (dot-notation) whose string value is an unresolved placeholder."""
    hits: list[str] = []
    if isinstance(value, str):
        if is_placeholder(value):
            hits.append(path)
        return hits
    if isinstance(value, dict):
        for key, item in value.items():
            hits.extend(_collect_payload_placeholders(item, f"{path}.{key}"))
        return hits
    if isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(_collect_payload_placeholders(item, f"{path}[{index}]"))
    return hits


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def validate_configuration_payload(
    object_type: Annotated[
        Object_type,
        Field(
            description=(
                "Configuration object type for the payload. Must match the object_type you will pass "
                "to digital_twin(action='simulate'). Use org_* or site_* enum values. "
                "Singletons: 'site_info' for Site document writes (template bindings like "
                "networktemplate_id / rftemplate_id / gatewaytemplate_id, site identity); "
                "'site_setting' for site-level runtime settings (wireless defaults, auto_upgrade, "
                "wids/rogue, switch_mgmt). Do NOT use site_setting for template bindings."
            ),
            examples=['org_wlans', 'site_wlans', 'site_info', 'site_setting'],
        ),
    ],
    org_id: Annotated[
        UUID,
        Field(
            description="Mist organization UUID.",
            examples=['8aa21779-1178-4357-b3e0-42c02b93b870'],
        ),
    ],
    payload: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Draft create/update payload (JSON object). The tool walks it against the OAS schema "
                "derived for this object_type and reports missing required fields, type mismatches, "
                "and unknown keys."
            ),
            examples=[{'ssid': 'Guest', 'enabled': True, 'vlan_id': '200'}],
        ),
    ],
    site_id: Annotated[
        UUID | None,
        Field(
            default=None,
            description=(
                "Site UUID. Required when object_type is site-scoped. "
                "Forbidden for org-scoped object_type."
            ),
        ),
    ] = None,
    action_type: Annotated[
        str,
        Field(
            default="create",
            description=(
                "Whether the payload will be used for 'create' (default) or 'update'. "
                "Update uses the detail endpoint schema (PUT/PATCH) when available."
            ),
            examples=['create', 'update'],
        ),
    ] = "create",
) -> str:
    """Dry-validate a draft payload against the Mist OAS schema BEFORE calling digital_twin(simulate).

    Lets the LLM iterate on a payload cheaply without consuming a Digital Twin session slot.
    Returns a structured report:
    - valid: True when no errors and no missing required fields were found.
    - errors: list of {path, message} for type mismatches, enum mismatches, and forbidden fields.
    - missing_required: list of dotted paths for required fields absent from the payload.
    - warnings: list of {path, message} for keys not listed in OAS (Mist may accept or ignore them).
    - schema_source: which OAS operation the schema was derived from.

    This tool is read-only. It does NOT call Mist, does NOT create twin sessions, and does NOT persist
    anything. Raises ToolError only on invalid tool arguments (bad UUID, placeholder in org_id/site_id,
    unsupported object_type). Validation failures are returned as structured data so the LLM can iterate.
    """
    normalized_action_type = (action_type or "create").strip().lower()
    if normalized_action_type not in {"create", "update"}:
        raise ToolError("action_type must be 'create' or 'update'")

    validated = _normalize_schema_inputs(
        object_type=object_type,
        org_id=org_id,
        site_id=site_id,
        object_id=None,
    )

    if not isinstance(payload, dict):
        raise ToolError("payload must be a JSON object (dict)")

    placeholder_hits = _collect_payload_placeholders(payload)

    spec = await _load_mist_oas_spec()
    oas_paths = _find_oas_paths(
        spec=spec,
        scope=validated["scope"],
        resource=validated["resource"],
        object_type=object_type,
    )
    if not oas_paths["collection"] and not oas_paths["detail"]:
        raise ToolError(
            "No matching endpoint path was found in Mist OAS for this object_type. "
            "Verify the object_type mapping or Mist OAS coverage."
        )

    schema, path_template, method, schema_source, _example = _pick_operation_schema(
        spec=spec,
        collection_path=oas_paths["collection"],
        detail_path=oas_paths["detail"],
        object_id_present=(normalized_action_type == "update"),
    )
    if schema.get("type") != "object":
        schema = {"type": "object", "properties": {"value": schema}}

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    missing_required: list[str] = []
    _validate_against_schema(payload, schema, "", errors, warnings, missing_required)

    for placeholder_path in placeholder_hits:
        errors.append(
            {
                "path": placeholder_path,
                "message": "Unresolved placeholder (e.g. {{var}}, {id}). Replace with a real value before simulation.",
            }
        )

    is_valid = not errors and not missing_required

    return to_json(
        {
            "valid": is_valid,
            "object_type": validated["object_type"],
            "org_id": validated["org_id"],
            "site_id": validated["site_id"],
            "action_type": normalized_action_type,
            "errors": errors,
            "missing_required": missing_required,
            "warnings": warnings,
            "schema_source": schema_source,
            "operation": {"method": method, "path_template": path_template},
            "next_action": (
                "proceed_to_simulate"
                if is_valid
                else "fix_errors_and_revalidate"
            ),
        }
    )


# ---------------------------------------------------------------------------
# find_configuration_field — reverse field index for intent→object_type discovery.
# ---------------------------------------------------------------------------


def _flatten_schema_fields(
    schema: dict[str, Any],
    *,
    object_type_value: str,
    variant: str | None = None,
    path: str = "",
    depth: int = 0,
    seen: set[int] | None = None,
) -> list[dict[str, Any]]:
    """Walk a resolved JSON schema and return a flat list of field entries.

    Each entry: {object_type, variant, path, field_name, description, type, enum}.
    Dict-of-object (additionalProperties) uses `*` at the path segment.
    Array items use `[]`. The optional `variant` field holds a discriminator value
    (e.g. 'switch') when the owning object_type is a oneOf union.
    """
    if depth > 10 or not isinstance(schema, dict):
        return []

    if seen is None:
        seen = set()
    schema_id = id(schema)
    if schema_id in seen:
        return []
    seen = seen | {schema_id}

    entries: list[dict[str, Any]] = []

    if "allOf" in schema:
        schema = _merge_allof_object_schema(schema)

    schema_type = _choose_primary_type(schema.get("type"))

    if schema_type == "object":
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for field_name, field_schema in properties.items():
                if not isinstance(field_schema, dict):
                    continue
                field_path = f"{path}.{field_name}" if path else field_name
                inner_type = _choose_primary_type(field_schema.get("type"))
                description = str(field_schema.get("description", "")).strip()
                enum_values = field_schema.get("enum") if isinstance(field_schema.get("enum"), list) else None

                entries.append(
                    {
                        "object_type": object_type_value,
                        "variant": variant,
                        "path": field_path,
                        "field_name": field_name,
                        "description": description,
                        "type": inner_type,
                        "enum": [str(v) for v in enum_values[:10]] if enum_values else None,
                    }
                )

                if inner_type in ("object", "array"):
                    entries.extend(
                        _flatten_schema_fields(
                            field_schema,
                            object_type_value=object_type_value,
                            variant=variant,
                            path=field_path,
                            depth=depth + 1,
                            seen=seen,
                        )
                    )

        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            dict_path = f"{path}.*" if path else "*"
            entries.extend(
                _flatten_schema_fields(
                    additional,
                    object_type_value=object_type_value,
                    variant=variant,
                    path=dict_path,
                    depth=depth + 1,
                    seen=seen,
                )
            )

    elif schema_type == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            item_path = f"{path}[]"
            entries.extend(
                _flatten_schema_fields(
                    items,
                    object_type_value=object_type_value,
                    variant=variant,
                    path=item_path,
                    depth=depth + 1,
                    seen=seen,
                )
            )

    return entries


def _build_field_index(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a reverse field index across every Object_type enum value.

    For each enum entry, pick the best available CREATE/UPDATE request schema and flatten
    it to leaves. If the schema is a discriminated oneOf (e.g. site_devices: ap|switch|gateway),
    each variant is flattened independently and tagged with its discriminator value so the
    LLM can pass `variant=<value>` to get_configuration_object_schema afterwards.
    Falls back silently for object_types the OAS doesn't cover.
    """
    index: list[dict[str, Any]] = []

    for object_type in Object_type:
        try:
            scope, resource = _scope_and_resource(object_type)
        except ToolError:
            continue

        oas_paths = _find_oas_paths(spec=spec, scope=scope, resource=resource, object_type=object_type)
        if not oas_paths["collection"] and not oas_paths["detail"]:
            continue

        try:
            schema, _path_template, _method, _schema_source, _example = _pick_operation_schema(
                spec=spec,
                collection_path=oas_paths["collection"],
                detail_path=oas_paths["detail"],
                object_id_present=False,
            )
        except ToolError:
            continue

        # Discriminated union: flatten each variant separately.
        discriminator_info = _extract_discriminator_info(schema)
        if discriminator_info:
            for variant_name, variant_schema in discriminator_info["variants"].items():
                if not isinstance(variant_schema, dict):
                    continue
                if variant_schema.get("type") != "object":
                    variant_schema = {"type": "object", "properties": {"value": variant_schema}}
                index.extend(
                    _flatten_schema_fields(
                        variant_schema,
                        object_type_value=object_type.value,
                        variant=variant_name,
                    )
                )
            continue

        if schema.get("type") != "object":
            schema = {"type": "object", "properties": {"value": schema}}

        index.extend(_flatten_schema_fields(schema, object_type_value=object_type.value))

    return index


def _get_field_index(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a cached reverse field index for the given OAS spec instance."""
    cached_id = _FIELD_INDEX_CACHE.get("spec_id")
    if cached_id == id(spec):
        cached_entries = _FIELD_INDEX_CACHE.get("entries")
        if isinstance(cached_entries, list):
            return cached_entries

    entries = _build_field_index(spec)
    _FIELD_INDEX_CACHE["spec_id"] = id(spec)
    _FIELD_INDEX_CACHE["entries"] = entries
    return entries


def _score_entry(entry: dict[str, Any], query_terms: list[str]) -> tuple[int, int]:
    """Score a field-index entry against a set of lowercase query terms.

    Returns (score, hit_count) where `hit_count` is how many distinct query terms
    matched anywhere in the entry (field_name, path, description, or enum). Used
    together, these let the ranker prefer entries that cover more of the query
    (AND semantics) over entries that only hit a single generic term (OR noise).

    Per-term weights:
    - Exact field-name match: 18 (reduced from 20; dampened for 1-4 char names)
    - Field-name substring: 8
    - Path segment substring: 6 (only when not already matched via field_name)
    - Description substring: 4
    - Enum value substring: 3
    Post-scoring bonuses:
    - All query terms hit anywhere: +25 (strong AND bonus)
    - 2+ terms hit: +10 per extra term beyond the first
    """
    if not query_terms:
        return (0, 0)

    field_name = (entry.get("field_name") or "").lower()
    path = (entry.get("path") or "").lower()
    description = (entry.get("description") or "").lower()
    enum_values = entry.get("enum") or []
    enum_text = " ".join(str(v).lower() for v in enum_values)
    variant = (entry.get("variant") or "").lower()

    score = 0
    hit_count = 0
    description_term_hits = 0

    for term in query_terms:
        if not term:
            continue
        term_hit = False

        if field_name == term:
            # Dampen exact-match for very short/common names like "port", "name", "id".
            score += 12 if len(term) <= 4 else 18
            term_hit = True
        elif term in field_name:
            score += 8
            term_hit = True

        if term in path and term not in field_name:
            score += 6
            term_hit = True

        if term in description:
            score += 4
            term_hit = True
            description_term_hits += 1

        if term in enum_text:
            score += 3
            term_hit = True

        if variant and term == variant:
            score += 5
            term_hit = True

        if term_hit:
            hit_count += 1

    # Description co-occurrence bonus: when multiple query terms appear in the SAME
    # description, that's a strong signal the field is actually about the concept the
    # user is searching for (e.g., "port profile" both in "Port usage profile reference").
    if description_term_hits >= 2:
        score += 15 * (description_term_hits - 1)

    if hit_count >= len(query_terms):
        score += 25
    if hit_count >= 2:
        score += 10 * (hit_count - 1)

    return (score, hit_count)


_COMPOUND_SUFFIXES: tuple[str, ...] = (
    "templates",
    "template",
    "profiles",
    "profile",
    "policies",
    "policy",
    "settings",
    "setting",
    "configs",
    "config",
    "groups",
    "group",
    "webhooks",
    "webhook",
    "topologies",
    "topology",
    "rules",
    "rule",
    "tags",
    "tag",
)


def _tokenize_query(query: str) -> list[str]:
    """Split a free-form query into lowercase search terms.

    After the basic non-alphanumeric split, long tokens ending in a known domain
    root (template, profile, policy, setting, config, group, webhook, topology,
    rule, tag) are additionally split into their head and root pieces. The
    original token is kept so exact-name matches still score. Example:
    'networktemplate' -> ['networktemplate', 'network', 'template'].
    """
    raw = (query or "").strip().lower()
    if not raw:
        return []
    # Split on non-alphanumeric so 'port-config' and 'port_config' both match.
    tokens: list[str] = []
    current = ""
    for ch in raw:
        if ch.isalnum():
            current += ch
        elif current:
            tokens.append(current)
            current = ""
    if current:
        tokens.append(current)

    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        if len(token) < 8:
            continue
        for suffix in _COMPOUND_SUFFIXES:
            if token.endswith(suffix) and len(token) > len(suffix) + 1:
                head = token[: -len(suffix)]
                if head:
                    expanded.append(head)
                expanded.append(suffix)
                break

    # De-dup while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for t in expanded:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
async def find_configuration_field(
    query: Annotated[
        str,
        Field(
            description=(
                "Free-form keyword(s) describing the Mist configuration setting you want to change. "
                "The tool splits the query into words and matches against OAS field names, field paths, "
                "field descriptions, and enum values across every supported object_type. "
                "Examples: 'port usage profile', 'ssid enabled', 'dhcp relay', 'bgp neighbor', 'vlan id'."
            ),
            examples=['port usage', 'ssid vlan', 'ntp servers'],
        ),
    ],
    scope: Annotated[
        str,
        Field(
            description=(
                "Optional scope filter. One of: 'org' (only org_* object types), "
                "'site' (only site_*), or empty string for both (default)."
            ),
        ),
    ] = "",
    limit: Annotated[
        int,
        Field(
            description="Max matches to return (1-50). Lower scores are dropped.",
            ge=1,
            le=50,
        ),
    ] = 20,
) -> str:
    """Reverse-lookup: find WHICH object_type owns a configuration field matching your query.

    Use this as the FIRST step when the user wants to change a setting but you don't know which
    Mist object holds it. The tool walks every supported object_type's OAS schema, flattens the
    schemas into a field index, and returns the best matches ranked by keyword score.

    Workflow:
    1. find_configuration_field(query='port usage profile')
       → matches include {object_type: 'site_devices', path: 'port_config.*.usage', ...}
    2. get_configuration_object_schema(object_type='site_devices', org_id=..., site_id=..., object_id=...)
       → full payload schema for building a valid update.
    3. validate_configuration_payload(object_type='site_devices', ..., payload={...})
       → dry-check the draft.
    4. digital_twin(action='simulate', action_type='update', object_type='site_devices', ..., payload={...})
       → run the simulation.

    Returns a JSON document with `matches` (list of {object_type, path, field_name, description,
    type, enum, score}), `total_candidates` (how many entries in the index), and `truncated` (true if
    more results existed beyond `limit`).

    This tool is read-only. It does not hit Mist and does not modify any state.
    """
    query_terms = _tokenize_query(query)
    if not query_terms:
        raise ToolError("query is required and must contain at least one alphanumeric word")

    normalized_scope = (scope or "").strip().lower()
    if normalized_scope and normalized_scope not in {"org", "site"}:
        raise ToolError("scope must be 'org', 'site', or empty")

    spec = await _load_mist_oas_spec()
    index = _get_field_index(spec)

    scored: list[tuple[int, int, dict[str, Any]]] = []
    for entry in index:
        if normalized_scope and not entry["object_type"].startswith(f"{normalized_scope}_"):
            continue
        score, hit_count = _score_entry(entry, query_terms)
        if hit_count == 0:
            continue
        scored.append((hit_count, score, entry))

    # Prefer entries that cover ALL query terms. If multi-term coverage exists, drop
    # single-term matches entirely — this removes the generic-word noise (e.g. "port"
    # alone matching radius ports). Single-term queries naturally skip this filter.
    max_hit = max((hit for hit, _s, _e in scored), default=0)
    if len(query_terms) >= 2 and max_hit >= 2:
        scored = [triple for triple in scored if triple[0] >= 2]

    # Rank: more terms hit first, then higher score, then deterministic tiebreak on object/path.
    scored.sort(key=lambda triple: (-triple[0], -triple[1], triple[2]["object_type"], triple[2]["path"]))

    truncated = len(scored) > limit
    top = scored[:limit]

    return to_json(
        {
            "query": query,
            "query_terms": query_terms,
            "scope": normalized_scope or "all",
            "total_candidates": len(index),
            "match_count": len(scored),
            "truncated": truncated,
            "matches": [
                {**entry, "score": score, "terms_matched": hit_count}
                for hit_count, score, entry in top
            ],
            "next_action": (
                "call get_configuration_object_schema with the returned object_type "
                "(and variant if the match has a variant field)"
                if top
                else "broaden the query or try different keywords"
            ),
        }
    )
