import { Injectable, inject } from '@angular/core';
import { BehaviorSubject, Observable, tap } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';
import { SystemSettings } from '../../../core/models/admin.model';

@Injectable({ providedIn: 'root' })
export class SettingsService {
  private readonly api = inject(ApiService);
  private readonly _settings$ = new BehaviorSubject<SystemSettings | null>(null);

  readonly settings$ = this._settings$.asObservable();

  get current(): SystemSettings | null {
    return this._settings$.value;
  }

  load(): Observable<SystemSettings> {
    return this.api.get<SystemSettings>('/admin/settings').pipe(
      tap((s) => {
        this._settings$.next(s);
      }),
    );
  }

  save(updates: Record<string, unknown>): Observable<unknown> {
    return this.api.put('/admin/settings', updates);
  }
}
