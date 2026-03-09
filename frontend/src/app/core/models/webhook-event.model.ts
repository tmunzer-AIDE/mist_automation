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
}

export interface WebhookEventDetail extends WebhookEventSummary {
  payload: Record<string, unknown>;
  headers: Record<string, string>;
}

export interface WebhookEventListResponse {
  events: WebhookEventSummary[];
  total: number;
}
