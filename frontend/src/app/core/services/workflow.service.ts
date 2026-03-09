import { Injectable, inject } from '@angular/core';
import { Observable, of } from 'rxjs';
import { map, shareReplay } from 'rxjs/operators';
import { ApiService } from './api.service';
import {
  WorkflowCreate,
  WorkflowUpdate,
  WorkflowResponse,
  WorkflowListResponse,
  WorkflowExecution,
  WorkflowExecutionListResponse,
  PipelineBlock,
  WorkflowTrigger,
  WorkflowAction,
  ActionType,
  ApiCatalogEntry,
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
  set_variable: { label: 'Set Variable', icon: 'data_object', color: '#795548' },
  for_each: { label: 'For Each', icon: 'loop', color: '#4527a0' },
};

let blockIdCounter = 0;

function nextBlockId(): string {
  return `blk_${++blockIdCounter}`;
}

@Injectable({ providedIn: 'root' })
export class WorkflowService {
  private readonly api = inject(ApiService);
  private catalogCache$: Observable<ApiCatalogEntry[]> | null = null;

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

  getExecution(
    workflowId: string,
    executionId: string
  ): Observable<WorkflowExecution> {
    return this.api.get<WorkflowExecution>(
      `/workflows/${workflowId}/executions/${executionId}`
    );
  }

  // ── API Catalog ───────────────────────────────────────────────────────

  getApiCatalog(): Observable<ApiCatalogEntry[]> {
    if (!this.catalogCache$) {
      this.catalogCache$ = this.api
        .get<ApiCatalogEntry[]>('/workflows/api-catalog')
        .pipe(shareReplay(1));
    }
    return this.catalogCache$;
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
          ? `Webhook: ${trigger.webhook_type || 'any'}`
          : `Cron: ${trigger.cron_expression || ''}`,
      icon: trigger.type === 'webhook' ? 'webhook' : 'schedule',
      color: '#6a1b9a',
    });

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
  ): Pick<WorkflowCreate, 'trigger' | 'actions'> {
    let trigger: Record<string, unknown> = { type: 'webhook' };
    const actions: Record<string, unknown>[] = [];

    for (const block of blocks) {
      switch (block.kind) {
        case 'trigger':
          trigger = { ...(block.data as WorkflowTrigger) };
          break;
        case 'action':
          actions.push({ ...(block.data as WorkflowAction) });
          break;
      }
    }

    return { trigger, actions };
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
    kind: 'action',
    actionType?: ActionType
  ): PipelineBlock {
    const type = actionType || 'webhook';
    const meta = ACTION_META[type];
    let actionData: WorkflowAction;

    if (type === 'condition') {
      actionData = { name: '', type, enabled: true, branches: [{ condition: '', actions: [] }] };
    } else if (type === 'for_each') {
      actionData = { name: '', type, enabled: true, loop_over: '', loop_variable: 'item', loop_actions: [], max_iterations: 100 };
    } else if (type === 'set_variable') {
      actionData = { name: '', type, enabled: true, variable_name: '', variable_expression: '' };
    } else {
      actionData = { name: '', type, enabled: true };
    }

    return {
      id: nextBlockId(),
      kind: 'action',
      data: actionData,
      label: meta.label,
      icon: meta.icon,
      color: meta.color,
    };
  }
}
