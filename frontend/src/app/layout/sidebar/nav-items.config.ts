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
  { label: 'Reports', icon: 'assessment', route: '/reports', roles: ['post_deployment', 'admin'] },
  { label: 'Impact Analysis', icon: 'vital_signs', route: '/impact-analysis', roles: ['impact_analysis', 'admin'], },
  { label: 'Digital Twin', icon: 'flip', route: '/digital-twin', roles: ['admin'] },
  {
    label: 'Power Scheduling',
    icon: 'power_settings_new',
    route: '/power-scheduling',
    roles: ['impact_analysis', 'admin'],
  },
];

export const MNTR_NAV_ITEMS: NavItem[] = [
  { label: 'Webhooks', icon: 'webhook', route: '/monitoring' },
  { label: 'Telemetry', icon: 'sensors', route: '/telemetry', roles: ['impact_analysis', 'admin'], },
]

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
    { label: 'LLM Usage', icon: 'smart_toy', route: '/admin/llm-usage' },
  ],
};
