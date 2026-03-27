# Workflow Tags Design

Add manual and auto-generated tags to workflows for categorization and filtering.

## Manual Tags

### Backend

**Model** (`backend/app/modules/automation/models/workflow.py`):
- Add `tags: list[str] = []` field to `Workflow` document
- Add `"tags"` to the `indexes` list for query performance

**Router** (`backend/app/modules/automation/router.py`):
- Add `tags: str | None = None` query param to `GET /workflows` (comma-separated values)
- Filter: `{"tags": {"$all": parsed_tags_list}}` — AND logic, all specified tags must be present
- Add `"tags"` to response serialization

**Schemas**:
- Add `tags: list[str] = []` to `WorkflowCreate` and `WorkflowResponse` Pydantic models
- Add `tags: list[str] | None = None` to `WorkflowUpdate`

### Frontend

**TypeScript interfaces** (`core/models/workflow.model.ts`):
- Add `tags: string[]` to `WorkflowResponse`
- Add `tags?: string[]` to `WorkflowCreate` and `WorkflowUpdate`

**Description dialog** (`editor/description-dialog/`):
- Add `mat-chip-grid` + `mat-chip-input` below the sharing field
- Free-text input, Enter or comma to add a tag, X button to remove
- Pass current tags into dialog, return updated tags on save

**Editor component** (`editor/workflow-editor.component.ts`):
- Add `workflowTags` signal, populate from loaded workflow
- Pass to description dialog, update on dialog close
- Include `tags` in save payload

**List component** (`list/workflow-list.component.ts`):
- Add "Tags" column to the table showing `mat-chip` per tag (solid style)
- Add tag filter: text input with autocomplete from all tags across loaded workflows
- `tagsFilter` signal, `setTagsFilter()` method following existing `setTypeFilter()` pattern
- Pass tags filter to service `list()` call

**Workflow service** (`core/services/workflow.service.ts`):
- Add `tags?: string` param to `list()` method (comma-separated string for query param)

## Auto-Tags

Computed client-side from the `nodes` array in `WorkflowResponse`. Not stored in the database.

### Action type to auto-tag mapping

| Action type(s) | Auto-tag |
|---|---|
| `ai_agent` | AI |
| `slack` | Slack |
| `email` | Email |
| `servicenow` | ServiceNow |
| `pagerduty` | PagerDuty |
| `mist_api_*` | Mist API |
| `syslog` | Syslog |
| `trigger_backup`, `restore_backup`, `compare_backups` | Backup |
| `webhook` | Webhook |
| `device_utils` | Device |
| `invoke_subflow` | Sub-Flow |

### Frontend

**Auto-tag utility** (in workflow model or a small helper):
- `computeAutoTags(nodes: WorkflowNode[]): string[]` — deduplicated, sorted
- Extract unique action types from nodes, map to auto-tag labels

**List component**:
- Show auto-tags alongside manual tags in the Tags column
- Auto-tags use outlined/muted chip style to distinguish from solid manual tags
- Auto-tags are included in tag filtering (client-side match since they aren't stored)

**Tag filtering logic**:
- Manual tags: filtered server-side via `$all` query
- Auto-tags: filtered client-side after response — workflows matching either the server tag filter OR the auto-tag filter are shown
- When a filter term matches an auto-tag, apply client-side post-filter on the response
