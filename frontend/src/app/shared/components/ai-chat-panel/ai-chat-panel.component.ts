import { Component, ElementRef, input, output, signal, inject, effect, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CdkTextareaAutosize, TextFieldModule } from '@angular/cdk/text-field';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { marked } from 'marked';
import { LlmService } from '../../../core/services/llm.service';
import { extractErrorMessage } from '../../utils/error.utils';

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  html: string;
}

function renderMarkdown(md: string): string {
  return marked.parse(md, { async: false }) as string;
}

@Component({
  selector: 'app-ai-chat-panel',
  standalone: true,
  imports: [
    FormsModule,
    TextFieldModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressBarModule,
  ],
  template: `
    <div class="ai-chat-panel">
      @if (loading()) {
        <mat-progress-bar mode="indeterminate"></mat-progress-bar>
      }

      @if (messages().length === 0 && loading()) {
        <div class="loading-hint">Generating summary...</div>
      }

      <div class="chat-messages" #chatMessages>
        @for (msg of messages(); track $index) {
          <div
            class="chat-message"
            [class.user]="msg.role === 'user'"
            [class.assistant]="msg.role === 'assistant'"
          >
            <div class="message-header">
              <mat-icon>{{ msg.role === 'user' ? 'person' : 'smart_toy' }}</mat-icon>
              <span>{{ msg.role === 'user' ? 'You' : 'AI' }}</span>
            </div>
            @if (msg.role === 'assistant') {
              <div class="message-content markdown-body" [innerHTML]="msg.html"></div>
            } @else {
              <div class="message-content">{{ msg.content }}</div>
            }
          </div>
        }
        @if (error()) {
          <div class="chat-error">{{ error() }}</div>
        }
      </div>

      @if (threadId()) {
        <div class="chat-input-row">
          <mat-form-field appearance="outline" class="chat-input">
            <textarea
              matInput
              cdkTextareaAutosize
              [cdkAutosizeMinRows]="1"
              [cdkAutosizeMaxRows]="5"
              [(ngModel)]="followUpText"
              placeholder="Ask a follow-up question..."
              (keydown.enter)="onEnter($event)"
              [disabled]="loading()"
            ></textarea>
          </mat-form-field>
          <button mat-icon-button (click)="sendFollowUp()" [disabled]="loading() || !followUpText.trim()">
            <mat-icon>send</mat-icon>
          </button>
        </div>
      }
    </div>
  `,
  styles: [
    `
      .ai-chat-panel {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .loading-hint {
        padding: 12px;
        font-size: 13px;
        color: var(--app-neutral, #888);
        font-style: italic;
      }
      .chat-messages {
        display: flex;
        flex-direction: column;
        gap: 12px;
        max-height: 500px;
        overflow-y: auto;
        padding: 8px 0;
      }
      .chat-message {
        padding: 12px 16px;
        border-radius: 8px;
        background: var(--mat-sys-surface-container, var(--app-canvas, #f5f5f5));
        color: var(--mat-sys-on-surface, inherit);
      }
      .chat-message.assistant {
        border-left: 3px solid var(--app-info, #2196f3);
      }
      .message-header {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-bottom: 8px;
        font-size: 12px;
        font-weight: 500;
        color: var(--app-neutral, #666);
      }
      .message-header mat-icon {
        font-size: 16px;
        width: 16px;
        height: 16px;
      }
      .message-content {
        font-size: 14px;
        line-height: 1.6;
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
      }
      .chat-error {
        color: var(--app-error, #f44336);
        padding: 8px 12px;
        font-size: 13px;
      }
      .chat-input-row {
        display: flex;
        align-items: flex-end;
        gap: 4px;
      }
      .chat-input {
        flex: 1;
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

  /** Emits when a follow-up is sent */
  followUpSent = output<void>();

  private readonly llmService = inject(LlmService);
  private readonly chatMessagesEl = viewChild<ElementRef<HTMLDivElement>>('chatMessages');

  messages = signal<ChatMessage[]>([]);
  loading = signal(false);
  error = signal<string | null>(null);
  followUpText = '';

  constructor() {
    // Reactively populate messages when initialSummary input changes
    effect(() => {
      const summary = this.initialSummary();
      if (summary) {
        this.messages.set([{ role: 'assistant', content: summary, html: renderMarkdown(summary) }]);
        this.scrollToBottom();
      }
    });
    effect(() => {
      const err = this.errorMessage();
      if (err) {
        this.error.set(err);
      }
    });
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
    const text = this.followUpText.trim();
    const thread = this.threadId();
    if (!text || !thread) return;

    this.messages.update((msgs) => [...msgs, { role: 'user', content: text, html: '' }]);
    this.followUpText = '';
    this.loading.set(true);
    this.error.set(null);
    this.scrollToBottom();

    this.llmService.followUp(thread, text).subscribe({
      next: (res) => {
        this.messages.update((msgs) => [
          ...msgs,
          { role: 'assistant', content: res.reply, html: renderMarkdown(res.reply) },
        ]);
        this.loading.set(false);
        this.followUpSent.emit();
        this.scrollToBottom();
      },
      error: (err) => {
        this.error.set(extractErrorMessage(err));
        this.loading.set(false);
      },
    });
  }

  private scrollToBottom(): void {
    // Wait one tick for the DOM to update, then scroll if already near bottom
    setTimeout(() => {
      const el = this.chatMessagesEl()?.nativeElement;
      if (!el) return;
      const threshold = 100;
      const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
      if (isNearBottom || el.scrollTop === 0) {
        el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
      }
    });
  }
}
