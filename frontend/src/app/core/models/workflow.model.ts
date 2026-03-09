// ── Enums ────────────────────────────────────────────────────────────────────

export type WorkflowStatus = 'enabled' | 'disabled' | 'draft';
export type TriggerType = 'webhook' | 'cron';
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
  | 'condition'
  | 'set_variable'
  | 'for_each';
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
  condition?: string;
  save_as?: VariableBinding[];
}

// ── Condition branches ───────────────────────────────────────────────────────

export interface ConditionBranch {
  condition: string;
  actions: WorkflowAction[];
}

// ── Variable binding ─────────────────────────────────────────────────────────

export interface VariableBinding {
  name: string;
  expression: string;
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
  branches?: ConditionBranch[];
  else_actions?: WorkflowAction[];
  delay_seconds?: number;
  // Variable storage — list of bindings extracted from action output
  save_as?: VariableBinding[];
  // SET_VARIABLE action
  variable_name?: string;
  variable_expression?: string;
  // FOR_EACH loop
  loop_over?: string;
  loop_variable?: string;
  loop_actions?: WorkflowAction[];
  max_iterations?: number;
  // Retry / error handling
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
  actions: Record<string, unknown>[];
}

export interface WorkflowUpdate {
  name?: string;
  description?: string;
  status?: WorkflowStatus;
  timeout_seconds?: number;
  trigger?: Record<string, unknown>;
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
  trigger_condition_passed: boolean | null;
  trigger_condition: string | null;
  actions_executed: number;
  actions_succeeded: number;
  actions_failed: number;
  action_results: ActionExecutionResult[];
  error: string | null;
  error_details: string | null;
  variables?: Record<string, unknown>;
  logs?: string[];
}

export interface WorkflowExecutionListResponse {
  executions: WorkflowExecution[];
  total: number;
}

// ── API Catalog ──────────────────────────────────────────────────────────────

export interface QueryParam {
  name: string;
  description: string;
  required: boolean;
  type: string;
}

export interface ApiCatalogEntry {
  id: string;
  label: string;
  method: string;
  endpoint: string;
  path_params: string[];
  query_params: QueryParam[];
  category: string;
  description: string;
  has_body: boolean;
}

// ── Pipeline UI types ────────────────────────────────────────────────────────

export interface PipelineBlock {
  id: string;
  kind: 'trigger' | 'action';
  data: WorkflowTrigger | WorkflowAction;
  label: string;
  icon: string;
  color: string;
}
