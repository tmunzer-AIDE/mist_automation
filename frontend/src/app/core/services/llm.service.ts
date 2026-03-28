import { Injectable, inject } from '@angular/core';
import { Observable, shareReplay } from 'rxjs';
import { ApiService } from './api.service';
import {
  ConversationThreadDetail,
  ConversationThreadListResponse,
  GlobalChatResponse,
  LlmConfig,
  LlmConfigAvailable,
  LlmModel,
  LlmStatus,
  LlmTestResult,
  McpConfig,
  McpConfigAvailable,
  McpTestResult,
  McpTool,
} from '../models/llm.model';

interface SummaryResponse {
  summary: string;
  thread_id: string;
  usage: Record<string, number>;
}

interface ChatResponse {
  reply: string;
  thread_id: string;
  usage: Record<string, number>;
}

export interface CategorySelectionResponse {
  categories: string[];
  usage: Record<string, number>;
}

export interface WorkflowAssistResponse {
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
  name: string;
  description: string;
  explanation: string;
  thread_id: string;
  validation_errors: string[];
  usage: Record<string, number>;
}

interface DebugResponse {
  analysis: string;
  thread_id: string;
  usage: Record<string, number>;
}

interface WebhookSummaryResponse {
  summary: string;
  event_count: number;
  thread_id: string;
  usage: Record<string, number>;
}

interface FieldAssistResponse {
  suggested_value: string;
  explanation: string;
  usage: Record<string, number>;
}

@Injectable({ providedIn: 'root' })
export class LlmService {
  private readonly api = inject(ApiService);

  /** Cached LLM status — shared across all components, fetched once */
  private readonly status$ = this.api.get<LlmStatus>('/llm/status').pipe(shareReplay(1));

  /** Check if LLM features are available (cached, single HTTP call) */
  getStatus(): Observable<LlmStatus> {
    return this.status$;
  }

  /** Test LLM connection */
  testConnection(): Observable<LlmTestResult> {
    return this.api.post<LlmTestResult>('/llm/test');
  }

  // ── LLM Config CRUD ──────────────────────────────────────────────────────

  listConfigs(): Observable<LlmConfig[]> {
    return this.api.get<LlmConfig[]>('/llm/configs');
  }

  createConfig(data: Record<string, unknown>): Observable<LlmConfig> {
    return this.api.post<LlmConfig>('/llm/configs', data);
  }

  updateConfig(id: string, data: Record<string, unknown>): Observable<LlmConfig> {
    return this.api.put<LlmConfig>(`/llm/configs/${id}`, data);
  }

  deleteConfig(id: string): Observable<void> {
    return this.api.delete<void>(`/llm/configs/${id}`);
  }

  setDefaultConfig(id: string): Observable<LlmConfig> {
    return this.api.post<LlmConfig>(`/llm/configs/${id}/set-default`);
  }

  testConfig(id: string): Observable<LlmTestResult> {
    return this.api.post<LlmTestResult>(`/llm/configs/${id}/test`);
  }

  listAvailableConfigs(): Observable<LlmConfigAvailable[]> {
    return this.api.get<LlmConfigAvailable[]>('/llm/configs/available');
  }

  listModels(configId: string): Observable<{ models: LlmModel[] }> {
    return this.api.get<{ models: LlmModel[] }>(`/llm/configs/${configId}/models`);
  }

  /** Test connection with unsaved config values */
  testConnectionAnonymous(data: Record<string, unknown>): Observable<LlmTestResult> {
    return this.api.post<LlmTestResult>('/llm/test-connection', data);
  }

  /** Discover models with unsaved config values */
  discoverModels(data: Record<string, unknown>): Observable<{ models: LlmModel[] }> {
    return this.api.post<{ models: LlmModel[] }>('/llm/discover-models', data);
  }

  /** Global chat with MCP tool access */
  globalChat(
    message: string,
    threadId?: string,
    pageContext?: string,
    streamId?: string,
    mcpConfigIds?: string[],
  ): Observable<GlobalChatResponse> {
    return this.api.post<GlobalChatResponse>('/llm/chat', {
      message,
      thread_id: threadId ?? null,
      page_context: pageContext ?? null,
      stream_id: streamId ?? null,
      mcp_config_ids: mcpConfigIds ?? [],
    });
  }

  /** Respond to a tool elicitation prompt */
  respondToElicitation(requestId: string, accepted: boolean): Observable<{ status: string }> {
    return this.api.post<{ status: string }>(`/llm/elicitation/${requestId}/respond`, { accepted });
  }

  /** Summarize changes between two backup object versions */
  summarizeDiff(
    versionId1: string,
    versionId2: string,
    threadId?: string,
  ): Observable<SummaryResponse> {
    return this.api.post<SummaryResponse>('/llm/backup/summarize', {
      version_id_1: versionId1,
      version_id_2: versionId2,
      thread_id: threadId ?? null,
    });
  }

  /** Send a follow-up message in an existing conversation thread */
  followUp(threadId: string, message: string, streamId?: string, mcpConfigIds?: string[]): Observable<ChatResponse> {
    const body: Record<string, unknown> = {
      message,
      stream_id: streamId ?? null,
    };
    if (mcpConfigIds !== undefined) {
      body['mcp_config_ids'] = mcpConfigIds;
    }
    return this.api.post<ChatResponse>(`/llm/chat/${threadId}`, body);
  }

