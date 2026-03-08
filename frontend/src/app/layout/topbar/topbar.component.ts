import { Component, Output, EventEmitter, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { Store } from '@ngrx/store';
import { selectCurrentUser } from '../../core/state/auth/auth.selectors';
import { AuthActions } from '../../core/state/auth/auth.actions';

@Component({
  selector: 'app-topbar',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatToolbarModule,
    MatButtonModule,
    MatIconModule,
    MatMenuModule,
  ],
  templateUrl: './topbar.component.html',
  styleUrl: './topbar.component.scss',
})
export class TopbarComponent {
  @Output() toggleSidebar = new EventEmitter<void>();

  private readonly store = inject(Store);
  user$ = this.store.select(selectCurrentUser);

  userInitial(email: string): string {
    return (email || '?')[0].toUpperCase();
  }

  logout(): void {
    this.store.dispatch(AuthActions.logout());
  }
}
