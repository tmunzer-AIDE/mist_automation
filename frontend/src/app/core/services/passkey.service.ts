import { Injectable, inject } from '@angular/core';
import { Observable, from, switchMap } from 'rxjs';
import { startRegistration, startAuthentication } from '@simplewebauthn/browser';
import { ApiService } from './api.service';
import { TokenResponse } from '../models/user.model';
import {
  PasskeyResponse,
  PasskeyListResponse,
  PasskeyRegisterBeginResponse,
  PasskeyLoginBeginResponse,
} from '../models/passkey.model';

@Injectable({ providedIn: 'root' })
export class PasskeyService {
  private readonly api = inject(ApiService);

  isSupported(): boolean {
    return typeof window !== 'undefined' && typeof window.PublicKeyCredential !== 'undefined';
  }

  register(name: string): Observable<PasskeyResponse> {
    return this.api
      .post<PasskeyRegisterBeginResponse>('/auth/passkey/register/begin')
      .pipe(
        switchMap((beginRes) =>
          from(startRegistration({ optionsJSON: beginRes.options })).pipe(
            switchMap((credential) =>
              this.api.post<PasskeyResponse>('/auth/passkey/register/complete', {
                session_id: beginRes.session_id,
                credential: JSON.stringify(credential),
                name,
              }),
            ),
          ),
        ),
      );
  }

  login(): Observable<TokenResponse> {
    return this.api
      .post<PasskeyLoginBeginResponse>('/auth/passkey/login/begin')
      .pipe(
        switchMap((beginRes) =>
          from(startAuthentication({ optionsJSON: beginRes.options })).pipe(
            switchMap((assertion) =>
              this.api.post<TokenResponse>('/auth/passkey/login/complete', {
                session_id: beginRes.session_id,
                credential: JSON.stringify(assertion),
              }),
            ),
          ),
        ),
      );
  }

  listPasskeys(): Observable<PasskeyListResponse> {
    return this.api.get<PasskeyListResponse>('/auth/passkeys');
  }

  deletePasskey(credentialId: string, password: string): Observable<void> {
    return this.api.post<void>(`/auth/passkey/${credentialId}/delete`, { password });
  }
}
