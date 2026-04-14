import { Component, DestroyRef, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe, NgClass } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { forkJoin, debounceTime, skip, Subscription } from 'rxjs';
import { BaseChartDirective } from 'ng2-charts';
import { Chart, registerables } from 'chart.js';
import type { ChartConfiguration } from 'chart.js';
import 'chartjs-adapter-date-fns';
import { TelemetryService } from '../telemetry.service';
import { TelemetryNavService } from '../telemetry-nav.service';
import { getTopicColors, getChartColor } from '../../../shared/utils/chart-defaults';
import { ToMbpsPipe } from '../../../shared/pipes/to-mbps.pipe';
import {
  ScopeSummary,
  ScopeDevices,
  APScopeSummary,
  SwitchScopeSummary,
  GatewayScopeSummary,
  BandSummary,
  AggregatePoint,
  AggregateResult,
  type ClientSiteSummary,
} from '../models';

Chart.register(...registerables);

@Component({
  selector: 'app-telemetry-site',
  standalone: true,
  imports: [
    DecimalPipe,
    NgClass,
    RouterModule,
    BaseChartDirective,
    ToMbpsPipe,
  ],
  templateUrl: './telemetry-site.component.html',
  styleUrl: './telemetry-site.component.scss',
})
export class TelemetrySiteComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly telemetryService = inject(TelemetryService);
  readonly nav = inject(TelemetryNavService);
  private readonly navTimeRange$ = toObservable(this.nav.timeRange);

  readonly siteId = signal('');
  readonly siteName = signal('');
  readonly loading = signal(false);
  readonly summary = signal<ScopeSummary | null>(null);
  readonly devices = signal<ScopeDevices | null>(null);
  readonly clientSummary = signal<ClientSiteSummary | null>(null);

  private wsSub?: Subscription;

  // Per-section charts
  readonly apClientsChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly apRadioChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly swPoeChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly swPortsChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly gwWanChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly gwSpuChart = signal<ChartConfiguration<'line'> | null>(null);

  readonly hasAP = computed(() => !!this.summary()?.ap);
  readonly hasSwitch = computed(() => !!this.summary()?.switch);
  readonly hasGateway = computed(() => !!this.summary()?.gateway);

  readonly clientBandEntries = computed(() => {
    const counts = this.clientSummary()?.band_counts ?? {};
    const bandClasses: Record<string, string> = { '24': 'band-24', '5': 'band-5', '6': 'band-6' };
    return ['24', '5', '6']
      .filter((b) => b in counts)
      .map((band) => ({
        label: band === '24' ? '2.4G' : band === '5' ? '5G' : '6G',
        count: counts[band],
        bandClass: bandClasses[band],
      }));
  });

  readonly clientBandChart = computed((): ChartConfiguration<'doughnut'> | null => {
    const s = this.clientSummary();
    if (!s) return null;
    const order = ['24', '5', '6'];
    const labels: Record<string, string> = { '24': '2.4G', '5': '5G', '6': '6G' };
    const entries = order.filter((k) => k in s.band_counts);
    if (!entries.length) return null;
    return this._buildDoughnutConfig(
      entries.map((k) => labels[k]),
      entries.map((k) => s.band_counts[k]),
    );
  });

  readonly clientProtoChart = computed((): ChartConfiguration<'doughnut'> | null => {
    const s = this.clientSummary();
    if (!s) return null;
    const entries = Object.entries(s.proto_counts ?? {}).sort((a, b) => b[1] - a[1]);
    if (!entries.length) return null;
    return this._buildDoughnutConfig(
      entries.map((e) => e[0].toUpperCase()),
      entries.map((e) => e[1]),
    );
  });

  readonly clientAuthChart = computed((): ChartConfiguration<'doughnut'> | null => {
    const s = this.clientSummary();
    if (!s) return null;
    const authLabels: Record<string, string> = { psk: 'PSK', eap: '802.1X' };
    const entries = Object.entries(s.auth_counts ?? {});
    if (!entries.length) return null;
    return this._buildDoughnutConfig(
      entries.map((e) => authLabels[e[0]] ?? e[0]),
      entries.map((e) => e[1]),
    );
  });

  get ap(): APScopeSummary | null {
    return this.summary()?.ap ?? null;
  }

  get sw(): SwitchScopeSummary | null {
    return this.summary()?.switch ?? null;
  }

  get gw(): GatewayScopeSummary | null {
    return this.summary()?.gateway ?? null;
  }

  ngOnDestroy(): void {
    this.wsSub?.unsubscribe();
  }

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id') ?? '';
      this.siteId.set(id);
      if (id) {
        this.loadData();
        this.wsSub?.unsubscribe();
        this.wsSub = this.telemetryService
          .subscribeToSite(id)
          .pipe(debounceTime(5000))
          .subscribe(() => this.refreshSummary(id));
      }
    });

    this.navTimeRange$
      .pipe(skip(1), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.loadCharts());
  }

  private refreshSummary(siteId: string): void {
    forkJoin({
      summary: this.telemetryService.getScopeSummary(siteId),
      devices: this.telemetryService.getScopeDevices(siteId),
    }).subscribe({
      next: ({ summary, devices }) => {
        this.summary.set(summary);
        this.devices.set(devices);
      },
      error: (err) => console.error('Failed to refresh telemetry site summary:', err),
    });
  }

  loadData(): void {
    const siteId = this.siteId();
    this.loading.set(true);
    forkJoin({
      summary: this.telemetryService.getScopeSummary(siteId),
      devices: this.telemetryService.getScopeDevices(siteId),
      sites: this.telemetryService.getScopeSites(),
      clientSummary: this.telemetryService.getSiteClientsSummary(siteId),
    }).subscribe({
      next: ({ summary, devices, sites, clientSummary }) => {
        this.summary.set(summary);
        this.devices.set(devices);
        this.clientSummary.set(clientSummary);
        const site = sites.sites.find((s) => s.site_id === siteId);
        this.siteName.set(site?.site_name ?? siteId);
        this.loading.set(false);
        this.loadCharts();
      },
      error: () => this.loading.set(false),
    });
  }

  bandEntries(
    bands: Record<string, BandSummary>,
  ): Array<{ band: string; label: string; avg_util_all: number }> {
    const labels: Record<string, string> = { band_24: '2.4G', band_5: '5G', band_6: '6G' };
    return Object.entries(bands).map(([band, v]) => ({
      band,
      label: labels[band] ?? band,
      avg_util_all: v.avg_util_all,
    }));
  }

  reportingBadgeClass(active: number, total: number): string {
    if (total === 0) return 'badge-neutral';
    const ratio = active / total;
    if (ratio >= 1) return 'badge-ok';
    if (ratio >= 0.5) return 'badge-warn';
    return 'badge-crit';
  }

  cpuClass(value: number): string {
    if (value > 80) return 'crit';
    if (value > 40) return 'warn';
    return '';
  }

  memClass(value: number): string {
    if (value > 90) return 'crit';
    if (value > 70) return 'warn';
    return '';
  }

  loadCharts(): void {
    const tr = this.nav.timeRange();
    const siteId = this.siteId();

    if (this.hasAP()) {
      this.telemetryService
        .queryAggregate({ measurement: 'device_summary', field: 'num_clients', agg: 'sum', timeRange: tr, siteId, deviceType: 'ap' })
        .subscribe({
          next: (r) => this.apClientsChart.set(this._buildLineChart(r, 'Clients', getChartColor('completed'))),
          error: () => this.apClientsChart.set(null),
        });
      this.telemetryService
        .queryAggregate({ measurement: 'radio_stats', field: 'util_all', agg: 'mean', timeRange: tr, siteId, groupBy: 'band' })
        .subscribe({
          next: (r) => this.apRadioChart.set(this._buildBandedLineChart(r)),
          error: () => this.apRadioChart.set(null),
        });
    }

    if (this.hasSwitch()) {
      this.telemetryService
        .queryAggregate({ measurement: 'device_summary', field: 'poe_draw_total', agg: 'sum', timeRange: tr, siteId, deviceType: 'switch' })
        .subscribe({
          next: (r) => this.swPoeChart.set(this._buildLineChart(r, 'PoE Draw (W)', getChartColor('duration'))),
          error: () => this.swPoeChart.set(null),
        });
      this.telemetryService
        .queryAggregate({ measurement: 'port_stats', field: 'speed', agg: 'count', timeRange: tr, siteId })
        .subscribe({
          next: (r) => this.swPortsChart.set(this._buildLineChart(r, 'Ports Up', getChartColor('objects'))),
          error: () => this.swPortsChart.set(null),
        });
    }

    if (this.hasGateway()) {
      forkJoin({
        tx: this.telemetryService.queryAggregate({ measurement: 'gateway_wan', field: 'tx_bytes', agg: 'sum', timeRange: tr, siteId }),
        rx: this.telemetryService.queryAggregate({ measurement: 'gateway_wan', field: 'rx_bytes', agg: 'sum', timeRange: tr, siteId }),
      }).subscribe({
        next: ({ tx, rx }) => this.gwWanChart.set(this._buildWanChart(tx, rx)),
        error: () => this.gwWanChart.set(null),
      });
      this.telemetryService
        .queryAggregate({ measurement: 'gateway_spu', field: 'spu_sessions', agg: 'mean', timeRange: tr, siteId })
        .subscribe({
          next: (r) => this.gwSpuChart.set(this._buildLineChart(r, 'SPU Sessions', getChartColor('objects'))),
          error: () => this.gwSpuChart.set(null),
        });
    }
  }

  private _buildLineChart(result: AggregateResult, label: string, color: string): ChartConfiguration<'line'> {
    return {
      type: 'line',
      data: {
        datasets: [
          {
            label,
            data: result.points.map((p) => ({ x: new Date(p._time).getTime(), y: p._value })),
            borderColor: color,
            backgroundColor: color + '22',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
            fill: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        scales: { x: { type: 'time', display: true }, y: { beginAtZero: true } },
        plugins: { legend: { display: false } },
      },
    };
  }

  private _buildWanChart(tx: AggregateResult, rx: AggregateResult): ChartConfiguration<'line'> {
    const txColor = getChartColor('objects');
    const rxColor = getChartColor('completed');
    return {
      type: 'line',
      data: {
        datasets: [
          {
            label: 'TX Mbps',
            data: tx.points.map((p) => ({ x: new Date(p._time).getTime(), y: p._value / 1_000_000 })),
            borderColor: txColor,
            backgroundColor: txColor + '22',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
          },
          {
            label: 'RX Mbps',
            data: rx.points.map((p) => ({ x: new Date(p._time).getTime(), y: p._value / 1_000_000 })),
            borderColor: rxColor,
            borderDash: [5, 3],
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        scales: { x: { type: 'time', display: true }, y: { beginAtZero: true } },
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 12 } } },
      },
    };
  }

  private _buildBandedLineChart(result: AggregateResult): ChartConfiguration<'line'> {
    const bandConfig: Record<string, { label: string; color: string }> = {
      band_24: { label: '2.4G', color: getChartColor('duration') },
      band_5: { label: '5G', color: getChartColor('completed') },
      band_6: { label: '6G', color: getChartColor('objects') },
    };

    const grouped: Record<string, AggregatePoint[]> = {};
    for (const point of result.points) {
      const band = point['band'] as string;
      if (!grouped[band]) grouped[band] = [];
      grouped[band].push(point);
    }

    const datasets = Object.entries(grouped)
      .filter(([band]) => band in bandConfig)
      .map(([band, pts]) => {
        const { label, color } = bandConfig[band];
        return {
          label,
          data: pts.map((p) => ({ x: new Date(p._time).getTime(), y: p._value })),
          borderColor: color,
          backgroundColor: color + '22',
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
        };
      });

    return {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        scales: { x: { type: 'time', display: true }, y: { beginAtZero: true, max: 100 } },
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 12 } } },
      },
    };
  }

  private _buildDoughnutConfig(labels: string[], data: number[]): ChartConfiguration<'doughnut'> {
    const colors = getTopicColors();
    return {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{ data, backgroundColor: colors.slice(0, data.length), borderWidth: 0 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        plugins: {
          legend: { position: 'bottom', labels: { boxWidth: 12, padding: 8, font: { size: 11 } } },
        },
      },
    };
  }
}
