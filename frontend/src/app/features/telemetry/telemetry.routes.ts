import { Routes } from '@angular/router';

const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./scope/telemetry-scope.component').then((m) => m.TelemetryScopeComponent),
  },
  {
    path: 'site/:id',
    loadComponent: () =>
      import('./site/telemetry-site.component').then((m) => m.TelemetrySiteComponent),
  },
  {
    path: 'site/:id/clients',
    loadComponent: () =>
      import('./clients/telemetry-clients.component').then(
        (m) => m.TelemetryClientsComponent
      ),
  },
  {
    path: 'site/:id/client/:mac',
    loadComponent: () =>
      import('./client-detail/telemetry-client-detail.component').then(
        (m) => m.TelemetryClientDetailComponent,
      ),
  },
  {
    path: 'device/:mac',
    loadComponent: () =>
      import('./device/telemetry-device.component').then((m) => m.TelemetryDeviceComponent),
  },
];

export default routes;
