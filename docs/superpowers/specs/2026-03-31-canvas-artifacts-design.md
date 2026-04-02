# Canvas Artifacts for AI Chat

**Date**: 2026-03-31
**Status**: Approved

## Overview

Add inline artifact rendering to the AI Chat system. When the LLM produces structured content (code, reports, charts, diagrams), it wraps it in `<artifact>` tags. The frontend parses these tags and renders rich, sandboxed cards inline within the chat flow. This applies to global chat, impact analysis chat, and all summarization endpoints.

## Artifact Protocol

### Tag Format

```
<artifact type="TYPE" title="Short title" language="python">
content
</artifact>
```

### Supported Types

| Type | Attributes | Renderer | Example use |
|---|---|---|---|
| `code` | `language` (required), `title` | iframe with highlight.js | JSON configs, Jinja2, Python snippets |
| `markdown` | `title` | iframe with marked + DOMPurify | Impact summaries, structured reports |
| `html` | `title` | iframe srcdoc (raw) | Rich formatted tables, styled content |
| `mermaid` | `title` | iframe with mermaid.js | Topology diagrams, flowcharts |
| `svg` | `title` | iframe srcdoc | Network diagrams |
| `chart` | `title` | iframe with Chart.js, JSON spec | Device stats, change frequency |

### Chart JSON Spec

The LLM outputs a JSON object inside `<artifact type="chart">`:

```json
{
  "chartType": "bar",
  "data": {
    "labels": ["WLAN", "Switch", "Gateway", "Site"],
    "datasets": [{ "label": "Changes", "data": [8, 6, 5, 4] }]
  },
  "options": { "indexAxis": "y" }
}
```

### Parsing Rules

- Prose outside `<artifact>` tags renders as normal chat markdown
- One artifact per response enforced in system prompt (not client-side — if LLM produces multiple, render all)
- Short code snippets (< 15 lines) stay as inline markdown code blocks
- `title` is universal across all types, displayed in card header
- Fallback: if parser detects a markdown code block > 15 lines but no artifact tag, auto-promote to `code` artifact

## Frontend Architecture

### New Service: `ArtifactParserService`

Standalone injectable service.

- Input: raw text (accumulated tokens or stored message content)
- Output: `{ prose: string, artifacts: Artifact[] }` where prose contains `[artifact:id]` placeholders
- Regex-based extraction of `<artifact>` tags
- Fallback: auto-promote large code blocks (> 15 lines) to `code` artifacts
- Strips outer markdown code block fencing if LLM wraps `<artifact>` inside one

### Data Model

New interfaces in `llm.model.ts`:

```typescript
interface Artifact {
  id: string;           // generated UUID
  type: 'code' | 'markdown' | 'html' | 'mermaid' | 'svg' | 'chart';
  title: string;
  language?: string;    // for type="code"
  content: string;      // raw content from LLM
}
```

### Timeline Extension

Add a new `TimelineItem` kind in `AiChatPanelComponent`:

```typescript
| { kind: 'artifact'; artifact: Artifact; state: 'loading' | 'ready'; expanded: boolean }
```

### New Component: `ArtifactCardComponent`

Standalone component used by `AiChatPanelComponent` and summarization displays.

**Collapsed state**:
- Type badge (colored by type)
- Title
- Content preview (first 2-3 lines for code/markdown, chart type label for chart)
- "Expand" button, "Copy" button

**Expanded state (accordion)**:
- Full iframe render
- "Collapse" button, "Copy" button
- iframe auto-sizes height via `postMessage` from content

**Loading state**:
- Type badge + title (parsed from opening tag attributes)
- Shimmer/typing animation placeholder

### Iframe Rendering

All renderable content goes in `<iframe srcdoc="..." sandbox="allow-scripts">`.

**Height auto-sizing**: iframe posts `document.body.scrollHeight` via `postMessage` on load and resize. Component listens and sets iframe height. Max-height capped at 600px with internal scroll; expand grows to full content.

**Theme injection**: CSS custom properties (`--bg`, `--fg`, `--code-bg`, etc.) injected into iframe `<style>` based on `ThemeService` dark/light state. On theme toggle, `srcdoc` is regenerated.

**Per-type templates**:

| Type | Libraries (CDN, pinned versions) | Notes |
|---|---|---|
| `code` | highlight.js | Language from `language` attr. Line numbers. |
| `markdown` | marked + DOMPurify | Same pipeline as chat, isolated |
| `html` | None | Raw srcdoc, theme CSS injected |
| `mermaid` | mermaid.js | `mermaid.initialize({ theme })` from app theme |
| `svg` | None | SVG injected directly, theme CSS |
| `chart` | Chart.js | JSON spec parsed, theme-aware default colors from `--app-primary`, `--app-success`, etc. |

**Chart theme integration**: If the LLM doesn't specify colors in the dataset, the chart template overrides defaults using app CSS custom properties for visual consistency.

## Streaming Integration

### Token Flow

1. WS `token` event → append to `streamingContent`
2. Lightweight check after each append:
   - **No `<artifact` detected** → render as normal markdown
   - **`<artifact` opening detected, no `</artifact>` yet** → split: prose before tag renders as markdown, insert `loading` artifact timeline item (type + title from attributes), buffer subsequent tokens
   - **`</artifact>` detected** → parse content, set artifact to `ready`, resume prose rendering
3. WS `done` event → finalize. Unclosed `<artifact>` → render as `code` artifact with "Truncated" badge

### State Tracking

```typescript
private _artifactBuffer: string | null = null;
private _artifactMeta: { type: string; title: string; language?: string } | null = null;
```

