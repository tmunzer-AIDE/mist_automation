# AI Panel Phase 1: Persistent Split Layout

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the floating AI chat FAB with a persistent, resizable side panel integrated into the app shell layout — making AI the primary interaction surface.

**Architecture:** The layout changes from `sidebar + full-width content` to `sidebar + AI panel + resize handle + content`. The AI panel absorbs both the `GlobalChatComponent` (FAB popup) and the `/ai-chats` page (thread management). `AiChatPanel` is reused unchanged. When LLM is disabled, the panel hides and the layout reverts to full-width.

**Tech Stack:** Angular 21 standalone components, Angular Material, signals, CSS custom properties, localStorage for state persistence.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `frontend/src/app/core/services/panel-state.service.ts` | Persists panel width + collapsed state per route in localStorage |
| Create | `frontend/src/app/shared/components/ai-panel/ai-panel.component.ts` | Persistent split panel: header, context breadcrumb, thread drawer, chat, input |
| Modify | `frontend/src/app/layout/layout.component.ts` | Import AiPanel, add split layout with resize handle |
| Modify | `frontend/src/app/layout/layout.component.html` | Replace `<app-global-chat>` with `<app-ai-panel>` + resize handle structure |
| Modify | `frontend/src/app/layout/layout.component.scss` | Split layout CSS: panel + handle + content flex layout |
| Modify | `frontend/src/app/core/services/global-chat.service.ts` | Add `toggle()` method + `panelOpen` signal for keyboard shortcut |
| Modify | `frontend/src/app/app.routes.ts` | Remove `/ai-chats` route |
| Modify | `frontend/src/app/layout/sidebar/nav-items.config.ts` | Remove AI Chats nav item (if present) |
| Delete | `frontend/src/app/features/ai-chats/ai-chats.component.ts` | Replaced by AiPanel's thread drawer |
| Delete | `frontend/src/app/features/ai-chats/ai-chats.routes.ts` | Route removed |

---

### Task 1: PanelStateService

**Files:**
- Create: `frontend/src/app/core/services/panel-state.service.ts`

- [ ] **Step 1: Create PanelStateService**

```typescript
// frontend/src/app/core/services/panel-state.service.ts
import { Injectable, signal } from '@angular/core';

const STORAGE_KEY = 'ai-panel-state';
const DEFAULT_WIDTH = 380;
const MIN_WIDTH = 280;
const MAX_WIDTH_RATIO = 0.6;

interface PersistedState {
  width: number;
  collapsed: boolean;
}

@Injectable({ providedIn: 'root' })
export class PanelStateService {
  readonly width = signal(DEFAULT_WIDTH);
  readonly collapsed = signal(false);

  constructor() {
    this._load();
  }

  setWidth(px: number): void {
    const clamped = Math.max(MIN_WIDTH, Math.min(px, window.innerWidth * MAX_WIDTH_RATIO));
    this.width.set(clamped);
    this._save();
  }

  toggleCollapsed(): void {
    this.collapsed.update((v) => !v);
    this._save();
  }

  setCollapsed(value: boolean): void {
    this.collapsed.set(value);
    this._save();
  }

  get minWidth(): number {
    return MIN_WIDTH;
  }

  get maxWidthRatio(): number {
    return MAX_WIDTH_RATIO;
  }

  private _load(): void {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const state: PersistedState = JSON.parse(raw);
        if (typeof state.width === 'number') this.width.set(state.width);
        if (typeof state.collapsed === 'boolean') this.collapsed.set(state.collapsed);
      }
    } catch {
      // Ignore corrupt storage
    }
  }

  private _save(): void {
    const state: PersistedState = { width: this.width(), collapsed: this.collapsed() };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng build --configuration production 2>&1 | tail -5`
