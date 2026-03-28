import { Routes } from '@angular/router';

export default [
  {
    path: '',
    loadComponent: () => import('./ai-chats.component').then((m) => m.AiChatsComponent),
    data: { fullWidth: true },
  },
] satisfies Routes;