### HTTP Response Handling

When HTTP response arrives, re-parse full `content` through `ArtifactParserService` and rebuild timeline (replaces streamed state with authoritative version — same existing pattern).

### Thread Detail Loading

When loading saved threads (`GET /llm/threads/{id}`), parse each message's `content` through `ArtifactParserService`. Artifacts render as ready cards. No backend storage change.

## Backend: System Prompt Architecture

### Prompt Tier System

New field on `LLMConfig` model:

```python
canvas_prompt_tier: str | None = None  # None = auto-detect
```

Validated against `{"full", "explicit", "none"}` or `None`.

Three tiers:

| Tier | Target models | Prompt style |
|---|---|---|
| `full` | GPT-4o, Claude Sonnet, Gemini Pro, Bedrock | Concise artifact rules + type table |
| `explicit` | Qwen 9B, Llama 8B, Ollama, LM Studio | Verbose rules + concrete example per type + "never wrap in markdown code block" |
| `none` | Disable canvas | No artifact instructions |

### Auto-Detection

`_default_canvas_tier()` in `llm_service_factory.py`:

- `openai` + model contains `gpt-4` → `full`
- `anthropic` → `full`
- `vertex` + model contains `gemini-2` → `full`
- `bedrock` → `full`
- `ollama` → `explicit`
- `lm_studio` → `explicit`
- Fallback → `explicit`

Admin overrides per config via LLM settings UI.

### Prompt Builder

New function `build_canvas_instructions(tier: str) -> str` in `prompt_builders.py`.

**`full` tier** appends:

```
## Canvas Artifacts

When your response contains rich content, wrap it in an <artifact> tag:

<artifact type="TYPE" title="Short title">
content
</artifact>

| Type | When to use | Extra attributes |
|------|-------------|-----------------|
| code | Code snippets > 15 lines | language="python|json|jinja2|..." (required) |
| markdown | Structured reports, long analysis | |
| html | Rich formatted tables, styled content | |
| mermaid | Diagrams, flowcharts, topologies | |
| svg | Vector graphics | |
| chart | Data visualizations | JSON: { chartType, data, options } |

Rules:
- One artifact per response unless asked for more
- Short code (< 15 lines) stays as inline markdown code blocks
- Prose and explanation go outside the artifact tag
- title attribute is always required
```

**`explicit` tier** — Same as above plus:
- Concrete example showing input → output with `<artifact>` tag
- Explicit "Do NOT wrap the artifact tag inside a markdown code block" reminder
- Chart JSON spec shown inline

### Affected Prompt Builders

`build_canvas_instructions(tier)` is appended by all prompt builders:

- `build_global_chat_system_prompt()`
- `build_backup_summary_prompt()`
- `build_webhook_summary_prompt()`
- `build_dashboard_summary_prompt()`
- `build_audit_log_summary_prompt()`
- `build_system_log_summary_prompt()`
- `build_backup_list_summary_prompt()`

Tier determined from default LLM config at call time.

### Storage

Artifacts stored as-is in message `content` (raw `<artifact>` tags). No separate storage model. Frontend parses on load. Conversation history stays faithful to LLM output.

## Summarization Endpoints Integration

### Already Using `AiChatPanelComponent` (automatic)

- Backup diff summarization (agent loop)
- Impact analysis chat

These get canvas for free — same panel renders artifacts.

### Simple Summary Displays (need `ArtifactCardComponent`)

| Page | Change |
|---|---|
| Webhook events summary | Parse response, render artifact card if found |
| Dashboard summary | Parse response, render artifact card if found |
| Audit logs summary | Parse response, render artifact card if found |
| Backup list summary | Parse response, render artifact card if found |
| System logs summary | Parse response, render artifact card if found |

These use `ArtifactCardComponent` directly — no need for a full chat panel wrapper.

## Error Handling

### Malformed Artifacts

- Missing `</artifact>` (LLM cut off) → render as `code` artifact with "Truncated" badge
- Missing `type` → default to `markdown`
- Missing `title` → generate from type ("Code Snippet", "Chart", "Report")
- Invalid `chart` JSON → render as `code` artifact with `language="json"`

### Iframe Failures

- CDN unreachable → fallback: raw content as `<pre>` with "Rendering unavailable" message
- Mermaid syntax error → mermaid.js shows its own error inside iframe
- Oversized content → max-height 600px with scroll, expand grows to full

### Model Behavior

- LLM wraps `<artifact>` inside markdown code block → parser strips outer fencing
- LLM produces multiple artifacts → render all
- LLM mentions `<artifact>` in prose explanation → only match tags at start of line or after whitespace

### Copy Button

- `html` → raw HTML source
- `chart` → JSON spec
- `svg` → SVG source
- `mermaid` → mermaid source text
- `code` → raw code
- `markdown` → raw markdown

### Theme Switching

On dark/light toggle while artifact displayed: regenerate `srcdoc` with new theme variables, re-assign to iframe.

## Admin UI

### LLM Config Changes

Add `canvas_prompt_tier` field to LLM config edit form:

- Dropdown: "Auto-detect" (default/null), "Full", "Explicit", "None"
- Help text: "Controls how canvas artifact instructions are included in system prompts. Auto-detect selects based on model size."
- Shown alongside existing model/provider/temperature fields

### API Changes

- `LLMConfigUpdate` schema: add optional `canvas_prompt_tier: str | None`
- `LLMConfigResponse` schema: add `canvas_prompt_tier: str | None` and `canvas_prompt_tier_effective: str` (resolved value after auto-detect)
