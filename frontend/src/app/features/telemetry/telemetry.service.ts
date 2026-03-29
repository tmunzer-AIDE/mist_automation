import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { WebSocketService } from '../../core/services/websocket.service';
import {
  ScopeSummary,
  ScopeDevices,
  LatestStats,
  AggregateResult,
  DeviceLiveEvent,
  TimeRange,
} from './models';

const TIME_RANGE_MAP: Record<TimeRange, string> = { '1h': '-1h', '6h': '-6h', '24h': '-24h' };
const WINDOW_MAP: Record<TimeRange, string> = { '1h': '2m', '6h': '10m', '24h': '30m' };

@Injectable({ providedIn: 'root' })
export class TelemetryService {
  private readonly api = inject(ApiService);
  private readonly ws = inject(WebSocketService);

  getScopeSummary(siteId?: string): Observable<ScopeSummary> {
    const params: Record<string, string> = {};
    if (siteId) params['site_id'] = siteId;
    return this.api.get<ScopeSummary>('/telemetry/scope/summary', params);
  }

  getScopeDevices(siteId?: string): Observable<ScopeDevices> {
    const params: Record<string, string> = {};
    if (siteId) params['site_id'] = siteId;
    return this.api.get<ScopeDevices>('/telemetry/scope/devices', params);
  }

  getLatestStats(mac: string): Observable<LatestStats> {
    return this.api.get<LatestStats>(`/telemetry/latest/${mac}`);
  }

  queryAggregate(params: {
    siteId?: string;
    orgId?: string;
    measurement: string;
    field: string;
    agg?: string;
    timeRange: TimeRange;
  }): Observable<AggregateResult> {
    const p: Record<string, string> = {
      measurement: params.measurement,
      field: params.field,
      agg: params.agg ?? 'mean',
      window: WINDOW_MAP[params.timeRange],
      start: TIME_RANGE_MAP[params.timeRange],
    };
    if (params.siteId) p['site_id'] = params.siteId;
    if (params.orgId) p['org_id'] = params.orgId;
    return this.api.get<AggregateResult>('/telemetry/query/aggregate', p);
  }

  subscribeToDevice(mac: string): Observable<DeviceLiveEvent> {
    return this.ws.subscribe<DeviceLiveEvent>(`telemetry:device:${mac}`);
  }
}
