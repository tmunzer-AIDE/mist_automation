import { Component, inject, OnInit } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { Store } from '@ngrx/store';
import { TokenService } from './core/services/token.service';
import { AuthActions } from './core/state/auth/auth.actions';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet],
  template: '<router-outlet></router-outlet>',
  styleUrl: './app.scss',
})
export class App implements OnInit {
  private readonly store = inject(Store);
  private readonly tokenService = inject(TokenService);

  ngOnInit(): void {
    if (this.tokenService.hasValidToken()) {
      this.store.dispatch(AuthActions.loadUser());
    }
  }
}
