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
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription } from 'rxjs';
import { BaseChartDirective } from 'ng2-charts';
import { ChartConfiguration } from 'chart.js/auto';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { WebhookEventDetailDialogComponent } from '../../../shared/components/webhook-event-detail-dialog/webhook-event-detail-dialog.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { WebhookEventService } from '../../../core/services/webhook-event.service';
import { WebSocketService } from '../../../core/services/websocket.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { MonitorEvent } from '../../../core/models/webhook-event.model';
import { barDataset, getChartGridColor } from '../../../shared/utils/chart-defaults';

const MAX_EVENTS = 500;

const TOPIC_COLORS = [
  '#2563eb',
  '#8b5cf6',
  '#ef4444',
  '#f59e0b',
  '#10b981',
  '#ec4899',
  '#06b6d4',
  '#84cc16',
  '#f97316',
  '#6366f1',
];

interface WsMonitorMessage {
  type: 'webhook_received' | 'webhook_processed';
  data: Record<string, unknown>;
}

interface ChartRange {
  label: string;
  hours: number;
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
    MatProgressSpinnerModule,
    MatTooltipModule,
    MatAutocompleteModule,
    BaseChartDirective,
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
  pageSize = signal(25);
  pageIndex = signal(0);

  // ── Filters ──────────────────────────────────────────────────────────
  topicFilter = new FormControl('');
  eventTypeFilter = new FormControl('');
  orgFilter = new FormControl('');
  siteFilter = new FormControl('');
  deviceFilter = new FormControl('');
  macFilter = new FormControl('');
  detailsFilter = new FormControl('');

  // Signal bridges for reactivity
  private topicValue = signal('');
  private eventTypeValue = signal('');
  private orgValue = signal('');
  private siteValue = signal('');
  private deviceValue = signal('');
  private macValue = signal('');
  private detailsValue = signal('');

  // Unique values for autocomplete
  topicOptions = computed(() => this.uniqueFiltered(this.events(), 'webhook_topic', this.topicValue()));
  eventTypeOptions = computed(() =>
    this.uniqueFiltered(this.events(), 'event_type', this.eventTypeValue()),
  );
  orgOptions = computed(() => this.uniqueFiltered(this.events(), 'org_name', this.orgValue()));
  siteOptions = computed(() => this.uniqueFiltered(this.events(), 'site_name', this.siteValue()));
  deviceOptions = computed(() =>
    this.uniqueFiltered(this.events(), 'device_name', this.deviceValue()),
  );
  macOptions = computed(() => this.uniqueFiltered(this.events(), 'device_mac', this.macValue()));

  filteredEvents = computed(() => {
    const topic = this.topicValue().toLowerCase();
    const eventType = this.eventTypeValue().toLowerCase();
    const org = this.orgValue().toLowerCase();
    const site = this.siteValue().toLowerCase();
    const device = this.deviceValue().toLowerCase();
    const mac = this.macValue().toLowerCase();
    const details = this.detailsValue().toLowerCase();

    return this.events().filter((ev) => {
      if (topic && !ev.webhook_topic?.toLowerCase().includes(topic)) return false;
      if (eventType && !ev.event_type?.toLowerCase().includes(eventType)) return false;
      if (org && !ev.org_name?.toLowerCase().includes(org)) return false;
      if (site && !ev.site_name?.toLowerCase().includes(site)) return false;
      if (device && !ev.device_name?.toLowerCase().includes(device)) return false;
      if (mac && !ev.device_mac?.toLowerCase().includes(mac)) return false;
      if (details && !ev.event_details?.toLowerCase().includes(details)) return false;
      return true;
    });
  });

  pagedEvents = computed(() => {
    const start = this.pageIndex() * this.pageSize();
    return this.filteredEvents().slice(start, start + this.pageSize());
  });

  // ── Chart ────────────────────────────────────────────────────────────
  chartConfig = signal<ChartConfiguration<'bar'> | null>(null);
  chartHours = signal(24);
  chartLoading = signal(false);
  chartRanges: ChartRange[] = [
    { label: '24h', hours: 24 },
    { label: '7d', hours: 168 },
    { label: '14d', hours: 336 },
    { label: '30d', hours: 720 },
  ];

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

    // Wire filter FormControls → signals
    this.wireFilter(this.topicFilter, this.topicValue);
    this.wireFilter(this.eventTypeFilter, this.eventTypeValue);
    this.wireFilter(this.orgFilter, this.orgValue);
    this.wireFilter(this.siteFilter, this.siteValue);
    this.wireFilter(this.deviceFilter, this.deviceValue);
    this.wireFilter(this.macFilter, this.macValue);
    this.wireFilter(this.detailsFilter, this.detailsValue);

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

    // Load chart
    this.loadChart();
  }

  ngOnDestroy(): void {
    this.wsSub?.unsubscribe();
    this.topbarService.clearActions();
    for (const timer of this.highlightTimers.values()) {
      clearTimeout(timer);
    }
  }

  private wireFilter(control: FormControl<string | null>, sig: ReturnType<typeof signal<string>>): void {
    control.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((v) => {
      sig.set(v || '');
      this.pageIndex.set(0);
    });
  }

  private uniqueFiltered(
    events: MonitorEvent[],
    field: keyof MonitorEvent,
    typed: string,
  ): string[] {
    const unique = new Set<string>();
    for (const ev of events) {
      const val = ev[field];
      if (typeof val === 'string' && val) unique.add(val);
    }
    const arr = Array.from(unique).sort();
    if (!typed) return arr;
    const lower = typed.toLowerCase();
    return arr.filter((v) => v.toLowerCase().includes(lower));
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

  selectChartRange(hours: number): void {
    this.chartHours.set(hours);
    this.loadChart();
  }

  loadChart(): void {
    this.chartLoading.set(true);
    this.webhookEventService.getStats(this.chartHours()).subscribe({
      next: (stats) => {
        const labels = stats.buckets.map((b) => b.bucket);

        // Collect all unique topics
        const topicSet = new Set<string>();
        for (const b of stats.buckets) {
          for (const t of Object.keys(b.by_topic)) topicSet.add(t);
        }
        const topics = Array.from(topicSet).sort();

        const datasets = topics.map((topic, i) =>
          barDataset(
            topic,
            stats.buckets.map((b) => b.by_topic[topic] || 0),
            TOPIC_COLORS[i % TOPIC_COLORS.length],
            'webhooks',
          ),
        );

        this.chartConfig.set({
          type: 'bar',
          data: { labels, datasets },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: true, position: 'bottom' } },
            scales: {
              x: {
                stacked: true,
                grid: { display: false },
                ticks: { maxTicksLimit: 15, font: { size: 10 } },
              },
              y: {
                stacked: true,
                beginAtZero: true,
                grid: { color: getChartGridColor() },
                ticks: { precision: 0, font: { size: 10 } },
              },
            },
          },
        });
        this.chartLoading.set(false);
      },
      error: () => this.chartLoading.set(false),
    });
  }

  getStatusClass(code: number): string {
    if (code >= 200 && code < 300) return 'status-ok';
    if (code >= 400 && code < 500) return 'status-client-error';
    if (code >= 500) return 'status-server-error';
    return '';
  }
}
