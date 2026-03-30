export interface ConfigChangeEvent {
  event_type: string;
  device_mac: string;
  device_name: string;
  timestamp: string;
  webhook_event_id: string | null;
  payload_summary: Record<string, unknown>;
  config_diff: string | null;
  device_model: string;
  firmware_version: string;
  commit_user: string;
  commit_method: string;
}

export interface DeviceIncident {
  event_type: string;
  device_mac: string;
  device_name: string;
  timestamp: string;
  webhook_event_id: string | null;
  severity: string;
  is_revert: boolean;
  resolved: boolean;
  resolved_at: string | null;
}

export interface SleDataResponse {
  baseline: Record<string, unknown> | null;
  snapshots: Record<string, unknown>[];
  delta: Record<string, unknown> | null;
  drill_down: Record<string, unknown> | null;
}

export interface SessionResponse {
  id: string;
  site_id: string;
  site_name: string;
  device_mac: string;
  device_name: string;
  device_type: string;
  status: string;
  config_change_count: number;
  incident_count: number;
  has_impact: boolean;
  impact_severity: string;
  change_group_id: string | null;
  duration_minutes: number;
  polls_completed: number;
  polls_total: number;
  progress: { phase: string; message: string; percent: number };
  monitoring_started_at: string | null;
  monitoring_ends_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TimelineEntryResponse {
  timestamp: string;
  type: string;
  title: string;
  severity: string;
  data: Record<string, unknown>;
}

export interface SessionDetailResponse extends SessionResponse {
  org_id: string;
  config_changes: ConfigChangeEvent[];
  incidents: DeviceIncident[];
  sle_data: SleDataResponse | null;
  topology_baseline: Record<string, unknown> | null;
  topology_latest: Record<string, unknown> | null;
  validation_results: Record<string, unknown> | null;
  ai_assessment: Record<string, unknown> | null;
  ai_assessment_error: string | null;
  timeline: TimelineEntryResponse[];
}

export const SLE_METRIC_LABELS: Record<string, string> = {
  'time-to-connect': 'Time to Connect',
  'successful-connect': 'Successful Connect',
  throughput: 'Throughput',
  roaming: 'Roaming',
  capacity: 'Capacity',
  coverage: 'Coverage',
  'ap-health': 'AP Health',
  'switch-throughput': 'Switch Throughput',
  'switch-health': 'Switch Health',
  'switch-stc': 'Successful Connect (Wired)',
  'switch-stc-new': 'Successful Connect (New)',
  'gateway-health': 'Gateway Health',
  'wan-link-health': 'WAN Link Health',
};

export const VALIDATION_CHECK_LABELS: Record<string, string> = {
  connectivity: 'Upstream/Downstream Connectivity',
  performance: 'SLE Performance',
  stability: 'Device Stability',
  loop_detection: 'Loop Detection',
  black_holes: 'Black Hole Detection',
  client_impact: 'Client Impact',
  alarm_correlation: 'Alarm Correlation',
  port_flapping: 'Port Flapping',
  dhcp_health: 'DHCP Health',
  vc_integrity: 'Virtual Chassis Integrity',
  lag_mclag_integrity: 'LAG/MCLAG Integrity',
  routing_adjacency: 'Routing Adjacency (OSPF/BGP)',
  config_drift: 'Configuration Drift',
  poe_budget: 'PoE Budget',
  wan_failover: 'WAN Failover',
};

export interface SessionSummary {
  active: number;
  impacted: number;
  completed_24h: number;
  total: number;
}

/**
 * Chat message for the split-view session detail UI.
 * Mapped from timeline entries and user/AI chat interactions.
 */
export interface ChatMessage {
  id: string;
  role: 'system' | 'ai' | 'user';
  content: string;
  html: string;
  timestamp: string;
  severity?: string;
  type: 'narration' | 'event' | 'chat' | 'analysis';
}

export interface SessionChatResponse {
  reply: string;
  thread_id: string;
  usage: Record<string, unknown>;
}

// ── Change Group models ──────────────────────────────────────────────────

export interface IncidentSummary {
  type: string;
  severity: string;
  timestamp: string;
  resolved: boolean;
}

export interface SLEDeltaSummary {
  metric: string;
  baseline: number;
  current: number;
  delta_pct: number;
}

export interface DeviceSummary {
  session_id: string;
  device_mac: string;
  device_name: string;
  device_type: string;
  site_name: string;
  status: string;
  impact_severity: string;
  failed_checks: string[];
  active_incidents: IncidentSummary[];
  worst_sle_delta: SLEDeltaSummary | null;
}

export interface DeviceTypeCounts {
  total: number;
  monitoring: number;
  completed: number;
  impacted: number;
}

export interface ValidationCheckSummary {
  check_name: string;
  passed: number;
  failed: number;
  skipped: number;
}

export interface GroupSummary {
  total_devices: number;
  by_type: Record<string, DeviceTypeCounts>;
  worst_severity: string;
  validation_summary: ValidationCheckSummary[];
  sle_summary: Record<string, SLEDeltaSummary>;
  devices: DeviceSummary[];
  status: string;
  last_updated: string | null;
}

export interface ChangeGroupResponse {
  id: string;
  audit_id: string;
  org_id: string;
  site_id: string | null;
  change_source: string;
  change_description: string;
  triggered_by: string | null;
  triggered_at: string;
  session_count: number;
  summary: GroupSummary;
  ai_assessment: Record<string, unknown> | null;
  ai_assessment_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChangeGroupDetailResponse extends ChangeGroupResponse {
  timeline: TimelineEntryResponse[];
}

export interface ChangeGroupListResponse {
  groups: ChangeGroupResponse[];
  total: number;
}

export interface SessionSummaryWithGroups extends SessionSummary {
  active_groups: number;
  impacted_groups_24h: number;
}
