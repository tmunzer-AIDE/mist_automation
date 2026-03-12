import { Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatChipsModule } from '@angular/material/chips';
import { AuthService } from '../../../core/services/auth.service';
import { UserSession } from '../../../core/models/session.model';
import { extractErrorMessage } from '../../../shared/utils/error.utils';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';

@Component({
  selector: 'app-sessions',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatSnackBarModule,
    MatChipsModule,
    DateTimePipe,
    EmptyStateComponent,
  ],
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    }

    @if (!loading() && sessions().length === 0) {
      <app-empty-state icon="devices" title="No active sessions"></app-empty-state>
    } @else {
      <div class="table-container">
        <table mat-table [dataSource]="sessions()">
          <ng-container matColumnDef="ip">
            <th mat-header-cell *matHeaderCellDef>IP Address</th>
            <td mat-cell *matCellDef="let s">{{ s.device_info.ip_address }}</td>
          </ng-container>

          <ng-container matColumnDef="browser">
            <th mat-header-cell *matHeaderCellDef>Browser / OS</th>
            <td mat-cell *matCellDef="let s">
              {{ s.device_info.browser || 'Unknown' }} / {{ s.device_info.os || 'Unknown' }}
            </td>
          </ng-container>

          <ng-container matColumnDef="last_activity">
            <th mat-header-cell *matHeaderCellDef>Last Activity</th>
            <td mat-cell *matCellDef="let s">{{ s.last_activity | dateTime }}</td>
          </ng-container>

          <ng-container matColumnDef="created_at">
            <th mat-header-cell *matHeaderCellDef>Created</th>
            <td mat-cell *matCellDef="let s">{{ s.created_at | dateTime }}</td>
          </ng-container>

          <ng-container matColumnDef="actions">
            <th mat-header-cell *matHeaderCellDef></th>
            <td mat-cell *matCellDef="let s">
              @if (s.is_current) {
                <mat-chip highlighted>Current</mat-chip>
              } @else {
                <button mat-stroked-button color="warn" (click)="revoke(s)">Revoke</button>
              }
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
      .table-container {
        overflow-x: auto;
      }
      table {
        width: 100%;
      }
    `,
  ],
})
export class SessionsComponent implements OnInit {
  private readonly authService = inject(AuthService);
  private readonly snackBar = inject(MatSnackBar);

  sessions = signal<UserSession[]>([]);
  loading = signal(true);
  displayedColumns = ['ip', 'browser', 'last_activity', 'created_at', 'actions'];

  ngOnInit(): void {
    this.loadSessions();
  }

  loadSessions(): void {
    this.loading.set(true);
    this.authService.getSessions().subscribe({
      next: (res) => {
        this.sessions.set(res.sessions);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
      },
    });
  }

  revoke(session: UserSession): void {
    this.authService.revokeSession(session.id).subscribe({
      next: () => {
        this.snackBar.open('Session revoked', 'OK', { duration: 3000 });
        this.loadSessions();
      },
      error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
    });
  }
}
