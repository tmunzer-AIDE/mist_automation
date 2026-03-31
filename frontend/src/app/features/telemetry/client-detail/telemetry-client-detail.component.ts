import {
  Component,
  DestroyRef,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { DecimalPipe, DatePipe } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription, forkJoin } from 'rxjs';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { BaseChartDirective } from 'ng2-charts';
import { Chart, registerables } from 'chart.js';
import type { ChartConfiguration } from 'chart.js';
import 'chartjs-adapter-date-fns';
import { TelemetryService, TIME_RANGE_MAP } from '../telemetry.service';
import { getChartColor } from '../../../shared/utils/chart-defaults';
import type { ClientStatRecord, ClientLiveEvent, RangeResult, ScopeSite, TimeRange } from '../models';

Chart.register(...registerables);

@Component({
  selector: 'app-telemetry-client-detail',
  standalone: true,
  imports: [
    DecimalPipe,
    DatePipe,
    RouterModule,
    MatButtonModule,
    MatButtonToggleModule,
    MatIconModule,
    MatProgressBarModule,
    BaseChartDirective,
  ],
  templateUrl: './telemetry-client-detail.component.html',
  styleUrl: './telemetry-client-detail.component.scss',
})
export class TelemetryClientDetailComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly telemetryService = inject(TelemetryService);

  readonly mac = signal('');
  readonly siteId = signal('');
  readonly siteName = signal('');
  readonly loading = signal(false);
  readonly client = signal<ClientStatRecord | null>(null);
  readonly timeRange = signal<TimeRange>('1h');
  readonly rssiChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly bpsChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly liveEvents = signal<ClientLiveEvent[]>([]);
  readonly viewMode = signal<'formatted' | 'raw'>('formatted');
  readonly expandedRows = signal<Set<number>>(new Set());

  readonly timeRanges: TimeRange[] = ['1h', '6h', '24h'];

  readonly displayName = computed(() => this.client()?.hostname || this.mac());
  readonly bandLabel = computed(() => {
    const b = this.client()?.band;
    return b === '24' ? '2.4G' : b === '5' ? '5G' : b === '6' ? '6G' : b || '—';
  });
  readonly uptimeFormatted = computed(() => {
    const u = this.client()?.uptime ?? 0;
    const h = Math.floor(u / 3600);
    const m = Math.floor((u % 3600) / 60);
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  });

  private wsSub?: Subscription;

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const mac = params.get('mac') ?? '';
      const siteId = params.get('id') ?? '';
      this.mac.set(mac);
      this.siteId.set(siteId);
      this._loadClient();
      this._subscribeClientWs(mac);
    });
  }

  ngOnDestroy(): void {
    this.wsSub?.unsubscribe();
  }

  setTimeRange(tr: TimeRange): void {
    this.timeRange.set(tr);
    this._loadCharts();
  }

  setViewMode(mode: 'formatted' | 'raw'): void {
    this.viewMode.set(mode);
    this.expandedRows.set(new Set());
  }

  toggleExpand(index: number): void {
    this.expandedRows.update((s) => {
      const next = new Set(s);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }

  isExpanded(index: number): boolean {
    return this.expandedRows().has(index);
  }

  formatJson(value: unknown): string {
    return JSON.stringify(value, null, 2);
  }

  private _loadClient(): void {
    const mac = this.mac();
    const siteId = this.siteId();
    if (!mac || !siteId) return;
    this.loading.set(true);

    forkJoin({
      client: this.telemetryService.getClient(mac, siteId),
      sites: this.telemetryService.getScopeSites(),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ client, sites }) => {
          this.client.set(client);
          const site = sites.sites.find((s: ScopeSite) => s.site_id === siteId);
          if (site) this.siteName.set(site.site_name);
          this.loading.set(false);
          this._loadCharts();
        },
        error: () => this.loading.set(false),
      });
  }

  private _loadCharts(): void {
    const mac = this.mac();
    const siteId = this.siteId();
    if (!mac || !siteId) return;

    const tr = this.timeRange();
    const start = TIME_RANGE_MAP[tr];
    const end = 'now()';

    this.telemetryService
      .queryClientRange(mac, siteId, start, end)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((result: RangeResult) => {
        const rssiPoints = result.points.filter((p) => p['_field'] === 'rssi');
        const bpsPoints = result.points.filter((p) => p['_field'] === 'tx_bps');
        this.rssiChart.set(this._buildChart(rssiPoints, 'RSSI (dBm)', getChartColor('duration')));
        this.bpsChart.set(this._buildChart(bpsPoints, 'TX bps', getChartColor('objects')));
      });
  }

  private _buildChart(
    points: Record<string, unknown>[],
    label: string,
    color: string,
  ): ChartConfiguration<'line'> {
    return {
      type: 'line',
      data: {
        datasets: [
          {
            label,
            data: points.map((p) => ({
              x: new Date(p['_time'] as string).getTime(),
              y: p['_value'] as number,
            })),
            borderColor: color,
            backgroundColor: color + '22',
            borderWidth: 2,
            tension: 0.3,
            pointRadius: 0,
            fill: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { type: 'time', display: true },
          y: { beginAtZero: false },
        },
      },
    };
  }

  private _subscribeClientWs(mac: string): void {
    this.wsSub?.unsubscribe();
    this.liveEvents.set([]);
    this.wsSub = this.telemetryService
      .subscribeToClient(mac)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((event) => {
        this.liveEvents.update((prev) => {
          const next = [event, ...prev];
          return next.length > 100 ? next.slice(0, 100) : next;
        });
      });
  }
}
