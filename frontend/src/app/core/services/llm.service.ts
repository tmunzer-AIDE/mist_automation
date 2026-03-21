import { Injectable, inject } from '@angular/core';
import { Observable, shareReplay } from 'rxjs';
import { ApiService } from './api.service';
import { LlmStatus, LlmTestResult } from '../models/llm.model';

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
  followUp(threadId: string, message: string): Observable<ChatResponse> {
    return this.api.post<ChatResponse>(`/llm/chat/${threadId}`, { message });
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
}
