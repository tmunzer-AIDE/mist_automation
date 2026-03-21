import {
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  input,
  output,
  signal,
  inject,
  effect,
  viewChild,
} from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { AiIconComponent } from '../ai-icon/ai-icon.component';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { Subscription } from 'rxjs';
import { LlmService } from '../../../core/services/llm.service';
import { WebSocketService } from '../../../core/services/websocket.service';
import { extractErrorMessage } from '../../utils/error.utils';

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  html: string;
}

function renderMarkdown(md: string): string {
  const raw = marked.parse(md, { async: false }) as string;
  return DOMPurify.sanitize(raw);
}

@Component({
  selector: 'app-ai-chat-panel',
  standalone: true,
  imports: [ReactiveFormsModule, MatIconModule, MatButtonModule, AiIconComponent],
  template: `
    <div class="ai-chat-panel">
      <div class="chat-messages" #chatMessages>
        @if (messages().length === 0 && isLoading()) {
          <div class="loading-hint">
            <div class="typing-indicator">
              <span></span><span></span><span></span>
            </div>
            <span>{{ loadingLabel() }}</span>
          </div>
        }

        @for (msg of messages(); track $index) {
          <div
            class="chat-message"
            [class.user]="msg.role === 'user'"
            [class.assistant]="msg.role === 'assistant'"
          >
            @if (msg.role === 'assistant') {
              <div class="avatar assistant-avatar">
                <app-ai-icon [size]="16"></app-ai-icon>
              </div>
            }
            <div class="message-bubble">
              @if (msg.role === 'assistant') {
                <div class="message-content markdown-body" [innerHTML]="msg.html"></div>
              } @else {
                <div class="message-content">{{ msg.content }}</div>
              }
            </div>
            @if (msg.role === 'user') {
              <div class="avatar user-avatar">
                <mat-icon>person</mat-icon>
              </div>
            }
          </div>
        }

        @if (isLoading() && messages().length > 0) {
          <div class="chat-message assistant">
            <div class="avatar assistant-avatar">
              <app-ai-icon [size]="16"></app-ai-icon>
            </div>
            <div class="message-bubble typing-bubble">
              <div class="typing-indicator">
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>
        }

        @if (pendingElicitation()) {
          <div class="elicitation-card">
            <div class="elicitation-icon">
              <mat-icon>verified_user</mat-icon>
            </div>
            <div class="elicitation-body">
              <div class="elicitation-label">Tool confirmation</div>
              <div class="elicitation-desc">{{ pendingElicitation()!.description }}</div>
              <div class="elicitation-actions">
                <button mat-flat-button color="primary" (click)="respondElicitation(true)">Accept</button>
                <button mat-stroked-button (click)="respondElicitation(false)">Decline</button>
              </div>
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

      @if (threadId()) {
        <div class="chat-input-container">
          <textarea
            class="chat-textarea"
            rows="1"
            [formControl]="followUpText"
            placeholder="Ask a follow-up question..."
            (keydown.enter)="onEnter($event)"
            (input)="autoGrow($event)"
          ></textarea>
          <button
            class="send-button"
            (click)="sendFollowUp()"
            [disabled]="isLoading() || !followUpText.value?.trim()"
          >
            <mat-icon>arrow_upward</mat-icon>
          </button>
        </div>
      }
    </div>
  `,
  styles: [
    `
      :host {
        display: flex;
        flex-direction: column;
        width: 100%;
        height: 100%;
        overflow: hidden;
        border-radius: inherit;
      }

      .ai-chat-panel {
        display: flex;
        flex-direction: column;
        overflow: hidden;
        border-radius: inherit;
        height: 100%;
      }

      .chat-messages {
        display: flex;
        flex-direction: column;
        gap: 16px;
        flex: 1;
        overflow-y: auto;
        padding: 16px;
        border-radius: inherit;
      }

      .loading-hint {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 12px;
        padding: 32px;
        color: var(--app-neutral);
        font-size: 13px;
      }

      .chat-message {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        width: fit-content;
        max-width: 85%;

        &.user {
          align-self: flex-end;
        }

        &.assistant {
          align-self: flex-start;
        }
      }

      .avatar {
        flex-shrink: 0;
        width: 28px;
        height: 28px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;

        mat-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
        }
      }

      .assistant-avatar {
        background: var(--app-purple-bg);
        color: var(--app-purple);
      }

      .user-avatar {
        background: var(--mat-sys-primary-container, #e3f2fd);
        color: var(--mat-sys-on-primary-container, #1565c0);
      }

      .message-bubble {
        min-width: 0;
        overflow: hidden;

        .user & {
          background: var(--mat-sys-primary-container, #e3f2fd);
          color: var(--mat-sys-on-primary-container, #1565c0);
          border-radius: 18px 18px 4px 18px;
          padding: 10px 16px;
        }

        .assistant & {
          background: var(--mat-sys-surface-container, #f5f5f5);
          color: var(--mat-sys-on-surface, inherit);
          border-radius: 18px 18px 18px 4px;
          padding: 10px 16px;
        }
      }

      .message-content {
        font-size: 14px;
        line-height: 1.6;
        overflow-x: auto;
      }

      .typing-bubble {
        padding: 14px 20px;
      }

      .typing-indicator {
        display: flex;
        gap: 5px;
        align-items: center;

        span {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          background: var(--app-neutral);
          animation: typing-bounce 1.4s infinite ease-in-out both;

          &:nth-child(1) {
            animation-delay: 0s;
          }
          &:nth-child(2) {
            animation-delay: 0.2s;
          }
          &:nth-child(3) {
            animation-delay: 0.4s;
          }
        }
      }

      @keyframes typing-bounce {
        0%,
        80%,
        100% {
          transform: scale(0.6);
          opacity: 0.4;
        }
        40% {
          transform: scale(1);
          opacity: 1;
        }
      }

      :host ::ng-deep .markdown-body {
        p {
          margin: 0 0 8px;
        }
        p:last-child {
          margin-bottom: 0;
        }
        strong {
          font-weight: 600;
        }
        ul,
        ol {
          margin: 4px 0 8px;
          padding-left: 20px;
        }
        li {
          margin-bottom: 2px;
        }
        code {
          background: rgba(128, 128, 128, 0.15);
          padding: 1px 4px;
          border-radius: 3px;
          font-size: 13px;
        }
        pre {
          background: rgba(128, 128, 128, 0.1);
          padding: 8px 12px;
          border-radius: 6px;
          overflow-x: auto;
        }
        pre code {
          background: none;
          padding: 0;
        }
        h1,
        h2,
        h3 {
          margin: 12px 0 4px;
          font-size: 15px;
          font-weight: 600;
        }
        table {
          border-collapse: collapse;
          width: 100%;
          font-size: 13px;
          margin: 8px 0;
          border-radius: 6px;
          overflow: hidden;
          border: 1px solid rgba(128, 128, 128, 0.25);
        }
        th,
        td {
          padding: 8px 12px;
          border: 1px solid rgba(128, 128, 128, 0.25);
          text-align: left;
        }
        th {
          font-weight: 600;
          background: rgba(128, 128, 128, 0.12);
        }
        tr:nth-child(even) td {
          background: rgba(128, 128, 128, 0.05);
        }
      }

      .elicitation-card {
        display: flex;
        gap: 12px;
        padding: 14px 16px;
        margin: 0 4px;
        border-radius: 12px;
        border: 1px solid var(--app-warning-bg, #fff3cd);
        background: var(--mat-sys-surface-container, #f5f5f5);
        animation: elicit-in 200ms ease-out;
      }

      @keyframes elicit-in {
        from { opacity: 0; transform: translateY(8px); }
        to { opacity: 1; transform: translateY(0); }
      }

      .elicitation-icon {
        flex-shrink: 0;
        width: 32px;
        height: 32px;
        border-radius: 50%;
        background: var(--app-warning-bg, #fff3cd);
        color: var(--app-warning, #e65100);
        display: flex;
        align-items: center;
        justify-content: center;

        mat-icon { font-size: 18px; width: 18px; height: 18px; }
      }

      .elicitation-body {
        flex: 1;
        min-width: 0;
      }

      .elicitation-label {
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--app-warning, #e65100);
        margin-bottom: 4px;
      }

      .elicitation-desc {
        font-size: 14px;
        line-height: 1.5;
        margin-bottom: 10px;
      }

      .elicitation-actions {
        display: flex;
        gap: 8px;

        button { font-size: 13px; height: 32px; }
      }

      .chat-error {
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--app-error);
        padding: 8px 12px;
        font-size: 13px;
        border-radius: var(--app-radius-sm);
        background: var(--app-error-bg);

        mat-icon {
          font-size: 18px;
          width: 18px;
          height: 18px;
        }
      }

      .chat-input-container {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 12px 16px;
        border-top: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
        flex-shrink: 0;
      }

      .chat-textarea {
        flex: 1;
        margin: 0;
        box-sizing: border-box;
        border: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
        border-radius: 20px;
        padding: 10px 16px;
        font: inherit;
        font-size: 14px;
        line-height: 1.5;
        resize: none;
        overflow-y: auto;
        background: var(--mat-sys-surface-container, #f5f5f5);
        color: var(--mat-sys-on-surface, inherit);
        outline: none;

        &:focus {
          border-color: var(--mat-sys-primary, #1976d2);
          box-shadow: 0 0 0 1px var(--mat-sys-primary, #1976d2);
        }

        &:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        &::placeholder {
          color: var(--app-neutral);
        }
      }

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
    `,
  ],
})
export class AiChatPanelComponent {
  /** Thread ID for follow-up messages */
  threadId = input<string | null>(null);

