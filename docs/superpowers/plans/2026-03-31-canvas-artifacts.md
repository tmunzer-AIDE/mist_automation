# Canvas Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add inline artifact rendering (code, markdown, html, mermaid, svg, chart) to the AI Chat system with iframe sandboxing, system prompt tiers, and accordion expand.

**Architecture:** The LLM is instructed via system prompt to wrap rich content in `<artifact>` tags. A new frontend parser extracts these tags, and a new card component renders each artifact in a sandboxed iframe. The system prompt instructions are tier-based (full/explicit/none) with auto-detection from provider+model and admin override.

**Tech Stack:** Angular 21 (standalone components, signals), Chart.js, highlight.js, mermaid.js, marked+DOMPurify (existing), FastAPI/Beanie (existing)

**Spec:** `docs/superpowers/specs/2026-03-31-canvas-artifacts-design.md`

---

### Task 1: Backend -- Canvas Prompt Builder

**Files:**
- Modify: `backend/app/modules/llm/services/prompt_builders.py` (append after line 449)
- Test: `backend/tests/unit/test_prompt_builders_canvas.py`

- [ ] **Step 1: Write tests for `build_canvas_instructions()`**

Create `backend/tests/unit/test_prompt_builders_canvas.py`:

```python
"""Tests for canvas artifact prompt instructions."""
import pytest
from app.modules.llm.services.prompt_builders import build_canvas_instructions


def test_full_tier_contains_artifact_rules():
    result = build_canvas_instructions("full")
    assert "<artifact" in result
    assert "code" in result
    assert "markdown" in result
    assert "html" in result
    assert "mermaid" in result
    assert "svg" in result
    assert "chart" in result
    assert "title" in result


def test_explicit_tier_contains_example():
    result = build_canvas_instructions("explicit")
    assert "<artifact" in result
    assert "Example" in result or "example" in result
    assert "Do NOT wrap" in result or "do not wrap" in result.lower()


def test_none_tier_returns_empty():
    result = build_canvas_instructions("none")
    assert result == ""


def test_full_and_explicit_both_have_chart_spec():
    for tier in ("full", "explicit"):
        result = build_canvas_instructions(tier)
        assert "chartType" in result
        assert "datasets" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/unit/test_prompt_builders_canvas.py -v`
Expected: FAIL with `ImportError` -- function doesn't exist yet.

- [ ] **Step 3: Implement `build_canvas_instructions()`**

Add to `backend/app/modules/llm/services/prompt_builders.py` after the last function (after line 449):

```python
# -- Canvas Artifact Instructions -----------------------------------------------


_CANVAS_INSTRUCTIONS_FULL = """\


## Canvas Artifacts

When your response contains rich content, wrap it in an <artifact> tag instead of a markdown code block:

<artifact type="TYPE" title="Short descriptive title">
content
</artifact>

Supported types:

| Type | When to use | Extra attributes |
|------|-------------|-----------------|
| code | Code snippets longer than 15 lines | language="python|json|jinja2|bash|yaml|..." (required) |
| markdown | Structured reports, detailed analysis, long documents | |
| html | Rich formatted tables, styled content, custom layouts | |
| mermaid | Diagrams, flowcharts, network topologies | |
| svg | Vector graphics, simple diagrams | |
| chart | Data visualizations (bar, line, pie, doughnut, radar) | JSON spec (see below) |

Chart artifact content must be a JSON object:
{"chartType": "bar", "data": {"labels": [...], "datasets": [{"label": "...", "data": [...]}]}, "options": {}}

Rules:
- One artifact per response unless the user explicitly asks for more
- Short code snippets (under 15 lines) stay inline as markdown code blocks
- Prose and explanations go OUTSIDE the artifact tag, before or after it
- The title attribute is always required
- When asked to update an artifact, return the full updated content"""

_CANVAS_INSTRUCTIONS_EXPLICIT_EXTRA = """

IMPORTANT: Do NOT wrap the <artifact> tag inside a markdown code block. The tag goes directly in your response text.

### Example

User: Show me a Python script that pings a list of hosts.
Assistant: Here is a script that pings each host and reports the result.

<artifact type="code" language="python" title="Host Ping Script">
import subprocess
import sys

hosts = ["8.8.8.8", "1.1.1.1", "10.0.0.1"]
for host in hosts:
    result = subprocess.run(
        ["ping", "-c", "1", "-W", "2", host],
        capture_output=True,
        text=True,
    )
    status = "UP" if result.returncode == 0 else "DOWN"
    print(f"{host}: {status}")

print("Scan complete.")
</artifact>

The script pings each host once with a 2-second timeout.

### Chart Example

<artifact type="chart" title="Device Health">
{"chartType": "doughnut", "data": {"labels": ["Healthy", "Warning", "Critical"], "datasets": [{"data": [45, 12, 3]}]}, "options": {}}
</artifact>"""


def build_canvas_instructions(tier: str) -> str:
    """Return canvas artifact instructions for the given prompt tier.

    Args:
        tier: One of "full", "explicit", or "none".

    Returns:
        Prompt text to append to system prompts, or "" for "none".
    """
    if tier == "none":
        return ""
    if tier == "explicit":
        return _CANVAS_INSTRUCTIONS_FULL + _CANVAS_INSTRUCTIONS_EXPLICIT_EXTRA
    # "full" or any unrecognised value
    return _CANVAS_INSTRUCTIONS_FULL
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/unit/test_prompt_builders_canvas.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/modules/llm/services/prompt_builders.py tests/unit/test_prompt_builders_canvas.py
git commit -m "feat(canvas): add build_canvas_instructions() prompt builder with full/explicit/none tiers"
```

---

### Task 2: Backend -- LLMConfig Model and Schema Changes

**Files:**
- Modify: `backend/app/modules/llm/models.py:15-32` (LLMConfig class)
- Modify: `backend/app/modules/llm/schemas.py:12-52` (Create/Update/Response schemas)
- Test: `backend/tests/unit/test_canvas_config.py`

- [ ] **Step 1: Write test for canvas_prompt_tier on LLMConfig**

Create `backend/tests/unit/test_canvas_config.py`:

