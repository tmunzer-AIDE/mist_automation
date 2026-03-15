// ── Enums ────────────────────────────────────────────────────────────────────

export type WorkflowStatus = 'enabled' | 'disabled' | 'draft';
export type TriggerType = 'webhook' | 'cron' | 'manual';
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
  | 'for_each'
  | 'data_transform'
  | 'format_report'
  | 'email'
  | 'invoke_subflow'
  | 'subflow_output'
  | 'device_utils';
export type WorkflowType = 'standard' | 'subflow';

export interface DeviceUtilParam {
  name: string;
  description: string;
  required: boolean;
  type: string;
}

export interface DeviceUtilEntry {
  id: string;
  device_type: string;
  function: string;
  label: string;
  params: DeviceUtilParam[];
  description: string;
}

export interface SubflowParameter {
  name: string;
  type: string;
  description: string;
  required: boolean;
  default_value: unknown;
}
export type ExecutionStatus =
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'timeout'
  | 'cancelled'
  | 'filtered'
  | 'partial';

// ── Graph model ─────────────────────────────────────────────────────────────

export interface NodePosition {
  x: number;
  y: number;
}

export interface NodePort {
  id: string;
  label: string;
  type: string; // 'default' | 'branch' | 'loop_body' | 'loop_done'
}

export interface WorkflowNode {
  id: string;
  type: string; // 'trigger' or ActionType
  name: string;
  position: NodePosition;
  config: Record<string, unknown>;
  output_ports: NodePort[];
  enabled: boolean;
  continue_on_error: boolean;
  max_retries: number;
  retry_delay: number;
  save_as?: VariableBinding[];
}

export interface WorkflowEdge {
  id: string;
  source_node_id: string;
  source_port_id: string;
  target_node_id: string;
  target_port_id: string;
  label: string;
}

export interface WorkflowGraph {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  viewport?: { x: number; y: number; zoom: number } | null;
}

// ── Variable binding ─────────────────────────────────────────────────────────

export interface VariableBinding {
  name: string;
  expression: string;
}

// ── Workflow CRUD ────────────────────────────────────────────────────────────

export interface WorkflowCreate {
  name: string;
  description?: string;
  workflow_type?: WorkflowType;
  timeout_seconds?: number;
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
  viewport?: Record<string, unknown> | null;
  input_parameters?: SubflowParameter[];
  output_parameters?: SubflowParameter[];
}

export interface WorkflowUpdate {
  name?: string;
  description?: string;
  status?: WorkflowStatus;
  timeout_seconds?: number;
  nodes?: Record<string, unknown>[];
  edges?: Record<string, unknown>[];
  viewport?: Record<string, unknown> | null;
  input_parameters?: SubflowParameter[];
  output_parameters?: SubflowParameter[];
}

export interface WorkflowResponse {
  id: string;
  name: string;
  description: string | null;
  workflow_type: WorkflowType;
  created_by: string;
  status: WorkflowStatus;
  sharing: string;
  timeout_seconds: number;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  viewport: { x: number; y: number; zoom: number } | null;
  input_parameters: SubflowParameter[];
  output_parameters: SubflowParameter[];
  execution_count: number;
  success_count: number;
  failure_count: number;
  last_execution: string | null;
  created_at: string;
  updated_at: string;
}

export interface SubflowSchemaResponse {
  id: string;
  name: string;
  input_parameters: SubflowParameter[];
  output_parameters: SubflowParameter[];
}

export interface WorkflowListResponse {
  workflows: WorkflowResponse[];
  total: number;
}

// ── Execution ────────────────────────────────────────────────────────────────

export interface NodeExecutionResult {
  node_id: string;
  node_name: string;
  node_type: string;
  status: 'success' | 'failed' | 'skipped';
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  error: string | null;
  output_data: Record<string, unknown> | null;
  input_snapshot: Record<string, unknown> | null;
  retry_count: number;
}

export interface NodeSnapshot {
  node_id: string;
  node_name: string;
  step: number;
  input_variables: Record<string, unknown>;
  output_data: Record<string, unknown> | null;
  status: string;
  duration_ms: number | null;
  error: string | null;
  variables_after: Record<string, unknown>;
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
  nodes_executed: number;
  nodes_succeeded: number;
  nodes_failed: number;
  node_results: Record<string, NodeExecutionResult>;
  node_snapshots: NodeSnapshot[];
  is_simulation: boolean;
  is_dry_run: boolean;
  parent_execution_id: string | null;
  parent_workflow_id: string | null;
  child_execution_ids: string[];
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

// ── Variable autocomplete ────────────────────────────────────────────────────

export interface VariableTree {
  trigger: Record<string, unknown>;
  nodes: Record<string, Record<string, unknown>>;
  utilities: Record<string, string>;
}

// ── Simulation ───────────────────────────────────────────────────────────────

export interface SimulateRequest {
  payload?: Record<string, unknown>;
  webhook_event_id?: string;
  dry_run: boolean;
  stream_id?: string;
}

export interface SimulationWsMessage {
  type: 'node_started' | 'node_completed' | 'simulation_completed';
  channel: string;
  data: Record<string, unknown>;
}

export interface SamplePayload {
  event_id: string;
  timestamp: string;
  topic: string;
  webhook_type: string;
  payload_preview: Record<string, unknown>;
  payload: Record<string, unknown>;
}

export interface SimulationState {
  execution: WorkflowExecution | null;
  currentStep: number;
  totalSteps: number;
  isRunning: boolean;
  nodeStatuses: Record<string, 'pending' | 'success' | 'failed' | 'active'>;
  activeEdges: Set<string>;
}
