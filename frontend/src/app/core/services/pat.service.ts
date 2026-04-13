import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';

export interface PersonalAccessToken {
  id: string;
  name: string;
  token_prefix: string;
  scopes: string[];
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface PATListResponse {
  tokens: PersonalAccessToken[];
  total: number;
  max_per_user: number;
}

export interface PATCreateRequest {
  name: string;
  expires_at?: string | null;
}

export interface PATCreateResponse extends PersonalAccessToken {
  token: string;
}

@Injectable({ providedIn: 'root' })
export class PatService {
  private readonly api = inject(ApiService);

  list(): Observable<PATListResponse> {
    return this.api.get<PATListResponse>('/users/me/tokens');
  }

  create(payload: PATCreateRequest): Observable<PATCreateResponse> {
    return this.api.post<PATCreateResponse>('/users/me/tokens', payload);
  }

  revoke(tokenId: string): Observable<void> {
    return this.api.delete<void>(`/users/me/tokens/${tokenId}`);
  }
}
