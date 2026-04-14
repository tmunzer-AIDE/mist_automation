import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import {
  WebhookEventDetail,
  WebhookEventListFilters,
  WebhookEventListResponse,
  WebhookStatsResponse,
} from '../models/webhook-event.model';

@Injectable({ providedIn: 'root' })
export class WebhookEventService {
  private readonly api = inject(ApiService);

  listEvents(
    skip = 0,
    limit = 100,
    webhookType?: string,
    processed?: boolean,
    hours?: number,
    filters?: WebhookEventListFilters,
  ): Observable<WebhookEventListResponse> {
    const params: Record<string, string | number | boolean | undefined> = {
      skip,
      limit,
    };
    if (webhookType) params['webhook_type'] = webhookType;
    if (processed !== undefined) params['processed'] = processed;
    if (hours !== undefined) params['hours'] = hours;
    if (filters) {
      params['webhook_topic'] = filters.webhook_topic;
      params['event_type'] = filters.event_type;
      params['org_name'] = filters.org_name;
      params['site_name'] = filters.site_name;
      params['device_name'] = filters.device_name;
      params['device_mac'] = filters.device_mac;
      params['event_details'] = filters.event_details;
    }
    return this.api.get<WebhookEventListResponse>('/webhooks/events', params);
  }

  getEvent(eventId: string): Observable<WebhookEventDetail> {
    return this.api.get<WebhookEventDetail>(`/webhooks/events/${eventId}`);
  }

  replayEvent(eventId: string): Observable<{ status: string; message: string }> {
    return this.api.post<{ status: string; message: string }>(`/webhooks/events/${eventId}/replay`);
  }

  getStats(hours = 24): Observable<WebhookStatsResponse> {
    return this.api.get<WebhookStatsResponse>('/webhooks/stats', { hours });
  }
}
