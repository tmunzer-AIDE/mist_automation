import { Component, ChangeDetectorRef, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../../core/services/api.service';
import { RestoreResponse } from '../../../core/models/backup.model';

@Component({
  selector: 'app-restore-dialog',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
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
      <mat-checkbox [(ngModel)]="dryRun">Dry run (preview changes only)</mat-checkbox>

      @if (result) {
        <div class="result">
          <p><strong>Status:</strong> {{ result.status }}</p>
          <p>{{ result.message }}</p>
          @if (result.changes) {
            <pre>{{ result.changes | json }}</pre>
          }
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button mat-flat-button color="warn" (click)="restore()" [disabled]="restoring">
        {{ restoring ? 'Restoring...' : (dryRun ? 'Preview' : 'Restore') }}
      </button>
    </mat-dialog-actions>
  `,
  styles: [`
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
  `],
})
export class RestoreDialogComponent {
  private readonly data = inject<{ backupId: string }>(MAT_DIALOG_DATA);
  private readonly dialogRef = inject(MatDialogRef<RestoreDialogComponent>);
  private readonly api = inject(ApiService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly cdr = inject(ChangeDetectorRef);

  dryRun = true;
  restoring = false;
  result: RestoreResponse | null = null;

  restore(): void {
    this.restoring = true;
    this.result = null;

    this.api
      .post<RestoreResponse>(`/backups/${this.data.backupId}/restore?dry_run=${this.dryRun}`, {})
      .subscribe({
        next: (res) => {
          this.restoring = false;
          this.result = res;
          this.cdr.detectChanges();
          if (!this.dryRun) {
            this.dialogRef.close(true);
          }
        },
        error: (err) => {
          this.restoring = false;
          this.snackBar.open(err.message, 'OK', { duration: 5000 });
          this.cdr.detectChanges();
        },
      });
  }
}
