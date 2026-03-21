"""
MCP client using the MCP SDK directly with a pre-configured httpx client.

Uses streamable HTTP transport. Bypasses FastMCP's Client wrapper for full
control over the httpx client (SSL, headers, timeouts).
"""

import os
from dataclasses import dataclass

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for connecting to an MCP server over HTTP."""

    name: str
    url: str
    headers: dict[str, str] | None = None
    ssl_verify: bool = True


@dataclass
class MCPTool:
    """A tool exposed by an MCP server."""

    name: str
    description: str
    input_schema: dict


class MCPClientWrapper:
    """Connects to an MCP server via streamable HTTP using the MCP SDK directly."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._session = None
        self._exit_stack = None

    async def connect(self) -> None:
        """Connect to the MCP server and initialize the session."""
        import contextlib

        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        verify = self._build_verify()
        logger.info(
            "mcp_connecting",
            server=self.config.name,
            url=self.config.url,
            ssl_verify=self.config.ssl_verify,
        )

        stack = contextlib.AsyncExitStack()
        try:
            http_client = await stack.enter_async_context(
                httpx.AsyncClient(verify=verify, headers=self.config.headers)
            )
            read_stream, write_stream, _ = await stack.enter_async_context(
                streamable_http_client(self.config.url, http_client=http_client)
            )
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()

            self._session = session
            self._exit_stack = stack
            logger.info("mcp_connected", server=self.config.name)
        except Exception:
            await stack.aclose()
            raise

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception:
                logger.debug("mcp_disconnect_error", server=self.config.name)
            self._session = None
            self._exit_stack = None

    async def list_tools(self) -> list[MCPTool]:
        """List available tools from the MCP server."""
        if not self._session:
            raise RuntimeError("Not connected")

        result = await self._session.list_tools()
        return [
            MCPTool(
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema if hasattr(t, "inputSchema") else {},
            )
            for t in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Call a tool on the MCP server and return the result as a string."""
        if not self._session:
            raise RuntimeError("Not connected")

        result = await self._session.call_tool(name, arguments)
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts) if parts else ""

    def _build_verify(self) -> str | bool:
        """Determine the httpx verify setting."""
        if not self.config.ssl_verify:
            return False
        if settings.ca_cert_path and os.path.isfile(settings.ca_cert_path):
            return settings.ca_cert_path
        return True


class InProcessMCPClient:
    """MCP client using in-process memory transport.

    Connects directly to a FastMCP server object — no HTTP round-trip.
    Python ContextVars propagate from the caller to the tool handlers.
    """

    def __init__(self, server: object, name: str = "local"):
        self._server = server
        self._client: object | None = None
        self.config = MCPServerConfig(name=name, url="in-process")

    async def connect(self) -> None:
        """Connect to the FastMCP server in-process."""
        from fastmcp import Client

        self._client = Client(self._server)
        await self._client.__aenter__()
        logger.info("mcp_connected_inprocess", server=self.config.name)

    async def disconnect(self) -> None:
        """Disconnect from the in-process server."""
        if self._client:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                logger.debug("mcp_disconnect_error", server=self.config.name)
            self._client = None

    async def list_tools(self) -> list[MCPTool]:
        """List available tools from the in-process server."""
        if not self._client:
            raise RuntimeError("Not connected")

        tools = await self._client.list_tools()
        return [
            MCPTool(
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema if hasattr(t, "inputSchema") else {},
            )
            for t in tools
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Call a tool on the in-process server and return the result as a string."""
        if not self._client:
            raise RuntimeError("Not connected")

        result = await self._client.call_tool(name, arguments)
        # fastmcp.Client.call_tool returns a list of content blocks
        if isinstance(result, list):
            parts = []
            for block in result:
                if hasattr(block, "text"):
                    parts.append(block.text)
                else:
                    parts.append(str(block))
            return "\n".join(parts) if parts else ""
        return str(result) if result else ""


def create_local_mcp_client() -> InProcessMCPClient:
    """Create an in-process MCP client connected to the local FastMCP server.

    Uses memory transport — ContextVars propagate from caller to tool handlers.
    """
    from app.modules.mcp_server.server import mcp

    return InProcessMCPClient(mcp, name="mist-automation")
