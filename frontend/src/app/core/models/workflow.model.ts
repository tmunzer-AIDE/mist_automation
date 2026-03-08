// ── Enums ────────────────────────────────────────────────────────────────────

export type WorkflowStatus = 'enabled' | 'disabled' | 'draft';
export type TriggerType = 'webhook' | 'cron';
export type FilterOperator =
  | 'equals'
  | 'not_equals'
  | 'contains'
  | 'not_contains'
  | 'starts_with'
  | 'ends_with'
  | 'greater_than'
  | 'less_than'
  | 'greater_equal'
  | 'less_equal'
  | 'in'
  | 'not_in'
  | 'in_list'
  | 'not_in_list'
  | 'between'
  | 'is_true'
  | 'is_false'
  | 'exists'
  | 'regex';
export type FilterLogic = 'and' | 'or';
export type ActionType =
  | 'mist_api_get'
  | 'mist_api_post'
  | 'mist_api_put'
  | 'mist_api_delete'
  | 'webhook'
  | 'slack'
  | 'servicenow'
  | 'pagerduty'
  | 'delay'
  | 'condition';
export type ExecutionStatus =
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'timeout'
  | 'cancelled'
  | 'filtered'
  | 'partial';

// ── Trigger ──────────────────────────────────────────────────────────────────

export interface WorkflowTrigger {
  type: TriggerType;
  webhook_type?: string;
  webhook_topic?: string;
  cron_expression?: string;
  timezone?: string;
  skip_if_running?: boolean;
}

// ── Filters ──────────────────────────────────────────────────────────────────

export interface WorkflowFilter {
  field: string;
  operator: FilterOperator;
  value: unknown;
  case_sensitive?: boolean;
  logic?: FilterLogic;
}

export interface SecondaryFilter {
  api_endpoint: string;
  field: string;
  operator: FilterOperator;
  value: unknown;
  logic?: FilterLogic;
}

// ── Actions ──────────────────────────────────────────────────────────────────

export interface WorkflowAction {
  name: string;
  type: ActionType;
  enabled?: boolean;
  api_endpoint?: string;
  api_method?: string;
  api_body?: Record<string, unknown>;
  api_params?: Record<string, unknown>;
  webhook_url?: string;
  webhook_headers?: Record<string, string>;
  webhook_body?: Record<string, unknown>;
  notification_template?: string;
  notification_channel?: string;
  condition?: string;
  then_actions?: WorkflowAction[];
  else_actions?: WorkflowAction[];
  delay_seconds?: number;
  max_retries?: number;
  retry_delay?: number;
  continue_on_error?: boolean;
}

// ── Workflow CRUD ────────────────────────────────────────────────────────────

export interface WorkflowCreate {
  name: string;
  description?: string;
  timeout_seconds?: number;
  trigger: Record<string, unknown>;
  filters?: Record<string, unknown>[];
  secondary_filters?: Record<string, unknown>[];
  actions: Record<string, unknown>[];
}

export interface WorkflowUpdate {
  name?: string;
  description?: string;
  status?: WorkflowStatus;
  timeout_seconds?: number;
  trigger?: Record<string, unknown>;
  filters?: Record<string, unknown>[];
  secondary_filters?: Record<string, unknown>[];
  actions?: Record<string, unknown>[];
}

export interface WorkflowResponse {
  id: string;
  name: string;
  description: string | null;
  created_by: string;
  status: WorkflowStatus;
  sharing: string;
  timeout_seconds: number;
  trigger: WorkflowTrigger;
  filters: WorkflowFilter[];
  secondary_filters: SecondaryFilter[];
  actions: WorkflowAction[];
  execution_count: number;
  success_count: number;
  failure_count: number;
  last_execution: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowListResponse {
  workflows: WorkflowResponse[];
  total: number;
}

// ── Execution ────────────────────────────────────────────────────────────────

export interface ActionExecutionResult {
  action_name: string;
  status: 'success' | 'failed' | 'skipped';
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  error: string | null;
  output: Record<string, unknown> | null;
  retry_count: number;
}

export interface WorkflowExecution {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: ExecutionStatus;
  trigger_type: string;
  trigger_data: Record<string, unknown> | null;
  triggered_by: string | null;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  filters_passed: boolean;
  filter_results: Record<string, unknown>[];
  actions_executed: number;
  actions_succeeded: number;
  actions_failed: number;
  action_results: ActionExecutionResult[];
  error: string | null;
  error_details: string | null;
}

export interface WorkflowExecutionListResponse {
  executions: WorkflowExecution[];
  total: number;
}

// ── Pipeline UI types ────────────────────────────────────────────────────────

export interface PipelineBlock {
  id: string;
  kind: 'trigger' | 'filter' | 'secondary_filter' | 'action';
  data: WorkflowTrigger | WorkflowFilter | SecondaryFilter | WorkflowAction;
  label: string;
  icon: string;
  color: string;
}
