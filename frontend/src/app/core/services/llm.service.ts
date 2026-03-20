import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
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

@Injectable({ providedIn: 'root' })
export class LlmService {
  private readonly api = inject(ApiService);

  /** Check if LLM features are available */
  getStatus(): Observable<LlmStatus> {
    return this.api.get<LlmStatus>('/llm/status');
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
}
