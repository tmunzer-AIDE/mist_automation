export interface DashboardHighlight {
  level: 'error' | 'warning' | 'info';
  icon: string;
  message: string;
  route: string;
  count: number;
}

export interface DashboardStats {
  display_name?: string;
  stats_window_days?: number;
  highlights?: DashboardHighlight[];
  users?: { total: number; active: number; admins: number };
  workflows?: { total: number; enabled: number; draft: number };
  executions?: { total: number; succeeded: number; failed: number; running: number };
  webhooks?: { total: number; processed: number; pending: number };
  backups?: { total: number; completed: number; pending: number; failed: number };
  reports?: { total: number; completed: number; pending: number; failed: number };
  activity?: DashboardActivity;
  recent?: RecentActivityItem[];
}

export interface DashboardActivity {
  labels: string[];
  executions?: { succeeded: number[]; failed: number[] };
  backups?: { completed: number[]; failed: number[] };
  webhooks?: { received: number[] };
}

export interface RecentActivityItem {
  type: 'execution' | 'backup' | 'report';
  id: string;
  title: string;
  status: string;
  timestamp: string;
  detail: string | null;
}
