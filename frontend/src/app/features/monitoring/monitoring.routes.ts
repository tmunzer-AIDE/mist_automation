import { Routes } from '@angular/router';

const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./webhook-monitor/webhook-monitor.component').then(
        (m) => m.WebhookMonitorComponent,
      ),
  },
];

export default routes;