```python
"""Tests for canvas_prompt_tier on LLMConfig and schemas."""
import pytest
from pydantic import ValidationError
from app.modules.llm.schemas import LLMConfigCreate, LLMConfigUpdate, LLMConfigResponse


def test_config_create_accepts_canvas_tier():
    config = LLMConfigCreate(name="test", provider="openai", canvas_prompt_tier="full")
    assert config.canvas_prompt_tier == "full"


def test_config_create_default_none():
    config = LLMConfigCreate(name="test", provider="openai")
    assert config.canvas_prompt_tier is None


def test_config_create_rejects_invalid_tier():
    with pytest.raises(ValidationError):
        LLMConfigCreate(name="test", provider="openai", canvas_prompt_tier="invalid")


def test_config_update_accepts_canvas_tier():
    update = LLMConfigUpdate(canvas_prompt_tier="explicit")
    assert update.canvas_prompt_tier == "explicit"


def test_config_response_includes_canvas_fields():
    resp = LLMConfigResponse(
        id="abc",
        name="test",
        provider="openai",
        api_key_set=True,
        model="gpt-4o",
        base_url=None,
        temperature=0.3,
        max_tokens_per_request=4096,
        is_default=True,
        enabled=True,
        canvas_prompt_tier=None,
        canvas_prompt_tier_effective="full",
    )
    assert resp.canvas_prompt_tier is None
    assert resp.canvas_prompt_tier_effective == "full"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/unit/test_canvas_config.py -v`
Expected: FAIL -- fields don't exist yet.

- [ ] **Step 3: Add `canvas_prompt_tier` to LLMConfig model**

In `backend/app/modules/llm/models.py`, add after the `enabled` field (line 27):

```python
    canvas_prompt_tier: str | None = Field(default=None, description="Canvas prompt tier override: full, explicit, none, or None for auto-detect")
```

- [ ] **Step 4: Add `canvas_prompt_tier` to schemas**

In `backend/app/modules/llm/schemas.py`:

Add to `LLMConfigCreate` (after `enabled: bool = True` on line 23):

```python
    canvas_prompt_tier: str | None = Field(None, pattern=r"^(full|explicit|none)$")
```

Add to `LLMConfigUpdate` (after `enabled: bool | None = None` on line 37):

```python
    canvas_prompt_tier: str | None = Field(None, pattern=r"^(full|explicit|none)$")
```

Add to `LLMConfigResponse` (after `enabled: bool` on line 52):

```python
    canvas_prompt_tier: str | None
    canvas_prompt_tier_effective: str
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/unit/test_canvas_config.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/modules/llm/models.py app/modules/llm/schemas.py tests/unit/test_canvas_config.py
git commit -m "feat(canvas): add canvas_prompt_tier field to LLMConfig model and schemas"
```

---

### Task 3: Backend -- Auto-Detect Tier and Factory Changes

**Files:**
- Modify: `backend/app/modules/llm/services/llm_service_factory.py` (add function after line 103)
- Test: `backend/tests/unit/test_canvas_tier_detection.py`

- [ ] **Step 1: Write tests for `_default_canvas_tier()`**

Create `backend/tests/unit/test_canvas_tier_detection.py`:

```python
"""Tests for canvas prompt tier auto-detection."""
import pytest
from app.modules.llm.services.llm_service_factory import _default_canvas_tier


def test_openai_gpt4_is_full():
    assert _default_canvas_tier("openai", "gpt-4o") == "full"
    assert _default_canvas_tier("openai", "gpt-4-turbo") == "full"


def test_openai_gpt35_is_explicit():
    assert _default_canvas_tier("openai", "gpt-3.5-turbo") == "explicit"


def test_anthropic_is_full():
    assert _default_canvas_tier("anthropic", "claude-sonnet-4-20250514") == "full"
    assert _default_canvas_tier("anthropic", None) == "full"


def test_vertex_gemini2_is_full():
    assert _default_canvas_tier("vertex", "gemini-2.0-flash") == "full"


def test_vertex_gemini1_is_explicit():
    assert _default_canvas_tier("vertex", "gemini-1.5-flash") == "explicit"


def test_bedrock_is_full():
    assert _default_canvas_tier("bedrock", "anthropic.claude-sonnet-4-20250514-v1:0") == "full"


def test_ollama_is_explicit():
    assert _default_canvas_tier("ollama", "llama3.1") == "explicit"


def test_lm_studio_is_explicit():
    assert _default_canvas_tier("lm_studio", "local-model") == "explicit"


def test_unknown_provider_defaults_to_explicit():
    assert _default_canvas_tier("unknown", "some-model") == "explicit"


def test_none_model_handled():
    assert _default_canvas_tier("ollama", None) == "explicit"
    assert _default_canvas_tier("openai", None) == "explicit"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/unit/test_canvas_tier_detection.py -v`
Expected: FAIL -- `_default_canvas_tier` doesn't exist yet.

- [ ] **Step 3: Implement `_default_canvas_tier()`**

Add to `backend/app/modules/llm/services/llm_service_factory.py` after `_default_model()` (after line 103):

```python


def _default_canvas_tier(provider: str, model: str | None) -> str:
    """Auto-detect canvas prompt tier from provider and model name.

    Returns "full" for large models that follow instructions well,
    "explicit" for smaller models that need verbose examples.
    """
    model_lower = (model or "").lower()

    # Providers where all models are capable
    if provider == "anthropic":
        return "full"
    if provider == "bedrock":
        return "full"

    # OpenAI: GPT-4+ is full, others explicit
    if provider in ("openai", "azure_openai"):
        if "gpt-4" in model_lower:
            return "full"
        return "explicit"

    # Vertex: Gemini 2+ is full
    if provider == "vertex":
        if "gemini-2" in model_lower:
            return "full"
        return "explicit"

    # Local providers default to explicit
    if provider in ("ollama", "lm_studio"):
        return "explicit"

    return "explicit"


def get_effective_canvas_tier(config) -> str:
    """Resolve the effective canvas tier for a config.

    If config.canvas_prompt_tier is set, use it.
    Otherwise, auto-detect from provider and model.
    """
    if config.canvas_prompt_tier:
        return config.canvas_prompt_tier
    return _default_canvas_tier(config.provider, config.model)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/unit/test_canvas_tier_detection.py -v`
