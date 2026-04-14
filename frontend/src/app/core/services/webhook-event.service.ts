import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import {
  WebhookEventDetail,
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
  ): Observable<WebhookEventListResponse> {
    const params: Record<string, string | number | boolean | undefined> = {
      skip,
      limit,
    };
    if (webhookType) params['webhook_type'] = webhookType;
    if (processed !== undefined) params['processed'] = processed;
    if (hours !== undefined) params['hours'] = hours;
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
