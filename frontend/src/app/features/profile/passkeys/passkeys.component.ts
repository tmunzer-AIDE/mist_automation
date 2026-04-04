import { Component, inject, OnInit, signal } from '@angular/core';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { PasskeyService } from '../../../core/services/passkey.service';
import { PasskeyResponse } from '../../../core/models/passkey.model';
import { extractErrorMessage } from '../../../shared/utils/error.utils';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';

@Component({
  selector: 'app-passkeys',
  standalone: true,
  imports: [
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatSnackBarModule,
    DateTimePipe,
    EmptyStateComponent,
  ],
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    }

    <div class="passkeys-header">
      @if (passkeySupported) {
        <button mat-flat-button (click)="addPasskey()">
          <mat-icon>add</mat-icon>
          Add passkey
        </button>
      }
    </div>

    @if (!loading() && passkeys().length === 0) {
      <app-empty-state
        icon="passkey"
        title="No passkeys registered"
        message="Add a passkey for faster, passwordless sign-in."
      ></app-empty-state>
    } @else if (passkeys().length > 0) {
      <div class="table-container">
        <table mat-table [dataSource]="passkeys()">
          <ng-container matColumnDef="name">
            <th mat-header-cell *matHeaderCellDef>Name</th>
            <td mat-cell *matCellDef="let p">
              <mat-icon class="passkey-icon">passkey</mat-icon>
              {{ p.name }}
            </td>
          </ng-container>

          <ng-container matColumnDef="created_at">
            <th mat-header-cell *matHeaderCellDef>Registered</th>
            <td mat-cell *matCellDef="let p">{{ p.created_at | dateTime }}</td>
          </ng-container>

          <ng-container matColumnDef="last_used_at">
            <th mat-header-cell *matHeaderCellDef>Last Used</th>
            <td mat-cell *matCellDef="let p">
              {{ p.last_used_at ? (p.last_used_at | dateTime) : 'Never' }}
            </td>
          </ng-container>

          <ng-container matColumnDef="actions">
            <th mat-header-cell *matHeaderCellDef></th>
            <td mat-cell *matCellDef="let p">
              <button mat-stroked-button color="warn" (click)="deletePasskey(p)">Remove</button>
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
      .passkeys-header {
        display: flex;
        justify-content: flex-end;
        margin-bottom: 16px;
      }
      .table-container {
        overflow-x: auto;
      }
      table {
        width: 100%;
      }
      .passkey-icon {
        vertical-align: middle;
        margin-right: 8px;
        font-size: 20px;
        height: 20px;
        width: 20px;
      }
    `,
  ],
})
export class PasskeysComponent implements OnInit {
  private readonly passkeyService = inject(PasskeyService);
  private readonly snackBar = inject(MatSnackBar);

  passkeys = signal<PasskeyResponse[]>([]);
  loading = signal(true);
  passkeySupported = false;
  displayedColumns = ['name', 'created_at', 'last_used_at', 'actions'];

  ngOnInit(): void {
    this.passkeySupported = this.passkeyService.isSupported();
    this.loadPasskeys();
  }

  loadPasskeys(): void {
    this.loading.set(true);
    this.passkeyService.listPasskeys().subscribe({
      next: (res) => {
        this.passkeys.set(res.passkeys);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
      },
    });
  }

  addPasskey(): void {
    const name = prompt('Enter a name for this passkey (e.g., "MacBook Touch ID"):');
    if (!name) return;

    this.passkeyService.register(name).subscribe({
      next: () => {
        this.snackBar.open('Passkey registered', 'OK', { duration: 3000 });
        this.loadPasskeys();
      },
      error: (err) => {
        if (err?.name === 'NotAllowedError') return;
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  deletePasskey(passkey: PasskeyResponse): void {
    const password = prompt('Enter your password to confirm removal:');
    if (!password) return;

    this.passkeyService.deletePasskey(passkey.id, password).subscribe({
      next: () => {
        this.snackBar.open('Passkey removed', 'OK', { duration: 3000 });
        this.loadPasskeys();
      },
      error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
    });
  }
}
