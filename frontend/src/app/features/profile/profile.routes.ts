import { Routes } from '@angular/router';

const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./profile.component').then((m) => m.ProfileComponent),
    children: [
      { path: '', redirectTo: 'settings', pathMatch: 'full' },
      {
        path: 'settings',
        loadComponent: () =>
          import('./settings/password-change.component').then(
            (m) => m.PasswordChangeComponent
          ),
      },
      {
        path: 'sessions',
        loadComponent: () =>
          import('./sessions/sessions.component').then(
            (m) => m.SessionsComponent
          ),
      },
    ],
  },
];

export default routes;
