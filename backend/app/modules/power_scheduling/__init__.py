"""Power scheduling module package.

Exports the API router module under `router` for backward-compatible test patch paths.
"""

from app.api.v1 import power_scheduling as router

__all__ = ["router"]
