export interface CheckResultModel {
  check_id: string;
  check_name: string;
  layer: number;
  status: 'pass' | 'warning' | 'error' | 'critical' | 'skipped';
  summary: string;
  details: string[];
  affected_objects: string[];
  affected_sites: string[];
  remediation_hint: string | null;
}

export interface PredictionReportModel {
  total_checks: number;
  passed: number;
  warnings: number;
  errors: number;
  critical: number;
  skipped: number;
  check_results: CheckResultModel[];
  overall_severity: string;
  summary: string;
  execution_safe: boolean;
}

export interface StagedWriteModel {
  sequence: number;
  method: string;
  endpoint: string;
  body: Record<string, unknown> | null;
  object_type: string | null;
  site_id: string | null;
  object_id: string | null;
}

export interface RemediationAttemptModel {
  attempt: number;
  changed_writes: number[];
  previous_severity: string;
  new_severity: string;
  fixed_checks: string[];
  introduced_checks: string[];
  timestamp: string | null;
}

export interface TwinSessionSummary {
  id: string;
  status: string;
  source: string;
  source_ref: string | null;
  overall_severity: string;
  writes_count: number;
  affected_sites: string[];
  remediation_count: number;
  prediction_report: PredictionReportModel | null;
  created_at: string;
  updated_at: string;
}

export interface TwinSessionDetail extends TwinSessionSummary {
  ai_assessment: string | null;
  execution_safe: boolean;
  staged_writes: StagedWriteModel[];
  remediation_history: RemediationAttemptModel[];
}

export interface TwinSessionListResponse {
  sessions: TwinSessionSummary[];
  total: number;
}
