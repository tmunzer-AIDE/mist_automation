export interface NavItem {
  label: string;
  icon: string;
  route: string;
  roles?: string[];
  children?: NavItem[];
}

export const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', icon: 'dashboard', route: '/dashboard' },
  { label: 'Workflows', icon: 'account_tree', route: '/workflows' },
  { label: 'Backups', icon: 'backup', route: '/backup' },
  { label: 'Webhooks', icon: 'webhook', route: '/monitoring' },
  {
    label: 'Impact Analysis',
    icon: 'analytics',
    route: '/impact-analysis',
    roles: ['impact_analysis', 'admin'],
  },
  {
    label: 'Telemetry',
    icon: 'sensors',
    route: '/telemetry',
    roles: ['impact_analysis', 'admin'],
  },
  {
    label: 'Reports',
    icon: 'assessment',
    route: '/reports',
    roles: ['post_deployment', 'admin'],
  },
];

export const ADMIN_NAV_ITEM: NavItem = {
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
};