Expected: Build succeeds (unused service is tree-shaken, no errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/core/services/panel-state.service.ts
git commit -m "feat(frontend): add PanelStateService for AI panel width/collapsed persistence"
```

---

### Task 2: GlobalChatService — Add toggle + panelOpen signal

**Files:**
- Modify: `frontend/src/app/core/services/global-chat.service.ts`

- [ ] **Step 1: Add panelOpen signal and toggle method**

Add to `GlobalChatService`:

```typescript
// After the existing openChat$ subject, add:
/** Whether the AI panel is currently visible */
readonly panelOpen = signal(true);

/** Toggle AI panel visibility (for keyboard shortcut) */
toggle(): void {
  this.panelOpen.update((v) => !v);
}
```

Also update the `open()` method to ensure the panel is visible when triggered:

```typescript
/** Open the global chat, optionally with a pre-filled message */
open(message?: string): void {
  this.panelOpen.set(true);
  this.openChat$.next({ message });
}
```

The full file after edits:

```typescript
import { Injectable, signal } from '@angular/core';
import { Observable, Subject } from 'rxjs';

export interface PageContext {
  /** Current page name (e.g., "Backup Object Detail", "Workflow Editor") */
  page: string;
  /** Key details about what the user is viewing */
  details?: Record<string, string | number | null>;
}

@Injectable({ providedIn: 'root' })
export class GlobalChatService {
  private readonly openChat$ = new Subject<{ message?: string }>();

  /** Current page context — set by each page component on init */
  readonly context = signal<PageContext | null>(null);

  /** Whether the AI panel is currently visible */
  readonly panelOpen = signal(true);

  /** Set the current page context (called by page components) */
  setContext(ctx: PageContext): void {
    this.context.set(ctx);
  }

  /** Clear context (called on component destroy if needed) */
  clearContext(): void {
    this.context.set(null);
  }

  /** Toggle AI panel visibility (for keyboard shortcut) */
  toggle(): void {
    this.panelOpen.update((v) => !v);
  }

  /** Open the global chat, optionally with a pre-filled message */
  open(message?: string): void {
    this.panelOpen.set(true);
    this.openChat$.next({ message });
  }

  /** Observable for chat open events */
  onOpen(): Observable<{ message?: string }> {
    return this.openChat$.asObservable();
  }

  /** Build a context string for the LLM from current page state */
  buildContextString(): string {
    const ctx = this.context();
    if (!ctx) return '';

    const parts = [`The user is currently viewing: ${ctx.page}`];
    if (ctx.details) {
      for (const [key, value] of Object.entries(ctx.details)) {
        if (value !== null && value !== undefined && value !== '') {
          parts.push(`${key}: ${value}`);
        }
      }
    }
    return parts.join('\n');
  }
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng build --configuration production 2>&1 | tail -5`
Expected: Build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/core/services/global-chat.service.ts
git commit -m "feat(frontend): add panelOpen signal and toggle() to GlobalChatService"
```

---

### Task 3: AiPanelComponent

**Files:**
- Create: `frontend/src/app/shared/components/ai-panel/ai-panel.component.ts`

This is the main component. It absorbs the FAB's chat logic AND the `/ai-chats` page's thread management. It reuses `AiChatPanel` unchanged.

- [ ] **Step 1: Create AiPanelComponent**

```typescript
// frontend/src/app/shared/components/ai-panel/ai-panel.component.ts
import { Component, DestroyRef, ElementRef, Injector, afterNextRender, computed, inject, OnInit, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { ConversationThreadSummary, McpConfigAvailable } from '../../../core/models/llm.model';
import { LlmService } from '../../../core/services/llm.service';
import { GlobalChatService } from '../../../core/services/global-chat.service';
import { AiChatPanelComponent, ChatMessage } from '../ai-chat-panel/ai-chat-panel.component';
import { AiIconComponent } from '../ai-icon/ai-icon.component';
import { extractErrorMessage } from '../../utils/error.utils';

interface ThreadGroup {
  label: string;
  threads: ConversationThreadSummary[];
}

const FEATURE_LABELS: Record<string, string> = {
  global_chat: 'Chat',
  backup_summary: 'Backup',
  workflow_assist: 'Workflow',
  workflow_debug: 'Debug',
  webhook_summary: 'Webhooks',
  impact_analysis_chat: 'Impact',
};

function renderMarkdown(md: string): string {
  return DOMPurify.sanitize(marked.parse(md, { async: false }) as string);
}

function groupByDate(threads: ConversationThreadSummary[]): ThreadGroup[] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86_400_000);
  const last7 = new Date(today.getTime() - 7 * 86_400_000);

  const buckets: Record<string, ConversationThreadSummary[]> = {
    Today: [],
    Yesterday: [],
    'Previous 7 days': [],
    Older: [],
  };

  for (const t of threads) {
    const d = new Date(t.updated_at);
    if (d >= today) buckets['Today'].push(t);
    else if (d >= yesterday) buckets['Yesterday'].push(t);
    else if (d >= last7) buckets['Previous 7 days'].push(t);
    else buckets['Older'].push(t);
  }

  return Object.entries(buckets)
    .filter(([, items]) => items.length > 0)
    .map(([label, items]) => ({ label, threads: items }));
}

@Component({
  selector: 'app-ai-panel',
  standalone: true,
  imports: [
    MatButtonModule, MatIconModule, MatMenuModule, MatTooltipModule,
    AiChatPanelComponent, AiIconComponent,
  ],
  template: `
    <div class="ai-panel">
      <!-- Header -->
      <div class="panel-header">
        <div class="header-title">
          <app-ai-icon [size]="20"></app-ai-icon>
          <span>Assistant</span>
        </div>
        <div class="header-actions">
          <button mat-icon-button matTooltip="New Chat" (click)="newChat()" [disabled]="!threadId()">
            <mat-icon>add_comment</mat-icon>
          </button>
          <button
            mat-icon-button
            [matTooltip]="showHistory() ? 'Back to chat' : 'Chat history'"
            (click)="showHistory.update(v => !v)"
          >
            <mat-icon>{{ showHistory() ? 'chat' : 'history' }}</mat-icon>
          </button>
        </div>
      </div>

      <!-- Context breadcrumb -->
      @if (contextLabel() && !showHistory()) {
        <div class="context-bar">
          <mat-icon class="context-icon">location_on</mat-icon>
          <span class="context-text">{{ contextLabel() }}</span>
        </div>
      }

      @if (showHistory()) {
        <!-- Thread history drawer -->
        <div class="thread-drawer">
          @if (threads().length === 0) {
            <div class="drawer-empty">No conversations yet</div>
          }
          @for (group of threadGroups(); track group.label) {
            <div class="thread-group">
              <div class="group-label">{{ group.label }}</div>
              @for (thread of group.threads; track thread.id) {
                <div
                  class="thread-item"
                  [class.active]="thread.id === threadId()"
                  (click)="selectThread(thread)"
                >
                  <div class="thread-content">
                    <span class="thread-feature">{{ featureLabel(thread.feature) }}</span>
                    <span class="thread-preview">{{ thread.preview || 'New conversation' }}</span>
                  </div>
                  <button
                    class="thread-delete"
                    (click)="deleteThread(thread.id, $event)"
                    matTooltip="Delete"
                  >
                    <mat-icon>close</mat-icon>
                  </button>
                </div>
              }
            </div>
          }
        </div>
      } @else {
        <!-- Chat area -->
        <div class="panel-body">
          @if (!threadId() && !sending()) {
            <div class="welcome">
              <app-ai-icon [size]="40" class="welcome-icon-wrap"></app-ai-icon>
              <p>Ask me anything about your Mist infrastructure.</p>
              <p class="welcome-hint">I can query backups, workflows, device events, and more.</p>
            </div>
          }
          <app-ai-chat-panel
            #chatPanel
            [threadId]="threadId()"
            [initialSummary]="replySummary()"
            [initialMessages]="loadedMessages()"
            [errorMessage]="chatError()"
            [parentLoading]="sending() || loadingThread()"
            [loadingLabel]="loadingThread() ? 'Loading...' : 'Thinking...'"
            [mcpConfigs]="availableMcpConfigs()"
            [(mcpConfigIds)]="selectedMcpIds"
          ></app-ai-chat-panel>
        </div>

        @if (!threadId()) {
          <div class="initial-input">
            <div class="chat-input-box">
              <textarea
                #initialInput
                class="chat-textarea"
                [value]="inputText"
                (input)="inputText = $any($event.target).value; autoGrow($event)"
                (keydown.enter)="onEnter($event)"
                placeholder="Ask a question..."
                rows="1"
              ></textarea>
              <div class="chat-input-actions">
                @if (availableMcpConfigs().length > 0) {
                  <button class="mcp-toggle" [class.active]="selectedMcpIds().length > 0" [matMenuTriggerFor]="mcpMenu" [matTooltip]="mcpTooltipText()">
                    <mat-icon>hub</mat-icon>
                    <span>{{ selectedMcpIds().length }}</span>
                  </button>
                  <mat-menu #mcpMenu="matMenu">
                    @for (cfg of availableMcpConfigs(); track cfg.id) {
                      <button mat-menu-item (click)="toggleMcp(cfg.id); $event.stopPropagation()">
                        <mat-icon>{{ selectedMcpIds().includes(cfg.id) ? 'check_box' : 'check_box_outline_blank' }}</mat-icon>
                        {{ cfg.name }}
                      </button>
                    }
                  </mat-menu>
                }
                <span class="spacer"></span>
                <button class="send-button" (click)="sendFirst()" [disabled]="sending() || !inputText.trim()">
                  <mat-icon>arrow_upward</mat-icon>
                </button>
              </div>
            </div>
          </div>
        }
      }
    </div>
  `,
  styles: [`
    :host {
      display: flex;
      flex-direction: column;
      height: 100%;
      overflow: hidden;
    }

    .ai-panel {
      display: flex;
      flex-direction: column;
      height: 100%;
      background: var(--mat-sys-surface);
    }

    /* ── Header ──────────────────────────────────────────── */

    .panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 4px 4px 4px 16px;
      border-bottom: 1px solid var(--mat-sys-outline-variant);
      background: var(--mat-sys-surface-container);
      flex-shrink: 0;
      min-height: 48px;
    }

    .header-title {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 14px;
      font-weight: 600;
    }

    .header-actions {
      display: flex;
    }

    /* ── Context breadcrumb ───────────────────────────────── */

    .context-bar {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 6px 16px;
      font-size: 11px;
      color: var(--mat-sys-on-surface-variant);
      background: var(--mat-sys-surface-container-low);
      border-bottom: 1px solid var(--mat-sys-outline-variant);
      flex-shrink: 0;
      min-height: 0;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }

    .context-icon {
      font-size: 14px;
      width: 14px;
      height: 14px;
      flex-shrink: 0;
      opacity: 0.6;
    }

    .context-text {
      overflow: hidden;
      text-overflow: ellipsis;
    }

    /* ── Thread history drawer ────────────────────────────── */

    .thread-drawer {
      flex: 1;
      overflow-y: auto;
      padding: 8px;
      scrollbar-width: thin;
      scrollbar-color: rgba(128, 128, 128, 0.3) transparent;
    }

    .drawer-empty {
      padding: 32px 16px;
      text-align: center;
      font-size: 13px;
      color: var(--app-neutral);
    }

    .thread-group {
      margin-bottom: 4px;
    }

    .group-label {
      padding: 12px 12px 6px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--app-neutral);
    }

    .thread-item {
      display: flex;
      align-items: center;
      gap: 4px;
      padding: 10px 12px;
      border-radius: 8px;
      cursor: pointer;
      transition: background 0.1s ease;

      &:hover {
        background: var(--mat-sys-surface-container-high, rgba(0, 0, 0, 0.04));

        .thread-delete { opacity: 1; }
      }

      &.active {
        background: var(--mat-sys-secondary-container, rgba(0, 0, 0, 0.08));
      }
    }

    .thread-content {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 2px;
    }

    .thread-feature {
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.3px;
      color: var(--mat-sys-primary);
    }

    .thread-preview {
      font-size: 13px;
      color: var(--mat-sys-on-surface);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .thread-delete {
      flex-shrink: 0;
      width: 24px;
      height: 24px;
      border: none;
      border-radius: 4px;
      background: transparent;
      color: var(--app-neutral);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      opacity: 0;
      transition: opacity 0.1s ease, color 0.1s ease;

      mat-icon { font-size: 16px; width: 16px; height: 16px; }
      &:hover { color: var(--app-error); }
    }

    /* ── Chat body ────────────────────────────────────────── */

    .panel-body {
      flex: 1;
      min-height: 0;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }

    .welcome {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 32px 20px 12px;
      text-align: center;
      color: var(--mat-sys-on-surface-variant);
    }

    .welcome-icon-wrap {
      margin-bottom: 10px;
      opacity: 0.7;
    }

    .welcome p {
      margin: 0 0 4px;
      font-size: 13px;
    }

    .welcome-hint {
      font-size: 11px !important;
      opacity: 0.7;
    }

    /* ── Initial input (no thread yet) ────────────────────── */

    .initial-input {
      padding: 12px;
      border-top: 1px solid var(--mat-sys-outline-variant);
    }

    .chat-input-box {
      border: 1px solid var(--mat-sys-outline-variant);
      border-radius: 16px;
      background: var(--mat-sys-surface-container);
      padding: 6px;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      transition: border-color 0.15s ease, box-shadow 0.15s ease;

      &:focus-within {
        border-color: var(--mat-sys-primary);
        box-shadow: 0 0 0 1px var(--mat-sys-primary);
      }
    }

    .chat-textarea {
      width: 100%;
      border: none;
      padding: 6px 10px;
      font: inherit;
      font-size: 13px;
      line-height: 1.5;
      resize: none;
      background: transparent;
      color: var(--mat-sys-on-surface);
      outline: none;

      &::placeholder { color: var(--app-neutral); }
    }

    .chat-input-actions {
      display: flex;
      align-items: center;
      padding: 0 4px;
    }

    .spacer { flex: 1; }

    .mcp-toggle {
      display: flex;
      align-items: center;
      gap: 4px;
      padding: 4px 8px;
      border: 1px solid var(--mat-sys-outline-variant);
      border-radius: 12px;
      background: transparent;
      color: var(--app-neutral);
      font-size: 11px;
      cursor: pointer;
      transition: border-color 0.15s ease, color 0.15s ease;

      mat-icon { font-size: 16px; width: 16px; height: 16px; }
      &.active { color: var(--mat-sys-primary); border-color: var(--mat-sys-primary); }
    }

    .send-button {
      flex-shrink: 0;
      width: 32px;
      height: 32px;
      border-radius: 50%;
      border: none;
      background: var(--mat-sys-primary);
      color: var(--mat-sys-on-primary);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: opacity 0.15s ease;

      &:hover:not(:disabled) { opacity: 0.85; }
      &:disabled { background: var(--app-neutral); opacity: 0.3; cursor: not-allowed; }
      mat-icon { font-size: 18px; width: 18px; height: 18px; }
    }
  `],
})
export class AiPanelComponent implements OnInit {
  private readonly llmService = inject(LlmService);
  private readonly globalChatService = inject(GlobalChatService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly injector = inject(Injector);
  private readonly chatPanel = viewChild<AiChatPanelComponent>('chatPanel');
  private readonly initialInput = viewChild<ElementRef<HTMLTextAreaElement>>('initialInput');

  // Thread state
  threadId = signal<string | null>(null);
  replySummary = signal<string | null>(null);
  chatError = signal<string | null>(null);
  loadedMessages = signal<ChatMessage[]>([]);
  sending = signal(false);
  loadingThread = signal(false);
  inputText = '';

  // Thread list
  threads = signal<ConversationThreadSummary[]>([]);
  showHistory = signal(false);
  threadGroups = computed(() => groupByDate(this.threads()));

  // MCP
  availableMcpConfigs = signal<McpConfigAvailable[]>([]);
  selectedMcpIds = signal<string[]>([]);

  // Context
  contextLabel = computed(() => {
    const ctx = this.globalChatService.context();
    return ctx ? ctx.page : '';
  });

  ngOnInit(): void {
    // Listen for external open requests (from sidebar impact alerts, dashboard, etc.)
    this.globalChatService.onOpen().pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
      this.showHistory.set(false);
      if (event.message) {
        this.inputText = event.message;
        setTimeout(() => this.sendFirst(), 100);
      } else {
        afterNextRender(() => this.initialInput()?.nativeElement.focus(), { injector: this.injector });
      }
    });

    // Load MCP configs
    this.llmService.listAvailableMcpConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (configs) => this.availableMcpConfigs.set(configs),
    });

    // Load thread list
    this.loadThreads();
  }

  // ── Thread management ──────────────────────────────────

  loadThreads(): void {
    this.llmService.listThreads(0, 50).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (res) => this.threads.set(res.threads),
    });
  }

  selectThread(thread: ConversationThreadSummary): void {
    if (this.threadId() === thread.id) {
      this.showHistory.set(false);
      return;
    }
    this.chatPanel()?.reset();
    this.threadId.set(thread.id);
    this.loadingThread.set(true);
    this.loadedMessages.set([]);
    this.replySummary.set(null);
    this.chatError.set(null);

    this.llmService.getThread(thread.id).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (detail) => {
        const msgs: ChatMessage[] = detail.messages
          .filter((m) => m.role !== 'system')
          .map((m) => ({
            role: m.role as 'user' | 'assistant',
            content: m.content,
            html: m.role === 'assistant' ? renderMarkdown(m.content) : '',
            metadata: m.metadata,
          }));
        this.loadedMessages.set(msgs);
        this.selectedMcpIds.set(detail.mcp_config_ids || []);
        this.loadingThread.set(false);
        this.showHistory.set(false);
      },
      error: () => this.loadingThread.set(false),
    });
  }

  newChat(): void {
    this.chatPanel()?.reset();
    this.threadId.set(null);
    this.replySummary.set(null);
    this.chatError.set(null);
    this.loadedMessages.set([]);
    this.selectedMcpIds.set([]);
    this.inputText = '';
    this.showHistory.set(false);
    afterNextRender(() => this.initialInput()?.nativeElement.focus(), { injector: this.injector });
  }

  deleteThread(id: string, event: Event): void {
    event.stopPropagation();
    this.llmService.deleteThread(id).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: () => {
        this.threads.update((t) => t.filter((th) => th.id !== id));
        if (this.threadId() === id) {
          this.newChat();
        }
      },
    });
  }

  featureLabel(feature: string): string {
    return FEATURE_LABELS[feature] ?? feature;
  }

  // ── Chat input ─────────────────────────────────────────

  toggleMcp(id: string): void {
    this.selectedMcpIds.update((ids) =>
      ids.includes(id) ? ids.filter((i) => i !== id) : [...ids, id],
    );
  }

  mcpTooltipText = computed(() => {
    const ids = new Set(this.selectedMcpIds());
    const names = this.availableMcpConfigs().filter((c) => ids.has(c.id)).map((c) => c.name);
    return names.length ? 'MCP: ' + names.join(', ') : 'No MCP servers active';
  });

  autoGrow(event: Event): void {
    const el = event.target as HTMLTextAreaElement;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 180) + 'px';
  }

  onEnter(event: Event): void {
    const ke = event as KeyboardEvent;
    if (!ke.shiftKey) {
      ke.preventDefault();
      this.sendFirst();
    }
  }

  sendFirst(): void {
    const text = this.inputText.trim();
    if (!text || this.sending()) return;

    this.inputText = '';
    this.sending.set(true);
    this.chatError.set(null);

    const streamId = crypto.randomUUID();
    this.chatPanel()?.startStream(streamId, text);

    this.llmService
      .globalChat(text, this.threadId() || undefined, this.globalChatService.buildContextString() || undefined, streamId, this.selectedMcpIds())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.threadId.set(res.thread_id);
          this.replySummary.set(res.reply);
          this.sending.set(false);
          this.loadThreads();
        },
        error: (err) => {
          this.chatError.set(extractErrorMessage(err));
          this.sending.set(false);
        },
      });
  }
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng build --configuration production 2>&1 | tail -10`
Expected: Build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/shared/components/ai-panel/ai-panel.component.ts
git commit -m "feat(frontend): add AiPanelComponent — persistent split panel with thread history"
```

---

### Task 4: Layout Component — Split Layout with Resize Handle

**Files:**
- Modify: `frontend/src/app/layout/layout.component.ts`
- Modify: `frontend/src/app/layout/layout.component.html`
- Modify: `frontend/src/app/layout/layout.component.scss`

- [ ] **Step 1: Update layout.component.ts — imports + resize logic + keyboard shortcut**

Replace the full file:

```typescript
import { Component, inject, signal, HostListener } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpClient } from '@angular/common/http';
import { Router, RouterOutlet, NavigationEnd, ActivatedRoute } from '@angular/router';
import { BreakpointObserver, Breakpoints } from '@angular/cdk/layout';
import { MatSidenavModule } from '@angular/material/sidenav';
import { SidebarComponent } from './sidebar/sidebar.component';
import { TopbarComponent } from './topbar/topbar.component';
import { AiPanelComponent } from '../shared/components/ai-panel/ai-panel.component';
import { LlmService } from '../core/services/llm.service';
import { GlobalChatService } from '../core/services/global-chat.service';
import { PanelStateService } from '../core/services/panel-state.service';
import { filter, map } from 'rxjs';

