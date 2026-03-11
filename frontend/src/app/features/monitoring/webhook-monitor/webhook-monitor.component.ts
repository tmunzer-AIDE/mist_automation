import {
  Component,
  computed,
  DestroyRef,
  inject,
  OnDestroy,
  OnInit,
  signal,
  TemplateRef,
  ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormControl } from '@angular/forms';
import { MatTableModule } from '@angular/material/table';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription } from 'rxjs';
import { PageHeaderComponent } from '../../../shared/components/page-header/page-header.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { WebhookEventDetailDialogComponent } from '../../../shared/components/webhook-event-detail-dialog/webhook-event-detail-dialog.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { WebhookEventService } from '../../../core/services/webhook-event.service';
import { WebSocketService } from '../../../core/services/websocket.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { MonitorEvent } from '../../../core/models/webhook-event.model';

const MAX_EVENTS = 500;

interface WsMonitorMessage {
  type: 'webhook_received' | 'webhook_processed';
  data: Record<string, unknown>;
}

@Component({
  selector: 'app-webhook-monitor',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatTableModule,
    MatPaginatorModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatDialogModule,
    MatProgressBarModule,
    MatTooltipModule,
    PageHeaderComponent,
    EmptyStateComponent,
    StatusBadgeComponent,
    DateTimePipe,
  ],
  templateUrl: './webhook-monitor.component.html',
  styleUrl: './webhook-monitor.component.scss',
})
export class WebhookMonitorComponent implements OnInit, OnDestroy {
  private readonly webhookEventService = inject(WebhookEventService);
  private readonly wsService = inject(WebSocketService);
  private readonly dialog = inject(MatDialog);
  private readonly topbarService = inject(TopbarService);
  private readonly destroyRef = inject(DestroyRef);

  @ViewChild('topbarActions', { static: true }) topbarActions!: TemplateRef<unknown>;

  events = signal<MonitorEvent[]>([]);
  paused = signal(false);
  pauseBuffer = signal<MonitorEvent[]>([]);
  connected = signal(false);
  loading = signal(true);
  filterControl = new FormControl('');
  pageSize = signal(25);
  pageIndex = signal(0);

  filteredEvents = computed(() => {
    const text = (this.filterControl.value || '').toLowerCase();
    const all = this.events();
    if (!text) return all;
    return all.filter(
      (ev) =>
        ev.webhook_type?.toLowerCase().includes(text) ||
        ev.webhook_topic?.toLowerCase().includes(text) ||
        ev.event_type?.toLowerCase().includes(text) ||
        ev.org_name?.toLowerCase().includes(text) ||
        ev.site_name?.toLowerCase().includes(text) ||
        ev.device_name?.toLowerCase().includes(text) ||
        ev.device_mac?.toLowerCase().includes(text) ||
        ev.event_details?.toLowerCase().includes(text),
    );
  });

  pagedEvents = computed(() => {
    const start = this.pageIndex() * this.pageSize();
    return this.filteredEvents().slice(start, start + this.pageSize());
  });

  displayedColumns = [
    'received_at',
    'webhook_topic',
    'event_type',
    'org_name',
    'site_name',
    'device_name',
    'device_mac',
    'event_details',
    'routed_to',
    'processed',
  ];

  private wsSub: Subscription | null = null;
  private highlightTimers = new Map<string, ReturnType<typeof setTimeout>>();

  ngOnInit(): void {
    this.topbarService.setTitle('Webhook Monitor');
    this.topbarService.setActions(this.topbarActions);

    // Track filter changes to reset pagination
    this.filterControl.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
      this.pageIndex.set(0);
    });

    // Load initial data via REST
    this.webhookEventService.listEvents(0, MAX_EVENTS).subscribe({
      next: (res) => {
        this.events.set(res.events.map((ev) => ({ ...ev, isNew: false })));
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });

    // WebSocket connection status
    this.wsService.connected$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((c) => {
      this.connected.set(c);
    });

    // Subscribe to monitor channel
    this.wsSub = this.wsService.subscribe<WsMonitorMessage>('webhook:monitor').subscribe((msg) => {
      if (msg.type === 'webhook_received') {
        this.onEventReceived(msg.data as unknown as MonitorEvent);
      } else if (msg.type === 'webhook_processed') {
        this.onEventProcessed(msg.data as Record<string, unknown>);
      }
    });
  }

  ngOnDestroy(): void {
    this.wsSub?.unsubscribe();
    this.topbarService.clearActions();
    for (const timer of this.highlightTimers.values()) {
      clearTimeout(timer);
    }
  }

  private onEventReceived(ev: MonitorEvent): void {
    ev.isNew = true;

    if (this.paused()) {
      this.pauseBuffer.update((buf) => [ev, ...buf]);
      return;
    }

    this.events.update((list) => [ev, ...list].slice(0, MAX_EVENTS));

    // Clear highlight after 3s
    this.highlightTimers.set(
      ev.id,
      setTimeout(() => {
        this.events.update((list) =>
          list.map((e) => (e.id === ev.id ? { ...e, isNew: false } : e)),
        );
        this.highlightTimers.delete(ev.id);
      }, 3000),
    );
  }

  private onEventProcessed(data: Record<string, unknown>): void {
    const id = data['id'] as string;
    if (!id) return;
    this.events.update((list) =>
      list.map((ev) =>
        ev.id === id
          ? {
              ...ev,
              processed: true,
              matched_workflows: (data['matched_workflows'] as string[]) || ev.matched_workflows,
              executions_triggered:
                (data['executions_triggered'] as string[]) || ev.executions_triggered,
              processed_at: (data['processed_at'] as string) || ev.processed_at,
            }
          : ev,
      ),
    );
  }

  togglePause(): void {
    const wasPaused = this.paused();
    this.paused.set(!wasPaused);

    if (wasPaused) {
      // Flush buffer
      const buffered = this.pauseBuffer();
      if (buffered.length > 0) {
        this.events.update((list) => [...buffered, ...list].slice(0, MAX_EVENTS));
        this.pauseBuffer.set([]);
      }
    }
  }

  clearEvents(): void {
    this.events.set([]);
    this.pauseBuffer.set([]);
    this.pageIndex.set(0);
  }

  onPage(event: PageEvent): void {
    this.pageIndex.set(event.pageIndex);
    this.pageSize.set(event.pageSize);
  }

  openEventDetail(ev: MonitorEvent): void {
    this.dialog.open(WebhookEventDetailDialogComponent, {
      width: '800px',
      maxHeight: '90vh',
      data: { eventId: ev.id },
    });
  }

  getStatusClass(code: number): string {
    if (code >= 200 && code < 300) return 'status-ok';
    if (code >= 400 && code < 500) return 'status-client-error';
    if (code >= 500) return 'status-server-error';
    return '';
  }
}
