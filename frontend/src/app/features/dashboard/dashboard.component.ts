import { Component, ChangeDetectorRef, DestroyRef, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { Store } from '@ngrx/store';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { filter, take, switchMap, of, catchError, forkJoin } from 'rxjs';
import { selectCurrentUser, selectIsAdmin } from '../../core/state/auth/auth.selectors';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { SystemStats } from '../../core/models/admin.model';
import { HealthResponse } from '../../core/models/session.model';
import { UserResponse } from '../../core/models/user.model';
import { PageHeaderComponent } from '../../shared/components/page-header/page-header.component';
import { StatusBadgeComponent } from '../../shared/components/status-badge/status-badge.component';
import { LoadingSpinnerComponent } from '../../shared/components/loading-spinner/loading-spinner.component';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatCardModule,
    MatIconModule,
    MatButtonModule,
    PageHeaderComponent,
    StatusBadgeComponent,
    LoadingSpinnerComponent,
  ],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent implements OnInit {
  private readonly store = inject(Store);
  private readonly api = inject(ApiService);
  private readonly authService = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly cdr = inject(ChangeDetectorRef);

  user$ = this.store.select(selectCurrentUser);
  isAdmin$ = this.store.select(selectIsAdmin);

  stats: SystemStats | null = null;
  health: HealthResponse | null = null;
  loading = true;

  ngOnInit(): void {
    this.authService.checkHealth().subscribe({
      next: (h) => {
        this.health = h;
        this.cdr.detectChanges();
      },
    });

    // Wait for user to be loaded, then decide whether to fetch stats
    this.store
      .select(selectCurrentUser)
      .pipe(
        filter((user): user is UserResponse => user !== null),
        take(1),
        switchMap((user) => {
          if (user.roles.includes('admin')) {
            return this.api.get<SystemStats>('/admin/stats').pipe(
              catchError(() => of(null))
            );
          }
          return of(null);
        }),
        takeUntilDestroyed(this.destroyRef)
      )
      .subscribe((stats) => {
        this.stats = stats;
        this.loading = false;
        this.cdr.detectChanges();
      });
  }
}
