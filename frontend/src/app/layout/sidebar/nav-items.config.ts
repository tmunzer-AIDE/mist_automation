export interface NavItem {
  label: string;
  icon: string;
  route: string;
  roles?: string[];
  children?: NavItem[];
}

export const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', icon: 'dashboard', route: '/dashboard' },
  { label: 'Backups', icon: 'backup', route: '/backup' },
  {
    label: 'Workflows',
    icon: 'account_tree',
    route: '/workflows',
    children: [
      { label: 'All Workflows', icon: 'list', route: '/workflows' },
      { label: 'Webhook Monitor', icon: 'webhook', route: '/workflows/webhooks' },
      { label: 'Executions', icon: 'history', route: '/workflows/executions' },
    ],
  },
  {
    label: 'Administration',
    icon: 'admin_panel_settings',
    route: '/admin',
    roles: ['admin'],
    children: [
      { label: 'Users', icon: 'people', route: '/admin/users' },
      { label: 'Settings', icon: 'settings', route: '/admin/settings' },
      { label: 'Audit Logs', icon: 'receipt_long', route: '/admin/logs' },
      { label: 'System Stats', icon: 'monitoring', route: '/admin/stats' },
    ],
  },
];