  /** Initial summary to display — set by parent, rendered on init */
  initialSummary = input<string | null>(null);

  /** Error message from parent */
  errorMessage = input<string | null>(null);

  /** Loading state from parent (initial summary generation) */
  parentLoading = input(false);

  /** Label shown during initial loading (default: "Thinking...") */
  loadingLabel = input('Thinking...');

  /** Pre-loaded messages (for loading existing threads). Takes priority over initialSummary. */
  initialMessages = input<ChatMessage[]>([]);

  /** Emits when a follow-up is sent */
  followUpSent = output<void>();

  private readonly llmService = inject(LlmService);
  private readonly wsService = inject(WebSocketService);
  private readonly injector = inject(Injector);
  private readonly chatMessagesEl = viewChild<ElementRef<HTMLDivElement>>('chatMessages');
  private streamSub: Subscription | null = null;

  messages = signal<ChatMessage[]>([]);
  loading = signal(false);
  error = signal<string | null>(null);
  pendingElicitation = signal<{ requestId: string; description: string } | null>(null);
  followUpText = new FormControl('');

  isLoading = computed(() => this.loading() || this.parentLoading());

  constructor() {
    // Disable/enable textarea based on loading state
    effect(() => {
      if (this.isLoading()) {
        this.followUpText.disable();
      } else {
        this.followUpText.enable();
      }
    });

    // Reactively populate messages when initialSummary input changes
    effect(() => {
      const summary = this.initialSummary();
      if (summary) {
        this.messages.set([{ role: 'assistant', content: summary, html: renderMarkdown(summary) }]);
        this.scrollToBottom();
      }
    });
    // Load pre-existing messages (thread history)
    effect(() => {
      const msgs = this.initialMessages();
      if (msgs.length > 0) {
        this.streamSub?.unsubscribe();
        this.streamSub = null;
        this.loading.set(false);
        this.error.set(null);
        this.pendingElicitation.set(null);
        this.followUpText.reset();
        this.messages.set(msgs);
        this.scrollToBottom();
      }
    });
    effect(() => {
      this.error.set(this.errorMessage());
    });
  }

