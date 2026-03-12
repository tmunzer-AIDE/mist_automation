import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { shareReplay } from 'rxjs/operators';
import { ApiService } from './api.service';
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
  private healthCache$: Observable<HealthResponse> | null = null;

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

  updateProfile(data: { timezone?: string }): Observable<UserResponse> {
    return this.api.put<UserResponse>('/auth/profile', data);
  }

  getSessions(): Observable<SessionListResponse> {
    return this.api.get<SessionListResponse>('/auth/sessions');
  }

  revokeSession(sessionId: string): Observable<void> {
    return this.api.delete<void>(`/auth/sessions/${sessionId}`);
  }

  checkHealth(): Observable<HealthResponse> {
    if (!this.healthCache$) {
      this.healthCache$ = this.api.getRaw<HealthResponse>('/health').pipe(shareReplay(1));
    }
    return this.healthCache$;
  }
}
