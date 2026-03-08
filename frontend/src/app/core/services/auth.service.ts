import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { HttpClient } from '@angular/common/http';
import {
  LoginRequest,
  TokenResponse,
  UserResponse,
  OnboardRequest,
  ChangePasswordRequest,
} from '../models/user.model';
import { HealthResponse, SessionListResponse } from '../models/session.model';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly api = inject(ApiService);
  private readonly http = inject(HttpClient);

  login(data: LoginRequest): Observable<TokenResponse> {
    return this.api.post<TokenResponse>('/auth/login', data);
  }

  logout(): Observable<void> {
    return this.api.post<void>('/auth/logout');
  }

  refresh(): Observable<TokenResponse> {
    return this.api.post<TokenResponse>('/auth/refresh');
  }

  me(): Observable<UserResponse> {
    return this.api.get<UserResponse>('/auth/me');
  }

  onboard(data: OnboardRequest): Observable<TokenResponse> {
    return this.api.post<TokenResponse>('/auth/onboard', data);
  }

  changePassword(data: ChangePasswordRequest): Observable<{ message: string }> {
    return this.api.post<{ message: string }>('/auth/change-password', data);
  }

  getSessions(): Observable<SessionListResponse> {
    return this.api.get<SessionListResponse>('/auth/sessions');
  }

  revokeSession(sessionId: string): Observable<void> {
    return this.api.delete<void>(`/auth/sessions/${sessionId}`);
  }

  checkHealth(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>('/health');
  }
}