Expected: All 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/modules/llm/services/llm_service_factory.py tests/unit/test_canvas_tier_detection.py
git commit -m "feat(canvas): add _default_canvas_tier() auto-detection and get_effective_canvas_tier()"
```

---

### Task 4: Backend -- Wire Canvas Instructions into Router Endpoints

**Files:**
- Modify: `backend/app/modules/llm/router.py` (helper + global_chat + all summarization endpoints + config response)

- [ ] **Step 1: Add `_get_canvas_instructions()` helper**

In `backend/app/modules/llm/router.py`, add a new helper function after `_check_llm_rate_limit` (around line 108):

```python
async def _get_canvas_instructions() -> str:
    """Load the effective canvas tier from the default LLM config and return instructions."""
    from app.modules.llm.models import LLMConfig as LLMConfigModel
    from app.modules.llm.services.llm_service_factory import get_effective_canvas_tier
    from app.modules.llm.services.prompt_builders import build_canvas_instructions

    default_config = await LLMConfigModel.find_one(LLMConfigModel.is_default == True, LLMConfigModel.enabled == True)  # noqa: E712
    if not default_config:
        return ""
    return build_canvas_instructions(get_effective_canvas_tier(default_config))
```

- [ ] **Step 2: Append canvas instructions in `global_chat` endpoint**

In the `global_chat` function (line 1462), after `system_prompt = build_global_chat_system_prompt(current_user.roles)` (line 1480) and before the skills catalog append (line 1481), add:

```python
    canvas_instr = await _get_canvas_instructions()
    if canvas_instr:
        system_prompt += "\n\n" + canvas_instr
```

- [ ] **Step 3: Append canvas instructions in all 5 summarization endpoints**

For each of the following endpoints, add canvas injection after the `prompt_messages = build_*_prompt(...)` line:

- `summarize_webhook_events` (line 1247): after line 1260
- `summarize_dashboard` (line 1282): after line 1296
- `summarize_audit_logs` (line 1322): after its `build_audit_log_summary_prompt()` call
- `summarize_system_logs` (line 1373): after its `build_system_log_summary_prompt()` call
- `summarize_backups` (line 1417): after its `build_backup_list_summary_prompt()` call

Add this 3-line block in each:

```python
    canvas_instr = await _get_canvas_instructions()
    if canvas_instr and prompt_messages and prompt_messages[0]["role"] == "system":
        prompt_messages[0]["content"] += "\n\n" + canvas_instr
