import { Routes } from '@angular/router';

const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./report-list/report-list.component').then((m) => m.ReportListComponent),
  },
  {
    path: ':id',
    loadComponent: () =>
      import('./report-detail/report-detail.component').then((m) => m.ReportDetailComponent),
  },
];

export default routes;
