export interface SystemSettings {
  mist_api_token_set: boolean;
  mist_org_id: string | null;
  mist_cloud_region: string;
  webhook_secret: string | null;
  // Smee.io
  smee_enabled: boolean;
  smee_channel_url: string | null;
  max_concurrent_workflows: number;
  workflow_default_timeout: number;
  // Password Policy
  min_password_length: number;
  require_uppercase: boolean;
  require_lowercase: boolean;
  require_digits: boolean;
  require_special_chars: boolean;
  // Session Management
  session_timeout_hours: number;
  max_concurrent_sessions: number;
  // Backup Configuration
  backup_enabled: boolean;
  backup_full_schedule_cron: string;
  backup_retention_days: number;
  backup_git_enabled: boolean;
  backup_git_repo_url: string | null;
  backup_git_branch: string;
  backup_git_author_name: string;
  backup_git_author_email: string;
  // External Integrations
  slack_webhook_url: string | null;
  servicenow_instance_url: string | null;
  servicenow_username: string | null;
  servicenow_password_set: boolean;
  pagerduty_api_key_set: boolean;
  updated_at: string;
}

export interface SystemSettingsUpdate {
  mist_api_token?: string;
  mist_org_id?: string;
  mist_cloud_region?: string;
  webhook_secret?: string;
  // Smee.io
  smee_enabled?: boolean;
  smee_channel_url?: string;
  max_concurrent_workflows?: number;
  workflow_default_timeout?: number;
  // Password Policy
  min_password_length?: number;
  require_uppercase?: boolean;
  require_lowercase?: boolean;
  require_digits?: boolean;
  require_special_chars?: boolean;
  // Session Management
  session_timeout_hours?: number;
  max_concurrent_sessions?: number;
  // Backup Configuration
  backup_enabled?: boolean;
  backup_full_schedule_cron?: string;
  backup_retention_days?: number;
  backup_git_enabled?: boolean;
  backup_git_repo_url?: string;
  backup_git_branch?: string;
  backup_git_author_name?: string;
  backup_git_author_email?: string;
  // External Integrations
  slack_webhook_url?: string;
  servicenow_instance_url?: string;
  servicenow_username?: string;
  servicenow_password?: string;
  pagerduty_api_key?: string;
}

export interface AuditLogEntry {
  id: string;
  event_type: string;
  user_id: string | null;
  user_email: string | null;
  source_ip: string | null;
  timestamp: string;
  details: Record<string, unknown>;
}

export interface AuditLogListResponse {
  logs: AuditLogEntry[];
  total: number;
}

export interface SystemStats {
  workflows: {
    total: number;
    enabled: number;
    draft: number;
  };
  executions: {
    total: number;
    pending: number;
    running: number;
    succeeded: number;
    failed: number;
  };
  backups: {
    total: number;
    completed: number;
    pending: number;
    failed: number;
  };
  webhooks: {
    total: number;
    processed: number;
    pending: number;
  };
  users: {
    total: number;
    active: number;
    admins: number;
  };
}

export interface WorkerStatus {
  scheduler: {
    status: string;
    scheduled_workflows: number;
    jobs: unknown[];
  };
}

export interface MistConnectionResult {
  status: string;
  error: string | null;
}

export interface SmeeStatus {
  running: boolean;
  channel_url: string | null;
}
