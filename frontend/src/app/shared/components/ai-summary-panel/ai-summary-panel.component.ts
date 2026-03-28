import { Component, input, output } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AiChatPanelComponent } from '../ai-chat-panel/ai-chat-panel.component';

@Component({
  selector: 'app-ai-summary-panel',
  standalone: true,
  imports: [MatButtonModule, MatIconModule, MatTooltipModule, AiChatPanelComponent],
  template: `
    @if (open()) {
      <div class="ai-summary-panel">
        <div class="panel-close">
          <button mat-icon-button (click)="closed.emit()" matTooltip="Close">
            <mat-icon>close</mat-icon>
          </button>
        </div>
        <app-ai-chat-panel
          [threadId]="threadId()"
          [initialSummary]="summary()"
          [errorMessage]="error()"
          [parentLoading]="loading()"
          [loadingLabel]="loadingLabel()"
        ></app-ai-chat-panel>
      </div>
    }
  `,
  styles: [`
    .ai-summary-panel {
      margin-bottom: 16px;
      border-radius: 12px;
      border: 1px solid var(--mat-sys-outline-variant);
      overflow: hidden;
      background: var(--mat-sys-surface);
      max-height: 50vh;
      display: flex;
      flex-direction: column;
      animation: slide-down 200ms ease;
    }

    @keyframes slide-down {
      from {
        max-height: 0;
        opacity: 0;
      }
      to {
        max-height: 50vh;
        opacity: 1;
      }
    }

    .panel-close {
      display: flex;
      justify-content: flex-end;
      padding: 4px 4px 0 0;
      flex-shrink: 0;
    }
  `],
})
export class AiSummaryPanelComponent {
  open = input(false);
  summary = input<string | null>(null);
  error = input<string | null>(null);
  loading = input(false);
  threadId = input<string | null>(null);
  loadingLabel = input('Analyzing...');

  closed = output<void>();
}
