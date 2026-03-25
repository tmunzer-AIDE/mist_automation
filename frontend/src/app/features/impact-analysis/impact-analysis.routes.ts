import { Routes } from '@angular/router';

const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./session-list/session-list.component').then((m) => m.SessionListComponent),
  },
  {
    path: ':id',
    loadComponent: () =>
      import('./session-detail/session-detail.component').then(
        (m) => m.SessionDetailComponent,
      ),
  },
];

export default routes;
