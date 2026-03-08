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
  value: string;   // "org:wlans" or "site:maps"
  label: string;   // "Org WLANs"
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
