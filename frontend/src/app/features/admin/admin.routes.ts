import { Routes } from '@angular/router';

const routes: Routes = [
  { path: '', redirectTo: 'users', pathMatch: 'full' },
  {
    path: 'users',
    loadComponent: () => import('./users/user-list.component').then((m) => m.UserListComponent),
  },
  {
    path: 'settings',
    loadComponent: () => import('./settings/settings.component').then((m) => m.SettingsComponent),
    children: [
      { path: '', redirectTo: 'mist', pathMatch: 'full' },
      {
        path: 'mist',
        loadComponent: () =>
          import('./settings/mist/settings-mist.component').then((m) => m.SettingsMistComponent),
      },
      {
        path: 'security',
        loadComponent: () =>
          import('./settings/security/settings-security.component').then(
            (m) => m.SettingsSecurityComponent,
          ),
      },
      {
        path: 'workflows',
        loadComponent: () =>
          import('./settings/workflows/settings-workflows.component').then(
            (m) => m.SettingsWorkflowsComponent,
          ),
      },
      {
        path: 'backups',
        loadComponent: () =>
          import('./settings/backups/settings-backups.component').then(
            (m) => m.SettingsBackupsComponent,
          ),
      },
      {
        path: 'webhooks',
        loadComponent: () =>
          import('./settings/webhooks/settings-webhooks.component').then(
            (m) => m.SettingsWebhooksComponent,
          ),
      },
      {
        path: 'integrations',
        loadComponent: () =>
          import('./settings/integrations/settings-integrations.component').then(
            (m) => m.SettingsIntegrationsComponent,
          ),
      },
      {
        path: 'llm',
        loadComponent: () =>
          import('./settings/llm/settings-llm.component').then((m) => m.SettingsLlmComponent),
      },
      {
        path: 'mcp',
        loadComponent: () =>
          import('./settings/mcp/settings-mcp.component').then((m) => m.SettingsMcpComponent),
      },
    ],
  },
  {
    path: 'logs',
    loadComponent: () => import('./logs/audit-logs.component').then((m) => m.AuditLogsComponent),
  },
  {
    path: 'system-logs',
    loadComponent: () =>
      import('./system-logs/system-logs.component').then((m) => m.SystemLogsComponent),
  },
  {
    path: 'stats',
    loadComponent: () => import('./stats/stats.component').then((m) => m.StatsComponent),
  },
  {
    path: 'llm-usage',
    loadComponent: () =>
      import('./llm-usage/llm-usage.component').then((m) => m.LlmUsageComponent),
  },
];

export default routes;
