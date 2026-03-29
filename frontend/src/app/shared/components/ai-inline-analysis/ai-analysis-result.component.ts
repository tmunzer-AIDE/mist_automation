import { Component, input } from '@angular/core';
import { AiChatPanelComponent } from '../ai-chat-panel/ai-chat-panel.component';

@Component({
  selector: 'app-ai-analysis-result',
  standalone: true,
  imports: [AiChatPanelComponent],
  template: `
    <div class="ai-analysis-section">
      <app-ai-chat-panel
        [threadId]="threadId()"
        [initialSummary]="summary()"
        [errorMessage]="error()"
        [parentLoading]="loading()"
        [loadingLabel]="loadingLabel()"
      />
    </div>
  `,
  styles: [
    `
      .ai-analysis-section {
        padding: 14px;
        background: color-mix(in srgb, var(--mat-sys-primary) 4%, transparent);
        border-radius: 10px;
        border: 1px solid color-mix(in srgb, var(--mat-sys-primary) 15%, transparent);
        max-height: 40vh;
        overflow: hidden;
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
          max-height: 40vh;
          opacity: 1;
        }
      }
    `,
  ],
})
export class AiAnalysisResultComponent {
  threadId = input<string | null>(null);
  summary = input<string | null>(null);
  error = input<string | null>(null);
  loading = input(false);
  loadingLabel = input('Analyzing...');
}
