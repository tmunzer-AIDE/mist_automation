import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { SystemHealth } from '../models/admin.model';

@Injectable({ providedIn: 'root' })
export class AdminService {
  private readonly api = inject(ApiService);

  getSystemHealth(): Observable<SystemHealth> {
    return this.api.get<SystemHealth>('/admin/system-health');
  }
}
