import { Component, computed, effect, input, model, output } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { AiChatPanelComponent } from '../ai-chat-panel/ai-chat-panel.component';
import { AiIconComponent } from '../ai-icon/ai-icon.component';

@Component({
  selector: 'app-ai-inline-analysis',
  standalone: true,
  imports: [MatIconModule, AiChatPanelComponent, AiIconComponent],
  template: `
    @if (llmAvailable()) {
      <button
        class="ai-trigger-chip"
        [class.active]="hasContent()"
        [disabled]="loading()"
        (click)="onChipClick()"
      >
        <app-ai-icon [size]="14" [animated]="loading()"></app-ai-icon>
        @if (loading()) {
          <span>{{ loadingLabel() }}</span>
        } @else {
          <span>AI Analysis</span>
        }
        @if (hasContent()) {
          <mat-icon class="toggle-icon">{{ expanded() ? 'expand_less' : 'expand_more' }}</mat-icon>
        }
      </button>

      @if (!buttonOnly() && hasContent() && expanded()) {
        <div class="ai-analysis-section">
          <app-ai-chat-panel
            [threadId]="threadId()"
            [initialSummary]="summary()"
            [errorMessage]="error()"
            [parentLoading]="loading()"
            [loadingLabel]="loadingLabel()"
          ></app-ai-chat-panel>
        </div>
      }
    }
  `,
  styles: [
    `
      :host {
        display: block;
      }

      .ai-trigger-chip {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        height: 36px;
        padding: 0 15px;
        border-radius: 4px;
        border: 1px solid var(--mat-sys-outline);
        background: transparent;
        color: var(--mat-sys-on-surface-variant);
        font: inherit;
        font-size: 14px;
        font-weight: 500;
        letter-spacing: 0.0178571em;
        cursor: pointer;
        transition:
          border-color 0.15s ease,
          background 0.15s ease,
          color 0.15s ease;

        &:hover,
        &.active {
          border-color: var(--mat-sys-primary);
          color: var(--mat-sys-primary);
          background: color-mix(in srgb, var(--mat-sys-primary) 6%, transparent);
        }

        &:disabled {
          cursor: wait;
          opacity: 0.7;
        }
      }

      .toggle-icon {
        font-size: 16px;
        width: 16px;
        height: 16px;
        opacity: 0.6;
      }

      .ai-analysis-section {
        margin: 10px 0;
        padding: 14px;
        background: color-mix(in srgb, var(--mat-sys-primary) 4%, transparent);
        border-radius: 10px;
        border: 1px solid color-mix(in srgb, var(--mat-sys-primary) 15%, transparent);
        max-height: 50vh;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        animation: analysis-expand 200ms ease;
      }

      @keyframes analysis-expand {
        from {
          max-height: 0;
          opacity: 0;
        }
        to {
          max-height: 50vh;
          opacity: 1;
        }
      }
    `,
  ],
})
export class AiInlineAnalysisComponent {
  // State signals — wired by parent page
  llmAvailable = input(false);
  summary = input<string | null>(null);
  error = input<string | null>(null);
  loading = input(false);
  threadId = input<string | null>(null);
  loadingLabel = input('Analyzing...');
  // When true, only renders the button — parent is responsible for showing the result panel
  buttonOnly = input(false);

  // Emits when user clicks the trigger chip for the first time
  analyzeRequested = output<void>();

  // Two-way bindable so parent can read/control expanded state when buttonOnly=true
  expanded = model(true);
  hasContent = computed(() => !!this.summary() || !!this.error() || this.loading());

  constructor() {
    // Auto-expand when new content arrives (handles re-analysis after collapse)
    effect(() => {
      if (this.loading()) {
        this.expanded.set(true);
      }
    });
  }

  onChipClick(): void {
    if (!this.hasContent()) {
      this.analyzeRequested.emit();
    } else {
      this.expanded.update((v) => !v);
    }
  }
}
