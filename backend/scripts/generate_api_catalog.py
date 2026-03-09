#!/usr/bin/env python3
"""
Generate Mist API catalog entries by introspecting the mistapi package.

Run manually when mistapi is updated:
    python -m scripts.generate_api_catalog

Outputs discovered endpoints to stdout as Python code that can be
reviewed and merged into api_catalog.py.
"""

import importlib
import inspect
import re
import sys


def extract_endpoints_from_module(module) -> list[dict]:
    """Extract API endpoint info from a mistapi module."""
    entries = []
    for name, func in inspect.getmembers(module, inspect.isfunction):
        # Skip private/internal functions
        if name.startswith("_"):
            continue

        sig = inspect.signature(func)
        doc = inspect.getdoc(func) or ""

        # Try to find endpoint pattern in docstring or source
        try:
            source = inspect.getsource(func)
        except (OSError, TypeError):
            continue

        # Look for URI patterns like /api/v1/...
        uri_match = re.search(r'["\'](/api/v1/[^"\']+)["\']', source)
        if not uri_match:
            continue

        endpoint = uri_match.group(1)

        # Determine HTTP method from function name or source
        method = "GET"
        name_lower = name.lower()
        if any(kw in name_lower for kw in ["create", "post", "add"]):
            method = "POST"
        elif any(kw in name_lower for kw in ["update", "put", "modify"]):
            method = "PUT"
        elif any(kw in name_lower for kw in ["delete", "remove"]):
            method = "DELETE"

        # Extract path parameters
        path_params = re.findall(r"\{(\w+)\}", endpoint)

        # Extract query parameters from function signature
        skip_params = {"mist_session", "self", "cls", "body"} | set(path_params)
        query_params = []
        for param_name, param in sig.parameters.items():
            if param_name in skip_params:
                continue
            qp = {"name": param_name, "description": "", "required": False, "type": "string"}
            if param.default is inspect.Parameter.empty:
                qp["required"] = True
            # Infer type from annotation
            annotation = param.annotation
            if annotation is not inspect.Parameter.empty:
                ann_str = str(annotation)
                if "int" in ann_str:
                    qp["type"] = "integer"
                elif "bool" in ann_str:
                    qp["type"] = "boolean"
            query_params.append(qp)

        # Generate a label from function name
        label = name.replace("_", " ").title()

        # Determine category from endpoint path
        parts = endpoint.split("/")
        category = "Other"
        for part in reversed(parts):
            if part and not part.startswith("{") and part not in ("api", "v1", "orgs", "sites"):
                category = part.replace("_", " ").title()
                break

        has_body = method in ("POST", "PUT")

        entries.append({
            "id": name,
            "label": label,
            "method": method,
            "endpoint": endpoint,
            "path_params": path_params,
            "query_params": query_params,
            "category": category,
            "description": doc.split("\n")[0] if doc else label,
            "has_body": has_body,
        })

    return entries


def main():
    try:
        import mistapi
    except ImportError:
        print("Error: mistapi package not installed.", file=sys.stderr)
        print("Install it first: pip install mistapi", file=sys.stderr)
        sys.exit(1)

    all_entries = []

    # Discover submodules
    package_path = getattr(mistapi, "__path__", None)
    if not package_path:
        print("Warning: Could not find mistapi package path", file=sys.stderr)
        return

    import pkgutil
    for importer, modname, ispkg in pkgutil.walk_packages(package_path, prefix="mistapi."):
        if ispkg:
            continue
        try:
            mod = importlib.import_module(modname)
            entries = extract_endpoints_from_module(mod)
            all_entries.extend(entries)
        except Exception as e:
            print(f"Warning: Could not introspect {modname}: {e}", file=sys.stderr)

    # Output as Python code
    print("# Auto-generated catalog entries — review before merging into api_catalog.py")
    print(f"# Found {len(all_entries)} endpoints")
    print()

    for entry in sorted(all_entries, key=lambda e: (e["category"], e["method"], e["endpoint"])):
        print(f"    ApiCatalogEntry(")
        print(f'        id="{entry["id"]}",')
        print(f'        label="{entry["label"]}",')
        print(f'        method="{entry["method"]}",')
        print(f'        endpoint="{entry["endpoint"]}",')
        print(f'        path_params={entry["path_params"]},')
        if entry.get("query_params"):
            print(f'        query_params=[')
            for qp in entry["query_params"]:
                print(f'            QueryParam(name="{qp["name"]}", description="{qp["description"]}", '
                      f'required={qp["required"]}, type="{qp["type"]}"),')
            print(f'        ],')
        print(f'        category="{entry["category"]}",')
        print(f'        description="{entry["description"]}",')
        print(f'        has_body={entry["has_body"]},')
        print(f"    ),")

    print(f"\n# Total: {len(all_entries)} entries")


if __name__ == "__main__":
    main()
