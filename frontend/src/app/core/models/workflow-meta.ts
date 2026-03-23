import { ActionType } from './workflow.model';

export interface ActionMeta {
  label: string;
  icon: string;
  color: string;
}

export const ACTION_META: Record<ActionType, ActionMeta> = {
  mist_api_get: { label: 'Mist API GET', icon: 'cloud_download', color: '#1976d2' },
  mist_api_post: { label: 'Mist API POST', icon: 'cloud_upload', color: '#1976d2' },
  mist_api_put: { label: 'Mist API PUT', icon: 'edit', color: '#1976d2' },
  mist_api_delete: { label: 'Mist API DELETE', icon: 'delete', color: '#d32f2f' },
  webhook: { label: 'Webhook', icon: 'send', color: '#7b1fa2' },
  slack: { label: 'Slack', icon: 'chat', color: '#e91e63' },
  servicenow: { label: 'ServiceNow', icon: 'confirmation_number', color: '#388e3c' },
  pagerduty: { label: 'PagerDuty', icon: 'notifications_active', color: '#f57c00' },
  delay: { label: 'Delay', icon: 'schedule', color: '#616161' },
  condition: { label: 'Condition', icon: 'call_split', color: '#0097a7' },
  set_variable: { label: 'Set Variable', icon: 'data_object', color: '#795548' },
  for_each: { label: 'For Each', icon: 'loop', color: '#4527a0' },
  data_transform: { label: 'Data Transform', icon: 'transform', color: '#ff6f00' },
  format_report: { label: 'Format Report', icon: 'table_chart', color: '#00838f' },
  email: { label: 'Email', icon: 'email', color: '#5c6bc0' },
  invoke_subflow: { label: 'Sub-Flow', icon: 'account_tree', color: '#00695c' },
  subflow_output: { label: 'Return Output', icon: 'output', color: '#00695c' },
  device_utils: { label: 'Device Utility', icon: 'terminal', color: '#00897b' },
  ai_agent: { label: 'AI Agent', icon: 'smart_toy', color: '#7c4dff' },
  wait_for_callback: { label: 'Wait for Callback', icon: 'hourglass_top', color: '#f4511e' },
  trigger_backup: { label: 'Trigger Backup', icon: 'backup', color: '#00897b' },
  restore_backup: { label: 'Restore Backup', icon: 'restore', color: '#e65100' },
  syslog: { label: 'Syslog', icon: 'dns', color: '#607d8b' },
  compare_backups: { label: 'Compare Backups', icon: 'compare_arrows', color: '#5e35b1' },
};

export const DEFAULT_ACTION_META: ActionMeta = {
  label: 'Unknown',
  icon: 'play_arrow',
  color: '#455a64',
};
