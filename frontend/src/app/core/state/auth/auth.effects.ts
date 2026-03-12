import { Injectable, inject } from '@angular/core';
import { Router } from '@angular/router';
import { Actions, createEffect, ofType } from '@ngrx/effects';
import { of } from 'rxjs';
import { catchError, exhaustMap, map, tap } from 'rxjs/operators';
import { AuthService } from '../../services/auth.service';
import { TokenService } from '../../services/token.service';
import { AuthActions } from './auth.actions';

@Injectable()
export class AuthEffects {
  private readonly actions$ = inject(Actions);
  private readonly authService = inject(AuthService);
  private readonly tokenService = inject(TokenService);
  private readonly router = inject(Router);

  login$ = createEffect(() =>
    this.actions$.pipe(
      ofType(AuthActions.login),
      exhaustMap(({ request }) =>
        this.authService.login(request).pipe(
          map((response) => {
            this.tokenService.setToken(response.access_token, response.expires_in);
            return AuthActions.loginSuccess({
              expiresIn: response.expires_in,
            });
          }),
          catchError((error) =>
            of(
              AuthActions.loginFailure({
                error: error.error?.detail || error.error?.message || 'Login failed',
              }),
            ),
          ),
        ),
      ),
    ),
  );

  loginSuccess$ = createEffect(() =>
    this.actions$.pipe(
      ofType(AuthActions.loginSuccess),
      map(() => AuthActions.loadUser()),
    ),
  );

  loadUser$ = createEffect(() =>
    this.actions$.pipe(
      ofType(AuthActions.loadUser),
      exhaustMap(() =>
        this.authService.me().pipe(
          map((user) => AuthActions.loadUserSuccess({ user })),
          catchError((error) =>
            of(
              AuthActions.loadUserFailure({
                error: error.error?.detail || error.error?.message || 'Failed to load user',
              }),
            ),
          ),
        ),
      ),
    ),
  );

  loadUserSuccess$ = createEffect(
    () =>
      this.actions$.pipe(
        ofType(AuthActions.loadUserSuccess),
        tap(() => {
          if (this.router.url === '/login' || this.router.url === '/onboard') {
            this.router.navigate(['/dashboard']);
          }
        }),
      ),
    { dispatch: false },
  );

  logout$ = createEffect(() =>
    this.actions$.pipe(
      ofType(AuthActions.logout),
      exhaustMap(() =>
        this.authService.logout().pipe(
          map(() => AuthActions.logoutComplete()),
          catchError(() => of(AuthActions.logoutComplete())),
        ),
      ),
    ),
  );

  logoutComplete$ = createEffect(
    () =>
      this.actions$.pipe(
        ofType(AuthActions.logoutComplete, AuthActions.sessionExpired),
        tap(() => {
          this.tokenService.clearToken();
          this.router.navigate(['/login']);
        }),
      ),
    { dispatch: false },
  );
}
