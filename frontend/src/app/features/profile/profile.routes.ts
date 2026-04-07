import { Routes } from '@angular/router';

const routes: Routes = [
  {
    path: '',
    loadComponent: () => import('./profile.component').then((m) => m.ProfileComponent),
    children: [
      { path: '', redirectTo: 'general', pathMatch: 'full' },
      {
        path: 'general',
        loadComponent: () =>
          import('./general/general-profile.component').then((m) => m.GeneralProfileComponent),
      },
      {
        path: 'settings',
        loadComponent: () =>
          import('./settings/password-change.component').then((m) => m.PasswordChangeComponent),
      },
      {
        path: 'sessions',
        loadComponent: () =>
          import('./sessions/sessions.component').then((m) => m.SessionsComponent),
      },
      {
        path: 'passkeys',
        loadComponent: () =>
          import('./passkeys/passkeys.component').then((m) => m.PasskeysComponent),
      },
      {
        path: 'memory',
        loadComponent: () =>
          import('./memory/memory.component').then((m) => m.MemoryComponent),
      },
    ],
  },
];

export default routes;
