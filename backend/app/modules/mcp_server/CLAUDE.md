# MCP Server Module

Part of mist_automation — see root `CLAUDE.md` for global architecture and conventions, `backend/CLAUDE.md` for backend patterns. See also `app/modules/llm/CLAUDE.md` for the LLM/agent layer that uses this server.

## Backend (`app/modules/mcp_server/`)

- FastMCP server exposing app data as MCP tools (backups, workflows, executions, webhook events, reports, system stats)
- HTTP endpoint (`/mcp`) gated by `MCPAuthMiddleware` (`auth_middleware.py`) — validates Bearer JWT, sets `mcp_user_id_var`. Returns 401 for unauthenticated requests.
- In-process memory transport (`InProcessMCPClient`) bypasses HTTP entirely — unaffected by auth middleware
- `mcp_user_id_var` and `mcp_thread_id_var` ContextVars for user and thread context in tool handlers
- **Elicitation bridge** (`helpers.py`): `elicit_confirmation()` sends simple text confirmations via WebSocket; `elicit_restore_confirmation()` sends rich payloads with `elicitation_type` and `data` fields for structured UI (e.g., diff viewer in restore confirmation card)
- **Backup restore action**: `backup(action="restore")` auto-computes diff between target and current version, sends rich elicitation with diff data, executes restore on approval
- **Workflow tool security** (`tools/workflow.py`): `_create` and `_update` mirror REST API security: role/ownership checks via `mcp_user_id_var`, `_encrypt_nodes()` for OAuth/auth secrets before persisting, `validate_no_circular_subflow_references()` on create. Uses same `_OAUTH_NODE_TYPES` set as the REST router.
- **Memory tools** (`tools/memory.py`): `memory_store(key, value, category)`, `memory_recall(query, category)`, `memory_forget(key)`. Per-user scoped via `mcp_user_id_var`. Store upserts by `(user_id, key)` — warns LLM about overwrite. Recall uses MongoDB text index. Cap enforced from `SystemConfig.memory_max_entries_per_user`. Internal helpers `_store_memory`, `_recall_memory`, `_forget_memory` are exported for direct testing.
- **`activate_skill` tool** (`tools/skills.py`): loads the full body of a named enabled `Skill` document from the filesystem. Returns content wrapped in `<skill_content name="...">` tags with `<skill_resources>` listing bundled files. Returns a graceful error string (not exception) if the skill is missing or the file is gone.
