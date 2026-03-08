import { Routes } from '@angular/router';

const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./list/workflow-list.component').then(
        (m) => m.WorkflowListComponent
      ),
  },
  {
    path: 'new',
    loadComponent: () =>
      import('./editor/workflow-editor.component').then(
        (m) => m.WorkflowEditorComponent
      ),
  },
  {
    path: ':id',
    loadComponent: () =>
      import('./editor/workflow-editor.component').then(
        (m) => m.WorkflowEditorComponent
      ),
  },
];

export default routes;
