import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Store } from '@ngrx/store';
import { ApiService } from '../../../core/services/api.service';
import { UserResponse, UserListResponse } from '../../../core/models/user.model';
import { selectCurrentUser } from '../../../core/state/auth/auth.selectors';
import { TopbarService } from '../../../core/services/topbar.service';
import { PageHeaderComponent } from '../../../shared/components/page-header/page-header.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { ConfirmDialogComponent } from '../../../shared/components/confirm-dialog/confirm-dialog.component';
import { UserDialogComponent } from './user-dialog.component';

@Component({
  selector: 'app-user-list',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatPaginatorModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatSlideToggleModule,
    MatDialogModule,
    MatProgressBarModule,
    MatSnackBarModule,
    MatTooltipModule,
    PageHeaderComponent,
    EmptyStateComponent,
    DateTimePipe,
  ],
  templateUrl: './user-list.component.html',
  styleUrl: './user-list.component.scss',
})
export class UserListComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly store = inject(Store);
  private readonly destroyRef = inject(DestroyRef);
  private readonly topbarService = inject(TopbarService);

  currentUserId: string | null = null;
  users = signal<UserResponse[]>([]);
  total = 0;
  pageSize = 25;
  pageIndex = 0;
  loading = signal(true);
  displayedColumns = ['email', 'roles', 'is_active', 'created_at', 'last_login', 'actions'];

  ngOnInit(): void {
    this.topbarService.setTitle('Users');
    this.store
      .select(selectCurrentUser)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((user) => {
        this.currentUserId = user?.id ?? null;
      });
    this.loadUsers();
  }

  isSelf(user: UserResponse): boolean {
    return user.id === this.currentUserId;
  }

  loadUsers(): void {
    this.loading.set(true);
    this.api
      .get<UserListResponse>('/users', {
        skip: this.pageIndex * this.pageSize,
        limit: this.pageSize,
      })
      .subscribe({
        next: (res) => {
          this.users.set(res.users);
          this.total = res.total;
          this.loading.set(false);
        },
        error: () => {
          this.loading.set(false);
        },
      });
  }

  onPage(event: PageEvent): void {
    this.pageIndex = event.pageIndex;
    this.pageSize = event.pageSize;
    this.loadUsers();
  }

  openCreateDialog(): void {
    const ref = this.dialog.open(UserDialogComponent, {
      width: '500px',
      data: { mode: 'create' },
    });
    ref.afterClosed().subscribe((result) => {
      if (result) this.loadUsers();
    });
  }

  openEditDialog(user: UserResponse): void {
    const ref = this.dialog.open(UserDialogComponent, {
      width: '500px',
      data: { mode: 'edit', user },
    });
    ref.afterClosed().subscribe((result) => {
      if (result) this.loadUsers();
    });
  }

  deleteUser(user: UserResponse): void {
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: 'Delete User',
        message: `Are you sure you want to delete ${user.email}?`,
        confirmText: 'Delete',
        warn: true,
      },
    });
    ref.afterClosed().subscribe((confirmed) => {
      if (confirmed) {
        this.api.delete(`/users/${user.id}`).subscribe({
          next: () => {
            this.snackBar.open('User deleted', 'OK', { duration: 3000 });
            this.loadUsers();
          },
          error: (err) => this.snackBar.open(err.message, 'OK', { duration: 5000 }),
        });
      }
    });
  }

  toggleActive(user: UserResponse): void {
    this.api.put(`/users/${user.id}`, { is_active: !user.is_active }).subscribe({
      next: () => this.loadUsers(),
      error: (err) => this.snackBar.open(err.message, 'OK', { duration: 5000 }),
    });
  }
}