  /** Pass 1: select relevant API categories for a workflow description */
  selectCategories(description: string): Observable<CategorySelectionResponse> {
    return this.api.post<CategorySelectionResponse>('/llm/workflow/select-categories', {
      description,
    });
  }

  /** Pass 2: generate a workflow from natural language (with pre-selected categories) */
  workflowAssist(
    description: string,
    categories?: string[],
    threadId?: string,
  ): Observable<WorkflowAssistResponse> {
    return this.api.post<WorkflowAssistResponse>('/llm/workflow/assist', {
      description,
      categories: categories ?? null,
      thread_id: threadId ?? null,
    });
  }

  /** Debug a failed workflow execution */
  debugExecution(executionId: string, threadId?: string): Observable<DebugResponse> {
    return this.api.post<DebugResponse>('/llm/workflow/debug', {
      execution_id: executionId,
      thread_id: threadId ?? null,
    });
  }

  /** Summarize recent webhook events */
  summarizeWebhooks(hours: number = 24): Observable<WebhookSummaryResponse> {
    return this.api.post<WebhookSummaryResponse>('/llm/webhooks/summarize', { hours });
  }

  /** Summarize dashboard state */
  summarizeDashboard(): Observable<SummaryResponse> {
    return this.api.post<SummaryResponse>('/llm/dashboard/summarize', {});
  }

  /** Summarize audit logs with current filters */
  summarizeAuditLogs(filters: {
    event_type?: string;
    user_id?: string;
    start_date?: string;
    end_date?: string;
  }): Observable<SummaryResponse> {
    return this.api.post<SummaryResponse>('/llm/audit-logs/summarize', filters);
  }

  /** Summarize system logs with current filters */
  summarizeSystemLogs(filters: {
    level?: string;
    logger?: string;
  }): Observable<SummaryResponse> {
    return this.api.post<SummaryResponse>('/llm/system-logs/summarize', filters);
  }

  /** Summarize backup health and changes */
  summarizeBackups(filters: {
    object_type?: string;
    site_id?: string;
    scope?: string;
  }): Observable<SummaryResponse> {
    return this.api.post<SummaryResponse>('/llm/backups/summarize', filters);
  }

  /** Help fill a single workflow node field */
  fieldAssist(
    nodeType: string,
    fieldName: string,
    description: string,
    upstreamVariables?: Record<string, unknown>,
  ): Observable<FieldAssistResponse> {
    return this.api.post<FieldAssistResponse>('/llm/workflow/field-assist', {
      node_type: nodeType,
      field_name: fieldName,
      description,
      upstream_variables: upstreamVariables ?? null,
    });
  }

  // ── Conversation Threads ─────────────────────────────────────────────────

  listThreads(skip = 0, limit = 25, feature?: string): Observable<ConversationThreadListResponse> {
    const params: Record<string, string | number> = { skip, limit };
    if (feature) params['feature'] = feature;
    return this.api.get<ConversationThreadListResponse>('/llm/threads', params);
  }

  getThread(id: string): Observable<ConversationThreadDetail> {
    return this.api.get<ConversationThreadDetail>(`/llm/threads/${id}`);
  }

  deleteThread(id: string): Observable<void> {
    return this.api.delete<void>(`/llm/threads/${id}`);
  }

  // ── MCP Config CRUD ──────────────────────────────────────────────────────

  listMcpConfigs(): Observable<McpConfig[]> {
    return this.api.get<McpConfig[]>('/mcp/configs');
  }

  createMcpConfig(data: Record<string, unknown>): Observable<McpConfig> {
    return this.api.post<McpConfig>('/mcp/configs', data);
  }

  updateMcpConfig(id: string, data: Record<string, unknown>): Observable<McpConfig> {
    return this.api.put<McpConfig>(`/mcp/configs/${id}`, data);
  }

  deleteMcpConfig(id: string): Observable<void> {
    return this.api.delete<void>(`/mcp/configs/${id}`);
  }

  testMcpConfig(id: string): Observable<McpTestResult> {
    return this.api.post<McpTestResult>(`/mcp/configs/${id}/test`);
  }

  listAvailableMcpConfigs(): Observable<McpConfigAvailable[]> {
    return this.api.get<McpConfigAvailable[]>('/mcp/configs/available');
  }

  testMcpConnectionAnonymous(data: Record<string, unknown>): Observable<McpTestResult> {
    return this.api.post<McpTestResult>('/mcp/test-connection', data);
  }

  // ── MCP Tool Browser ──────────────────────────────────────────────────────

  listMcpTools(configId: string): Observable<McpTool[]> {
    return this.api.get<McpTool[]>(`/mcp/configs/${configId}/tools`);
  }

  callMcpTool(configId: string, toolName: string, args: Record<string, unknown>): Observable<{ result: string }> {
    return this.api.post<{ result: string }>(`/mcp/configs/${configId}/tools/${toolName}/call`, { arguments: args });
  }

  listLocalMcpTools(): Observable<McpTool[]> {
    return this.api.get<McpTool[]>('/mcp/local/tools');
  }

  callLocalMcpTool(toolName: string, args: Record<string, unknown>): Observable<{ result: string }> {
    return this.api.post<{ result: string }>(`/mcp/local/tools/${toolName}/call`, { arguments: args });
  }
}