```

- [ ] **Step 4: Update config response builder to include canvas fields**

Find where `LLMConfigResponse` is constructed in the config CRUD handlers (search for `LLMConfigResponse(`). Add:

```python
    canvas_prompt_tier=config.canvas_prompt_tier,
    canvas_prompt_tier_effective=get_effective_canvas_tier(config),
```

Import `get_effective_canvas_tier` from `app.modules.llm.services.llm_service_factory` at the point of use.

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/modules/llm/router.py
git commit -m "feat(canvas): wire canvas instructions into global chat and all summarization endpoints"
```

---

### Task 5: Frontend -- Artifact Model and Parser Service

**Files:**
- Modify: `frontend/src/app/core/models/llm.model.ts` (add Artifact interface)
- Create: `frontend/src/app/shared/services/artifact-parser.service.ts`
- Test: `frontend/src/app/shared/services/artifact-parser.service.spec.ts`

- [ ] **Step 1: Add Artifact interface to llm.model.ts**

In `frontend/src/app/core/models/llm.model.ts`, add after the `SkillGitRepo` interface (after line 133):

```typescript

export type ArtifactType = 'code' | 'markdown' | 'html' | 'mermaid' | 'svg' | 'chart';

export interface Artifact {
  id: string;
  type: ArtifactType;
  title: string;
  language?: string;
  content: string;
}

export interface ParsedContent {
  prose: string;
  artifacts: Artifact[];
}
```

Also add `canvas_prompt_tier` to the `LlmConfig` interface (after `enabled: boolean` on line 25):

```typescript
  canvas_prompt_tier: string | null;
  canvas_prompt_tier_effective: string;
```

- [ ] **Step 2: Write tests for ArtifactParserService**

Create `frontend/src/app/shared/services/artifact-parser.service.spec.ts`:

```typescript
import { ArtifactParserService } from './artifact-parser.service';

describe('ArtifactParserService', () => {
  let service: ArtifactParserService;

  beforeEach(() => {
    service = new ArtifactParserService();
  });

  it('returns prose unchanged when no artifacts', () => {
    const result = service.parse('Hello world');
    expect(result.prose).toBe('Hello world');
    expect(result.artifacts).toEqual([]);
  });

  it('extracts a code artifact', () => {
    const input = 'Here is code:\n<artifact type="code" language="python" title="Test">print("hi")</artifact>\nDone.';
    const result = service.parse(input);
    expect(result.artifacts.length).toBe(1);
    expect(result.artifacts[0].type).toBe('code');
    expect(result.artifacts[0].language).toBe('python');
    expect(result.artifacts[0].title).toBe('Test');
    expect(result.artifacts[0].content).toBe('print("hi")');
    expect(result.prose).toContain('Here is code:');
    expect(result.prose).toContain('[artifact:');
    expect(result.prose).toContain('Done.');
  });

  it('extracts a chart artifact with JSON', () => {
    const json = '{"chartType":"bar","data":{"labels":["A"],"datasets":[{"data":[1]}]},"options":{}}';
    const input = `<artifact type="chart" title="Stats">${json}</artifact>`;
    const result = service.parse(input);
    expect(result.artifacts[0].type).toBe('chart');
    expect(result.artifacts[0].content).toBe(json);
  });

  it('extracts multiple artifacts', () => {
    const input = '<artifact type="code" language="js" title="A">a()</artifact> and <artifact type="html" title="B"><p>hi</p></artifact>';
    const result = service.parse(input);
    expect(result.artifacts.length).toBe(2);
  });

  it('strips markdown code block wrapping around artifact tag', () => {
    const input = '```\n<artifact type="code" language="python" title="X">code()</artifact>\n```';
    const result = service.parse(input);
    expect(result.artifacts.length).toBe(1);
    expect(result.artifacts[0].content).toBe('code()');
  });

  it('auto-promotes large code blocks without artifact tags', () => {
    const lines = Array.from({ length: 20 }, (_, i) => `line ${i}`).join('\n');
    const input = '```python\n' + lines + '\n```';
    const result = service.parse(input);
    expect(result.artifacts.length).toBe(1);
    expect(result.artifacts[0].type).toBe('code');
    expect(result.artifacts[0].language).toBe('python');
  });

  it('does not auto-promote small code blocks', () => {
    const input = '```python\nprint("hi")\n```';
    const result = service.parse(input);
    expect(result.artifacts.length).toBe(0);
    expect(result.prose).toContain('```python');
  });

  it('defaults missing type to markdown', () => {
    const input = '<artifact title="Note">some text</artifact>';
    const result = service.parse(input);
    expect(result.artifacts[0].type).toBe('markdown');
  });

  it('generates title when missing', () => {
    const input = '<artifact type="code" language="python">x = 1</artifact>';
    const result = service.parse(input);
    expect(result.artifacts[0].title).toBeTruthy();
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npx ng test --watch=false --include='**/artifact-parser*'`
Expected: FAIL -- file doesn't exist.

- [ ] **Step 4: Implement ArtifactParserService**

Create `frontend/src/app/shared/services/artifact-parser.service.ts`:

```typescript
import { Injectable } from '@angular/core';
import { Artifact, ArtifactType, ParsedContent } from '../../core/models/llm.model';

const AUTO_PROMOTE_LINE_THRESHOLD = 15;

const DEFAULT_TITLES: Record<string, string> = {
  code: 'Code Snippet',
  markdown: 'Document',
  html: 'HTML Content',
  mermaid: 'Diagram',
  svg: 'SVG Graphic',
  chart: 'Chart',
};

const VALID_TYPES = new Set<ArtifactType>(['code', 'markdown', 'html', 'mermaid', 'svg', 'chart']);

@Injectable({ providedIn: 'root' })
export class ArtifactParserService {
  parse(text: string): ParsedContent {
    // Step 1: Strip markdown code block wrapping around artifact tags
    let cleaned = text.replace(/```\w*\n(<artifact[\s\S]*?<\/artifact>)\n```/g, '$1');

    const artifacts: Artifact[] = [];
    let prose = cleaned;

    // Step 2: Extract <artifact> tags
    const attrRegex = /<artifact\s+([^>]*)>([\s\S]*?)<\/artifact>/g;
    let match: RegExpExecArray | null;

    while ((match = attrRegex.exec(cleaned)) !== null) {
      const attrsStr = match[1];
      const content = match[2];

      const type = (this._extractAttr(attrsStr, 'type') as ArtifactType) || 'markdown';
      const title = this._extractAttr(attrsStr, 'title') || DEFAULT_TITLES[type] || 'Artifact';
      const language = this._extractAttr(attrsStr, 'language') || undefined;

      const artifact: Artifact = {
        id: crypto.randomUUID(),
        type: VALID_TYPES.has(type) ? type : 'markdown',
        title,
        language,
        content: content.trim(),
      };
      artifacts.push(artifact);
      prose = prose.replace(match[0], `[artifact:${artifact.id}]`);
    }

    // Step 3: Auto-promote large code blocks (only if no artifacts were found via tags)
    if (artifacts.length === 0) {
      const codeRegex = /```(\w+)?\n([\s\S]*?)```/g;
      let codeMatch: RegExpExecArray | null;
      while ((codeMatch = codeRegex.exec(prose)) !== null) {
        const lang = codeMatch[1] || undefined;
        const code = codeMatch[2];
        const lineCount = code.split('\n').length;
        if (lineCount >= AUTO_PROMOTE_LINE_THRESHOLD) {
          const artifact: Artifact = {
            id: crypto.randomUUID(),
            type: 'code',
            title: DEFAULT_TITLES['code'],
            language: lang,
            content: code.trim(),
          };
          artifacts.push(artifact);
          prose = prose.replace(codeMatch[0], `[artifact:${artifact.id}]`);
        }
      }
    }

    return { prose: prose.trim(), artifacts };
  }

  /**
   * Detect if text contains an opening <artifact tag (for streaming).
   * Returns the parsed attributes if found, null otherwise.
   */
  detectOpeningTag(text: string): { type: ArtifactType; title: string; language?: string } | null {
    const openMatch = /<artifact\s+([^>]*)>/.exec(text);
    if (!openMatch) return null;
    const attrs = openMatch[1];
    const type = (this._extractAttr(attrs, 'type') as ArtifactType) || 'markdown';
    const title = this._extractAttr(attrs, 'title') || DEFAULT_TITLES[type] || 'Artifact';
    const language = this._extractAttr(attrs, 'language') || undefined;
    return { type: VALID_TYPES.has(type) ? type : 'markdown', title, language };
  }

  /** Check if text contains a closing </artifact> tag. */
  hasClosingTag(text: string): boolean {
    return text.includes('</artifact>');
  }

  private _extractAttr(attrsStr: string, name: string): string | null {
    const re = new RegExp(`${name}="([^"]*)"`, 'i');
    const m = re.exec(attrsStr);
    return m ? m[1] : null;
  }
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx ng test --watch=false --include='**/artifact-parser*'`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
cd frontend
git add src/app/core/models/llm.model.ts src/app/shared/services/artifact-parser.service.ts src/app/shared/services/artifact-parser.service.spec.ts
git commit -m "feat(canvas): add Artifact interfaces and ArtifactParserService with tests"
```

---

### Task 6: Frontend -- Artifact Card Component

**Files:**
- Create: `frontend/src/app/shared/components/artifact-card/artifact-card.component.ts`

- [ ] **Step 1: Create the ArtifactCardComponent**

Create `frontend/src/app/shared/components/artifact-card/artifact-card.component.ts`:

```typescript
import {
  Component,
  ElementRef,
  OnDestroy,
  computed,
  inject,
  input,
  signal,
  viewChild,
  Injector,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Artifact } from '../../../core/models/llm.model';
import { ThemeService } from '../../../core/services/theme.service';

const TYPE_LABELS: Record<string, { label: string; color: string }> = {
  code: { label: 'Code', color: '#60a5fa' },
  markdown: { label: 'Document', color: '#a78bfa' },
  html: { label: 'HTML', color: '#f472b6' },
  mermaid: { label: 'Diagram', color: '#34d399' },
  svg: { label: 'SVG', color: '#fb923c' },
  chart: { label: 'Chart', color: '#fbbf24' },
};

@Component({
  selector: 'app-artifact-card',
  standalone: true,
  imports: [MatButtonModule, MatIconModule, MatTooltipModule],
  template: `
    <div class="artifact-card" [class.expanded]="expanded()">
      <div class="artifact-header" (click)="toggle()">
        <span class="type-badge" [style.background]="badgeColor()">{{ badgeLabel() }}</span>
        <span class="artifact-title">{{ artifact().title }}</span>
        <span class="header-actions">
          <button mat-icon-button matTooltip="Copy" (click)="copy($event)" class="copy-btn">
            <mat-icon>content_copy</mat-icon>
          </button>
          <mat-icon class="expand-icon">{{ expanded() ? 'expand_less' : 'expand_more' }}</mat-icon>
        </span>
      </div>
      @if (state() === 'loading') {
        <div class="artifact-loading">
          <div class="shimmer"></div>
          <div class="shimmer short"></div>
        </div>
      } @else if (expanded()) {
        <div class="artifact-body">
          <iframe
            #iframeEl
            [srcdoc]="srcdoc()"
            sandbox="allow-scripts"
            (load)="onIframeLoad()"
          ></iframe>
        </div>
      } @else {
        <div class="artifact-preview" (click)="toggle()">
          <pre>{{ preview() }}</pre>
        </div>
      }
    </div>
  `,
  styles: `
    :host { display: block; }

    .artifact-card {
      border: 1px solid var(--mat-sys-outline-variant);
      border-radius: 8px;
      overflow: hidden;
      max-width: 100%;
    }

    .artifact-header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      background: var(--mat-sys-surface-container);
      cursor: pointer;
      user-select: none;
    }

    .type-badge {
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 10px;
      color: white;
      font-weight: 500;
      white-space: nowrap;
    }

    .artifact-title {
      font-size: 13px;
      color: var(--mat-sys-on-surface);
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 2px;
      margin-left: auto;
    }

    .copy-btn {
      width: 28px;
      height: 28px;
      --mdc-icon-button-icon-size: 16px;
    }

    .expand-icon {
      font-size: 20px;
      color: var(--mat-sys-on-surface-variant);
    }

    .artifact-preview {
      padding: 8px 12px;
      cursor: pointer;
      background: var(--mat-sys-surface-container-low);
    }

    .artifact-preview pre {
      margin: 0;
      font-size: 11px;
      color: var(--mat-sys-on-surface-variant);
      overflow: hidden;
      max-height: 48px;
      white-space: pre-wrap;
      word-break: break-all;
    }

    .artifact-body {
      background: var(--mat-sys-surface-container-low);
    }

    .artifact-body iframe {
      width: 100%;
      border: none;
      display: block;
      max-height: 600px;
      overflow: auto;
    }

    .artifact-loading {
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .shimmer {
      height: 14px;
      border-radius: 4px;
      background: linear-gradient(
        90deg,
        var(--mat-sys-surface-container) 25%,
        var(--mat-sys-surface-container-high) 50%,
        var(--mat-sys-surface-container) 75%
      );
      background-size: 200% 100%;
      animation: shimmer 1.5s ease-in-out infinite;
    }

    .shimmer.short { width: 60%; }

    @keyframes shimmer {
      0% { background-position: 200% 0; }
      100% { background-position: -200% 0; }
    }
  `,
})
export class ArtifactCardComponent implements OnDestroy {
  artifact = input.required<Artifact>();
  state = input<'loading' | 'ready'>('ready');

  expanded = signal(false);

  private readonly snackBar = inject(MatSnackBar);
  private readonly themeService = inject(ThemeService);
  private readonly iframeEl = viewChild<ElementRef<HTMLIFrameElement>>('iframeEl');
  private messageListener: ((e: MessageEvent) => void) | null = null;

  badgeLabel = computed(() => TYPE_LABELS[this.artifact().type]?.label ?? this.artifact().type);
  badgeColor = computed(() => TYPE_LABELS[this.artifact().type]?.color ?? '#888');

  preview = computed(() => {
    const content = this.artifact().content;
    const lines = content.split('\n').slice(0, 3);
    const text = lines.join('\n');
    return text.length > 200 ? text.slice(0, 200) + '...' : text;
  });

  srcdoc = computed(() => this._buildSrcdoc(this.artifact(), this.themeService.isDark()));

  toggle(): void {
    this.expanded.update((v) => !v);
  }

  copy(event: Event): void {
    event.stopPropagation();
    navigator.clipboard.writeText(this.artifact().content);
    this.snackBar.open('Copied to clipboard', '', { duration: 2000 });
  }

  onIframeLoad(): void {
    if (this.messageListener) window.removeEventListener('message', this.messageListener);
    this.messageListener = (e: MessageEvent) => {
      if (e.data?.type === 'artifact-height') {
        const iframe = this.iframeEl()?.nativeElement;
        if (iframe) {
          iframe.style.height = Math.min(e.data.height + 16, 600) + 'px';
        }
      }
    };
    window.addEventListener('message', this.messageListener);
  }

  ngOnDestroy(): void {
    if (this.messageListener) window.removeEventListener('message', this.messageListener);
  }

  private _buildSrcdoc(artifact: Artifact, isDark: boolean): string {
    const bg = isDark ? '#1e1e2e' : '#ffffff';
    const fg = isDark ? '#cdd6f4' : '#1e1e2e';
    const codeBg = isDark ? '#14141e' : '#f5f5f5';

    const baseStyle = `
      <style>
        * { box-sizing: border-box; }
        body { margin: 0; padding: 12px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: ${bg}; color: ${fg}; font-size: 14px; line-height: 1.6; }
        pre { background: ${codeBg}; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 13px; margin: 0; }
        code { font-family: 'SF Mono', 'Fira Code', monospace; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid ${isDark ? '#333' : '#ddd'}; padding: 6px 10px; text-align: left; font-size: 13px; }
        th { background: ${isDark ? '#252535' : '#f0f0f0'}; }
      </style>
    `;

    const heightScript = `
      <script>
        function reportHeight() {
          parent.postMessage({ type: 'artifact-height', height: document.body.scrollHeight }, '*');
        }
        window.addEventListener('load', reportHeight);
        new ResizeObserver(reportHeight).observe(document.body);
      </script>
    `;

    switch (artifact.type) {
      case 'code':
        return `<!DOCTYPE html><html><head>${baseStyle}
          <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/${isDark ? 'github-dark' : 'github'}.min.css">
          <script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/highlight.min.js"><\/script>
          ${heightScript}
          </head><body>
          <pre><code class="language-${artifact.language || 'plaintext'}">${this._escapeHtml(artifact.content)}</code></pre>
          <script>hljs.highlightAll();<\/script>
          </body></html>`;

      case 'markdown':
        return `<!DOCTYPE html><html><head>${baseStyle}
          <script src="https://cdn.jsdelivr.net/npm/marked@12.0.0/marked.min.js"><\/script>
          <script src="https://cdn.jsdelivr.net/npm/dompurify@3.0.9/dist/purify.min.js"><\/script>
          ${heightScript}
          </head><body>
          <div id="content"></div>
          <script>
            document.getElementById('content').innerHTML = DOMPurify.sanitize(marked.parse(${JSON.stringify(artifact.content)}));
          <\/script>
          </body></html>`;

      case 'html':
        return `<!DOCTYPE html><html><head>${baseStyle}${heightScript}</head><body>${artifact.content}</body></html>`;

      case 'mermaid':
        return `<!DOCTYPE html><html><head>${baseStyle}
          <script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.0/dist/mermaid.min.js"><\/script>
          ${heightScript}
          </head><body>
          <pre class="mermaid">${this._escapeHtml(artifact.content)}</pre>
          <script>mermaid.initialize({ startOnLoad: true, theme: '${isDark ? 'dark' : 'default'}' });<\/script>
          </body></html>`;

      case 'svg':
        return `<!DOCTYPE html><html><head>${baseStyle}${heightScript}</head><body>${artifact.content}</body></html>`;

      case 'chart': {
        const colors = isDark
          ? "['#60a5fa','#34d399','#fbbf24','#f472b6','#a78bfa','#fb923c']"
          : "['#3b82f6','#10b981','#f59e0b','#ec4899','#8b5cf6','#f97316']";
        return `<!DOCTYPE html><html><head>${baseStyle}
          <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"><\/script>
          ${heightScript}
          </head><body>
          <canvas id="chart" style="max-height:500px"></canvas>
          <script>
            try {
              var spec = ${JSON.stringify(artifact.content)};
              var parsed = JSON.parse(spec);
              var colors = ${colors};
              parsed.data.datasets.forEach(function(ds, i) {
                if (!ds.backgroundColor) ds.backgroundColor = colors;
                if (!ds.borderColor && parsed.chartType !== 'pie' && parsed.chartType !== 'doughnut') ds.borderColor = colors[i % colors.length];
              });
              new Chart(document.getElementById('chart'), {
                type: parsed.chartType || 'bar',
                data: parsed.data,
                options: Object.assign({}, parsed.options, { responsive: true, maintainAspectRatio: true }),
              });
            } catch (e) {
              document.body.innerHTML = '<pre style="color:#ef4444">Invalid chart spec: ' + e.message + '<\/pre>';
            }
          <\/script>
          </body></html>`;
      }

      default:
        return `<!DOCTYPE html><html><head>${baseStyle}${heightScript}</head><body><pre>${this._escapeHtml(artifact.content)}</pre></body></html>`;
    }
  }

  private _escapeHtml(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
}
```

- [ ] **Step 2: Verify component compiles**

Run: `cd frontend && npx ng build --configuration=development 2>&1 | tail -5`
Expected: Build succeeds (component is tree-shaken if not imported yet, but should compile).

- [ ] **Step 3: Commit**

```bash
cd frontend
git add src/app/shared/components/artifact-card/artifact-card.component.ts
git commit -m "feat(canvas): add ArtifactCardComponent with iframe rendering for all artifact types"
```

---

### Task 7: Frontend -- Integrate Artifacts into AiChatPanelComponent

**Files:**
- Modify: `frontend/src/app/shared/components/ai-chat-panel/ai-chat-panel.component.ts`

This is the core integration task. Changes: extend TimelineItem, import parser + card, modify streaming, modify effects, update template.

- [ ] **Step 1: Add imports**

In `ai-chat-panel.component.ts`, add to the imports section (after line 31):

```typescript
import { ArtifactCardComponent } from '../artifact-card/artifact-card.component';
import { ArtifactParserService } from '../../services/artifact-parser.service';
import { Artifact } from '../../../core/models/llm.model';
```

Add `ArtifactCardComponent` to the `imports` array in the `@Component` decorator.

- [ ] **Step 2: Extend TimelineItem type**

Replace the `TimelineItem` type (lines 41-43) with:

```typescript
export type TimelineItem =
  | { kind: 'message'; role: 'user' | 'assistant'; content: string; html: string }
  | { kind: 'tool'; tool: string; server: string; status: 'running' | 'success' | 'error'; resultPreview?: string; expanded: boolean }
  | { kind: 'artifact'; artifact: Artifact; state: 'loading' | 'ready'; expanded: boolean };
```

- [ ] **Step 3: Add streaming state fields to the component class**

Add to the component class body:

```typescript
  private readonly artifactParser = inject(ArtifactParserService);
  private _artifactBuffer: string | null = null;
  private _artifactMeta: { type: string; title: string; language?: string } | null = null;
```

- [ ] **Step 4: Add `_buildArtifactTimeline()` helper method**

Add a private method to the component class:

```typescript
  /** Parse content through artifact parser and return timeline items. */
  private _buildArtifactTimeline(content: string, role: 'user' | 'assistant'): TimelineItem[] {
    if (role === 'user') {
      return [{ kind: 'message', role, content, html: '' }];
    }
    const parsed = this.artifactParser.parse(content);
    if (parsed.artifacts.length === 0) {
      return [{ kind: 'message', role, content, html: renderMarkdown(content) }];
    }
    const items: TimelineItem[] = [];
    const parts = parsed.prose.split(/\[artifact:[^\]]+\]/);
    const placeholders = [...parsed.prose.matchAll(/\[artifact:([^\]]+)\]/g)];
    for (let i = 0; i < parts.length; i++) {
      const text = parts[i].trim();
      if (text) {
        items.push({ kind: 'message', role, content: text, html: renderMarkdown(text) });
      }
      if (i < placeholders.length) {
        const artifactId = placeholders[i][1];
        const artifact = parsed.artifacts.find((a) => a.id === artifactId);
        if (artifact) {
          items.push({ kind: 'artifact', artifact, state: 'ready', expanded: false });
        }
      }
    }
    return items;
  }
```

- [ ] **Step 5: Modify `_subscribeToStream()` token handler for artifact detection**

In the `_subscribeToStream` method (line 929), replace the `token` handler block (lines 978-993) with:

```typescript
        } else if (msg.type === 'token') {
          if (needsNewBubble) {
            streamedContent = '';
            needsNewBubble = false;
          }
          this.waitingAfterTool.set(false);
          streamedContent += msg.content ?? '';

          if (this._artifactBuffer !== null) {
            // Buffering artifact content
            this._artifactBuffer += msg.content ?? '';
            if (this.artifactParser.hasClosingTag(this._artifactBuffer)) {
              // Artifact complete -- parse and render
              const items = this._buildArtifactTimeline(streamedContent, 'assistant');
              this.timeline.update((tl) => {
                const trimmed = tl.filter(
                  (item, idx) =>
                    !(item.kind === 'artifact' && item.state === 'loading') &&
                    !(idx === tl.length - 1 && item.kind === 'message' && item.role === 'assistant'),
                );
                return [...trimmed, ...items];
              });
              this._artifactBuffer = null;
              this._artifactMeta = null;
            }
          } else {
            const tagMeta = this.artifactParser.detectOpeningTag(streamedContent);
            if (tagMeta && !this.artifactParser.hasClosingTag(streamedContent)) {
              // Opening tag detected -- start buffering
              this._artifactMeta = tagMeta;
              this._artifactBuffer = '';
              const proseBeforeTag = streamedContent.split(/<artifact/)[0].trim();
              this.timeline.update((tl) => {
                const newTl = [...tl];
                const last = newTl[newTl.length - 1];
                if (last?.kind === 'message' && last.role === 'assistant') {
                  if (proseBeforeTag) {
                    newTl[newTl.length - 1] = { kind: 'message', role: 'assistant', content: proseBeforeTag, html: renderMarkdown(proseBeforeTag) };
                  } else {
                    newTl.pop();
                  }
                }
                const loadingArtifact: Artifact = {
                  id: crypto.randomUUID(),
                  type: tagMeta.type as Artifact['type'],
                  title: tagMeta.title,
                  language: tagMeta.language,
                  content: '',
                };
                newTl.push({ kind: 'artifact', artifact: loadingArtifact, state: 'loading', expanded: false });
                return newTl;
              });
            } else if (tagMeta && this.artifactParser.hasClosingTag(streamedContent)) {
              // Complete artifact in one chunk
              const items = this._buildArtifactTimeline(streamedContent, 'assistant');
              this.timeline.update((tl) => {
                const last = tl[tl.length - 1];
                if (last?.kind === 'message' && last.role === 'assistant') {
                  return [...tl.slice(0, -1), ...items];
                }
                return [...tl, ...items];
              });
            } else {
              // Normal text
              const entry: TimelineItem = { kind: 'message', role: 'assistant', content: streamedContent, html: renderMarkdown(streamedContent) };
              this.timeline.update((tl) => {
                const last = tl[tl.length - 1];
                if (last?.kind === 'message' && last.role === 'assistant') {
                  return [...tl.slice(0, -1), entry];
                }
                return [...tl, entry];
              });
            }
          }
          this.scrollToBottom();
```

- [ ] **Step 6: Handle truncated artifacts on `done` event**

Replace the `done` handler (lines 1002-1004) with:

```typescript
        } else if (msg.type === 'done') {
          if (this._artifactBuffer !== null && this._artifactMeta) {
            const truncatedArtifact: Artifact = {
              id: crypto.randomUUID(),
              type: (this._artifactMeta.type as Artifact['type']) || 'code',
              title: this._artifactMeta.title + ' (Truncated)',
              language: this._artifactMeta.language,
              content: this._artifactBuffer,
            };
            this.timeline.update((tl) => {
              const filtered = tl.filter((item) => !(item.kind === 'artifact' && item.state === 'loading'));
              return [...filtered, { kind: 'artifact' as const, artifact: truncatedArtifact, state: 'ready' as const, expanded: false }];
            });
            this._artifactBuffer = null;
            this._artifactMeta = null;
          }
          this.streamSub?.unsubscribe();
          this.streamSub = null;
        }
```

- [ ] **Step 7: Modify `initialSummary` effect for artifact parsing**

Replace the `initialSummary` effect (lines 808-824) with:

```typescript
    effect(() => {
      const summary = this.initialSummary();
      if (!summary) return;
      untracked(() => {
        const items = this._buildArtifactTimeline(summary, 'assistant');
        this.timeline.update((tl) => {
          let trimIdx = tl.length;
          while (trimIdx > 0 && tl[trimIdx - 1].kind === 'message' && (tl[trimIdx - 1] as { role: string }).role === 'assistant') {
            trimIdx--;
          }
          const base = tl.slice(0, trimIdx).filter((item) => !(item.kind === 'artifact' && item.state === 'loading'));
          return [...base, ...items];
        });
      });
      this.streamSub?.unsubscribe();
      this.streamSub = null;
      this._artifactBuffer = null;
      this._artifactMeta = null;
      this.scrollToBottom();
    });
```

- [ ] **Step 8: Modify `initialMessages` effect for artifact parsing on thread load**

In the `initialMessages` effect (lines 826-860), replace the message rendering block (lines 853-856) with:

```typescript
        if (m.role === 'assistant' && m.content?.trim()) {
          const parsed = this._buildArtifactTimeline(m.content, 'assistant');
          tl.push(...parsed);
        } else if (m.role === 'user' || m.content?.trim()) {
          tl.push({ kind: 'message', role: m.role as 'user' | 'assistant', content: m.content, html: m.role === 'assistant' ? renderMarkdown(m.content) : '' });
        }
```

- [ ] **Step 9: Update template to render artifact cards**

In the template `@for` loop (lines 66-116), add an artifact case. Replace the `} @else {` at line 93 with:

```html
          } @else if (item.kind === 'artifact') {
            <div class="chat-message assistant">
              <div class="avatar assistant-avatar">
                <app-ai-icon [size]="16"></app-ai-icon>
              </div>
              <div class="message-bubble artifact-bubble">
                <app-artifact-card
                  [artifact]="item.artifact"
                  [state]="item.state"
                />
              </div>
            </div>
          } @else {
```

- [ ] **Step 10: Add CSS for artifact bubble**

Add to the component styles:

```css
    .artifact-bubble {
      padding: 0 !important;
      overflow: hidden;
      background: transparent !important;
      border: none !important;
    }
```

- [ ] **Step 11: Reset artifact state in `reset()` and `startStream()`**

In `reset()` (line 1017) and `startStream()` (line 1010), add:

```typescript
    this._artifactBuffer = null;
    this._artifactMeta = null;
```

- [ ] **Step 12: Verify build compiles**

Run: `cd frontend && npx ng build --configuration=development 2>&1 | tail -5`
Expected: Build succeeds.

- [ ] **Step 13: Commit**

```bash
cd frontend
git add src/app/shared/components/ai-chat-panel/ai-chat-panel.component.ts
git commit -m "feat(canvas): integrate artifact parsing and rendering into AiChatPanelComponent"
```

---

### Task 8: Frontend -- LLM Config Admin UI for Canvas Tier

**Files:**
- Modify: `frontend/src/app/features/admin/settings/llm/llm-config-dialog.component.ts`

- [ ] **Step 1: Add canvas_prompt_tier form control**

In the `form` definition (lines 209-219), add after the `enabled` control:

```typescript
  canvas_prompt_tier: [null as string | null],
```

- [ ] **Step 2: Add canvas tier dropdown to template**

In the template, after the "Enabled" toggle section (around line 145), add:

```html
        <mat-form-field appearance="outline" class="full-width">
          <mat-label>Canvas Prompt Tier</mat-label>
          <mat-select formControlName="canvas_prompt_tier">
            <mat-option [value]="null">Auto-detect</mat-option>
            <mat-option value="full">Full (large models)</mat-option>
            <mat-option value="explicit">Explicit (small models)</mat-option>
            <mat-option value="none">Disabled</mat-option>
          </mat-select>
          <mat-hint>Controls canvas artifact instructions in system prompts</mat-hint>
        </mat-form-field>
```

Add `MatSelectModule` to the component imports if not already present.

- [ ] **Step 3: Patch form on edit**

In the `ngOnInit` form patching section (lines 221-235), ensure the `canvas_prompt_tier` is included:

```typescript
      canvas_prompt_tier: config.canvas_prompt_tier ?? null,
```

- [ ] **Step 4: Verify build compiles**

Run: `cd frontend && npx ng build --configuration=development 2>&1 | tail -5`
Expected: Build succeeds.

- [ ] **Step 5: Commit**

```bash
cd frontend
git add src/app/features/admin/settings/llm/llm-config-dialog.component.ts
git commit -m "feat(canvas): add canvas prompt tier dropdown to LLM config admin dialog"
```

---

### Task 9: Update CLAUDE.md Documentation

**Files:**
- Modify: `backend/app/modules/llm/CLAUDE.md`
- Modify: `frontend/CLAUDE.md`

- [ ] **Step 1: Update LLM module CLAUDE.md**

Add to `backend/app/modules/llm/CLAUDE.md` in the Backend section, after the Agent Skills bullet:

```markdown
- **Canvas artifacts**: `build_canvas_instructions(tier)` in `prompt_builders.py` appends artifact tag instructions to system prompts. Three tiers: `full` (concise rules for large models), `explicit` (verbose + examples for small models), `none` (disabled). `_default_canvas_tier()` and `get_effective_canvas_tier()` in `llm_service_factory.py` auto-detect from provider+model with admin override via `LLMConfig.canvas_prompt_tier`. `_get_canvas_instructions()` helper in `router.py` loads the default config tier and returns instructions -- called by global chat and all summarization endpoints.
```

Add to the Frontend section, after the Skills admin bullet:

```markdown
- **Canvas artifacts**: `ArtifactParserService` extracts `<artifact>` tags from LLM output into `Artifact` objects (type, title, language, content). `ArtifactCardComponent` renders each artifact in a sandboxed `<iframe srcdoc>` with per-type templates (highlight.js for code, mermaid.js for diagrams, Chart.js for charts, marked+DOMPurify for markdown). Inline expandable cards in chat timeline with accordion expand. During streaming, opening `<artifact>` tags trigger a loading placeholder; content is buffered until `</artifact>` detected. Fallback: large code blocks (15+ lines) without artifact tags auto-promote. Theme-aware via CSS injection into iframes.
```

- [ ] **Step 2: Update frontend CLAUDE.md**

Add to `frontend/CLAUDE.md` in the Key Patterns section:

```markdown
- **Artifact rendering**: `ArtifactCardComponent` (`shared/components/artifact-card/`) renders LLM artifacts in sandboxed iframes. `ArtifactParserService` (`shared/services/`) parses `<artifact>` tags. Both integrated into `AiChatPanelComponent` timeline -- no per-page changes needed for summarization features.
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/modules/llm/CLAUDE.md frontend/CLAUDE.md
git commit -m "docs: update CLAUDE.md files with canvas artifact architecture"
```

---

### Task 10: End-to-End Verification

- [ ] **Step 1: Run all backend tests**

Run: `cd backend && .venv/bin/pytest tests/unit/ -v --tb=short`
Expected: All tests pass, including the new canvas tests.

- [ ] **Step 2: Run all frontend tests**

Run: `cd frontend && npx ng test --watch=false`
Expected: All tests pass.

- [ ] **Step 3: Run lint checks**

Run: `cd backend && .venv/bin/ruff check . && cd ../frontend && npx ng lint`
Expected: No lint errors.

- [ ] **Step 4: Build frontend production**

Run: `cd frontend && npx ng build`
Expected: Production build succeeds.

- [ ] **Step 5: Manual smoke test**

Start both backend and frontend dev servers. Open the AI Chat. Send a message that should trigger an artifact (e.g., "Show me a summary of the last 24h config changes as a chart"). Verify:
1. The artifact card renders inline in the chat
2. Expand/collapse works
3. Copy button copies raw content
4. Iframe renders correctly with theme-appropriate colors
5. Thread reload preserves artifacts

- [ ] **Step 6: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix(canvas): address smoke test findings"
```
