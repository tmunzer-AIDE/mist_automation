import { Component, DestroyRef, Input, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AsyncPipe } from '@angular/common';
import { NavigationEnd, Router, RouterModule } from '@angular/router';
import { MatBadgeModule } from '@angular/material/badge';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { MatMenuModule } from '@angular/material/menu';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Store } from '@ngrx/store';
import { Observable, filter, map } from 'rxjs';
import { selectUserRoles } from '../../core/state/auth/auth.selectors';
import { GlobalChatService } from '../../core/services/global-chat.service';
import { WebSocketService } from '../../core/services/websocket.service';
import { NAV_ITEMS, MNTR_NAV_ITEMS, ADMIN_NAV_ITEM, NavItem } from './nav-items.config';

interface ImpactAlertData {
  session_id: string;
  device_name: string;
  device_type: string;
  site_name: string;
  severity: string;
  summary: string;
  has_revert: boolean;
}

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [
    AsyncPipe,
    RouterModule,
    MatBadgeModule,
    MatIconModule,
    MatListModule,
    MatMenuModule,
    MatTooltipModule,
  ],
  templateUrl: './sidebar.component.html',
  styleUrl: './sidebar.component.scss',
})
export class SidebarComponent {
  @Input() collapsed = false;

  private readonly store = inject(Store);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly snackBar = inject(MatSnackBar);
  private readonly wsService = inject(WebSocketService);
  private readonly globalChatService = inject(GlobalChatService);
  private readonly roles$ = this.store.select(selectUserRoles);

  readonly impactAlertCount = signal(0);
  readonly currentUrl = signal('');

  filteredNavItems$: Observable<NavItem[]> = this.roles$.pipe(
    map((roles) =>
      NAV_ITEMS.filter((item) => !item.roles || item.roles.some((r) => roles.includes(r))),
    ),
  );
  filteredMntrNavItems$: Observable<NavItem[]> = this.roles$.pipe(
    map((roles) =>
      MNTR_NAV_ITEMS.filter((item) => !item.roles || item.roles.some((r) => roles.includes(r))),
    ),
  );

  adminItem$: Observable<NavItem | null> = this.roles$.pipe(
    map((roles) =>
      !ADMIN_NAV_ITEM.roles || ADMIN_NAV_ITEM.roles.some((r) => roles.includes(r))
        ? ADMIN_NAV_ITEM
        : null,
    ),
  );

  constructor() {
    // Track current URL for admin active state + reset impact badge
    this.router.events
      .pipe(
        filter((e): e is NavigationEnd => e instanceof NavigationEnd),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((e) => {
        this.currentUrl.set(e.url);
        if (e.url.startsWith('/impact-analysis')) {
          this.impactAlertCount.set(0);
        }
      });

    // Subscribe to impact alert WS broadcasts
    this.wsService
      .subscribe<{ type: string; data: ImpactAlertData }>('impact:alerts')
      .pipe(
        filter((msg) => msg.type === 'impact_alert'),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((msg) => {
        this.impactAlertCount.update((c) => c + 1);
        this.showImpactAlert(msg.data);
      });
  }

  private showImpactAlert(data: ImpactAlertData): void {
    const severity = data.severity === 'critical' ? 'CRITICAL' : 'Warning';
    const ref = this.snackBar.open(
      `${severity}: Impact detected on ${data.device_name} (${data.site_name})`,
      'Analyze',
      { duration: 15000, panelClass: 'impact-alert-snackbar' },
    );
    ref.onAction().subscribe(() => {
      this.globalChatService.open(
        `A configuration change on ${data.device_name} (${data.device_type}) at site ${data.site_name} ` +
          `has been flagged as ${data.severity}. Session ID: ${data.session_id}. ` +
          `Please analyze the impact and provide recommendations.`,
      );
    });
  }
}
