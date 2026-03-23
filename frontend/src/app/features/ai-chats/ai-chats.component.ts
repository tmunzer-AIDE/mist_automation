import { Component, DestroyRef, OnInit, computed, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { MatBadgeModule } from '@angular/material/badge';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { ConversationThreadSummary, McpConfigAvailable } from '../../core/models/llm.model';
import { LlmService } from '../../core/services/llm.service';
import { TopbarService } from '../../core/services/topbar.service';
import { AiChatPanelComponent, ChatMessage } from '../../shared/components/ai-chat-panel/ai-chat-panel.component';
import { AiIconComponent } from '../../shared/components/ai-icon/ai-icon.component';

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
  selector: 'app-ai-chats',
  standalone: true,
  imports: [
    MatBadgeModule, MatButtonModule, MatCheckboxModule, MatIconModule, MatMenuModule, MatTooltipModule,
    AiChatPanelComponent, AiIconComponent,
  ],
  template: `
    <div class="ai-chats-page">
      <!-- Sidebar -->
      <aside class="thread-sidebar" [class.collapsed]="sidebarCollapsed()">
        <div class="sidebar-header">
          <button class="new-chat-btn" (click)="newChat()">
            <mat-icon>add</mat-icon>
            <span>New Chat</span>
          </button>
          <button
            mat-icon-button
            class="collapse-btn"
            (click)="sidebarCollapsed.update(v => !v)"
            [matTooltip]="sidebarCollapsed() ? 'Show sidebar' : 'Hide sidebar'"
          >
            <mat-icon>{{ sidebarCollapsed() ? 'chevron_right' : 'chevron_left' }}</mat-icon>
          </button>
        </div>

        @if (!sidebarCollapsed()) {
          <div class="thread-list">
            @if (threads().length === 0) {
              <div class="sidebar-empty">No conversations yet</div>
            }
            @for (group of threadGroups(); track group.label) {
              <div class="thread-group">
                <div class="group-label">{{ group.label }}</div>
                @for (thread of group.threads; track thread.id) {
                  <div
                    class="thread-item"
                    [class.active]="thread.id === activeThreadId()"
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
        }
      </aside>

      <!-- Main area -->
      <main class="main-area">
        @if (!activeThreadId() && !sending()) {
          <!-- Welcome state -->
          <div class="welcome-state">
            <app-ai-icon [size]="56" class="welcome-icon"></app-ai-icon>
            <h2 class="welcome-title">How can I help?</h2>
            <p class="welcome-subtitle">Ask me anything about your Mist infrastructure, backups, workflows, and more.</p>
            <div class="welcome-input-box">
              <textarea
                class="welcome-textarea"
                [value]="inputText"
                (input)="inputText = $any($event.target).value; autoGrow($event)"
                (keydown.enter)="onEnter($event)"
                placeholder="Ask a question..."
                rows="1"
              ></textarea>
              <div class="welcome-input-actions">
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
                <button class="welcome-send" (click)="sendFirst()" [disabled]="!inputText.trim()">
                  <mat-icon>arrow_upward</mat-icon>
                </button>
              </div>
            </div>
          </div>
        }
        <!-- Chat panel: always in DOM so startStream() can access it via viewChild -->
        <div class="chat-view" [class.hidden]="!activeThreadId() && !sending()">
          <app-ai-chat-panel
            #chatPanel
            [threadId]="activeThreadId()"
            [initialSummary]="replySummary()"
            [initialMessages]="loadedMessages()"
            [parentLoading]="sending() || loadingThread()"
            [loadingLabel]="loadingThread() ? 'Loading conversation...' : 'Thinking...'"
            [mcpConfigs]="availableMcpConfigs()"
            [(mcpConfigIds)]="selectedMcpIds"
          ></app-ai-chat-panel>
        </div>
      </main>
    </div>
  `,
  styles: [
    `
      :host {
        display: block;
        height: 100%;
      }

      .ai-chats-page {
        display: flex;
        height: 100%;
        background: var(--mat-sys-surface);
      }

      /* ── Sidebar ─────────────────────────────────────────── */

      .thread-sidebar {
        width: 280px;
        min-width: 280px;
        display: flex;
        flex-direction: column;
        background: var(--mat-sys-surface-container);
        border-right: 1px solid var(--mat-sys-outline-variant);
        transition: width 0.2s ease, min-width 0.2s ease;
        overflow: hidden;

        &.collapsed {
          width: 48px;
          min-width: 48px;
        }
      }

      .sidebar-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 12px;
        flex-shrink: 0;

        .collapsed & {
          justify-content: center;
          padding: 12px 4px;
        }
      }

      .new-chat-btn {
        flex: 1;

        .collapsed & {
          display: none;
        }
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 16px;
        border: 1px solid var(--mat-sys-outline-variant);
        border-radius: 10px;
        background: var(--mat-sys-surface);
        color: var(--mat-sys-on-surface);
        font: inherit;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: background 0.15s ease, border-color 0.15s ease;

        mat-icon {
          font-size: 18px;
          width: 18px;
          height: 18px;
        }

        &:hover {
          background: var(--mat-sys-surface-container-high, var(--mat-sys-surface));
          border-color: var(--mat-sys-primary);
        }
      }

      .collapse-btn {
        flex-shrink: 0;
      }

      .thread-list {
        flex: 1;
        overflow-y: auto;
        padding: 0 8px 12px;
      }

      .sidebar-empty {
        padding: 24px 16px;
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

          .thread-delete {
            opacity: 1;
          }
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

        mat-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
        }

        &:hover {
          color: var(--app-error);
        }
      }

      /* ── Main area ───────────────────────────────────────── */

      .main-area {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        overflow: hidden;
        position: relative;
      }

      /* ── Welcome state ───────────────────────────────────── */

      .welcome-state {
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 48px 24px;
        gap: 8px;
      }

      .welcome-icon {
        opacity: 0.6;
        margin-bottom: 8px;
      }

      .welcome-title {
        font-size: 24px;
        font-weight: 600;
        color: var(--mat-sys-on-surface);
        margin: 0;
      }

      .welcome-subtitle {
        font-size: 14px;
        color: var(--app-neutral);
        margin: 0 0 24px;
        text-align: center;
        max-width: 400px;
      }

      .welcome-input-box {
        width: 100%;
        max-width: 700px;
        border: 1px solid var(--mat-sys-outline-variant);
        border-radius: 20px;
        background: var(--mat-sys-surface-container);
        padding: 8px;
        display: flex;
        flex-direction: column;
        overflow: hidden;
        transition: border-color 0.15s ease, box-shadow 0.15s ease;

        &:focus-within {
          border-color: var(--mat-sys-primary);
          box-shadow: 0 0 0 1px var(--mat-sys-primary);
        }
      }

      .welcome-textarea {
        width: 100%;
        border: none;
        padding: 8px 12px;
        font: inherit;
        font-size: 15px;
        line-height: 1.5;
        resize: none;
        background: transparent;
        color: var(--mat-sys-on-surface);
        outline: none;
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.3) transparent;

        &::-webkit-scrollbar {
          width: 6px;
        }
        &::-webkit-scrollbar-track {
          background: transparent;
          margin: 4px 0;
        }
        &::-webkit-scrollbar-thumb {
          background: rgba(128, 128, 128, 0.3);
          border-radius: 3px;
        }
        &::-webkit-scrollbar-thumb:hover {
          background: rgba(128, 128, 128, 0.5);
        }

        &::placeholder {
          color: var(--app-neutral);
        }
      }

      .welcome-input-actions {
        display: flex;
        align-items: center;
        padding: 0 4px;
      }

      .spacer {
        flex: 1;
      }

      .welcome-send {
        flex-shrink: 0;
        width: 36px;
        height: 36px;
        border-radius: 50%;
        border: none;
        background: var(--mat-sys-primary);
        color: var(--mat-sys-on-primary);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: opacity 0.15s ease;

        &:hover:not(:disabled) {
          opacity: 0.85;
        }

        &:disabled {
          background: var(--app-neutral);
          opacity: 0.3;
          cursor: not-allowed;
        }

        mat-icon {
          font-size: 20px;
          width: 20px;
          height: 20px;
        }
      }

      /* ── Chat view ───────────────────────────────────────── */

      .chat-view {
        flex: 1;
        min-height: 0;
        display: flex;
        flex-direction: column;
        overflow: hidden;
        max-width: 900px;
        width: 100%;
        margin: 0 auto;

        &.hidden {
          display: none;
        }
      }

      /* ── Responsive ──────────────────────────────────────── */

      @media (max-width: 768px) {
        .thread-sidebar {
          position: absolute;
          z-index: 100;
          height: 100%;
          box-shadow: 4px 0 16px rgba(0, 0, 0, 0.1);

          &.collapsed {
            box-shadow: none;
          }
        }
      }
    `,
  ],
})
export class AiChatsComponent implements OnInit {
  private readonly llmService = inject(LlmService);
  private readonly topbarService = inject(TopbarService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly chatPanel = viewChild<AiChatPanelComponent>('chatPanel');

  threads = signal<ConversationThreadSummary[]>([]);
  activeThreadId = signal<string | null>(null);
  loadedMessages = signal<ChatMessage[]>([]);
  replySummary = signal<string | null>(null);
  sending = signal(false);
  loadingThread = signal(false);
  sidebarCollapsed = signal(false);
  inputText = '';
  availableMcpConfigs = signal<McpConfigAvailable[]>([]);
  selectedMcpIds = signal<string[]>([]);

  threadGroups = computed(() => groupByDate(this.threads()));

  ngOnInit(): void {
    this.topbarService.setTitle('AI Chats');
    this.loadThreads();

    // Load MCP configs
    this.llmService.listAvailableMcpConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (configs) => this.availableMcpConfigs.set(configs),
    });

