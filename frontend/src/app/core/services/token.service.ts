import { Injectable } from '@angular/core';

const TOKEN_KEY = 'access_token';
const EXPIRES_KEY = 'token_expires';

@Injectable({ providedIn: 'root' })
export class TokenService {
  getToken(): string | null {
    return localStorage.getItem(TOKEN_KEY);
  }

  setToken(token: string, expiresIn: number): void {
    localStorage.setItem(TOKEN_KEY, token);
    const expiresAt = Date.now() + expiresIn * 1000;
    localStorage.setItem(EXPIRES_KEY, expiresAt.toString());
  }

  clearToken(): void {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(EXPIRES_KEY);
  }

  isTokenExpired(): boolean {
    const expiresAt = localStorage.getItem(EXPIRES_KEY);
    if (!expiresAt) return true;
    return Date.now() > parseInt(expiresAt, 10);
  }

  hasValidToken(): boolean {
    return !!this.getToken() && !this.isTokenExpired();
  }
}
