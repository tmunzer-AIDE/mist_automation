import { Component, DestroyRef, inject, OnInit, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AiChatPanelComponent } from '../ai-chat-panel/ai-chat-panel.component';
import { AiIconComponent } from '../ai-icon/ai-icon.component';
import { LlmService } from '../../../core/services/llm.service';
import { GlobalChatService } from '../../../core/services/global-chat.service';
import { extractErrorMessage } from '../../utils/error.utils';

@Component({
  selector: 'app-global-chat',
  standalone: true,
  imports: [MatButtonModule, MatIconModule, MatTooltipModule, AiChatPanelComponent, AiIconComponent],
  template: `
    @if (!isOpen()) {
      <button
        class="chat-fab"
        [class.pulse]="showPulse()"
        (click)="open()"
        matTooltip="AI Assistant"
        matTooltipPosition="left"
      >
        <app-ai-icon [size]="36"></app-ai-icon>
      </button>
    }

    @if (isOpen()) {
      <div class="chat-panel" @panelAnimation>
        <div class="panel-header">
          <div class="header-title">
            <app-ai-icon [size]="22"></app-ai-icon>
            <span>AI Assistant</span>
          </div>
          <div class="header-actions">
            <button mat-icon-button matTooltip="New Chat" (click)="resetChat()">
              <mat-icon>add_comment</mat-icon>
            </button>
            <button mat-icon-button matTooltip="Close" (click)="close()">
              <mat-icon>close</mat-icon>
            </button>
          </div>
        </div>
        <div class="panel-body">
          @if (!threadId() && !loading()) {
            <!-- Initial state: show input for first message -->
            <div class="welcome">
              <app-ai-icon [size]="48" class="welcome-icon-wrap"></app-ai-icon>
              <p>Ask me anything about your Mist infrastructure.</p>
              <p class="welcome-hint">I can query backups, workflows, device events, and more.</p>
            </div>
          }
          <app-ai-chat-panel
            #chatPanel
            [threadId]="threadId()"
            [initialSummary]="initialReply()"
            [errorMessage]="chatError()"
            [parentLoading]="loading()"
          ></app-ai-chat-panel>
        </div>

        @if (!threadId()) {
          <div class="initial-input">
            <textarea
              class="chat-textarea"
              [value]="inputText"
              (input)="inputText = $any($event.target).value"
              (keydown.enter)="onEnter($event)"
              placeholder="Ask a question..."
              rows="1"
            ></textarea>
            <button class="send-button" (click)="sendFirst()" [disabled]="loading() || !inputText.trim()">
              <mat-icon>arrow_upward</mat-icon>
            </button>
          </div>
        }
      </div>
    }
  `,
  styles: [
    `
      :host {
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 1000;
      }

      .chat-fab {
        width: 56px;
        height: 56px;
        border-radius: 50%;
        border: 1px solid rgba(0, 120, 212, 0.3);
        background: rgba(0, 120, 212, 0.1);
        backdrop-filter: blur(12px);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 4px 20px rgba(0, 120, 212, 0.2), 0 2px 8px rgba(0, 0, 0, 0.15);
        transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
        position: relative;

        &:hover {
          transform: scale(1.08);
          border-color: rgba(0, 120, 212, 0.5);
          box-shadow: 0 8px 28px rgba(0, 120, 212, 0.3), 0 4px 12px rgba(0, 0, 0, 0.2);
        }
      }

      .chat-fab.pulse::after {
        content: '';
        position: absolute;
        width: 56px;
        height: 56px;
        border-radius: 50%;
        border: 2px solid rgba(0, 120, 212, 0.4);
        animation: pulse-ring 2s ease-out 3;
      }

      @keyframes pulse-ring {
        0% { transform: scale(1); opacity: 0.6; }
        100% { transform: scale(1.8); opacity: 0; }
      }

      .chat-panel {
        width: 420px;
        height: 560px;
        border-radius: 16px;
        background: var(--mat-sys-surface);
        border: 1px solid var(--mat-sys-outline-variant);
        box-shadow: 0 16px 48px rgba(0, 0, 0, 0.15), 0 6px 16px rgba(0, 0, 0, 0.1);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        animation: panel-in 250ms cubic-bezier(0.2, 0, 0, 1) forwards;
        transform-origin: bottom right;
      }

      @keyframes panel-in {
        from {
          opacity: 0;
          transform: scale(0.4) translateY(16px);
        }
        to {
          opacity: 1;
          transform: scale(1) translateY(0);
        }
      }

      .panel-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 6px 6px 6px 16px;
        border-bottom: 1px solid var(--mat-sys-outline-variant);
        background: var(--mat-sys-surface-container);
        flex-shrink: 0;
      }

      .header-title {
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 15px;
        font-weight: 600;
      }

      .header-actions {
        display: flex;
      }

      .panel-body {
        flex: 1;
        overflow: hidden;
        display: flex;
        flex-direction: column;
      }

      .welcome {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 40px 24px 16px;
        text-align: center;
        color: var(--mat-sys-on-surface-variant);
      }

      .welcome-icon-wrap {
        margin-bottom: 12px;
        opacity: 0.7;
      }

      .welcome p {
        margin: 0 0 4px;
        font-size: 14px;
      }

      .welcome-hint {
        font-size: 12px !important;
        opacity: 0.7;
      }

      .initial-input {
        display: flex;
        align-items: flex-end;
        gap: 8px;
        padding: 12px 16px;
        border-top: 1px solid var(--mat-sys-outline-variant);
      }

      .chat-textarea {
        flex: 1;
        border: 1px solid var(--mat-sys-outline-variant);
        border-radius: 20px;
        padding: 10px 16px;
        font: inherit;
        font-size: 14px;
        line-height: 1.5;
        resize: none;
        background: var(--mat-sys-surface-container);
        color: var(--mat-sys-on-surface);
        outline: none;

        &:focus {
          border-color: var(--mat-sys-primary);
          box-shadow: 0 0 0 1px var(--mat-sys-primary);
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
        background: var(--mat-sys-primary);
        color: var(--mat-sys-on-primary);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: opacity 0.15s ease;

        &:hover:not(:disabled) { opacity: 0.85; }
        &:disabled { background: var(--app-neutral); opacity: 0.3; cursor: not-allowed; }

        mat-icon { font-size: 20px; width: 20px; height: 20px; }
      }

      @media (max-width: 480px) {
        .chat-panel {
          width: calc(100vw - 16px);
          height: calc(100vh - 80px);
          bottom: 8px;
          right: 8px;
          border-radius: 12px;
        }
      }
    `,
  ],
})
export class GlobalChatComponent implements OnInit {
  private readonly llmService = inject(LlmService);
  private readonly globalChatService = inject(GlobalChatService);
  private readonly destroyRef = inject(DestroyRef);

