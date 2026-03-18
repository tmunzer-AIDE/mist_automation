import { Component, Input, inject } from '@angular/core';
import { AsyncPipe } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatListModule } from '@angular/material/list';
import { MatIconModule } from '@angular/material/icon';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDividerModule } from '@angular/material/divider';
import { Store } from '@ngrx/store';
import { selectUserRoles } from '../../core/state/auth/auth.selectors';
import { NAV_ITEMS, NavItem } from './nav-items.config';
import { Observable, map } from 'rxjs';

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [
    AsyncPipe,
    RouterModule,
    MatListModule,
    MatIconModule,
    MatExpansionModule,
    MatTooltipModule,
    MatDividerModule,
  ],
  templateUrl: './sidebar.component.html',
  styleUrl: './sidebar.component.scss',
})
export class SidebarComponent {
  @Input() collapsed = false;

  private readonly store = inject(Store);
  private readonly roles$ = this.store.select(selectUserRoles);

  filteredNavItems$: Observable<NavItem[]> = this.roles$.pipe(
    map((roles) =>
      NAV_ITEMS.filter((item) => !item.roles || item.roles.some((r) => roles.includes(r))),
    ),
  );
}
