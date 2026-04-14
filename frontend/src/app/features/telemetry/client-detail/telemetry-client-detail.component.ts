import { Component, DestroyRef, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe, DatePipe, NgClass } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { Subscription, forkJoin, skip } from 'rxjs';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatIconModule } from '@angular/material/icon';
import { BaseChartDirective } from 'ng2-charts';
import { Chart, registerables } from 'chart.js';
import type { ChartConfiguration } from 'chart.js';
import 'chartjs-adapter-date-fns';
import { TelemetryService, TIME_RANGE_MAP } from '../telemetry.service';
import { TelemetryNavService } from '../telemetry-nav.service';
import { getChartColor } from '../../../shared/utils/chart-defaults';
import type { ClientStatRecord, ClientLiveEvent, RangeResult } from '../models';

Chart.register(...registerables);

@Component({
  selector: 'app-telemetry-client-detail',
  standalone: true,
  imports: [
    DecimalPipe,
    DatePipe,
    NgClass,
    MatButtonModule,
    MatButtonToggleModule,
    MatExpansionModule,
    MatIconModule,
    BaseChartDirective,
  ],
  templateUrl: './telemetry-client-detail.component.html',
  styleUrl: './telemetry-client-detail.component.scss',
})
export class TelemetryClientDetailComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly telemetryService = inject(TelemetryService);
  readonly nav = inject(TelemetryNavService);
  private readonly navTimeRange$ = toObservable(this.nav.timeRange);

  readonly mac = signal('');
  readonly siteId = signal('');
  readonly loading = signal(false);
  readonly client = signal<ClientStatRecord | null>(null);
  readonly rssiChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly bpsChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly liveEvents = signal<ClientLiveEvent[]>([]);
  readonly viewMode = signal<'formatted' | 'raw'>('formatted');
  readonly expandedRows = signal<Set<number>>(new Set());

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

  // AP display: use ap_mac for now (AP name resolution is a future enhancement)
  readonly apName = computed(() => this.client()?.ap_mac || '');

  readonly lastEventAge = computed(() => {
    const events = this.liveEvents();
    if (!events.length) return '';
    const diffSec = Math.floor(Date.now() / 1000 - events[0].timestamp);
    if (diffSec < 60) return `${diffSec}s ago`;
    return `${Math.floor(diffSec / 60)}m ago`;
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

    this.navTimeRange$
      .pipe(skip(1), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this._loadCharts());
  }

  ngOnDestroy(): void {
    this.wsSub?.unsubscribe();
  }

  setViewMode(mode: 'formatted' | 'raw'): void {
    this.viewMode.set(mode);
    this.expandedRows.set(new Set());
  }

  toggleExpand(index: number): void {
    this.expandedRows.update((s) => {
      const next = new Set(s);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  isExpanded(index: number): boolean {
    return this.expandedRows().has(index);
  }

  formatJson(value: unknown): string {
    return JSON.stringify(value, null, 2);
  }

  rssiClass(rssi: number | null | undefined): string {
    if (rssi == null) return '';
    if (rssi > -60) return 'ok';
    if (rssi >= -75) return 'warn';
    return 'crit';
  }

  snrClass(snr: number | null | undefined): string {
    if (snr == null) return '';
    if (snr > 25) return 'ok';
    if (snr >= 15) return 'warn';
    return 'crit';
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
          const site = sites.sites.find((s) => s.site_id === siteId);
          this.nav.setDetailContext({
            title: client.hostname || client.mac,
            kind: 'client',
            stale: !client.fresh,
            siteId,
            siteName: site?.site_name || siteId,
          });
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

    const tr = this.nav.timeRange();
    const start = TIME_RANGE_MAP[tr];
    const end = 'now()';

    this.telemetryService
      .queryClientRange(mac, siteId, start, end)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((result: RangeResult) => {
        this.rssiChart.set(this._buildChart(result.points, 'rssi', 'RSSI (dBm)', getChartColor('duration')));
        this.bpsChart.set(this._buildThroughputChart(result.points));
      });
  }

  private _buildChart(
    points: Record<string, unknown>[],
    field: string,
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
              y: p[field] as number,
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
        animation: { duration: 0 },
        plugins: { legend: { display: false } },
        scales: { x: { type: 'time', display: true }, y: { beginAtZero: false } },
      },
    };
  }

  private _buildThroughputChart(points: Record<string, unknown>[]): ChartConfiguration<'line'> {
    const txColor = getChartColor('objects');
    const rxColor = getChartColor('completed');
    return {
      type: 'line',
      data: {
        datasets: [
          {
            label: 'TX Mbps',
            data: points.map((p) => ({
              x: new Date(p['_time'] as string).getTime(),
              y: ((p['tx_bps'] as number) || 0) / 1_000_000,
            })),
            borderColor: txColor,
            backgroundColor: txColor + '20',
            borderWidth: 2,
            tension: 0.3,
            pointRadius: 0,
          },
          {
            label: 'RX Mbps',
            data: points.map((p) => ({
              x: new Date(p['_time'] as string).getTime(),
              y: ((p['rx_bps'] as number) || 0) / 1_000_000,
            })),
            borderColor: rxColor,
            borderDash: [5, 3],
            borderWidth: 2,
            tension: 0.3,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        plugins: { legend: { position: 'bottom' } },
        scales: { x: { type: 'time', display: true }, y: { beginAtZero: true } },
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
