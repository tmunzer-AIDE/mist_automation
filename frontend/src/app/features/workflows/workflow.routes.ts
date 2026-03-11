import { Routes } from '@angular/router';

const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./list/workflow-list.component').then((m) => m.WorkflowListComponent),
  },
  {
    path: 'webhooks',
    redirectTo: '/monitoring',
    pathMatch: 'full',
  },
  {
    path: 'executions',
    loadComponent: () =>
      import('./executions/execution-list.component').then((m) => m.ExecutionListComponent),
  },
  {
    path: 'new',
    loadComponent: () =>
      import('./editor/workflow-editor.component').then((m) => m.WorkflowEditorComponent),
    data: { fullWidth: true },
  },
  {
    path: ':id',
    loadComponent: () =>
      import('./editor/workflow-editor.component').then((m) => m.WorkflowEditorComponent),
    data: { fullWidth: true },
  },
];

export default routes;
