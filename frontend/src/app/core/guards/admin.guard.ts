import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { Store } from '@ngrx/store';
import { catchError, map, of, switchMap, take, tap } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { TokenService } from '../services/token.service';
import { AuthActions } from '../state/auth/auth.actions';
import { selectCurrentUser } from '../state/auth/auth.selectors';

export const adminGuard: CanActivateFn = () => {
  const store = inject(Store);
  const router = inject(Router);
  const tokenService = inject(TokenService);
  const authService = inject(AuthService);

  if (!tokenService.hasValidToken()) {
    return router.createUrlTree(['/login']);
  }

  return store.select(selectCurrentUser).pipe(
    take(1),
    switchMap((user) => {
      if (user) {
        // User already in store — check admin role without API call
        return of(user.roles.includes('admin') ? true : router.createUrlTree(['/dashboard']));
      }
      // User not in store (hard refresh) — fetch directly
      return authService.me().pipe(
        tap((u) => store.dispatch(AuthActions.loadUserSuccess({ user: u }))),
        map((u) => (u.roles.includes('admin') ? true : router.createUrlTree(['/dashboard']))),
        catchError(() => of(router.createUrlTree(['/login']))),
      );
    }),
  );
};
