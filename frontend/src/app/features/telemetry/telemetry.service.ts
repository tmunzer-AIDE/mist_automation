import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { WebSocketService } from '../../core/services/websocket.service';
import {
  ScopeSummary,
  ScopeDevices,
  ScopeSites,
  LatestStats,
  AggregateResult,
  RangeResult,
  DeviceLiveEvent,
  TimeRange,
} from './models';

export const TIME_RANGE_MAP: Record<TimeRange, string> = { '1h': '-1h', '6h': '-6h', '24h': '-24h' };
export const WINDOW_MAP: Record<TimeRange, string> = { '1h': '2m', '6h': '10m', '24h': '30m' };

@Injectable({ providedIn: 'root' })
export class TelemetryService {
  private readonly api = inject(ApiService);
  private readonly ws = inject(WebSocketService);

  getScopeSites(): Observable<ScopeSites> {
    return this.api.get<ScopeSites>('/telemetry/scope/sites');
  }

  getScopeSummary(siteId?: string): Observable<ScopeSummary> {
    const params: Record<string, string> = {};
    if (siteId) params['site_id'] = siteId;
    return this.api.get<ScopeSummary>('/telemetry/scope/summary', params);
  }

  getScopeDevices(siteId?: string, deviceType?: string): Observable<ScopeDevices> {
    const params: Record<string, string> = {};
    if (siteId) params['site_id'] = siteId;
    if (deviceType) params['device_type'] = deviceType;
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

  queryRange(mac: string, measurement: string, start: string, end: string): Observable<RangeResult> {
    return this.api.get<RangeResult>('/telemetry/query/range', { mac, measurement, start, end });
  }

  subscribeToDevice(mac: string): Observable<DeviceLiveEvent> {
    return this.ws.subscribe<DeviceLiveEvent>(`telemetry:device:${mac}`);
  }
}
