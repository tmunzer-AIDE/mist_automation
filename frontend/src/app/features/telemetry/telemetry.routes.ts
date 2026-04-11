import { Routes } from '@angular/router';

const FW = { data: { fullWidth: true } };

const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./telemetry-shell.component').then((m) => m.TelemetryShellComponent),
    children: [
      {
        path: '',
        ...FW,
        loadComponent: () =>
          import('./scope/telemetry-scope.component').then((m) => m.TelemetryScopeComponent),
      },
      {
        path: 'site/:id',
        ...FW,
        loadComponent: () =>
          import('./site/telemetry-site.component').then((m) => m.TelemetrySiteComponent),
      },
      {
        path: 'site/:id/clients',
        ...FW,
        loadComponent: () =>
          import('./clients/telemetry-clients.component').then(
            (m) => m.TelemetryClientsComponent,
          ),
      },
      {
        path: 'site/:id/client/:mac',
        ...FW,
        loadComponent: () =>
          import('./client-detail/telemetry-client-detail.component').then(
            (m) => m.TelemetryClientDetailComponent,
          ),
      },
      {
        path: 'site/:id/devices',
        ...FW,
        loadComponent: () =>
          import('./site-devices/telemetry-site-devices.component').then(
            (m) => m.TelemetrySiteDevicesComponent,
          ),
      },
      {
        path: 'device/:mac',
        ...FW,
        loadComponent: () =>
          import('./device/telemetry-device.component').then((m) => m.TelemetryDeviceComponent),
      },
    ],
  },
];

export default routes;
