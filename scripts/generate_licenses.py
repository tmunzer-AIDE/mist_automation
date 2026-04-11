#!/usr/bin/env python3
"""Combine pip-licenses and license-checker JSON outputs into a single licenses.json."""
import json
import sys
from datetime import datetime, timezone

# Manual overrides for packages where pip-licenses cannot detect the license
# (e.g. packages using License-File in METADATA instead of a License classifier).
# Values verified against the actual license files in the dist-info directory.
OVERRIDES: dict[str, dict] = {
    "caio": {"license": "Apache-2.0", "url": "https://github.com/mosquito/caio"},
}


def normalize_backend(data: list) -> list:
    result = []
    for p in data:
        name = p["Name"]
        override = OVERRIDES.get(name, {})
        result.append(
            {
                "name": name,
                "version": p["Version"],
                "license": override.get("license") or p["License"],
                "url": override.get("url") or p.get("URL", ""),
                "author": p.get("Author", ""),
            }
        )
    return sorted(result, key=lambda x: x["name"].lower())


def normalize_frontend(data: dict) -> list:
    result = []
    for pkg_ver, info in data.items():
        # pkg_ver is like "package@1.0.0" or "@scope/package@1.0.0"
        at_idx = pkg_ver.rfind("@", 1)  # skip leading @ of scoped packages
        if at_idx <= 0:
            name, version = pkg_ver, ""
        else:
            name, version = pkg_ver[:at_idx], pkg_ver[at_idx + 1 :]
        result.append(
            {
                "name": name,
                "version": version,
                "license": info.get("licenses", "Unknown"),
                "url": info.get("repository", ""),
                "author": info.get("publisher", ""),
            }
        )
    return sorted(result, key=lambda x: x["name"].lower())


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: generate_licenses.py <backend.json> <frontend.json> <output.json>")
        sys.exit(1)

    backend_file, frontend_file, output_file = sys.argv[1:4]

    with open(backend_file) as f:
        backend = normalize_backend(json.load(f))
    with open(frontend_file) as f:
        frontend = normalize_frontend(json.load(f))

    output = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "backend": backend,
        "frontend": frontend,
    }
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Generated {len(backend)} backend + {len(frontend)} frontend licenses -> {output_file}")