@Component({
  selector: 'app-layout',
  standalone: true,
  imports: [RouterOutlet, MatSidenavModule, SidebarComponent, TopbarComponent, AiPanelComponent],
  templateUrl: './layout.component.html',
  styleUrl: './layout.component.scss',
})
export class LayoutComponent {
  private readonly router = inject(Router);
  private readonly activatedRoute = inject(ActivatedRoute);
  private readonly breakpointObserver = inject(BreakpointObserver);
  private readonly llmService = inject(LlmService);
  readonly globalChatService = inject(GlobalChatService);
  readonly panelState = inject(PanelStateService);

  isMobile = signal(false);
  sidebarOpen = signal(true);
  sidebarCollapsed = signal(false);
  isFullWidth = signal(false);
  llmAvailable = signal(false);
  maintenanceMode = signal(false);
  resizing = signal(false);

  constructor() {
    inject(HttpClient)
      .get<any>('/health')
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (h: any) => this.maintenanceMode.set(h.maintenance_mode ?? false),
        error: () => {},
      });

    this.llmService.getStatus().subscribe({
      next: (s) => this.llmAvailable.set(s.enabled),
      error: () => this.llmAvailable.set(false),
    });

    this.breakpointObserver
      .observe([Breakpoints.Handset])
      .pipe(takeUntilDestroyed())
      .subscribe((result) => {
        this.isMobile.set(result.matches);
        this.sidebarOpen.set(!result.matches);
      });

    this.router.events
      .pipe(
        filter((e): e is NavigationEnd => e instanceof NavigationEnd),
        map(() => {
          let route = this.activatedRoute;
          while (route.firstChild) route = route.firstChild;
          return route.snapshot.data;
        }),
        takeUntilDestroyed(),
      )
      .subscribe((data) => {
        this.isFullWidth.set(!!data['fullWidth']);
      });
  }

  toggleSidebar(): void {
    if (this.isMobile()) {
      this.sidebarOpen.update((v) => !v);
    } else {
      this.sidebarCollapsed.update((v) => !v);
    }
  }

  /** Whether the AI panel should render (LLM available + not mobile) */
  get showAiPanel(): boolean {
    return this.llmAvailable() && !this.isMobile() && this.globalChatService.panelOpen();
  }

  // ── Resize handle ──────────────────────────────────────

  onResizeStart(event: MouseEvent): void {
    event.preventDefault();
    this.resizing.set(true);

    const onMove = (e: MouseEvent) => {
      // Panel is on the left of content; width = mouse X - sidebar width
      const sidebarWidth = this.sidebarCollapsed() ? 56 : 240;
      const newWidth = e.clientX - sidebarWidth;
      this.panelState.setWidth(newWidth);
    };

    const onUp = () => {
      this.resizing.set(false);
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }

  // ── Keyboard shortcut (Ctrl+\) ────────────────────────

  @HostListener('document:keydown', ['$event'])
  onKeydown(event: KeyboardEvent): void {
    if (event.ctrlKey && event.key === '\\') {
      event.preventDefault();
      this.globalChatService.toggle();
    }
  }
}
```

- [ ] **Step 2: Update layout.component.html**

Replace the full template:

```html
<mat-sidenav-container
  class="layout-container"
  [class.desktop]="!isMobile()"
  [class.sidebar-collapsed]="sidebarCollapsed() && !isMobile()"
  [class.resizing]="resizing()"
