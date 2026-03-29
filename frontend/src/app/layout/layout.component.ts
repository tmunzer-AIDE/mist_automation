import { Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterOutlet, NavigationEnd, ActivatedRoute } from '@angular/router';
import { BreakpointObserver, Breakpoints } from '@angular/cdk/layout';
import { combineLatest } from 'rxjs';
import { MatSidenavModule } from '@angular/material/sidenav';
import { SidebarComponent } from './sidebar/sidebar.component';
import { TopbarComponent } from './topbar/topbar.component';
import { GlobalChatComponent } from '../shared/components/global-chat/global-chat.component';
import { ApiService } from '../core/services/api.service';
import { LlmService } from '../core/services/llm.service';
import { filter, map } from 'rxjs';

@Component({
  selector: 'app-layout',
  standalone: true,
  imports: [RouterOutlet, MatSidenavModule, SidebarComponent, TopbarComponent, GlobalChatComponent],
  templateUrl: './layout.component.html',
  styleUrl: './layout.component.scss',
})
export class LayoutComponent {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly activatedRoute = inject(ActivatedRoute);
  private readonly breakpointObserver = inject(BreakpointObserver);
  private readonly llmService = inject(LlmService);
  private readonly destroyRef = inject(DestroyRef);

  isMobile = signal(false);
  sidebarOpen = signal(true);
  sidebarCollapsed = signal(false);
  isFullWidth = signal(false);
  llmAvailable = signal(false);
  maintenanceMode = signal(false);

  constructor() {
    combineLatest([
      this.api.getRaw<{ maintenance_mode: boolean }>('/health'),
      this.llmService.getStatus(),
    ])
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ([healthData, llmStatus]) => {
          this.maintenanceMode.set(healthData.maintenance_mode ?? false);
          this.llmAvailable.set(llmStatus.enabled);
        },
        error: (err) => {
          console.error('Failed to fetch health/llm status:', err);
          this.maintenanceMode.set(false);
          this.llmAvailable.set(false);
        },
      });

    this.breakpointObserver
      .observe([Breakpoints.Handset])
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((result) => {
        this.isMobile.set(result.matches);
        this.sidebarOpen.set(!result.matches);
      });

    this.router.events
      .pipe(
        filter((e): e is NavigationEnd => e instanceof NavigationEnd),
        map(() => {
          let route = this.activatedRoute;
          while (route.firstChild) route = route.firstChild;
          return route.snapshot.data;
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((data) => {
        this.isFullWidth.set(!!data['fullWidth']);
      });
  }

  toggleSidebar(): void {
    if (this.isMobile()) {
      this.sidebarOpen.update((v) => !v);
    } else {
      this.sidebarCollapsed.update((v) => !v);
    }
  }
}
