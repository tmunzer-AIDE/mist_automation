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

  listAllExecutions(
    skip = 0,
    limit = 25,
    filters?: { status?: string; trigger_type?: string }
  ): Observable<WorkflowExecutionListResponse> {
    const params: Record<string, string | number> = { skip, limit };
    if (filters?.status) params['status_filter'] = filters.status;
    if (filters?.trigger_type) params['trigger_type'] = filters.trigger_type;
    return this.api.get<WorkflowExecutionListResponse>('/executions', params);
  }

  cancelExecution(executionId: string): Observable<{ status: string; message: string }> {
    return this.api.post(`/executions/${executionId}/cancel`);
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

  computeAvailableVariables(
    nodeId: string,
    nodes: WorkflowNode[],
    edges: WorkflowEdge[]
  ): Observable<VariableTree> {
    return this.api.post<VariableTree>(`/workflows/available-variables/${nodeId}`, { nodes, edges });
  }

  getEndpointSchema(
    method: string,
    path: string
  ): Observable<{ fields: string[]; schema: Record<string, unknown>; example: unknown }> {
    return this.api.get(`/workflows/endpoint-schema`, { method, path });
  }

  // ── Simulation ────────────────────────────────────────────────────────

  simulate(
    workflowId: string,
    request: SimulateRequest
  ): Observable<{ execution_id: string; status: string } & Partial<WorkflowExecution>> {
    return this.api.post(`/workflows/${workflowId}/simulate`, request);
  }

  getSamplePayloads(
    workflowId: string,
    limit = 10
  ): Observable<{ payloads: SamplePayload[] }> {
    return this.api.get(`/workflows/${workflowId}/sample-payloads`, { limit });
  }

  // ── Import / Export ──────────────────────────────────────────────

  exportWorkflow(workflow: WorkflowResponse | WorkflowGraph & { name: string; description?: string | null; timeout_seconds?: number }): void {
    const exportData = {
      _format: 'mist-automation-workflow',
      _version: 1,
      _exported_at: new Date().toISOString(),
      name: workflow.name,
      description: (workflow as WorkflowResponse).description ?? null,
      timeout_seconds: (workflow as WorkflowResponse).timeout_seconds ?? 300,
      nodes: ('nodes' in workflow ? workflow.nodes : []).map((n: WorkflowNode) => ({
        id: n.id,
        type: n.type,
        name: n.name,
        position: n.position,
        config: n.config,
        output_ports: n.output_ports,
        enabled: n.enabled,
        continue_on_error: n.continue_on_error,
        max_retries: n.max_retries,
        retry_delay: n.retry_delay,
        save_as: n.save_as,
      })),
      edges: ('edges' in workflow ? workflow.edges : []).map((e: WorkflowEdge) => ({
        id: e.id,
        source_node_id: e.source_node_id,
        source_port_id: e.source_port_id,
        target_node_id: e.target_node_id,
        target_port_id: e.target_port_id,
        label: e.label,
      })),
      viewport: (workflow as WorkflowResponse).viewport ?? null,
    };

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${exportData.name.replace(/[^a-zA-Z0-9_-]/g, '_')}.workflow.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  importWorkflowFromFile(): Promise<WorkflowCreate | null> {
    return new Promise((resolve) => {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.json';
      input.onchange = () => {
        const file = input.files?.[0];
        if (!file) { resolve(null); return; }
        const reader = new FileReader();
        reader.onload = () => {
          try {
            const data = JSON.parse(reader.result as string);
            const result = this.validateImport(data);
            resolve(result);
          } catch {
            resolve(null);
          }
        };
        reader.onerror = () => resolve(null);
        reader.readAsText(file);
      };
      input.oncancel = () => resolve(null);
      input.click();
    });
  }

  private validateImport(data: Record<string, unknown>): WorkflowCreate | null {
    if (!data || typeof data !== 'object') return null;
    const nodes = data['nodes'] as Record<string, unknown>[];
    if (!Array.isArray(nodes) || nodes.length === 0) return null;
    // Require at least a trigger node
    if (!nodes.some((n) => n['type'] === 'trigger')) return null;

    // Regenerate all node and edge IDs to avoid collisions
    const idMap = new Map<string, string>();
    const newNodes = nodes.map((n) => {
      const newId = crypto.randomUUID();
      idMap.set(n['id'] as string, newId);
      return { ...n, id: newId };
    });

    const edges = (data['edges'] as Record<string, unknown>[]) || [];
    const newEdges = edges.map((e) => ({
      ...e,
      id: crypto.randomUUID(),
      source_node_id: idMap.get(e['source_node_id'] as string) ?? e['source_node_id'],
      target_node_id: idMap.get(e['target_node_id'] as string) ?? e['target_node_id'],
    }));

    return {
      name: (data['name'] as string) || 'Imported Workflow',
      description: (data['description'] as string) || undefined,
      timeout_seconds: (data['timeout_seconds'] as number) || 300,
      nodes: newNodes,
      edges: newEdges,
      viewport: (data['viewport'] as Record<string, unknown>) ?? null,
    };
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
      case 'data_transform':
        return { source: '', fields: [{ path: '', label: '' }], filter: '' };
      case 'format_report':
        return {
          data_source: '',
          columns_source: '',
          format: 'markdown',
          title: '',
          footer_template: '',
        };
      default:
        return {};
    }
  }
}