  /** Auto-grow textarea up to 10 lines, then scroll */
  autoGrow(event: Event): void {
    const el = event.target as HTMLTextAreaElement;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 210) + 'px';
  }

  /** Enter sends, Shift+Enter inserts newline */
  onEnter(event: Event): void {
    const ke = event as KeyboardEvent;
    if (!ke.shiftKey) {
      ke.preventDefault();
      this.sendFollowUp();
    }
  }

  sendFollowUp(): void {
    const text = (this.followUpText.value ?? '').trim();
    const thread = this.threadId();
    if (!text || !thread) return;

    this.messages.update((msgs) => [...msgs, { role: 'user', content: text, html: '' }]);
    this.followUpText.reset();
    this.loading.set(true);
    this.error.set(null);
    this.scrollToBottom();

    // Subscribe to streaming tokens via WebSocket
    const streamId = crypto.randomUUID();
    const channel = `llm:${streamId}`;
    let streamedContent = '';

    this.streamSub?.unsubscribe();
    this.streamSub = this.wsService
      .subscribe<{ type: string; content?: string; request_id?: string; description?: string }>(channel)
      .subscribe((msg) => {
        if (msg.type === 'token') {
          streamedContent += msg.content ?? '';
          this.messages.update((msgs) => {
            const last = msgs[msgs.length - 1];
            if (last?.role === 'assistant') {
              return [...msgs.slice(0, -1), { ...last, content: streamedContent, html: renderMarkdown(streamedContent) }];
            }
            return [...msgs, { role: 'assistant', content: streamedContent, html: renderMarkdown(streamedContent) }];
          });
          this.scrollToBottom();
        } else if (msg.type === 'elicitation' && msg.request_id && msg.description) {
          this.pendingElicitation.set({ requestId: msg.request_id, description: msg.description });
          this.scrollToBottom();
        } else if (msg.type === 'done') {
          this.streamSub?.unsubscribe();
          this.streamSub = null;
        }
      });

    // Send API request with stream_id
    this.llmService.followUp(thread, text, streamId).subscribe({
      next: (res) => {
        // Final response — replace streaming content with the complete version
        this.messages.update((msgs) => {
          const withoutLast = msgs.filter((m, i) => !(i === msgs.length - 1 && m.role === 'assistant'));
          return [...withoutLast, { role: 'assistant', content: res.reply, html: renderMarkdown(res.reply) }];
        });
        this.loading.set(false);
        this.followUpSent.emit();
        this.scrollToBottom();
      },
      error: (err) => {
        this.streamSub?.unsubscribe();
        this.streamSub = null;
        this.error.set(extractErrorMessage(err));
        this.loading.set(false);
      },
    });
  }

  respondElicitation(accepted: boolean): void {
    const elicit = this.pendingElicitation();
    if (!elicit) return;
    this.pendingElicitation.set(null);
    this.llmService.respondToElicitation(elicit.requestId, accepted).subscribe();
  }

  private scrollToBottom(): void {
    afterNextRender(
      () => {
        const el = this.chatMessagesEl()?.nativeElement;
        if (!el) return;
        el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
      },
      { injector: this.injector }
    );
  }
}