>
  <mat-sidenav
    #sidenav
    [mode]="isMobile() ? 'over' : 'side'"
    [opened]="sidebarOpen()"
    (closedStart)="sidebarOpen.set(false)"
    class="sidenav"
    [class.collapsed]="sidebarCollapsed() && !isMobile()"
  >
    <app-sidebar [collapsed]="sidebarCollapsed() && !isMobile()"></app-sidebar>
  </mat-sidenav>

  <mat-sidenav-content>
    @if (maintenanceMode()) {
      <div class="maintenance-banner">
        System is in maintenance mode. Some features may be restricted.
      </div>
    }
    <app-topbar (toggleSidebar)="toggleSidebar()"></app-topbar>
    <div class="content-split" [class.has-panel]="showAiPanel">
      @if (showAiPanel) {
        <div class="ai-panel-wrapper" [style.width.px]="panelState.width()">
          <app-ai-panel></app-ai-panel>
        </div>
        <div
          class="resize-handle"
          (mousedown)="onResizeStart($event)"
        >
          <div class="resize-grip"></div>
        </div>
      }
      <main class="content" [class.full-width]="isFullWidth()">
        <router-outlet></router-outlet>
      </main>
    </div>
  </mat-sidenav-content>
</mat-sidenav-container>
```

- [ ] **Step 3: Update layout.component.scss**

Replace the full stylesheet:

```scss
.layout-container {
  height: 100%;

  &.desktop ::ng-deep .mat-sidenav-content {
    margin-left: 240px !important;
    transition: margin-left 0.2s ease !important;
  }

  &.desktop.sidebar-collapsed ::ng-deep .mat-sidenav-content {
    margin-left: 56px !important;
  }

  // Disable pointer events on iframe/canvas during resize to prevent capture
  &.resizing {
    iframe,
    canvas {
      pointer-events: none;
    }
  }
}

