import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { Store } from '@ngrx/store';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { filter, take, switchMap, of, catchError } from 'rxjs';
import { selectCurrentUser, selectIsAdmin } from '../../core/state/auth/auth.selectors';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { TopbarService } from '../../core/services/topbar.service';
import { SystemStats } from '../../core/models/admin.model';
import { HealthResponse } from '../../core/models/session.model';
import { UserResponse } from '../../core/models/user.model';
import { StatusBadgeComponent } from '../../shared/components/status-badge/status-badge.component';
@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatIconModule,
    MatButtonModule,
    MatProgressBarModule,
    StatusBadgeComponent,
  ],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent implements OnInit {
  private readonly store = inject(Store);
  private readonly api = inject(ApiService);
  private readonly authService = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly router = inject(Router);
  private readonly topbarService = inject(TopbarService);

  user$ = this.store.select(selectCurrentUser);
  isAdmin$ = this.store.select(selectIsAdmin);

  stats = signal<SystemStats | null>(null);
  health = signal<HealthResponse | null>(null);
  loading = signal(true);

  ngOnInit(): void {
    this.topbarService.setTitle('Dashboard');
    this.authService.checkHealth().subscribe({
      next: (h) => {
        this.health.set(h);
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
            return this.api.get<SystemStats>('/admin/stats').pipe(catchError(() => of(null)));
          }
          return of(null);
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((stats) => {
        this.stats.set(stats);
        this.loading.set(false);
      });
  }

  navigateTo(route: string): void {
    this.router.navigate([route]);
  }
}
