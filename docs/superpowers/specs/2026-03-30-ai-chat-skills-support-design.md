# AI Chat Skills Support — Design Spec

**Date**: 2026-03-30
**Status**: Approved

## Overview

Add support for [Agent Skills](https://agentskills.io) to all AI chat surfaces in the application. Skills are markdown instruction files (`SKILL.md`) that provide the LLM with specialized domain knowledge on demand, using a progressive disclosure model: a compact catalog is injected into every system prompt at session start, and the model loads full skill instructions only when it decides a skill is relevant.

Skills are managed by admins (global scope, available to all users) and stored on a persistent filesystem volume. They can be added by pasting a `SKILL.md` directly or by pointing to a git repository that is scanned for skill directories.

## Architecture

### Three-tier progressive disclosure

| Tier | Content | When loaded | Token cost |
|---|---|---|---|
| 1. Catalog | name + description | Every session start | ~50–100 tokens/skill |
| 2. Instructions | Full `SKILL.md` body | Model calls `activate_skill` | < 5000 tokens (recommended) |
| 3. Resources | Bundled files (scripts, refs) | Model reads them via file tool | Varies |

This keeps the base context small — 20 installed skills don't pay the token cost of 20 full instruction sets upfront.

### Filesystem storage

Base directory configured via env var `SKILLS_DIR` (default: `/data/skills`). The Docker container/pod must mount a persistent volume at this path.

```
/data/skills/
├── direct/                        # Skills uploaded via SKILL.md paste
│   └── <skill-name>/
│       ├── SKILL.md
│       └── <bundled files...>
└── repos/                         # Git-cloned repositories
    └── <repo-slug>/               # Cloned repo root
        └── skills/                # Skills can be anywhere in the tree
            └── <skill-name>/
                ├── SKILL.md
                └── <bundled files...>
```

Discovery scans the repo tree recursively (max depth 6) for directories containing a file named exactly `SKILL.md`. Skills can live anywhere in the repo — no fixed structure required.

## Data Model

### `Skill` (MongoDB document, in `app/modules/llm/models.py`)

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | From SKILL.md frontmatter; unique |
| `description` | `str` | From SKILL.md frontmatter |
| `source` | `Literal["direct", "git"]` | How it was added |
| `local_path` | `str` | Absolute path to skill directory |
| `enabled` | `bool` | Admin toggle; default `True` |
| `git_repo_id` | `Optional[PydanticObjectId]` | FK to `SkillGitRepo` if source=git |
| `error` | `Optional[str]` | Last parse/sync error |
| `last_synced_at` | `Optional[datetime]` | Last successful SKILL.md parse |

Inherits `TimestampMixin` for `created_at` / `updated_at`.

### `SkillGitRepo` (MongoDB document, in `app/modules/llm/models.py`)

| Field | Type | Notes |
|---|---|---|
| `url` | `str` | Git repo URL (SSRF-validated on save) |
| `branch` | `str` | Default: `"main"` |
| `token` | `Optional[str]` | Encrypted deploy token (`encrypt_sensitive_data()`) |
| `token_set` | `bool` | Returned in API responses instead of the token value |
| `local_path` | `str` | Absolute path to clone destination |
| `last_refreshed_at` | `Optional[datetime]` | Last successful pull |
| `error` | `Optional[str]` | Last clone/pull error |

Inherits `TimestampMixin`.

## Backend API

All endpoints require `require_admin`. Routed under `/llm/skills` in the existing LLM router (`app/modules/llm/router.py`).

### Skills

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/llm/skills` | List all skills (with repo name if source=git) |
| `POST` | `/llm/skills/direct` | Add skill from raw SKILL.md content |
| `PATCH` | `/llm/skills/{id}/toggle` | Enable / disable a skill |
| `DELETE` | `/llm/skills/{id}` | Remove skill + its directory (direct-source skills only) |

**`POST /llm/skills/direct`** body:
```json
{ "content": "<raw SKILL.md text>" }
```
Backend parses frontmatter, extracts `name` and `description`, writes to `/data/skills/direct/<name>/SKILL.md`, creates `Skill` doc. Rejects if `name` or `description` is missing, or if a skill with the same name already exists.

Git-sourced skills cannot be deleted individually — their existence is controlled by the git repo. To suppress a specific git skill without deleting the entire repo, disable it via the toggle. The `DELETE /llm/skills/{id}` endpoint returns 400 if `source == "git"`.

### Git Repos

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/llm/skills/repos` | List all git repos |
| `POST` | `/llm/skills/repos` | Add repo (triggers background clone + scan) |
| `POST` | `/llm/skills/repos/{id}/refresh` | Pull latest + re-scan (background task) |
| `DELETE` | `/llm/skills/repos/{id}` | Remove repo + all its skills + cloned directory |

**`POST /llm/skills/repos`** body:
```json
{ "url": "https://github.com/...", "branch": "main", "token": "ghp_..." }
```
URL is validated via `validate_outbound_url()` before cloning. Clone and scan run as a `create_background_task()` fire-and-forget; the repo document transitions from `error=null` with no `last_refreshed_at` (pending) to populated on completion.

**Refresh** does `git pull` then re-scans: updates existing skill docs, adds newly discovered skills, marks removed ones with an error (not deleted automatically — admin must delete explicitly).

**Delete repo** removes: the `SkillGitRepo` doc, all linked `Skill` docs, and the cloned directory from disk.

### Skill parsing utility

Shared module `app/modules/llm/services/skills_service.py`:

- `parse_skill_md(path) -> (name, description, body)` — extracts frontmatter + body; applies lenient YAML parsing (unquoted colons fallback)
- `scan_for_skills(base_dir) -> list[Path]` — recursive walk, max depth 6, skips `.git`/`node_modules`, returns paths to `SKILL.md` files
- `list_skill_resources(skill_dir) -> list[str]` — lists non-`SKILL.md` files in the skill directory
- `build_skills_catalog() -> str` — async, queries enabled skills, returns XML catalog string (empty string if no skills enabled)

## MCP Tool: `activate_skill`

Added to `app/modules/mcp_server/` alongside existing tools.

```python
@mcp.tool()
async def activate_skill(name: str) -> str:
    """
    Load the full instructions for a named skill.
    Call this when the user's request matches a skill's description.
    """
    skill = await Skill.find_one(Skill.name == name, Skill.enabled == True)
    if not skill:
        return f"Skill '{name}' not found or not enabled."
    _, _, body = parse_skill_md(Path(skill.local_path) / "SKILL.md")
    resources = list_skill_resources(Path(skill.local_path))
    return (
        f'<skill_content name="{name}">\n'
        f"{body}\n\n"
        f"Skill directory: {skill.local_path}\n"
        f"<skill_resources>\n"
        + "\n".join(f"  <file>{r}</file>" for r in resources)
        + "\n</skill_resources>\n</skill_content>"
    )
```

The tool is always registered (MCP tools are registered at startup and cannot be conditionally added/removed at runtime). The `name` parameter's description is built dynamically per-request to list currently enabled skill names, reducing hallucination. If no skills are enabled, the catalog is omitted from the system prompt and the model will not attempt to call the tool.

## System Prompt Integration

`build_skills_catalog()` is called by all prompt builder functions in `prompt_builders.py` and appended to their existing system prompt strings:

```python
async def build_global_chat_system_prompt(user_roles: list[str]) -> str:
    base = "You are an assistant for the Mist Automation..."
    skills_section = await build_skills_catalog()
    return base + ("\n\n" + skills_section if skills_section else "")
```

The catalog block format:

```xml
<available_skills>
  <skill>
    <name>pdf-processing</name>
    <description>Extract PDF text, fill forms, merge files. Use when handling PDFs.</description>
  </skill>
</available_skills>

When a task matches a skill's description, call the activate_skill tool with the skill's name to load its full instructions before proceeding.
```

If no skills are enabled, the catalog block and instructions are omitted entirely.

## Admin UI

Skills management is added as a new section at the bottom of the existing **LLM admin settings page** (no new route). Angular component: `SkillsAdminComponent` (standalone, lazy-loaded as part of the LLM admin section).

### Skills list

Table with columns: name, description (truncated), source badge (`direct` / `git:<repo-name>`), enabled toggle (inline `mat-slide-toggle`, PATCH on change), last synced, error icon (tooltip shows error message). Disabled skills are visually dimmed.

### Add direct skill

"Add Skill" button → `MatDialog` with a `<textarea>` for raw SKILL.md content. Submit calls `POST /llm/skills/direct`. Inline error display for validation failures.

### Git repo management

Separate card above the skills table listing repos. Each repo row: URL, branch, last refreshed, spinner while a background task is running, "Refresh" icon button (`POST .../refresh`), delete button (with confirmation dialog). "Add Git Repo" button → dialog with URL, branch, optional token fields.

After adding a repo or triggering refresh, the UI polls `GET /llm/skills/repos/{id}` every 3 seconds until `last_refreshed_at` is updated or `error` is set (max 60s timeout with user-visible error).

## Error Handling

- **SSRF on git URL**: `validate_outbound_url()` called before clone. Invalid URLs rejected with 400.
- **Clone failure**: `SkillGitRepo.error` set; surfaced in admin UI. Existing skills from a previous successful clone are unaffected.
- **Malformed SKILL.md**: Skill doc created with `error` field set; not included in catalog. Admin sees the error in the UI.
- **Missing description**: Skill is skipped entirely (description is required for catalog disclosure).
- **Name collision on direct upload**: Rejected with 409 + message.
- **Skill directory missing at activate time**: `activate_skill` returns a not-found error message rather than raising — the agent loop continues gracefully.

## Out of Scope

- Per-user or per-role skill scoping (all enabled skills are global)
- Automatic periodic refresh of git repos (admin-triggered only)
- Skill context deduplication across turns (the model will naturally not re-activate the same skill in the same conversation)
- Tier 3 resource loading (the model can request bundled files via existing file-access tools if available; no special infrastructure added)
