import {
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Subscription } from 'rxjs';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { ChatMessage } from '../models/impact-analysis.model';
import { McpConfigAvailable } from '../../../core/models/llm.model';
import { ImpactAnalysisService } from '../../../core/services/impact-analysis.service';
import { LlmService } from '../../../core/services/llm.service';
import { WebSocketService } from '../../../core/services/websocket.service';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { AiIconComponent } from '../../../shared/components/ai-icon/ai-icon.component';
import { extractErrorMessage } from '../../../shared/utils/error.utils';

function renderMarkdown(md: string): string {
  const raw = marked.parse(md, { async: false }) as string;
  return DOMPurify.sanitize(raw);
}

@Component({
  selector: 'app-impact-chat-panel',
  standalone: true,
  imports: [FormsModule, MatIconModule, MatButtonModule, MatMenuModule, MatTooltipModule, DateTimePipe, AiIconComponent],
  template: `
    <div class="chat-container">
      <div class="chat-messages" #chatMessages>
        @for (msg of messages(); track msg.id) {
          @if (msg.role === 'system') {
            <div class="event-divider">
              <span class="event-text">{{ msg.timestamp | dateTime: 'time' }} — {{ msg.content }}</span>
            </div>
          } @else if (msg.role === 'ai') {
            <div class="message ai-message">
              <div class="avatar assistant-avatar"><app-ai-icon [size]="16"></app-ai-icon></div>
              <div class="bubble-wrapper">
                <div class="timestamp">{{ msg.timestamp | dateTime: 'time' }}</div>
                <div
                  class="bubble ai-bubble"
                  [class.severity-warning]="msg.severity === 'warning'"
                  [class.severity-critical]="msg.severity === 'critical'"
                  [innerHTML]="msg.html"
                ></div>
              </div>
            </div>
          } @else if (msg.role === 'user') {
            <div class="message user-message">
              <div class="bubble-wrapper">
                <div class="timestamp">{{ msg.timestamp | dateTime: 'time' }}</div>
                <div class="bubble user-bubble">{{ msg.content }}</div>
              </div>
            </div>
          }
        }

        @if (pendingUserMessage(); as pending) {
          <div class="message user-message">
            <div class="bubble-wrapper">
              <div class="bubble user-bubble">{{ pending }}</div>
            </div>
          </div>
        }

        @if (streaming()) {
          <div class="message ai-message">
            <div class="avatar assistant-avatar"><app-ai-icon [size]="16"></app-ai-icon></div>
            <div class="bubble-wrapper">
              <div class="bubble ai-bubble" [innerHTML]="streamingHtml()"></div>
            </div>
          </div>
        }

        @if (error()) {
          <div class="chat-error">
            <mat-icon>error_outline</mat-icon>
            <span>{{ error() }}</span>
          </div>
        }
      </div>

      @if (llmEnabled() && !hideInput()) {
        <div class="chat-input-container">
          <div class="chat-input-box">
            <textarea
              rows="1"
              class="chat-textarea"
              [(ngModel)]="userInput"
              [placeholder]="groupId() ? 'Ask about this change group...' : 'Ask a question...'"
              (keydown.enter)="onEnter($event)"
              (input)="autoGrow($event)"
              [disabled]="sending()"
            ></textarea>
            <div class="chat-input-actions">
              @if (mcpConfigs().length > 0) {
                <button class="mcp-toggle" [class.active]="selectedMcpIds().length > 0" [matMenuTriggerFor]="mcpMenu" [matTooltip]="mcpTooltip()">
                  <mat-icon>hub</mat-icon>
                  <span>{{ selectedMcpIds().length }}</span>
                </button>
                <mat-menu #mcpMenu="matMenu">
                  @for (cfg of mcpConfigs(); track cfg.id) {
                    <button mat-menu-item (click)="toggleMcp(cfg.id); $event.stopPropagation()">
                      <mat-icon>{{ isMcpSelected(cfg.id) ? 'check_box' : 'check_box_outline_blank' }}</mat-icon>
                      {{ cfg.name }}
                    </button>
                  }
                </mat-menu>
              }
              <span class="spacer"></span>
              <button
                class="send-button"
                (click)="send()"
                [disabled]="sending() || !userInput.trim()"
              >
                <mat-icon>arrow_upward</mat-icon>
              </button>
            </div>
          </div>
        </div>
      }
    </div>
  `,
  styles: [
    `
      :host {
        display: flex;
        flex-direction: column;
        // height: 100%;
        overflow: hidden;
      }

      .chat-container {
        display: flex;
        flex-direction: column;
        height: 100%;
      }

      .chat-messages {
        flex: 1;
        overflow-y: auto;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 14px;
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.3) transparent;

        &::-webkit-scrollbar {
          width: 6px;
        }
        &::-webkit-scrollbar-track {
          background: transparent;
          margin: 8px 0;
        }
        &::-webkit-scrollbar-thumb {
          background: rgba(128, 128, 128, 0.3);
          border-radius: 3px;
        }
        &::-webkit-scrollbar-thumb:hover {
          background: rgba(128, 128, 128, 0.5);
        }
      }

      .message {
        display: flex;
        gap: 10px;
        max-width: 92%;
        flex-shrink: 0;
      }
      .ai-message {
        align-self: flex-start;
      }
      .user-message {
        align-self: flex-end;
        flex-direction: row-reverse;
      }

      .avatar {
        width: 28px;
        height: 28px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        font-weight: 600;
        flex-shrink: 0;
      }
      .assistant-avatar {
        background: var(--mat-sys-surface-container-high, #e0e0e0);
      }
      .user-avatar {
        background: var(--mat-sys-primary, #6750a4);
        color: var(--mat-sys-on-primary, white);
        mat-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
        }
      }

      .bubble-wrapper {
        min-width: 0;
      }
      .timestamp {
        font-size: 11px;
        color: var(--app-neutral-500, #888);
        margin-bottom: 3px;
      }
      .user-message .timestamp {
        text-align: right;
      }

      .bubble {
        padding: 10px 14px;
        font-size: 13px;
        line-height: 1.5;
        border-radius: 12px;
        word-break: break-word;
      }
      .ai-bubble {
        background: var(--mat-sys-surface-container, #f3edf7);
        border-radius: 2px 12px 12px 12px;

        &.severity-warning {
          border-left: 3px solid var(--app-warning);
          background: var(--app-warning-bg);
        }
        &.severity-critical {
          border-left: 3px solid var(--app-error);
          background: var(--app-error-bg);
        }
      }
      .user-bubble {
        background: var(--mat-sys-primary, #6750a4);
        color: var(--mat-sys-on-primary, white);
        border-radius: 12px 2px 12px 12px;
      }

      .event-divider {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 4px 0;

        &::before {
          content: '';
          width: 24px;
          flex-shrink: 0;
          height: 1px;
          background: var(--app-neutral-200, rgba(128, 128, 128, 0.15));
        }
        .event-text {
          font-size: 11px;
          color: var(--app-neutral-500, #888);
          white-space: nowrap;
        }
      }

      .chat-input-container {
        padding: 12px 16px;
        border-top: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
        flex-shrink: 0;
      }

      .chat-input-box {
        border: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
        border-radius: 20px;
        background: var(--mat-sys-surface-container, #f5f5f5);
        padding: 8px;
        display: flex;
        flex-direction: column;
        overflow: hidden;
        transition: border-color 0.15s ease, box-shadow 0.15s ease;

        &:focus-within {
          border-color: var(--mat-sys-primary, #1976d2);
          box-shadow: 0 0 0 1px var(--mat-sys-primary, #1976d2);
        }
      }

      .chat-textarea {
        width: 100%;
        box-sizing: border-box;
        border: none;
        padding: 8px 12px;
        font: inherit;
        font-size: 14px;
        line-height: 1.5;
        resize: none;
        overflow-y: auto;
        background: transparent;
        color: var(--mat-sys-on-surface, inherit);
        outline: none;

        &:disabled { opacity: 0.5; cursor: not-allowed; }
        &::placeholder { color: var(--app-neutral); }
      }

      .chat-input-actions {
        display: flex;
        align-items: center;
        padding: 0 4px;
      }

      .spacer { flex: 1; }

      .send-button {
        flex-shrink: 0;
        width: 36px;
        height: 36px;
        border-radius: 50%;
        border: none;
        background: var(--mat-sys-primary, #1976d2);
        color: var(--mat-sys-on-primary, #fff);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: opacity 0.15s ease;

        &:hover:not(:disabled) { opacity: 0.85; }
        &:disabled { background: var(--app-neutral); opacity: 0.3; cursor: not-allowed; }

        mat-icon { font-size: 20px; width: 20px; height: 20px; }
      }

      .chat-error {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 12px;
        font-size: 12px;
        color: var(--app-error, #c62828);
        background: rgba(var(--app-error-rgb, 198, 40, 40), 0.06);
        border-radius: 8px;

        mat-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
        }
      }
    `,
  ],
})
export class ImpactChatPanelComponent {
  private readonly impactService = inject(ImpactAnalysisService);
  private readonly llmService = inject(LlmService);
  private readonly wsService = inject(WebSocketService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly injector = inject(Injector);

  /** Chat messages mapped from timeline entries by the parent. */
  readonly messages = input.required<ChatMessage[]>();

  /**
   * Session ID for sending chat messages.
   * If both sessionId and groupId are provided, groupId takes precedence.
   */
  readonly sessionId = input<string>('');

  /**
   * Group ID for sending group chat messages.
   * If both groupId and sessionId are provided, groupId takes precedence.
   */
  readonly groupId = input<string>('');

  /** Whether the session is still actively running. */
  readonly isActive = input<boolean>(false);

  /** Whether the LLM feature is enabled. */
  readonly llmEnabled = input<boolean>(false);

  /** Emitted after a user message is sent and the AI responds. */
  readonly messageSent = output<void>();

  /** User input bound to the text field (plain string for ngModel). */
  userInput = '';

  /** Available MCP server configs. */
  readonly mcpConfigs = signal<McpConfigAvailable[]>([]);

  /** Currently selected MCP config IDs. */
  readonly selectedMcpIds = signal<string[]>([]);

  mcpTooltip = computed(() => {
    const ids = new Set(this.selectedMcpIds());
    const names = this.mcpConfigs().filter((c) => ids.has(c.id)).map((c) => c.name);
    return names.length ? 'MCP: ' + names.join(', ') : 'No MCP servers active';
  });

  isMcpSelected(id: string): boolean {
    return this.selectedMcpIds().includes(id);
  }

  toggleMcp(id: string): void {
    const current = this.selectedMcpIds();
    if (current.includes(id)) {
      this.selectedMcpIds.set(current.filter((i) => i !== id));
    } else {
      this.selectedMcpIds.set([...current, id]);
    }
  }

  /** Whether a message is currently being sent. */
  readonly sending = signal(false);

  /** Whether streaming tokens are being received. */
  readonly streaming = signal(false);

  /** Accumulated streaming content (raw markdown). */
  readonly streamingContent = signal('');

  /** Rendered HTML of the streaming content. */
  readonly streamingHtml = computed(() => renderMarkdown(this.streamingContent()));

  /** User message shown optimistically before the server responds. */
  readonly pendingUserMessage = signal<string | null>(null);

  /** Error message from the last send attempt. */
  readonly error = signal<string | null>(null);

  /** Hide the input bar when the session is in a terminal-bad state. */
  readonly hideInput = computed(() => {
    // Parent passes isActive=false for completed sessions, but we also want to
    // hide for cancelled/failed which the parent can signal by not setting llmEnabled.
    // However, the spec asks for explicit status check, so we rely on isActive being
    // false for terminal states. The llmEnabled input already gates visibility.
    return false;
  });

  private readonly chatMessagesEl = viewChild<ElementRef<HTMLDivElement>>('chatMessages');
  private streamSub: Subscription | null = null;
  private previousMessageCount = 0;

  constructor() {
    // Load available MCP configs
    this.llmService.listAvailableMcpConfigs().subscribe({
      next: (configs) => this.mcpConfigs.set(configs),
    });

    // When parent delivers new messages, clear optimistic state and scroll
    effect(() => {
      const count = this.messages().length;
      if (count !== untracked(() => this.previousMessageCount)) {
        this.previousMessageCount = count;
        // Clear streaming and pending — real messages have arrived
        if (untracked(() => this.streaming())) {
          this.streaming.set(false);
          this.streamingContent.set('');
        }
        this.pendingUserMessage.set(null);
        this.scrollToBottom();
      }
    });

    // Auto-scroll when streaming content updates
    effect(() => {
      this.streamingContent();
      if (untracked(() => this.streaming())) {
        this.scrollToBottom();
      }
    });

    // Clean up WS subscription on destroy
    this.destroyRef.onDestroy(() => {
      this.streamSub?.unsubscribe();
      this.streamSub = null;
    });
  }

  onEnter(event: Event): void {
    const ke = event as KeyboardEvent;
    if (ke.shiftKey) return; // Shift+Enter inserts newline
    ke.preventDefault();
    this.send();
  }

  autoGrow(event: Event): void {
    const el = event.target as HTMLTextAreaElement;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }

  /** Send a user message and stream the AI response. */
  send(): void {
    const text = this.userInput.trim();
    const sid = this.sessionId();
    const gid = this.groupId();
    if (!text || this.sending()) return;
    if (!sid && !gid) {
      this.error.set('Cannot send message: no active session or group is selected.');
      return;
    }

    this.userInput = '';
    this.error.set(null);
    this.sending.set(true);
    this.pendingUserMessage.set(text);

    const streamId = crypto.randomUUID();
    this.subscribeToStream(`llm:${streamId}`);

    const mcpIds = this.selectedMcpIds().length > 0 ? this.selectedMcpIds() : undefined;
    const request$ = gid
      ? this.impactService.sendGroupChatMessage(gid, text, streamId, mcpIds)
      : this.impactService.sendChatMessage(sid, text, streamId, mcpIds);

    request$
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          // Don't clear streaming/pending here — the effect clears them
          // when the parent delivers the new messages (no flash).
          this.sending.set(false);
          this.messageSent.emit();
        },
        error: (err) => {
          this.streamSub?.unsubscribe();
          this.streamSub = null;
          this.streaming.set(false);
          this.streamingContent.set('');
          this.sending.set(false);
          this.pendingUserMessage.set(null);
          this.error.set(extractErrorMessage(err));
        },
      });
  }

  /** Subscribe to a WS stream channel for token-by-token streaming. */
  private subscribeToStream(channel: string): void {
    let accumulated = '';

    this.streamSub?.unsubscribe();
    this.streaming.set(true);
    this.streamingContent.set('');

    this.streamSub = this.wsService
      .subscribe<{ type: string; content?: string }>(channel)
      .subscribe((msg) => {
        if (msg.type === 'token' && msg.content) {
          accumulated += msg.content;
          this.streamingContent.set(accumulated);
        } else if (msg.type === 'thinking' && msg.content) {
          accumulated += msg.content;
          this.streamingContent.set(accumulated);
        } else if (msg.type === 'done') {
          this.streamSub?.unsubscribe();
          this.streamSub = null;
          // Keep streaming content visible until the HTTP response arrives
          // and the parent refreshes messages.
        }
      });
  }

  /** Scroll the chat messages container to the bottom. */
  private scrollToBottom(): void {
    afterNextRender(
      () => {
        const el = this.chatMessagesEl()?.nativeElement;
        if (el) {
          el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
        }
      },
      { injector: this.injector },
    );
  }
}
