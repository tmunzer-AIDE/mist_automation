import { Component, inject, OnInit } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { Store } from '@ngrx/store';
import { MatIconRegistry } from '@angular/material/icon';
import { TokenService } from './core/services/token.service';
import { AuthActions } from './core/state/auth/auth.actions';
import { ThemeService } from './core/services/theme.service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet],
  template: '<router-outlet></router-outlet>',
  styleUrl: './app.scss',
})
export class App implements OnInit {
  private readonly store = inject(Store);
  private readonly tokenService = inject(TokenService);
  private readonly iconRegistry = inject(MatIconRegistry);
  private readonly themeService = inject(ThemeService);

  ngOnInit(): void {
    this.iconRegistry.setDefaultFontSetClass('material-symbols-rounded');

    if (this.tokenService.hasValidToken()) {
      this.store.dispatch(AuthActions.loadUser());
    }
  }
}
