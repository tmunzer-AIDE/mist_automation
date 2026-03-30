import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '../../core/services/api.service';

export interface ScheduleWindow {
  days: number[];
  start: string;
  end: string;
}

export interface PowerSchedule {
  id: string;
  site_id: string;
  site_name: string;
  timezone: string;
  windows: ScheduleWindow[];
  off_profile_id: string;
  grace_period_minutes: number;
  neighbor_rssi_threshold_dbm: number;
  roam_rssi_threshold_dbm: number;
  critical_ap_macs: string[];
  enabled: boolean;
  current_status: 'IDLE' | 'OFF_HOURS' | 'TRANSITIONING_OFF' | 'TRANSITIONING_ON';
}

export interface ScheduleStatus {
  site_id: string;
  status: string;
  disabled_ap_count: number;
  pending_disable_count: number;
  client_ap_count: number;
}

export interface ScheduleLog {
  id: string;
  site_id: string;
  timestamp: string;
  event_type: string;
  ap_mac: string | null;
  details: Record<string, unknown>;
}

export interface CreateScheduleRequest {
  site_name: string;
  windows: ScheduleWindow[];
  grace_period_minutes: number;
  neighbor_rssi_threshold_dbm: number;
  roam_rssi_threshold_dbm: number;
  critical_ap_macs: string[];
  enabled: boolean;
}

@Injectable({ providedIn: 'root' })
export class PowerSchedulingService {
  private readonly api = inject(ApiService);

  listSchedules(): Observable<PowerSchedule[]> {
    return this.api.get<PowerSchedule[]>('/power-scheduling/sites');
  }

  createSchedule(siteId: string, body: CreateScheduleRequest): Observable<PowerSchedule> {
    return this.api.post<PowerSchedule>(`/power-scheduling/sites/${siteId}`, body);
  }

  updateSchedule(siteId: string, body: CreateScheduleRequest): Observable<PowerSchedule> {
    return this.api.put<PowerSchedule>(`/power-scheduling/sites/${siteId}`, body);
  }

  deleteSchedule(siteId: string): Observable<void> {
    return this.api.delete<void>(`/power-scheduling/sites/${siteId}`);
  }

  getStatus(siteId: string): Observable<ScheduleStatus> {
    return this.api.get<ScheduleStatus>(`/power-scheduling/sites/${siteId}/status`);
  }

  getLogs(
    siteId: string,
    params?: { limit?: number; skip?: number; event_type?: string },
  ): Observable<ScheduleLog[]> {
    return this.api.get<ScheduleLog[]>(`/power-scheduling/sites/${siteId}/logs`, params);
  }

  trigger(siteId: string, action: 'start' | 'end'): Observable<{ status: string }> {
    return this.api.post<{ status: string }>(`/power-scheduling/sites/${siteId}/trigger`, {
      action,
    });
  }
}