  isOpen = signal(false);
  showPulse = signal(true);
  loading = signal(false);
  threadId = signal<string | null>(null);
  initialReply = signal<string | null>(null);
  chatError = signal<string | null>(null);
  inputText = '';

  ngOnInit(): void {
    // Listen for external open requests (from dashboard, webhook monitor, etc.)
    this.globalChatService.onOpen().pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
      this.open();
      if (event.message) {
        this.inputText = event.message;
        // Auto-send after a tick to let the panel render
        setTimeout(() => this.sendFirst(), 100);
      }
    });

    // Stop pulse after 6 seconds
    setTimeout(() => this.showPulse.set(false), 6000);
  }

  open(): void {
    this.isOpen.set(true);
    this.showPulse.set(false);
  }

  close(): void {
    this.isOpen.set(false);
  }

  resetChat(): void {
    this.threadId.set(null);
    this.initialReply.set(null);
    this.chatError.set(null);
    this.inputText = '';
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
    if (!text || this.loading()) return;

    this.inputText = '';
    this.loading.set(true);
    this.chatError.set(null);

    this.llmService
      .globalChat(text, this.threadId() || undefined, this.globalChatService.buildContextString() || undefined)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.threadId.set(res.thread_id);
          this.initialReply.set(res.reply);
          this.loading.set(false);
        },
        error: (err) => {
          this.chatError.set(extractErrorMessage(err));
          this.loading.set(false);
        },
      });
  }
}