.sidenav {
  border-right: none;
  --mat-sidenav-container-width: 240px;
  transition: width 0.2s ease;

  &.collapsed {
    --mat-sidenav-container-width: 56px;
  }
}

.maintenance-banner {
  background: var(--app-warning, #f59e0b);
  color: #000;
  text-align: center;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 500;
}

// ── Split layout ──────────────────────────────────────

.content-split {
  display: flex;
  height: calc(100vh - 64px); // 64px topbar
  overflow: hidden;
}

.ai-panel-wrapper {
  flex-shrink: 0;
  height: 100%;
  overflow: hidden;
  border-right: 1px solid var(--mat-sys-outline-variant);
}

.resize-handle {
  flex-shrink: 0;
  width: 6px;
  cursor: col-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  transition: background 0.15s ease;
  position: relative;
  z-index: 10;

  &:hover,
  .resizing & {
    background: var(--mat-sys-primary-container, rgba(0, 120, 212, 0.08));
  }
}

.resize-grip {
  width: 2px;
  height: 32px;
  border-radius: 1px;
  background: var(--mat-sys-outline-variant);
  transition: background 0.15s ease, height 0.15s ease;

  .resize-handle:hover &,
  .resizing & {
    background: var(--mat-sys-primary);
    height: 48px;
  }
}

.content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 24px 32px;

  // Center content when no AI panel
  .content-split:not(.has-panel) & {
    max-width: 1200px;
    margin: 0 auto;
  }

  &.full-width {
    max-width: none;
    padding: 0;
    height: 100%;
    margin: 0;
  }
}
```

- [ ] **Step 4: Verify it compiles**

Run: `cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng build --configuration production 2>&1 | tail -10`
Expected: Build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/layout/layout.component.ts frontend/src/app/layout/layout.component.html frontend/src/app/layout/layout.component.scss
git commit -m "feat(frontend): split layout with persistent AI panel and resize handle"
```

