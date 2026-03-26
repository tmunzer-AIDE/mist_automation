export interface NavItem {
  label: string;
  icon: string;
  route: string;
  roles?: string[];
  children?: NavItem[];
}

export const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', icon: 'dashboard', route: '/dashboard' },
  { label: 'Webhook Monitor', icon: 'webhook', route: '/monitoring' },
  {
    label: 'Reports',
    icon: 'assessment',
    route: '/reports',
    roles: ['post_deployment', 'admin'],
  },
  {
    label: 'Impact Analysis',
    icon: 'analytics',
    route: '/impact-analysis',
    roles: ['impact_analysis', 'admin'],
  },
  {
    label: 'Backups',
    icon: 'backup',
    route: '/backup',
    children: [
      { label: 'Objects', icon: 'widgets', route: '/backup' },
      { label: 'Jobs', icon: 'work_history', route: '/backup/jobs' },
    ],
  },
  {
    label: 'Workflows',
    icon: 'account_tree',
    route: '/workflows',
    children: [
      { label: 'All Workflows', icon: 'list', route: '/workflows' },
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
      { label: 'System Logs', icon: 'terminal', route: '/admin/system-logs' },
      { label: 'System Stats', icon: 'monitoring', route: '/admin/stats' },
    ],
  },
];
