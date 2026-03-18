import { Component, inject, signal } from '@angular/core';
import { JsonPipe } from '@angular/common';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ApiService } from '../../../core/services/api.service';
import { RestoreResponse } from '../../../core/models/backup.model';
import { extractErrorMessage } from '../../../shared/utils/error.utils';

@Component({
  selector: 'app-restore-dialog',
  standalone: true,
  imports: [
    JsonPipe,
    MatDialogModule,
    MatButtonModule,
    MatCheckboxModule,
    MatSnackBarModule,
  ],
  template: `
    <h2 mat-dialog-title>Restore Backup</h2>
    <mat-dialog-content>
      <p class="warning">
        This will restore configuration from the backup. Existing configuration may be overwritten.
      </p>
      <mat-checkbox [checked]="dryRun()" (change)="dryRun.set($event.checked)">Dry run (preview changes only)</mat-checkbox>

      @if (result()) {
        <div class="result">
          <p><strong>Status:</strong> {{ result()!.status }}</p>
          <p>{{ result()!.message }}</p>
          @if (result()!.changes) {
            <pre>{{ result()!.changes | json }}</pre>
          }
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button mat-flat-button color="warn" (click)="restore()" [disabled]="restoring()">
        {{ restoring() ? 'Restoring...' : dryRun() ? 'Preview' : 'Restore' }}
      </button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .warning {
        color: var(--mat-sys-error);
        margin-bottom: 16px;
      }
      .result {
        margin-top: 16px;
        padding: 12px;
        background: var(--mat-sys-surface-container);
        border-radius: 8px;
      }
      pre {
        font-size: 12px;
        max-height: 200px;
        overflow: auto;
      }
    `,
  ],
})
export class RestoreDialogComponent {
  private readonly data = inject<{ backupId: string }>(MAT_DIALOG_DATA);
  private readonly dialogRef = inject(MatDialogRef<RestoreDialogComponent>);
  private readonly api = inject(ApiService);
  private readonly snackBar = inject(MatSnackBar);

  dryRun = signal(true);
  restoring = signal(false);
  result = signal<RestoreResponse | null>(null);

  restore(): void {
    this.restoring.set(true);
    this.result.set(null);

    this.api
      .post<RestoreResponse>(`/backups/${this.data.backupId}/restore?dry_run=${this.dryRun()}`, {})
      .subscribe({
        next: (res) => {
          this.restoring.set(false);
          this.result.set(res);
          if (!this.dryRun()) {
            this.dialogRef.close(true);
          }
        },
        error: (err) => {
          this.restoring.set(false);
          this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
        },
      });
  }
}