---

### Task 5: Remove GlobalChatComponent and /ai-chats Route

**Files:**
- Modify: `frontend/src/app/app.routes.ts` — remove `/ai-chats` route
- Delete: `frontend/src/app/shared/components/global-chat/global-chat.component.ts`
- Delete: `frontend/src/app/features/ai-chats/ai-chats.component.ts`
- Delete: `frontend/src/app/features/ai-chats/ai-chats.routes.ts`

- [ ] **Step 1: Remove /ai-chats route from app.routes.ts**

Remove these lines from `app.routes.ts`:

```typescript
      {
        path: 'ai-chats',
        loadChildren: () => import('./features/ai-chats/ai-chats.routes'),
      },
```

The routes array children should go from `workflows` directly to `impact-analysis`.

- [ ] **Step 2: Delete the GlobalChatComponent file**

```bash
rm frontend/src/app/shared/components/global-chat/global-chat.component.ts
```

- [ ] **Step 3: Delete the ai-chats feature files**

```bash
rm frontend/src/app/features/ai-chats/ai-chats.component.ts
rm frontend/src/app/features/ai-chats/ai-chats.routes.ts
rmdir frontend/src/app/features/ai-chats
```

- [ ] **Step 4: Check for any remaining imports of deleted files**

Run: `cd /Users/tmunzer/4_dev/mist_automation/frontend && grep -r "global-chat\|ai-chats" src/app/ --include="*.ts" -l`

