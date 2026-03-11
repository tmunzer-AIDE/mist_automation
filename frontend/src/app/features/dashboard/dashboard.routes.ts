import { Routes } from '@angular/router';

const routes: Routes = [
  {
    path: '',
    loadComponent: () => import('./dashboard.component').then((m) => m.DashboardComponent),
  },
];

export default routes;
