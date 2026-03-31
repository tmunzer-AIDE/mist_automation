"""
Mist OpenAPI Specification service — loads, indexes, and queries the Mist OAS.

Used by:
- Variable autocomplete (Phase 4): response field trees for upstream nodes
- Simulation (Phase 5): realistic mock responses from OAS examples/schemas
"""

import re
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
import yaml

logger = structlog.get_logger(__name__)


class EndpointSchema:
    """Processed schema for a single API endpoint."""

    __slots__ = (
        "method",
        "path_template",
        "path_params",
        "query_params",
        "response_schema",
        "response_example",
        "description",
    )

    def __init__(
        self,
        method: str,
        path_template: str,
        path_params: list[str],
        query_params: list[str],
        response_schema: dict,
        response_example: dict | None,
        description: str,
    ):
        self.method = method
        self.path_template = path_template
        self.path_params = path_params
        self.query_params = query_params
        self.response_schema = response_schema
        self.response_example = response_example
        self.description = description


class OASService:
    """Loads and indexes the Mist OpenAPI Specification."""

    _index: dict[str, EndpointSchema] = {}
    _loaded_at: datetime | None = None

    @classmethod
    async def load(cls, oas_url: str) -> None:
        """Fetch and index the OAS from the given URL."""
        if not oas_url:
            logger.info("oas_service_skip", reason="no URL configured")
            return

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(oas_url)
                resp.raise_for_status()
                spec = yaml.safe_load(resp.text)
        except Exception as e:
            logger.warning("oas_load_failed", url=oas_url, error=str(e))
            return

        cls._build_index(spec)
        cls._loaded_at = datetime.now(timezone.utc)
        logger.info("oas_loaded", endpoints=len(cls._index), url=oas_url)

    @classmethod
    def _build_index(cls, spec: dict) -> None:
        """Build an in-memory index from the OAS."""
        new_index: dict[str, EndpointSchema] = {}
        paths = spec.get("paths", {})

        for path_template, path_item in paths.items():
            for method in ("get", "post", "put", "delete", "patch"):
                operation = path_item.get(method)
                if not operation:
                    continue

                # Extract path params
                path_params = re.findall(r"\{(\w+)\}", path_template)

                # Extract query params
                query_params = []
                for param in operation.get("parameters", []):
                    if param.get("in") == "query":
                        query_params.append(param.get("name", ""))

                # Extract response schema (200 or 201)
                response_schema: dict = {}
                response_example: dict | None = None

                for code in ("200", "201"):
                    resp_spec = operation.get("responses", {}).get(code, {})
                    content = resp_spec.get("content", {}).get("application/json", {})
                    if "schema" in content:
                        response_schema = cls._resolve_schema(content["schema"], spec)
                        break
                    if "example" in content:
                        response_example = content["example"]
                        break

                # Check for example in schema
                if not response_example and response_schema.get("example"):
                    response_example = response_schema["example"]

                key = f"{method.upper()} {path_template}"
                new_index[key] = EndpointSchema(
                    method=method.upper(),
                    path_template=path_template,
                    path_params=path_params,
                    query_params=query_params,
                    response_schema=response_schema,
                    response_example=response_example,
                    description=operation.get("summary", operation.get("description", "")),
                )

        cls._index = new_index

    @classmethod
    def _resolve_schema(cls, schema: dict, spec: dict, depth: int = 0) -> dict:
        """Resolve $ref references in a schema (limited depth to prevent infinite loops)."""
        if depth > 10:
            return schema

        ref = schema.get("$ref")
        if ref:
            parts = ref.lstrip("#/").split("/")
            resolved = spec
            for part in parts:
                resolved = resolved.get(part, {})
            return cls._resolve_schema(resolved, spec, depth + 1)

        # Resolve nested properties
        result = dict(schema)
        if "properties" in result:
            resolved_props = {}
            for prop_name, prop_schema in result["properties"].items():
                resolved_props[prop_name] = cls._resolve_schema(prop_schema, spec, depth + 1)
            result["properties"] = resolved_props

        if "items" in result:
            result["items"] = cls._resolve_schema(result["items"], spec, depth + 1)

        return result

    @classmethod
    def get_endpoint(cls, method: str, path: str) -> EndpointSchema | None:
        """Look up an endpoint by method and path template."""
        key = f"{method.upper()} {path}"
        return cls._index.get(key)

    @classmethod
    def generate_mock_response(cls, endpoint: EndpointSchema) -> dict:
        """Generate a mock response for the given endpoint."""
        # Prefer OAS example if available
        if endpoint.response_example:
            return dict(endpoint.response_example)

        # Otherwise generate from schema
        return cls._generate_from_schema(endpoint.response_schema)

    @classmethod
    def _generate_from_schema(cls, schema: dict) -> Any:
        """Walk a JSON Schema and generate sample values."""
        if not schema:
            return {}

        schema_type = schema.get("type", "object")

        if schema_type == "object":
            result = {}
            for prop_name, prop_schema in schema.get("properties", {}).items():
                if prop_schema.get("example") is not None:
                    result[prop_name] = prop_schema["example"]
                else:
                    result[prop_name] = cls._generate_from_schema(prop_schema)
            return result

        if schema_type == "array":
            items_schema = schema.get("items", {})
            return [cls._generate_from_schema(items_schema)]

        if schema_type == "string":
            fmt = schema.get("format", "")
            if fmt == "date-time":
                return "2024-01-01T00:00:00Z"
            if fmt == "uuid":
                return "00000000-0000-0000-0000-000000000000"
            if fmt == "email":
                return "user@example.com"
            return schema.get("default", "example_string")

        if schema_type == "integer":
            return schema.get("default", 1)

        if schema_type == "number":
            return schema.get("default", 1.0)

        if schema_type == "boolean":
            return schema.get("default", True)

        return None

    @classmethod
    def get_response_fields(cls, endpoint: EndpointSchema) -> list[str]:
        """Return a flat list of dot-notation field paths from the response schema."""
        fields: list[str] = []
        cls._collect_fields(endpoint.response_schema, "", fields)
        return fields

    @classmethod
    def _collect_fields(cls, schema: dict, prefix: str, fields: list[str], depth: int = 0) -> None:
        """Recursively collect field paths from a JSON Schema."""
        if depth > 8:
            return

        schema_type = schema.get("type", "object")

        if schema_type == "object":
            for prop_name, prop_schema in schema.get("properties", {}).items():
                path = f"{prefix}.{prop_name}" if prefix else prop_name
                fields.append(path)
                cls._collect_fields(prop_schema, path, fields, depth + 1)

        elif schema_type == "array":
            items_schema = schema.get("items", {})
            path = f"{prefix}[0]" if prefix else "[0]"
            cls._collect_fields(items_schema, path, fields, depth + 1)

    @classmethod
    def is_loaded(cls) -> bool:
        """Check if the OAS has been loaded."""
        return bool(cls._index)

    @classmethod
    def get_loaded_at(cls) -> datetime | None:
        """Return when the OAS was last loaded."""
        return cls._loaded_at