Fix any remaining references. The layout component was already updated in Task 4 to import `AiPanelComponent` instead of `GlobalChatComponent`. If the sidebar component references an "AI Chats" nav item, it should be removed too — check `nav-items.config.ts` (it currently has no AI Chats entry, so this should be clean).

- [ ] **Step 5: Verify it compiles**

Run: `cd /Users/tmunzer/4_dev/mist_automation/frontend && npx ng build --configuration production 2>&1 | tail -10`
Expected: Build succeeds with no errors about missing modules.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(frontend): remove GlobalChatComponent and /ai-chats route — replaced by AiPanel"
```

---

### Task 6: Visual Verification and Edge Cases

- [ ] **Step 1: Start dev server and verify the split layout**

Run: `cd /Users/tmunzer/4_dev/mist_automation/frontend && npm start`

Verify in browser at http://localhost:4200:
1. AI panel renders on the left of content with header, context bar, welcome state, and input
2. Resize handle between panel and content works (drag to resize)
3. `Ctrl+\` toggles panel visibility
4. Panel width persists across page refreshes (check localStorage for `ai-panel-state`)
5. Thread history drawer opens/closes with the history button
6. Sending a message creates a thread and streams the response
7. Thread list populates and clicking a thread loads it
8. New Chat button resets to welcome state
9. Context bar updates when navigating between pages

- [ ] **Step 2: Verify LLM-disabled fallback**

Disable LLM in admin settings (or set `llm_enabled = false` in SystemConfig). Reload the page.
Expected: AI panel is hidden, content takes full width, no resize handle, layout looks like the original.

- [ ] **Step 3: Verify mobile layout**

Resize browser to mobile width (< 600px).
Expected: AI panel is hidden on mobile (only shows on desktop), layout falls back to sidebar drawer + full-width content.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix(frontend): polish AI panel edge cases"
```

