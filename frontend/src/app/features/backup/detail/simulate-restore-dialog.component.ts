import { Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ApiService } from '../../../core/services/api.service';
import { RestoreSimulationResponse } from '../../../core/models/backup.model';
import { extractErrorMessage } from '../../../shared/utils/error.utils';

interface SimulateDialogData {
  versionId: string;
  objectName: string;
  objectType: string;
}

type DialogStep = 'confirm' | 'loading' | 'result' | 'error';

@Component({
  selector: 'app-simulate-restore-dialog',
  standalone: true,
  imports: [MatDialogModule, MatButtonModule, MatIconModule, MatProgressBarModule],
  template: `
    <h2 mat-dialog-title>
      <mat-icon class="title-icon">science</mat-icon>
      Restore Simulation — "{{ data.objectName }}"
    </h2>

    <mat-dialog-content>
      @if (step() === 'confirm') {
        <p class="info-msg">
          This will apply the restore to a <strong>Digital Twin</strong> — a virtual copy of your
          network. The real network will not be affected.
        </p>
        <p class="info-msg">
          Once complete, you can review the outcome and optionally open the Digital Twin to
          inspect the result in detail.
        </p>
      }

      @if (step() === 'loading') {
        <mat-progress-bar mode="indeterminate"></mat-progress-bar>
        <p class="status-msg">Running Digital Twin simulation...</p>
      }

      @if (step() === 'result' && result()) {
        <div
          class="result-header"
          [class.safe]="result()!.execution_safe"
          [class.unsafe]="!result()!.execution_safe"
        >
          <mat-icon class="result-icon">{{
            result()!.execution_safe ? 'check_circle' : 'warning'
          }}</mat-icon>
          <span class="result-label">{{
            result()!.execution_safe ? 'Restore succeeded in Digital Twin' : 'Restore failed in Digital Twin'
          }}</span>
          <span [class]="'severity-chip sev-' + result()!.overall_severity">
            {{ result()!.overall_severity }}
          </span>
        </div>

        @if (result()!.summary && !result()!.execution_safe) {
          <p class="summary-text">{{ result()!.summary }}</p>
        }

        @if (result()!.counts.warnings || result()!.counts.errors || result()!.counts.critical) {
          <div class="counts-row">
            @if (result()!.counts.warnings) {
              <span class="count-chip warn">
                <mat-icon>warning</mat-icon>
                {{ result()!.counts.warnings }} warning{{ result()!.counts.warnings === 1 ? '' : 's' }}
              </span>
            }
            @if (result()!.counts.errors) {
              <span class="count-chip err">
                <mat-icon>error</mat-icon>
                {{ result()!.counts.errors }} error{{ result()!.counts.errors === 1 ? '' : 's' }}
              </span>
            }
            @if (result()!.counts.critical) {
              <span class="count-chip crit">
                <mat-icon>dangerous</mat-icon> {{ result()!.counts.critical }} critical
              </span>
            }
          </div>
        }

        @if (result()!.warnings.length) {
          <div class="warnings-list">
            @for (w of result()!.warnings; track w) {
              <p class="warn-item"><mat-icon class="warn-icon">warning</mat-icon> {{ w }}</p>
            }
          </div>
        }
      }

      @if (step() === 'error') {
        <p class="error-msg"><mat-icon class="err-icon">error</mat-icon> {{ error() }}</p>
      }
    </mat-dialog-content>

    <mat-dialog-actions align="end">
      @if (step() === 'confirm' || step() === 'loading') {
        <button mat-button mat-dialog-close [disabled]="step() === 'loading'">Cancel</button>
      }
      @if (step() === 'confirm') {
        <button mat-flat-button color="primary" [disabled]="step() !== 'confirm'" (click)="runSimulation()">
          <mat-icon>science</mat-icon> Run Simulation
        </button>
      }
      @if (step() === 'result' || step() === 'error') {
        <button mat-button mat-dialog-close>Close</button>
        @if (result()?.twin_session_id) {
          <button mat-flat-button color="primary" (click)="openTwin()">
            <mat-icon>open_in_new</mat-icon> Open Digital Twin
          </button>
        }
      }
    </mat-dialog-actions>
  `,
  styles: [
    `
      .title-icon {
        vertical-align: middle;
        margin-right: 6px;
      }

      .info-msg {
        font-size: 14px;
        color: var(--mat-sys-on-surface-variant);
        line-height: 1.6;
        margin-bottom: 10px;
      }

      .status-msg {
        text-align: center;
        color: var(--mat-sys-on-surface-variant);
        margin-top: 16px;
      }

      .result-header {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px 16px;
        border-radius: 8px;
        margin-bottom: 16px;
        font-weight: 600;
        font-size: 15px;
      }

      .result-header.safe {
        background: var(--app-success-bg);
        color: var(--app-success);
      }

      .result-header.safe .result-icon {
        color: var(--app-success-border);
      }

      .result-header.unsafe {
        background: var(--app-warning-bg);
        color: var(--app-warning-lvl);
      }

      .result-header.unsafe .result-icon {
        color: var(--app-warning);
      }

      .result-label {
        flex: 1;
      }

      .severity-chip {
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        padding: 2px 10px;
        border-radius: 10px;
        background: var(--mat-sys-surface-container);
        color: var(--mat-sys-on-surface-variant);
      }

      .severity-chip.sev-clean   { background: var(--app-success-bg); color: var(--app-success); }
      .severity-chip.sev-info    { background: var(--app-info-chip-bg); color: var(--app-info-chip); }
      .severity-chip.sev-warning { background: var(--app-warning-bg); color: var(--app-warning-lvl); }
      .severity-chip.sev-error   { background: var(--mat-sys-error-container); color: var(--mat-sys-on-error-container); }
      .severity-chip.sev-critical { background: var(--mat-sys-error); color: var(--mat-sys-on-error); }

      .summary-text {
        font-size: 14px;
        color: var(--mat-sys-on-surface-variant);
        margin-bottom: 14px;
        line-height: 1.5;
      }

      .counts-row {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-bottom: 14px;
      }

      .count-chip {
        display: flex;
        align-items: center;
        gap: 4px;
        font-size: 12px;
        font-weight: 600;
        padding: 3px 10px;
        border-radius: 10px;
      }

      .count-chip mat-icon {
        font-size: 14px;
        width: 14px;
        height: 14px;
      }

      .count-chip.warn { background: var(--app-warning-bg); color: var(--app-warning-lvl); }
      .count-chip.err  { background: var(--mat-sys-error-container); color: var(--mat-sys-on-error-container); }
      .count-chip.crit { background: var(--mat-sys-error); color: var(--mat-sys-on-error); }

      .warnings-list {
        padding: 8px 12px;
        background: var(--app-warning-bg);
        border-radius: 8px;
      }

      .warn-item {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 13px;
        color: var(--app-warning-lvl);
        margin: 4px 0;
      }

      .warn-icon {
        font-size: 18px;
        width: 18px;
        height: 18px;
        color: var(--app-warning);
      }

      .error-msg {
        display: flex;
        align-items: center;
        gap: 6px;
        color: var(--mat-sys-error);
        margin-top: 12px;
      }

      .err-icon {
        font-size: 18px;
        width: 18px;
        height: 18px;
      }
    `,
  ],
})
export class SimulateRestoreDialogComponent {
  readonly data = inject<SimulateDialogData>(MAT_DIALOG_DATA);
  private readonly dialogRef = inject(MatDialogRef<SimulateRestoreDialogComponent>);
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  step = signal<DialogStep>('confirm');
  result = signal<RestoreSimulationResponse | null>(null);
  error = signal<string | null>(null);

  runSimulation(): void {
    this.step.set('loading');
    this.api
      .post<RestoreSimulationResponse>(
        `/backups/objects/versions/${this.data.versionId}/restore?simulate=true`,
      )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.result.set(res);
          this.step.set('result');
        },
        error: (err) => {
          this.error.set(extractErrorMessage(err) || 'Simulation failed');
          this.step.set('error');
        },
      });
  }

  openTwin(): void {
    const twinId = this.result()?.twin_session_id;
    if (twinId) {
      this.dialogRef.close({ twinSessionId: twinId });
      this.router.navigate(['/digital-twin', twinId]);
    }
  }
}
