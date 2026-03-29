# MCP Server Module

Part of mist_automation — see root `CLAUDE.md` for global architecture and conventions, `backend/CLAUDE.md` for backend patterns. See also `app/modules/llm/CLAUDE.md` for the LLM/agent layer that uses this server.

## Backend (`app/modules/mcp_server/`)

- FastMCP server exposing app data as MCP tools (backups, workflows, executions, webhook events, reports, system stats)
- HTTP endpoint (`/mcp`) gated by `MCPAuthMiddleware` (`auth_middleware.py`) — validates Bearer JWT, sets `mcp_user_id_var`. Returns 401 for unauthenticated requests.
- In-process memory transport (`InProcessMCPClient`) bypasses HTTP entirely — unaffected by auth middleware
- `mcp_user_id_var` ContextVar for user context in tool handlers
- **Elicitation bridge** (`helpers.py`): `elicit_confirmation()` sends simple text confirmations via WebSocket; `elicit_restore_confirmation()` sends rich payloads with `elicitation_type` and `data` fields for structured UI (e.g., diff viewer in restore confirmation card)
- **Backup restore action**: `backup(action="restore")` auto-computes diff between target and current version, sends rich elicitation with diff data, executes restore on approval
- **Workflow tool security** (`tools/workflow.py`): `_create` and `_update` mirror REST API security: role/ownership checks via `mcp_user_id_var`, `_encrypt_nodes()` for OAuth/auth secrets before persisting, `validate_no_circular_subflow_references()` on create. Uses same `_OAUTH_NODE_TYPES` set as the REST router.
