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
  slack_signing_secret_set: boolean;
  servicenow_instance_url: string | null;
  servicenow_username: string | null;
  servicenow_password_set: boolean;
  pagerduty_api_key_set: boolean;
  // Email / SMTP
  smtp_host: string | null;
  smtp_port: number;
  smtp_username: string | null;
  smtp_password_set: boolean;
  smtp_from_email: string;
  smtp_use_tls: boolean;
  // Webhook
  webhook_ip_whitelist: string[];
  // Execution retention
  execution_retention_days: number;
  // System
  maintenance_mode: boolean;
  // LLM (global toggle — configs managed via /llm/configs)
  llm_enabled: boolean;
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
  slack_signing_secret?: string;
  servicenow_instance_url?: string;
  servicenow_username?: string;
  servicenow_password?: string;
  pagerduty_api_key?: string;
  // Email / SMTP
  smtp_host?: string;
  smtp_port?: number;
  smtp_username?: string;
  smtp_password?: string;
  smtp_from_email?: string;
  smtp_use_tls?: boolean;
  // Webhook
  webhook_ip_whitelist?: string[];
  // Execution retention
  execution_retention_days?: number;
  // System
  maintenance_mode?: boolean;
  // LLM
  llm_enabled?: boolean;
}

export interface IntegrationTestResult {
  status: 'connected' | 'failed';
  error: string | null;
}

export interface AuditLogEntry {
  id: string;
  event_type: string;
  event_category: string | null;
  description: string | null;
  user_id: string | null;
  user_email: string | null;
  source_ip: string | null;
  target_type: string | null;
  target_id: string | null;
  target_name: string | null;
  success: boolean;
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

export interface ServiceHealth {
  status: string;
  [key: string]: unknown;
}

export interface MongoHealth extends ServiceHealth {
  collections: number;
  total_documents: number;
  storage_size_mb: number;
  uptime_seconds: number;
}

export interface RedisHealth extends ServiceHealth {
  used_memory_mb: number;
  connected_clients: number;
  uptime_seconds: number;
}

export interface InfluxHealth extends ServiceHealth {
  buffer_size: number;
  buffer_capacity: number;
  buffer_pct: number;
  points_written: number;
  points_dropped: number;
  flush_count: number;
  last_flush_at: number;
  last_error: string | null;
}

export interface MistWsHealth extends ServiceHealth {
  connections: number;
  connections_ready: number;
  sites_subscribed: number;
  messages_received: number;
  messages_bridge_dropped: number;
  last_message_at: number;
  started_at: number;
}

export interface IngestionHealth extends ServiceHealth {
  queue_size: number;
  queue_capacity: number;
  queue_pct: number;
  messages_processed: number;
  points_extracted: number;
  points_written: number;
  points_filtered: number;
  last_message_at: number;
}

export interface AppWsHealth {
  connected_clients: number;
  active_channels: number;
  total_subscriptions: number;
}

export interface SchedulerHealth extends ServiceHealth {
  scheduled_jobs: number;
}

export interface SystemHealth {
  overall_status: 'operational' | 'degraded' | 'down';
  checked_at: number;
  services: {
    mongodb: MongoHealth;
    redis: RedisHealth;
    influxdb: InfluxHealth;
    mist_websocket: MistWsHealth;
    ingestion: IngestionHealth;
    app_websocket: AppWsHealth;
    scheduler: SchedulerHealth;
  };
}
