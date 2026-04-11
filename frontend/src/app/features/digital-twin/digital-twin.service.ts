import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import {
  TwinSessionDetail,
  TwinSessionListResponse,
} from './models/twin-session.model';

@Injectable({ providedIn: 'root' })
export class DigitalTwinService {
  private readonly api = inject(ApiService);

  listSessions(params: {
    status?: string;
    source?: string;
    search?: string;
    skip?: number;
    limit?: number;
  }): Observable<TwinSessionListResponse> {
    return this.api.get<TwinSessionListResponse>('/digital-twin/sessions', params);
  }

  getSession(id: string): Observable<TwinSessionDetail> {
    return this.api.get<TwinSessionDetail>(`/digital-twin/sessions/${id}`);
  }

  approveSession(id: string): Observable<TwinSessionDetail> {
    return this.api.post<TwinSessionDetail>(`/digital-twin/sessions/${id}/approve`);
  }

  cancelSession(id: string): Observable<{ status: string; session_id: string }> {
    return this.api.post<{ status: string; session_id: string }>(
      `/digital-twin/sessions/${id}/cancel`,
    );
  }
}
