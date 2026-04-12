export interface BackupJobResponse {
  id: string;
  backup_type: string;
  org_id: string;
  org_name: string | null;
  site_id: string | null;
  site_name: string | null;
  status: string;
  object_count: number;
  size_bytes: number;
  created_at: string;
  created_by: string | null;
  data: Record<string, unknown> | null;
  webhook_event: Record<string, unknown>[] | null;
  error: string | null;
}

export interface BackupJobListResponse {
  backups: BackupJobResponse[];
  total: number;
}

export interface BackupDiffResponse {
  backup_id_1: string;
  backup_id_2: string;
  differences: BackupDiffEntry[];
  added_count: number;
  removed_count: number;
  modified_count: number;
}

export interface BackupDiffEntry {
  path: string;
  change_type: 'added' | 'removed' | 'modified';
  old_value?: unknown;
  new_value?: unknown;
}

export interface BackupTimelineEntry {
  id: string;
  backup_type: string;
  status: string;
  object_count: number;
  size_bytes: number;
  created_at: string;
  created_by: string | null;
}

export interface BackupTimelineResponse {
  entries: BackupTimelineEntry[];
  total: number;
}

export interface BackupCreateRequest {
  backup_type: string;
  site_id?: string;
  object_type?: string;
  object_ids?: string[];
}

export interface MistSiteOption {
  id: string;
  name: string;
}

export interface MistObjectOption {
  id: string;
  name: string;
  type?: string;
}

export interface MistObjectTypeOption {
  value: string; // "org:wlans" or "site:maps"
  label: string; // "Org WLANs"
  scope: 'org' | 'site';
  is_list: boolean;
}

// ── Object-centric models ──────────────────────────────────────────────────

export interface BackupObjectSummary {
  object_id: string;
  object_type: string;
  object_name: string | null;
  org_id: string;
  site_id: string | null;
  site_name: string | null;
  scope: string;
  version_count: number;
  latest_version: number;
  first_backed_up_at: string;
  last_backed_up_at: string;
  last_modified_at: string | null;
  is_deleted: boolean;
  event_type: string;
}

export interface BackupObjectListResponse {
  objects: BackupObjectSummary[];
  total: number;
}

export interface BackupChangeEvent {
  id: string;
  object_id: string;
  object_type: string;
  object_name: string | null;
  site_id: string | null;
  site_name: string | null;
  scope: string;
  event_type: string;
  version: number;
  changed_fields: string[];
  backed_up_at: string;
  backed_up_by: string | null;
}

export interface BackupChangeListResponse {
  changes: BackupChangeEvent[];
  total: number;
}

export interface RestoreRequest {
  dry_run: boolean;
}

export interface RestoreResponse {
  status: string;
  message: string;
  changes?: Record<string, unknown>;
}

// ── Log models ──────────────────────────────────────────────────────────────

export interface BackupLogEntry {
  id: string;
  backup_job_id: string;
  timestamp: string;
  level: string;
  phase: string;
  message: string;
  object_type: string | null;
  object_id: string | null;
  object_name: string | null;
  site_id: string | null;
  details: Record<string, unknown> | null;
}

export interface BackupLogListResponse {
  logs: BackupLogEntry[];
  total: number;
}

// ── Stats models ─────────────────────────────────────────────────────────────

export interface DailyObjectStats {
  date: string;
  object_count: number;
}

export interface DailyJobStats {
  date: string;
  total: number;
  completed: number;
  failed: number;
  webhook_events: number;
  avg_duration_seconds: number | null;
  min_duration_seconds: number | null;
  max_duration_seconds: number | null;
}

export interface BackupObjectStatsResponse {
  days: DailyObjectStats[];
}

export interface BackupJobStatsResponse {
  days: DailyJobStats[];
}

// ── Dependency models ───────────────────────────────────────────────────────

export interface ParentReference {
  target_type: string;
  target_id: string;
  target_name: string | null;
  field_path: string;
  exists_in_backup: boolean;
  is_deleted: boolean;
}

export interface ChildReference {
  source_type: string;
  source_id: string;
  source_name: string | null;
  field_path: string;
  is_deleted: boolean;
}

export interface ObjectDependencyResponse {
  object_id: string;
  object_type: string;
  object_name: string | null;
  parents: ParentReference[];
  children: ChildReference[];
}

// ── Cascade restore models ──────────────────────────────────────────────────

export interface DeletedDependencyInfo {
  object_id: string;
  object_type: string;
  object_name: string | null;
  field_path: string;
  relationship: string;
  latest_version_id: string | null;
}

export interface ActiveChildInfo {
  object_id: string;
  object_type: string;
  object_name: string | null;
  field_path: string;
  relationship: string;
  site_id: string | null;
}

export interface DryRunRestoreResponse {
  status: string;
  object_id: string;
  object_type: string;
  object_name: string | null;
  version: number;
  warnings: string[];
  deleted_dependencies: DeletedDependencyInfo[];
  deleted_children: DeletedDependencyInfo[];
  active_children?: ActiveChildInfo[];
  note?: string;
}

export interface CascadeRestorePlanItem {
  role: 'parent' | 'target' | 'child' | 'update';
  object_id: string;
  object_type: string;
  object_name: string | null;
  field_path?: string;
}

export interface CascadeRestoreResult {
  status: string;
  restored_objects: {
    role: string;
    original_object_id: string;
    new_object_id: string;
    object_type: string;
    object_name: string | null;
  }[];
  id_remap: Record<string, string>;
}

export interface RestoreSimulationResponse {
  status: string;
  object_id: string;
  object_type: string;
  object_name: string | null;
  version: number;
  twin_session_id: string;
  overall_severity: 'clean' | 'info' | 'warning' | 'error' | 'critical' | string;
  execution_safe: boolean;
  summary: string;
  counts: {
    total: number;
    warnings: number;
    errors: number;
    critical: number;
  };
  warnings: string[];
  simulate_write: {
    method: 'POST' | 'PUT' | 'DELETE' | string;
    endpoint: string;
  };
}
