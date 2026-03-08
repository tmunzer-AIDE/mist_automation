import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map, catchError, of } from 'rxjs';
import { TokenService } from '../services/token.service';
import { AuthService } from '../services/auth.service';

export const authGuard: CanActivateFn = () => {
  const tokenService = inject(TokenService);
  const authService = inject(AuthService);
  const router = inject(Router);

  if (tokenService.hasValidToken()) {
    return true;
  }

  // Check if system is initialized — redirect to onboard if not
  return authService.checkHealth().pipe(
    map((health) => {
      if (!health.is_initialized) {
        return router.createUrlTree(['/onboard']);
      }
      return router.createUrlTree(['/login']);
    }),
    catchError(() => of(router.createUrlTree(['/login'])))
  );
};
