import { Routes } from '@angular/router';

const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./list/backup-object-list.component').then((m) => m.BackupObjectListComponent),
  },
  {
    path: 'jobs',
    loadComponent: () =>
      import('./list/backup-job-list.component').then((m) => m.BackupJobListComponent),
  },
  {
    path: 'timeline',
    loadComponent: () =>
      import('./timeline/backup-timeline.component').then((m) => m.BackupTimelineComponent),
  },
  {
    path: 'compare',
    loadComponent: () =>
      import('./compare/backup-compare.component').then((m) => m.BackupCompareComponent),
  },
  {
    path: 'object/:objectId',
    loadComponent: () =>
      import('./detail/backup-object-detail.component').then((m) => m.BackupObjectDetailComponent),
  },
  {
    path: ':id',
    loadComponent: () =>
      import('./detail/backup-detail.component').then((m) => m.BackupDetailComponent),
  },
];

export default routes;
