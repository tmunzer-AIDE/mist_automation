import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import {
  WorkflowCreate,
  WorkflowUpdate,
  WorkflowResponse,
  WorkflowListResponse,
  WorkflowExecutionListResponse,
  PipelineBlock,
  WorkflowTrigger,
  WorkflowFilter,
  SecondaryFilter,
  WorkflowAction,
  ActionType,
} from '../models/workflow.model';

const ACTION_META: Record<
  ActionType,
  { label: string; icon: string; color: string }
> = {
  mist_api_get: {
    label: 'Mist API GET',
    icon: 'cloud_download',
    color: '#1976d2',
  },
  mist_api_post: {
    label: 'Mist API POST',
    icon: 'cloud_upload',
    color: '#1976d2',
  },
  mist_api_put: { label: 'Mist API PUT', icon: 'edit', color: '#1976d2' },
  mist_api_delete: {
    label: 'Mist API DELETE',
    icon: 'delete',
    color: '#d32f2f',
  },
  webhook: { label: 'Webhook', icon: 'send', color: '#7b1fa2' },
  slack: { label: 'Slack', icon: 'chat', color: '#e91e63' },
  servicenow: {
    label: 'ServiceNow',
    icon: 'confirmation_number',
    color: '#388e3c',
  },
  pagerduty: {
    label: 'PagerDuty',
    icon: 'notifications_active',
    color: '#f57c00',
  },
  delay: { label: 'Delay', icon: 'schedule', color: '#616161' },
  condition: { label: 'Condition', icon: 'call_split', color: '#0097a7' },
};

let blockIdCounter = 0;

function nextBlockId(): string {
  return `blk_${++blockIdCounter}`;
}

@Injectable({ providedIn: 'root' })
export class WorkflowService {
  private readonly api = inject(ApiService);

  // ── CRUD ──────────────────────────────────────────────────────────────

  list(
    skip = 0,
    limit = 100,
    statusFilter?: string
  ): Observable<WorkflowListResponse> {
    const params: Record<string, string | number> = { skip, limit };
    if (statusFilter) params['status_filter'] = statusFilter;
    return this.api.get<WorkflowListResponse>('/workflows', params);
  }

  get(id: string): Observable<WorkflowResponse> {
    return this.api.get<WorkflowResponse>(`/workflows/${id}`);
  }

  create(data: WorkflowCreate): Observable<WorkflowResponse> {
    return this.api.post<WorkflowResponse>('/workflows', data);
  }

  update(id: string, data: WorkflowUpdate): Observable<WorkflowResponse> {
    return this.api.put<WorkflowResponse>(`/workflows/${id}`, data);
  }

  remove(id: string): Observable<void> {
    return this.api.delete<void>(`/workflows/${id}`);
  }

  execute(
    id: string
  ): Observable<{ execution_id: string; status: string; message: string }> {
    return this.api.post(`/workflows/${id}/execute`);
  }

  getExecutions(
    id: string,
    skip = 0,
    limit = 20
  ): Observable<WorkflowExecutionListResponse> {
    return this.api.get<WorkflowExecutionListResponse>(
      `/workflows/${id}/executions`,
      { skip, limit }
    );
  }

  // ── Block conversion ──────────────────────────────────────────────────

  toPipelineBlocks(workflow: WorkflowResponse): PipelineBlock[] {
    const blocks: PipelineBlock[] = [];

    // Trigger
    const trigger = workflow.trigger;
    blocks.push({
      id: nextBlockId(),
      kind: 'trigger',
      data: trigger,
      label:
        trigger.type === 'webhook'
          ? `Webhook: ${trigger.webhook_topic || trigger.webhook_type || 'any'}`
          : `Cron: ${trigger.cron_expression || ''}`,
      icon: trigger.type === 'webhook' ? 'webhook' : 'schedule',
      color: '#6a1b9a',
    });

    // Primary filters
    for (const f of workflow.filters) {
      blocks.push({
        id: nextBlockId(),
        kind: 'filter',
        data: f,
        label: `${f.field} ${f.operator} ${f.value}`,
        icon: 'filter_list',
        color: '#00838f',
      });
    }

    // Secondary filters
    for (const sf of workflow.secondary_filters) {
      blocks.push({
        id: nextBlockId(),
        kind: 'secondary_filter',
        data: sf,
        label: `${sf.api_endpoint}: ${sf.field} ${sf.operator}`,
        icon: 'filter_alt',
        color: '#00695c',
      });
    }

    // Actions
    for (const a of workflow.actions) {
      const meta = ACTION_META[a.type] || {
        label: a.type,
        icon: 'play_arrow',
        color: '#455a64',
      };
      blocks.push({
        id: nextBlockId(),
        kind: 'action',
        data: a,
        label: a.name || meta.label,
        icon: meta.icon,
        color: meta.color,
      });
    }

    return blocks;
  }

  fromPipelineBlocks(
    blocks: PipelineBlock[]
  ): Pick<
    WorkflowCreate,
    'trigger' | 'filters' | 'secondary_filters' | 'actions'
  > {
    let trigger: Record<string, unknown> = { type: 'webhook' };
    const filters: Record<string, unknown>[] = [];
    const secondaryFilters: Record<string, unknown>[] = [];
    const actions: Record<string, unknown>[] = [];

    for (const block of blocks) {
      switch (block.kind) {
        case 'trigger':
          trigger = { ...(block.data as WorkflowTrigger) };
          break;
        case 'filter':
          filters.push({ ...(block.data as WorkflowFilter) });
          break;
        case 'secondary_filter':
          secondaryFilters.push({ ...(block.data as SecondaryFilter) });
          break;
        case 'action':
          actions.push({ ...(block.data as WorkflowAction) });
          break;
      }
    }

    return {
      trigger,
      filters,
      secondary_filters: secondaryFilters,
      actions,
    };
  }

  createDefaultTriggerBlock(): PipelineBlock {
    return {
      id: nextBlockId(),
      kind: 'trigger',
      data: { type: 'webhook' } as WorkflowTrigger,
      label: 'Webhook Trigger',
      icon: 'webhook',
      color: '#6a1b9a',
    };
  }

  createBlockForType(
    kind: 'filter' | 'secondary_filter' | 'action',
    actionType?: ActionType
  ): PipelineBlock {
    if (kind === 'filter') {
      return {
        id: nextBlockId(),
        kind: 'filter',
        data: {
          field: '',
          operator: 'equals',
          value: '',
        } as WorkflowFilter,
        label: 'New Filter',
        icon: 'filter_list',
        color: '#00838f',
      };
    }
    if (kind === 'secondary_filter') {
      return {
        id: nextBlockId(),
        kind: 'secondary_filter',
        data: {
          api_endpoint: '',
          field: '',
          operator: 'equals',
          value: '',
        } as SecondaryFilter,
        label: 'New Secondary Filter',
        icon: 'filter_alt',
        color: '#00695c',
      };
    }
    // Action
    const type = actionType || 'webhook';
    const meta = ACTION_META[type];
    return {
      id: nextBlockId(),
      kind: 'action',
      data: { name: '', type, enabled: true } as WorkflowAction,
      label: meta.label,
      icon: meta.icon,
      color: meta.color,
    };
  }
}
