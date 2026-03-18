export interface WebhookEventSummary {
  id: string;
  webhook_type: string;
  webhook_topic: string | null;
  webhook_id: string;
  source_ip: string | null;
  site_id: string | null;
  org_id: string | null;
  signature_valid: boolean;
  processed: boolean;
  matched_workflows: string[];
  executions_triggered: string[];
  routed_to: string[];
  response_status: number;
  response_body: Record<string, unknown>;
  received_at: string;
  processed_at: string | null;

  // Extracted monitor fields
  event_type: string | null;
  org_name: string | null;
  site_name: string | null;
  device_name: string | null;
  device_mac: string | null;
  event_details: string | null;
  event_timestamp: string | null;
}

export interface WebhookEventDetail extends WebhookEventSummary {
  payload: Record<string, unknown>;
  headers: Record<string, string>;
}

export interface WebhookEventListResponse {
  events: WebhookEventSummary[];
  total: number;
}

export interface MonitorEvent extends WebhookEventSummary {
  isNew?: boolean;
}

export interface WebhookStatsBucket {
  bucket: string;
  total: number;
  by_topic: Record<string, number>;
}

export interface WebhookStatsResponse {
  buckets: WebhookStatsBucket[];
  granularity: 'hourly' | 'daily';
  hours: number;
}
