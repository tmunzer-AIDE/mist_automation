import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { Store } from '@ngrx/store';
import { combineLatest, filter, map, take } from 'rxjs';
import { selectIsAdmin, selectUserLoaded } from '../state/auth/auth.selectors';

export const adminGuard: CanActivateFn = () => {
  const store = inject(Store);
  const router = inject(Router);

  return combineLatest([
    store.select(selectUserLoaded),
    store.select(selectIsAdmin),
  ]).pipe(
    filter(([loaded]) => loaded),
    take(1),
    map(([, isAdmin]) => {
      if (isAdmin) return true;
      return router.createUrlTree(['/dashboard']);
    })
  );
};