    // Open thread from query param (e.g., from floating chat expand)
    const threadParam = this.route.snapshot.queryParamMap.get('thread');
    if (threadParam) {
      this.selectThread({ id: threadParam } as ConversationThreadSummary);
    }
  }

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

  featureLabel(feature: string): string {
    return FEATURE_LABELS[feature] ?? feature;
  }

  loadThreads(): void {
    this.llmService.listThreads(0, 50).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (res) => this.threads.set(res.threads),
    });
  }

  selectThread(thread: ConversationThreadSummary): void {
    if (this.activeThreadId() === thread.id) return;
    this.activeThreadId.set(thread.id);
    this.loadingThread.set(true);
    this.loadedMessages.set([]);
    this.replySummary.set(null);

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
        // Restore MCP selection from thread
        this.selectedMcpIds.set(detail.mcp_config_ids || []);
        this.loadingThread.set(false);
      },
      error: () => {
        this.loadingThread.set(false);
      },
    });
  }

  newChat(): void {
    this.activeThreadId.set(null);
    this.loadedMessages.set([]);
    this.replySummary.set(null);
    this.selectedMcpIds.set([]);
    this.inputText = '';
  }

  deleteThread(id: string, event: Event): void {
    event.stopPropagation();
    this.llmService.deleteThread(id).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: () => {
        this.threads.update((t) => t.filter((th) => th.id !== id));
        if (this.activeThreadId() === id) {
          this.activeThreadId.set(null);
          this.loadedMessages.set([]);
        }
      },
    });
  }

  autoGrow(event: Event): void {
    const el = event.target as HTMLTextAreaElement;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 378) + 'px';
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

    // Start WS subscription on the panel (handles thinking, tool events, elicitation)
    const streamId = crypto.randomUUID();
    this.chatPanel()?.startStream(streamId, text);

    this.llmService
      .globalChat(text, undefined, undefined, streamId, this.selectedMcpIds())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.activeThreadId.set(res.thread_id);
          this.replySummary.set(res.reply);
          this.sending.set(false);
          this.loadThreads();
        },
        error: () => {
          this.sending.set(false);
        },
      });
  }
}
