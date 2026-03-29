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
    path: 'device/:mac',
    loadComponent: () =>
      import('./device/telemetry-device.component').then((m) => m.TelemetryDeviceComponent),
  },
];

export default routes;
