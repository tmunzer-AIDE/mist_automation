import { Routes } from '@angular/router';

const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./list/power-scheduling-list.component').then(
        (m) => m.PowerSchedulingListComponent,
      ),
  },
  {
    path: ':siteId',
    loadComponent: () =>
      import('./detail/power-scheduling-detail.component').then(
        (m) => m.PowerSchedulingDetailComponent,
      ),
  },
];

export default routes;
