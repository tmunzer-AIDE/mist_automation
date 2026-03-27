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
          <button mat-icon-button matTooltip="Hide panel (Ctrl+\)" (click)="hidePanel()">
            <mat-icon>right_panel_close</mat-icon>
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

    /* -- Header ------------------------------------------------ */

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

    /* -- Context breadcrumb ------------------------------------- */

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

    /* -- Thread history drawer ---------------------------------- */

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

    /* -- Chat body ---------------------------------------------- */

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

    /* -- Initial input (no thread yet) -------------------------- */

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

  // -- Thread management ----------------------------------------

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

  hidePanel(): void {
    this.globalChatService.toggle();
  }

  // -- Chat input -----------------------------------------------

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
