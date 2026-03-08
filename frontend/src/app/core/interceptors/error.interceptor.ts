import { HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';
import { TokenService } from '../services/token.service';

export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const router = inject(Router);
  const tokenService = inject(TokenService);

  return next(req).pipe(
    catchError((error: HttpErrorResponse) => {
      if (error.status === 401 && !req.url.includes('/auth/login')) {
        tokenService.clearToken();
        router.navigate(['/login']);
      }

      const message =
        error.error?.detail ||
        error.error?.message ||
        error.statusText ||
        'An unexpected error occurred';

      return throwError(() => ({ status: error.status, message }));
    })
  );
};
