import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { shareReplay } from 'rxjs/operators';
import { ApiService } from './api.service';
import {
  WorkflowCreate,
  WorkflowUpdate,
  WorkflowResponse,
  WorkflowListResponse,
  WorkflowExecution,
  WorkflowExecutionListResponse,
  WorkflowNode,
  WorkflowEdge,
  WorkflowGraph,
  NodePosition,
  NodePort,
  ActionType,
  ApiCatalogEntry,
  VariableTree,
  SimulateRequest,
  SamplePayload,
} from '../models/workflow.model';
import { ACTION_META, DEFAULT_ACTION_META } from '../models/workflow-meta';

@Injectable({ providedIn: 'root' })
export class WorkflowService {
  private readonly api = inject(ApiService);
  private catalogCache$: Observable<ApiCatalogEntry[]> | null = null;

  // ── CRUD ──────────────────────────────────────────────────────────────

  list(skip = 0, limit = 100, statusFilter?: string): Observable<WorkflowListResponse> {
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

  execute(id: string): Observable<{ execution_id: string; status: string; message: string }> {
    return this.api.post(`/workflows/${id}/execute`);
  }

  getExecutions(id: string, skip = 0, limit = 20): Observable<WorkflowExecutionListResponse> {
    return this.api.get<WorkflowExecutionListResponse>(`/workflows/${id}/executions`, {
      skip,
      limit,
    });
  }

  getExecution(workflowId: string, executionId: string): Observable<WorkflowExecution> {
    return this.api.get<WorkflowExecution>(`/workflows/${workflowId}/executions/${executionId}`);
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

  // ── Variable autocomplete ─────────────────────────────────────────────

  getAvailableVariables(workflowId: string, nodeId: string): Observable<VariableTree> {
    return this.api.get<VariableTree>(`/workflows/${workflowId}/available-variables/${nodeId}`);
  }

  getEndpointSchema(
    method: string,
    path: string
  ): Observable<{ fields: string[]; schema: Record<string, unknown>; example: unknown }> {
    return this.api.get(`/workflows/endpoint-schema`, { method, path });
  }

  // ── Simulation ────────────────────────────────────────────────────────

  simulate(workflowId: string, request: SimulateRequest): Observable<WorkflowExecution> {
    return this.api.post<WorkflowExecution>(`/workflows/${workflowId}/simulate`, request);
  }

  getSamplePayloads(
    workflowId: string,
    limit = 10
  ): Observable<{ payloads: SamplePayload[] }> {
    return this.api.get(`/workflows/${workflowId}/sample-payloads`, { limit });
  }

  // ── Graph conversion ──────────────────────────────────────────────────

  toGraph(response: WorkflowResponse): WorkflowGraph {
    return {
      nodes: response.nodes || [],
      edges: response.edges || [],
      viewport: response.viewport,
    };
  }

  fromGraph(
    graph: WorkflowGraph
  ): Pick<WorkflowCreate, 'nodes' | 'edges' | 'viewport'> {
    return {
      nodes: graph.nodes as unknown as Record<string, unknown>[],
      edges: graph.edges as unknown as Record<string, unknown>[],
      viewport: graph.viewport as Record<string, unknown> | null,
    };
  }

  // ── Node factory ──────────────────────────────────────────────────────

  createNode(type: string, position: NodePosition): WorkflowNode {
    const id = crypto.randomUUID();

    if (type === 'trigger') {
      return {
        id,
        type: 'trigger',
        name: 'Webhook Trigger',
        position,
        config: { trigger_type: 'webhook' },
        output_ports: [{ id: 'default', label: '', type: 'default' }],
        enabled: true,
        continue_on_error: false,
        max_retries: 0,
        retry_delay: 0,
      };
    }

    const meta = ACTION_META[type as ActionType] || DEFAULT_ACTION_META;
    const ports = this.getDefaultPorts(type);
    const config = this.getDefaultConfig(type);

    return {
      id,
      type,
      name: meta.label,
      position,
      config,
      output_ports: ports,
      enabled: true,
      continue_on_error: false,
      max_retries: 3,
      retry_delay: 5,
    };
  }

  createEdge(
    sourceNodeId: string,
    sourcePortId: string,
    targetNodeId: string,
    targetPortId = 'input'
  ): WorkflowEdge {
    return {
      id: crypto.randomUUID(),
      source_node_id: sourceNodeId,
      source_port_id: sourcePortId,
      target_node_id: targetNodeId,
      target_port_id: targetPortId,
      label: '',
    };
  }

  private getDefaultPorts(type: string): NodePort[] {
    if (type === 'condition') {
      return [
        { id: 'branch_0', label: 'If', type: 'branch' },
        { id: 'else', label: 'Else', type: 'branch' },
      ];
    }
    if (type === 'for_each') {
      return [
        { id: 'loop_body', label: 'Loop', type: 'loop_body' },
        { id: 'done', label: 'Done', type: 'loop_done' },
      ];
    }
    return [{ id: 'default', label: '', type: 'default' }];
  }

  private getDefaultConfig(type: string): Record<string, unknown> {
    switch (type) {
      case 'condition':
        return { branches: [{ condition: '' }] };
      case 'for_each':
        return { loop_over: '', loop_variable: 'item', max_iterations: 100 };
      case 'set_variable':
        return { variable_name: '', variable_expression: '' };
      case 'delay':
        return { delay_seconds: 5 };
      default:
        return {};
    }
  }
}
