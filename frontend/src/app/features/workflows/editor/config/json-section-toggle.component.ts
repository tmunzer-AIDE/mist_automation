import { Component, EventEmitter, Input, Output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';

@Component({
  selector: 'app-json-section-toggle',
  standalone: true,
  imports: [FormsModule, MatIconModule, MatButtonModule, MatTooltipModule],
  template: `
    <div class="section-header">
      <span class="section-label">{{ sectionLabel }}</span>
      <button
        mat-icon-button
        class="toggle-btn"
        [matTooltip]="jsonMode() ? 'Switch to form view' : 'Switch to JSON view'"
        (click)="toggleMode()"
      >
        <mat-icon>{{ jsonMode() ? 'list' : 'code' }}</mat-icon>
      </button>
    </div>

    @if (jsonMode()) {
      <div class="json-editor">
        <textarea
          class="json-textarea"
          [ngModel]="jsonText()"
          (ngModelChange)="onJsonInput($event)"
          spellcheck="false"
        ></textarea>
        @if (parseError()) {
          <div class="parse-error">{{ parseError() }}</div>
        }
        <div class="json-actions">
          <button mat-button class="json-action-btn" (click)="copyJson()" matTooltip="Copy JSON">
            <mat-icon>content_copy</mat-icon> Copy
          </button>
          <button
            mat-button
            class="json-action-btn"
            [disabled]="!!parseError()"
            (click)="applyJson()"
            matTooltip="Apply changes"
          >
            <mat-icon>check</mat-icon> Apply
          </button>
        </div>
      </div>
    } @else {
      <ng-content />
    }
  `,
  styles: [
    `
      .section-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-top: 12px;
        margin-bottom: 4px;
      }

      .section-label {
        font-size: 12px;
        font-weight: 500;
        text-transform: uppercase;
        color: var(--mat-sys-on-surface-variant, #666);
        letter-spacing: 0.5px;
      }

      .toggle-btn {
        width: 28px;
        height: 28px;
        line-height: 28px;

        mat-icon {
          font-size: 18px;
          width: 18px;
          height: 18px;
        }
      }

      .json-editor {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }

      .json-textarea {
        font-family: 'Roboto Mono', monospace;
        font-size: 12px;
        line-height: 1.4;
        padding: 8px;
        border: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
        border-radius: 8px;
        min-height: 120px;
        resize: vertical;
        background: var(--mat-sys-surface-container-lowest, #fff);
        color: var(--mat-sys-on-surface, #1c1b1f);
      }

      .json-textarea:focus {
        outline: none;
        border-color: var(--mat-sys-primary, #6750a4);
      }

      .parse-error {
        font-size: 12px;
        color: var(--mat-sys-error, #b3261e);
        padding: 4px 0;
      }

      .json-actions {
        display: flex;
        gap: 8px;
        justify-content: flex-end;
      }

      .json-action-btn {
        font-size: 12px;

        mat-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
          margin-right: 2px;
        }
      }
    `,
  ],
})
export class JsonSectionToggleComponent {
  @Input() sectionLabel = '';
  @Input() sectionData: unknown[] = [];
  @Output() dataChanged = new EventEmitter<unknown[]>();

  jsonMode = signal(false);
  jsonText = signal('');
  parseError = signal<string | null>(null);

  private pendingJson: unknown[] | null = null;

  toggleMode(): void {
    if (!this.jsonMode()) {
      this.jsonText.set(JSON.stringify(this.sectionData ?? [], null, 2));
      this.parseError.set(null);
      this.pendingJson = null;
    }
    this.jsonMode.update((v) => !v);
  }

  onJsonInput(value: string): void {
    this.jsonText.set(value);
    try {
      const parsed = JSON.parse(value);
      if (!Array.isArray(parsed)) {
        this.parseError.set('Must be a JSON array');
        this.pendingJson = null;
        return;
      }
      this.parseError.set(null);
      this.pendingJson = parsed;
    } catch (e) {
      this.parseError.set('Invalid JSON');
      this.pendingJson = null;
    }
  }

  applyJson(): void {
    if (this.pendingJson) {
      this.dataChanged.emit(this.pendingJson);
      this.jsonMode.set(false);
    }
  }

  copyJson(): void {
    navigator.clipboard.writeText(this.jsonText());
  }
}
