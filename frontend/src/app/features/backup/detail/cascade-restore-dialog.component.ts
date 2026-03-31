import { Component, inject, OnInit, signal } from '@angular/core';
import { extractErrorMessage } from '../../../shared/utils/error.utils';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ApiService } from '../../../core/services/api.service';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import {
  DryRunRestoreResponse,
  CascadeRestorePlanItem,
  CascadeRestoreResult,
  ActiveChildInfo,
} from '../../../core/models/backup.model';

interface DialogData {
  versionId: string;
  objectName: string;
  objectType: string;
  isDeleted: boolean;
}

type DialogStep = 'loading' | 'confirm-simple' | 'show-deps' | 'plan' | 'result';

@Component({
  selector: 'app-cascade-restore-dialog',
  standalone: true,
  imports: [
    MatDialogModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatSnackBarModule,
    StatusBadgeComponent,
  ],
  template: `
    <h2 mat-dialog-title>
      <mat-icon class="title-icon">restore</mat-icon>
      {{ data.isDeleted ? 'Re-create' : 'Restore' }} "{{ data.objectName }}"
    </h2>

    <mat-dialog-content>
      <!-- Loading -->
      @if (step() === 'loading') {
        <mat-progress-bar mode="indeterminate"></mat-progress-bar>
        <p class="status-msg">Checking dependencies...</p>
      }

      <!-- Simple confirm (no dependency issues) -->
      @if (step() === 'confirm-simple') {
        <p class="warning">
          This will {{ data.isDeleted ? 're-create' : 'restore' }} the configuration in Mist.
          Existing configuration may be overwritten.
        </p>
        @if (dryRunResult()?.warnings?.length) {
          <div class="warnings-box">
            @for (w of dryRunResult()!.warnings; track w) {
              <p class="warn-item"><mat-icon class="warn-icon">warning</mat-icon> {{ w }}</p>
            }
          </div>
        }
      }

      <!-- Show deleted dependencies -->
      @if (step() === 'show-deps') {
        <p class="warning">This object has deleted dependencies that must be restored first.</p>

        @if (dryRunResult()?.deleted_dependencies?.length) {
          <h4 class="dep-heading"><mat-icon>arrow_upward</mat-icon> Deleted Parents</h4>
          <div class="dep-list">
            @for (d of dryRunResult()!.deleted_dependencies; track d.object_id) {
              <div class="dep-row">
                <span class="dep-type">{{ d.object_type }}</span>
                <span class="dep-name">{{ d.object_name || d.object_id.slice(0, 8) }}</span>
                <code class="dep-field">{{ d.field_path }}</code>
                <app-status-badge status="deleted"></app-status-badge>
              </div>
            }
          </div>
        }

        @if (dryRunResult()?.deleted_children?.length) {
          <h4 class="dep-heading"><mat-icon>arrow_downward</mat-icon> Deleted Children</h4>
          <div class="dep-list">
            @for (d of dryRunResult()!.deleted_children; track d.object_id) {
              <div class="dep-row">
                <span class="dep-type">{{ d.object_type }}</span>
                <span class="dep-name">{{ d.object_name || d.object_id.slice(0, 8) }}</span>
                <code class="dep-field">{{ d.field_path }}</code>
                <app-status-badge status="deleted"></app-status-badge>
              </div>
            }
          </div>
        }

        @if (dryRunResult()?.active_children?.length) {
          <h4 class="dep-heading"><mat-icon>sync</mat-icon> Active Children (will be updated)</h4>
          <div class="dep-list">
            @for (d of dryRunResult()!.active_children!; track d.object_id) {
              <div class="dep-row">
                <span class="dep-type">{{ d.object_type }}</span>
                <span class="dep-name">{{ d.object_name || d.object_id.slice(0, 8) }}</span>
                <code class="dep-field">{{ d.field_path }}</code>
                <app-status-badge status="active"></app-status-badge>
              </div>
            }
          </div>
        }

        @if (dryRunResult()?.warnings?.length) {
          <div class="warnings-box">
            @for (w of dryRunResult()!.warnings; track w) {
              <p class="warn-item"><mat-icon class="warn-icon">warning</mat-icon> {{ w }}</p>
            }
          </div>
        }
      }

      <!-- Cascade plan preview -->
      @if (step() === 'plan') {
        <p class="info-msg">The following objects will be restored in order:</p>
        <div class="plan-list">
          @for (item of cascadePlan(); track item.object_id; let i = $index) {
            <div class="plan-row">
              <span class="plan-order">{{ i + 1 }}</span>
              <span class="plan-role" [class]="'role-' + item.role">{{ item.role }}</span>
              <span class="dep-type">{{ item.object_type }}</span>
              <span class="dep-name">{{ item.object_name || item.object_id.slice(0, 8) }}</span>
            </div>
          }
        </div>
      }

      <!-- Result -->
      @if (step() === 'result' && cascadeResult()) {
        <div class="result-box">
          <p class="result-status">
            <mat-icon class="result-icon">check_circle</mat-icon>
            {{ cascadeResult()!.status }}
          </p>
          @if (cascadeResult()!.restored_objects.length) {
            <div class="plan-list">
              @for (obj of cascadeResult()!.restored_objects; track obj.original_object_id) {
                <div class="plan-row">
                  <span class="plan-role" [class]="'role-' + obj.role">{{ obj.role }}</span>
                  <span class="dep-type">{{ obj.object_type }}</span>
                  <span class="dep-name">{{
                    obj.object_name || obj.original_object_id.slice(0, 8)
                  }}</span>
                  @if (obj.new_object_id !== obj.original_object_id) {
                    <code class="id-remap"
                      >{{ obj.original_object_id.slice(0, 8) }} &rarr;
                      {{ obj.new_object_id.slice(0, 8) }}</code
                    >
                  }
                </div>
              }
            </div>
          }
        </div>
      }

      @if (error()) {
        <p class="error-msg"><mat-icon class="err-icon">error</mat-icon> {{ error() }}</p>
      }
    </mat-dialog-content>

    <mat-dialog-actions align="end">
      @if (step() === 'loading') {
        <button mat-button mat-dialog-close>Cancel</button>
      }

      @if (step() === 'confirm-simple') {
        <button mat-button mat-dialog-close>Cancel</button>
        <button mat-flat-button color="warn" (click)="executeSimple()" [disabled]="executing()">
          {{ executing() ? 'Restoring...' : data.isDeleted ? 'Re-create' : 'Restore' }}
        </button>
      }

      @if (step() === 'show-deps') {
        <button mat-button mat-dialog-close>Cancel</button>
        @if (!dryRunResult()?.deleted_dependencies?.length) {
          <button mat-stroked-button (click)="executeSimple()" [disabled]="executing()">
            Restore Only This
          </button>
        }
        <button mat-flat-button color="warn" (click)="loadCascadePlan()" [disabled]="executing()">
          {{ executing() ? 'Loading...' : 'Restore All' }}
        </button>
      }

      @if (step() === 'plan') {
        <button mat-button mat-dialog-close>Cancel</button>
        <button mat-flat-button color="warn" (click)="executeCascade()" [disabled]="executing()">
          {{ executing() ? 'Restoring...' : 'Confirm Cascade Restore' }}
        </button>
      }

      @if (step() === 'result') {
        <button mat-flat-button (click)="closeWithResult()">Close</button>
      }
    </mat-dialog-actions>
  `,
  styles: [
    `
      .title-icon {
        vertical-align: middle;
        margin-right: 6px;
      }

      .status-msg {
        text-align: center;
        color: var(--mat-sys-on-surface-variant);
        margin-top: 16px;
      }

      .warning {
        color: var(--mat-sys-error);
        margin-bottom: 16px;
      }

      .info-msg {
        color: var(--mat-sys-on-surface-variant);
        margin-bottom: 12px;
      }

      .warnings-box {
        margin-top: 12px;
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

      .dep-heading {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 13px;
        font-weight: 600;
        color: var(--mat-sys-on-surface-variant);
        margin: 12px 0 6px;
      }

      .dep-heading mat-icon {
        font-size: 18px;
        width: 18px;
        height: 18px;
      }

      .dep-list,
      .plan-list {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }

      .dep-row,
      .plan-row {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 10px;
        border-radius: 6px;
        background: var(--mat-sys-surface-container-low);
      }

      .dep-type {
        flex-shrink: 0;
        font-size: 11px;
        font-weight: 600;
        padding: 1px 8px;
        border-radius: 8px;
        background: var(--mat-sys-surface-container);
        color: var(--mat-sys-on-surface-variant);
      }

      .dep-name {
        font-size: 13px;
        font-weight: 500;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        min-width: 0;
      }

      .dep-field {
        font-size: 11px;
        font-family: var(--app-font-mono);
        color: var(--mat-sys-on-surface-variant);
        margin-left: auto;
        flex-shrink: 0;
      }

      .plan-order {
        flex-shrink: 0;
        width: 20px;
        height: 20px;
        border-radius: 50%;
        background: var(--mat-sys-primary);
        color: var(--mat-sys-on-primary);
        font-size: 11px;
        font-weight: 700;
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .plan-role {
        flex-shrink: 0;
        font-size: 11px;
        font-weight: 600;
        padding: 1px 8px;
        border-radius: 8px;
        text-transform: uppercase;

        &.role-parent {
          background: var(--app-info-chip-bg);
          color: var(--app-info-chip);
        }
        &.role-target {
          background: var(--app-purple-bg);
          color: var(--app-purple);
        }
        &.role-child {
          background: var(--app-success-bg);
          color: var(--app-success);
        }
        &.role-update {
          background: var(--app-warning-bg);
          color: var(--app-warning-lvl);
        }
      }

      .id-remap {
        font-size: 11px;
        font-family: var(--app-font-mono);
        color: var(--mat-sys-on-surface-variant);
        margin-left: auto;
        flex-shrink: 0;
      }

      .result-box {
        padding: 12px;
        background: var(--mat-sys-surface-container);
        border-radius: 8px;
      }

      .result-status {
        display: flex;
        align-items: center;
        gap: 6px;
        font-weight: 600;
        color: var(--app-success);
      }

      .result-icon {
        color: var(--app-success-border);
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
export class CascadeRestoreDialogComponent implements OnInit {
  readonly data = inject<DialogData>(MAT_DIALOG_DATA);
  private readonly dialogRef = inject(MatDialogRef<CascadeRestoreDialogComponent>);
  private readonly api = inject(ApiService);
  private readonly snackBar = inject(MatSnackBar);

  step = signal<DialogStep>('loading');
  executing = signal(false);
  error = signal<string | null>(null);

  dryRunResult = signal<DryRunRestoreResponse | null>(null);
  cascadePlan = signal<CascadeRestorePlanItem[]>([]);
  cascadeResult = signal<CascadeRestoreResult | null>(null);
  private targetObjectId: string | null = null;

  ngOnInit(): void {
    this.runDryRun();
  }

  private runDryRun(): void {
    this.step.set('loading');
    this.error.set(null);

    this.api
      .post<DryRunRestoreResponse>(
        `/backups/objects/versions/${this.data.versionId}/restore?dry_run=true`,
      )
      .subscribe({
        next: (res) => {
          this.dryRunResult.set(res);
          this.targetObjectId = res.object_id;
          const hasDeps =
            res.deleted_dependencies?.length > 0 ||
            res.deleted_children?.length > 0 ||
            (res.active_children?.length ?? 0) > 0;
          this.step.set(hasDeps ? 'show-deps' : 'confirm-simple');
        },
        error: (err) => {
          this.error.set(extractErrorMessage(err) || 'Failed to check dependencies');
          this.step.set('confirm-simple');
        },
      });
  }

  executeSimple(): void {
    this.executing.set(true);
    this.error.set(null);

    this.api
      .post<{
        status: string;
        object_name?: string;
        note?: string;
        id_remap?: Record<string, string>;
      }>(`/backups/objects/versions/${this.data.versionId}/restore`)
      .subscribe({
        next: (res) => {
          this.executing.set(false);
          const newId = res.id_remap?.[this.targetObjectId || ''];
          const msg = res.note
            ? `Restored — ${res.note}`
            : `Restored "${this.data.objectName}" successfully`;
          this.snackBar.open(msg, 'OK', { duration: 5000 });
          this.dialogRef.close({ restored: true, newObjectId: newId });
        },
        error: (err) => {
          this.executing.set(false);
          this.error.set(extractErrorMessage(err) || 'Restore failed');
        },
      });
  }

  loadCascadePlan(): void {
    this.executing.set(true);
    this.error.set(null);

    this.api
      .post<{
        status: string;
        plan?: CascadeRestorePlanItem[];
      }>(`/backups/objects/versions/${this.data.versionId}/restore?cascade=true&dry_run=true`)
      .subscribe({
        next: (res) => {
          this.executing.set(false);
          this.cascadePlan.set(res.plan || []);
          this.step.set('plan');
        },
        error: (err) => {
          this.executing.set(false);
          this.error.set(extractErrorMessage(err) || 'Failed to load cascade plan');
        },
      });
  }

  executeCascade(): void {
    this.executing.set(true);
    this.error.set(null);

    this.api
      .post<CascadeRestoreResult>(
        `/backups/objects/versions/${this.data.versionId}/restore?cascade=true`,
      )
      .subscribe({
        next: (res) => {
          this.executing.set(false);
          this.cascadeResult.set(res);
          this.step.set('result');
        },
        error: (err) => {
          this.executing.set(false);
          this.error.set(extractErrorMessage(err) || 'Cascade restore failed');
        },
      });
  }

  closeWithResult(): void {
    const newId = this.cascadeResult()?.id_remap?.[this.targetObjectId || ''];
    this.dialogRef.close({ restored: true, newObjectId: newId });
  }
}
