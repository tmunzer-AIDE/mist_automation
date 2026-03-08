import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-json-view-dialog',
  standalone: true,
  imports: [CommonModule, MatDialogModule, MatButtonModule, MatIconModule],
  template: `
    <h2 mat-dialog-title>{{ data.title }}</h2>
    <mat-dialog-content>
      <pre class="json-content">{{ data.json | json }}</pre>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="copyJson()">
        <mat-icon>content_copy</mat-icon> Copy
      </button>
      <button mat-button mat-dialog-close>Close</button>
    </mat-dialog-actions>
  `,
  styles: [`
    .json-content {
      font-size: 12px;
      white-space: pre-wrap;
      word-break: break-all;
      background: var(--mat-sys-surface-variant);
      border-radius: 8px;
      padding: 16px;
      margin: 0;
      max-height: 60vh;
      overflow: auto;
    }
  `],
})
export class JsonViewDialogComponent {
  readonly data = inject<{ title: string; json: Record<string, unknown> }>(MAT_DIALOG_DATA);

  copyJson(): void {
    navigator.clipboard.writeText(JSON.stringify(this.data.json, null, 2));
  }
}