---

### Task 7: Update CLAUDE.md

**Files:**
- Modify: `frontend/CLAUDE.md`
- Modify: `CLAUDE.md` (root)

- [ ] **Step 1: Update frontend CLAUDE.md**

Add to the Architecture section, after the "Key Patterns" subsection, a note about the AI panel:

> **AI Panel**: Persistent split layout (`AiPanelComponent` in `shared/components/ai-panel/`). Renders as left pane next to page content when LLM is enabled. Thread history, chat, and context breadcrumb are integrated. `PanelStateService` persists width/collapsed to localStorage. `Ctrl+\` toggles visibility. Hidden on mobile and when LLM is disabled.

- [ ] **Step 2: Update root CLAUDE.md**

In the LLM Module's Frontend section, replace the GlobalChatComponent description:

Replace:
> **Global floating chat** (`shared/components/global-chat/`): Bottom-right FAB with glass style, expands to 420x560 chat panel. Uses `GlobalChatService` for open/pre-fill from any page. Passes `page_context` (current page + details) to the LLM.

With:
> **Persistent AI panel** (`shared/components/ai-panel/`): Left-side split panel integrated into the app shell layout. Includes header, context breadcrumb, thread history drawer, and chat area. Uses `GlobalChatService` for context awareness and `PanelStateService` for width/collapsed persistence (localStorage). `Ctrl+\` toggles visibility. Hidden on mobile and when LLM is disabled. Replaces the former floating FAB chat and `/ai-chats` page.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md frontend/CLAUDE.md
git commit -m "docs: update CLAUDE.md for AI panel split layout"
```
