import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import {
  SessionResponse,
  SessionDetailResponse,
  SessionSummary,
  SessionChatResponse,
} from '../../features/impact-analysis/models/impact-analysis.model';

export interface SessionListResponse {
  sessions: SessionResponse[];
  total: number;
}

@Injectable({ providedIn: 'root' })
export class ImpactAnalysisService {
  private readonly api = inject(ApiService);

  getSessions(params?: {
    status?: string;
    site_id?: string;
    device_type?: string;
    limit?: number;
    skip?: number;
  }): Observable<SessionListResponse> {
    return this.api.get<SessionListResponse>('/impact-analysis/sessions', params);
  }

  getSession(id: string): Observable<SessionDetailResponse> {
    return this.api.get<SessionDetailResponse>(`/impact-analysis/sessions/${id}`);
  }

  createSession(body: {
    site_id: string;
    device_mac: string;
    device_type: string;
    monitoring_duration_minutes?: number;
    monitoring_interval_minutes?: number;
  }): Observable<SessionResponse> {
    return this.api.post<SessionResponse>('/impact-analysis/sessions', body);
  }

  cancelSession(id: string): Observable<SessionResponse> {
    return this.api.post<SessionResponse>(`/impact-analysis/sessions/${id}/cancel`, {});
  }

  reanalyze(id: string): Observable<SessionDetailResponse> {
    return this.api.post<SessionDetailResponse>(
      `/impact-analysis/sessions/${id}/reanalyze`,
      {},
    );
  }

  getSummary(): Observable<SessionSummary> {
    return this.api.get<SessionSummary>('/impact-analysis/summary');
  }

  getSleData(id: string): Observable<Record<string, unknown>> {
    return this.api.get<Record<string, unknown>>(
      `/impact-analysis/sessions/${id}/sle-data`,
    );
  }

  getSettings(): Observable<Record<string, unknown>> {
    return this.api.get<Record<string, unknown>>('/impact-analysis/settings');
  }

  updateSettings(body: Record<string, unknown>): Observable<Record<string, unknown>> {
    return this.api.put<Record<string, unknown>>('/impact-analysis/settings', body);
  }

  sendChatMessage(
    sessionId: string,
    message: string,
    streamId?: string,
    mcpConfigIds?: string[],
  ): Observable<SessionChatResponse> {
    return this.api.post<SessionChatResponse>(
      `/impact-analysis/sessions/${sessionId}/chat`,
      { message, stream_id: streamId ?? null, mcp_config_ids: mcpConfigIds ?? null },
    );
  }
}
