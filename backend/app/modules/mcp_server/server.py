"""
FastMCP server instance for Mist Automation & Backup.

Exposes 4 consolidated tools (search, backup, workflow, get_details)
that give LLM agents access to app data with a minimal token footprint.
"""

import contextvars

from fastmcp import FastMCP

# User context for write tools — set by the agent service before running
mcp_user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_user_id", default=None
)

mcp = FastMCP(
    name="mist-automation",
    instructions=(
        "Tools for querying and managing Mist Automation & Backup data. "
        "Domains: backups (versioned config snapshots), workflows (automation graphs), "
        "webhook events, validation reports, and system dashboard stats."
    ),
)

# Import tool modules to register them with the mcp instance.
# Each module uses @mcp.tool() to register its tools at import time.
from app.modules.mcp_server.tools import backup, details, impact_analysis, search, workflow  # noqa: E402, F401
