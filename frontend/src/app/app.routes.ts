import { Routes } from '@angular/router';
import { LayoutComponent } from './layout/layout.component';
import { authGuard } from './core/guards/auth.guard';
import { adminGuard } from './core/guards/admin.guard';
import { onboardGuard } from './core/guards/onboarding.guard';

export const routes: Routes = [
  {
    path: 'login',
    loadChildren: () => import('./features/auth/auth.routes'),
  },
  {
    path: 'onboard',
    loadComponent: () =>
      import('./features/auth/onboard/onboard.component').then((m) => m.OnboardComponent),
    canActivate: [onboardGuard],
  },
  {
    path: '',
    component: LayoutComponent,
    canActivate: [authGuard],
    children: [
      { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
      {
        path: 'dashboard',
        loadChildren: () => import('./features/dashboard/dashboard.routes'),
      },
      {
        path: 'profile',
        loadChildren: () => import('./features/profile/profile.routes'),
      },
      {
        path: 'admin',
        loadChildren: () => import('./features/admin/admin.routes'),
        canActivate: [adminGuard],
      },
      {
        path: 'backup',
        loadChildren: () => import('./features/backup/backup.routes'),
      },
      {
        path: 'reports',
        loadChildren: () => import('./features/reports/reports.routes'),
      },
      {
        path: 'monitoring',
        loadChildren: () => import('./features/monitoring/monitoring.routes'),
      },
      {
        path: 'workflows',
        loadChildren: () => import('./features/workflows/workflow.routes'),
      },
      {
        path: 'ai-chats',
        loadChildren: () => import('./features/ai-chats/ai-chats.routes'),
      },
      {
        path: 'impact-analysis',
        loadChildren: () => import('./features/impact-analysis/impact-analysis.routes'),
      },
      {
        path: 'telemetry',
        loadChildren: () => import('./features/telemetry/telemetry.routes'),
      },
    ],
  },
  { path: '**', redirectTo: 'dashboard' },
];
