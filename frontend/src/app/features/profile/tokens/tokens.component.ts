import { Component, inject, OnInit, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import {
  MAT_DIALOG_DATA,
  MatDialog,
  MatDialogModule,
  MatDialogRef,
} from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
  PatService,
  PersonalAccessToken,
  PATCreateResponse,
} from '../../../core/services/pat.service';
import {
  ConfirmDialogComponent,
  ConfirmDialogData,
} from '../../../shared/components/confirm-dialog/confirm-dialog.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { extractErrorMessage } from '../../../shared/utils/error.utils';

@Component({
  selector: 'app-tokens',
  standalone: true,
  imports: [
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatSnackBarModule,
    MatTooltipModule,
    MatDialogModule,
    DateTimePipe,
    EmptyStateComponent,
  ],
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    }

    <div class="tokens-header">
      <div class="tokens-intro">
        <h2>Personal Access Tokens</h2>
        <p>
          Long-lived tokens for connecting external MCP clients (Claude Desktop, VS Code, Cursor)
          to this server. Each token runs tools as you, with your roles and permissions.
        </p>
      </div>
      <button
        mat-flat-button
        color="primary"
        (click)="openCreateDialog()"
        [disabled]="!canCreate()"
        [matTooltip]="canCreate() ? '' : 'Token limit reached — revoke one to create another'"
      >
        <mat-icon>add</mat-icon>
        New token
      </button>
    </div>

    <p class="tokens-count">{{ tokens().length }} / {{ maxPerUser() }} active</p>

    @if (!loading() && tokens().length === 0) {
      <app-empty-state
        icon="vpn_key"
        title="No personal access tokens"
        message="Create a token to connect Claude Desktop or another MCP client."
      ></app-empty-state>
    } @else if (tokens().length > 0) {
      <div class="table-container">
        <table mat-table [dataSource]="tokens()">
          <ng-container matColumnDef="name">
            <th mat-header-cell *matHeaderCellDef>Name</th>
            <td mat-cell *matCellDef="let t">
              <mat-icon class="token-icon">vpn_key</mat-icon>
              {{ t.name }}
            </td>
          </ng-container>

          <ng-container matColumnDef="prefix">
            <th mat-header-cell *matHeaderCellDef>Token</th>
            <td mat-cell *matCellDef="let t">
              <code>{{ t.token_prefix }}…</code>
            </td>
          </ng-container>

          <ng-container matColumnDef="created_at">
            <th mat-header-cell *matHeaderCellDef>Created</th>
            <td mat-cell *matCellDef="let t">{{ t.created_at | dateTime }}</td>
          </ng-container>

          <ng-container matColumnDef="last_used_at">
            <th mat-header-cell *matHeaderCellDef>Last used</th>
            <td mat-cell *matCellDef="let t">
              {{ t.last_used_at ? (t.last_used_at | dateTime) : 'Never' }}
            </td>
          </ng-container>

          <ng-container matColumnDef="expires_at">
            <th mat-header-cell *matHeaderCellDef>Expires</th>
            <td mat-cell *matCellDef="let t">
              {{ t.expires_at ? (t.expires_at | dateTime) : 'Never' }}
            </td>
          </ng-container>

          <ng-container matColumnDef="actions">
            <th mat-header-cell *matHeaderCellDef></th>
            <td mat-cell *matCellDef="let t">
              <button mat-stroked-button color="warn" (click)="confirmRevoke(t)">Revoke</button>
            </td>
          </ng-container>

          <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
          <tr mat-row *matRowDef="let row; columns: displayedColumns"></tr>
        </table>
      </div>
    }
  `,
  styles: [
    `
      .tokens-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 16px;
        margin-bottom: 8px;
      }
      .tokens-intro h2 {
        margin: 0 0 4px 0;
        font-size: 18px;
      }
      .tokens-intro p {
        margin: 0;
        color: var(--mat-sys-on-surface-variant);
        max-width: 640px;
      }
      .tokens-count {
        margin: 16px 0 8px 0;
        color: var(--mat-sys-on-surface-variant);
        font-size: 13px;
      }
      .table-container {
        overflow-x: auto;
      }
      table {
        width: 100%;
      }
      .token-icon {
        vertical-align: middle;
        margin-right: 8px;
        font-size: 20px;
        height: 20px;
        width: 20px;
      }
      code {
        font-family: 'SF Mono', Menlo, Monaco, Consolas, monospace;
        font-size: 12px;
        padding: 2px 6px;
        background: var(--mat-sys-surface-container-highest);
        border-radius: 4px;
      }
    `,
  ],
})
export class TokensComponent implements OnInit {
  private readonly patService = inject(PatService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);

  tokens = signal<PersonalAccessToken[]>([]);
  maxPerUser = signal(10);
  loading = signal(true);
  displayedColumns = ['name', 'prefix', 'created_at', 'last_used_at', 'expires_at', 'actions'];

  canCreate(): boolean {
    return this.tokens().length < this.maxPerUser();
  }

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.patService.list().subscribe({
      next: (res) => {
        this.tokens.set(res.tokens);
        this.maxPerUser.set(res.max_per_user);
        this.loading.set(false);
      },
      error: (err) => {
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
        this.loading.set(false);
      },
    });
  }

  openCreateDialog(): void {
    const ref = this.dialog.open(CreateTokenDialog, { width: '480px' });
    ref.afterClosed().subscribe((result: { name: string; expires_at: string | null } | null) => {
      if (!result) return;
      this.patService.create(result).subscribe({
        next: (res) => {
          this.load();
          this.dialog.open(RevealTokenDialog, {
            width: '560px',
            data: res,
            disableClose: true,
          });
        },
        error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
      });
    });
  }

  confirmRevoke(token: PersonalAccessToken): void {
    const data: ConfirmDialogData = {
      title: 'Revoke token?',
      message: `The token "${token.name}" will stop working immediately. This cannot be undone.`,
      confirmText: 'Revoke',
      warn: true,
    };
    this.dialog
      .open(ConfirmDialogComponent, { data })
      .afterClosed()
      .subscribe((confirmed) => {
        if (!confirmed) return;
        this.patService.revoke(token.id).subscribe({
          next: () => {
            this.snackBar.open('Token revoked', 'OK', { duration: 3000 });
            this.load();
          },
          error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
        });
      });
  }
}

// ---------- Create dialog ----------

@Component({
  selector: 'app-create-token-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
  ],
  template: `
    <h2 mat-dialog-title>New personal access token</h2>
    <form [formGroup]="form" (ngSubmit)="submit()">
      <mat-dialog-content>
        <mat-form-field appearance="outline" class="full-width">
          <mat-label>Name</mat-label>
          <input
            matInput
            formControlName="name"
            placeholder="e.g. Claude Desktop – Work Laptop"
            autocomplete="off"
            required
          />
          <mat-hint>A label to help you recognize this token later.</mat-hint>
        </mat-form-field>

        <mat-form-field appearance="outline" class="full-width">
          <mat-label>Expires at (optional)</mat-label>
          <input matInput type="datetime-local" formControlName="expiresAt" />
          <mat-hint>Leave blank for no expiration. UTC.</mat-hint>
        </mat-form-field>
      </mat-dialog-content>
      <mat-dialog-actions align="end">
        <button mat-button type="button" mat-dialog-close>Cancel</button>
        <button mat-flat-button color="primary" type="submit" [disabled]="form.invalid">
          Create token
        </button>
      </mat-dialog-actions>
    </form>
  `,
  styles: [
    `
      .full-width {
        width: 100%;
      }
      mat-dialog-content {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
    `,
  ],
})
export class CreateTokenDialog {
  private readonly dialogRef = inject(MatDialogRef<CreateTokenDialog>);

  form = new FormGroup({
    name: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
    expiresAt: new FormControl<string | null>(null),
  });

  submit(): void {
    if (this.form.invalid) return;
    const { name, expiresAt } = this.form.getRawValue();
    const expires_at = expiresAt ? new Date(expiresAt).toISOString() : null;
    this.dialogRef.close({ name: name.trim(), expires_at });
  }
}

// ---------- Reveal-once dialog ----------

@Component({
  selector: 'app-reveal-token-dialog',
  standalone: true,
  imports: [MatDialogModule, MatButtonModule, MatIconModule],
  template: `
    <h2 mat-dialog-title>
      <mat-icon class="warn-icon">warning</mat-icon>
      Copy your token now
    </h2>
    <mat-dialog-content>
      <p>
        This is the only time you will see the full token. Store it somewhere safe — if you lose
        it, revoke this token and create a new one.
      </p>
      <div class="token-box">
        <code>{{ data.token }}</code>
        <button mat-icon-button (click)="copy()" aria-label="Copy token">
          <mat-icon>{{ copied ? 'check' : 'content_copy' }}</mat-icon>
        </button>
      </div>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-flat-button color="primary" mat-dialog-close>I've saved it</button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .warn-icon {
        color: var(--app-warn, #f39c12);
        vertical-align: middle;
        margin-right: 4px;
      }
      .token-box {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 12px;
        background: var(--mat-sys-surface-container-highest);
        border-radius: 6px;
        font-family: 'SF Mono', Menlo, Monaco, Consolas, monospace;
        font-size: 13px;
        word-break: break-all;
      }
      .token-box code {
        flex: 1;
      }
    `,
  ],
})
export class RevealTokenDialog {
  readonly data = inject<PATCreateResponse>(MAT_DIALOG_DATA);
  private readonly snackBar = inject(MatSnackBar);
  copied = false;

  copy(): void {
    navigator.clipboard
      .writeText(this.data.token)
      .then(() => {
        this.copied = true;
        this.snackBar.open('Token copied', 'OK', { duration: 2000 });
      })
      .catch(() => {
        this.snackBar.open('Copy failed — select and copy manually', 'OK', { duration: 3000 });
      });
  }
}
