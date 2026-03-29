import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { Router } from '@angular/router';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin, debounceTime } from 'rxjs';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { BaseChartDirective } from 'ng2-charts';
import { Chart, registerables } from 'chart.js';
import type { ChartConfiguration } from 'chart.js';
import 'chartjs-adapter-date-fns';
import { TelemetryService } from '../telemetry.service';
import {
  TimeRange,
  ScopeSummary,
  ScopeSite,
  APScopeSummary,
  SwitchScopeSummary,
  GatewayScopeSummary,
  BandSummary,
  AggregateResult,
} from '../models';

Chart.register(...registerables);

@Component({
  selector: 'app-telemetry-scope',
  standalone: true,
  imports: [
    DecimalPipe,
    ReactiveFormsModule,
    MatAutocompleteModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    BaseChartDirective,
  ],
  templateUrl: './telemetry-scope.component.html',
  styleUrl: './telemetry-scope.component.scss',
})
export class TelemetryScopeComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly telemetryService = inject(TelemetryService);

  readonly timeRange = signal<TimeRange>('6h');
  readonly loading = signal(false);
  readonly summary = signal<ScopeSummary | null>(null);
  readonly sites = signal<ScopeSite[]>([]);

  readonly siteSearchCtrl = new FormControl('');
  private readonly searchTerm = signal('');
  readonly filteredSites = computed(() => {
    const term = this.searchTerm().toLowerCase();
    const all = this.sites();
    if (!term) return all;
    return all.filter((s) => s.site_name.toLowerCase().includes(term));
  });

  readonly hasAP = computed(() => !!this.summary()?.ap);
  readonly hasSwitch = computed(() => !!this.summary()?.switch);
  readonly hasGateway = computed(() => !!this.summary()?.gateway);

  readonly timeRanges: TimeRange[] = ['1h', '6h', '24h'];

  // Chart signals: AP
  readonly apCpuChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly apClientsChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly apBandChart = signal<ChartConfiguration<'line'> | null>(null);

  // Chart signals: Switch
  readonly swCpuChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly swPoeChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly swClientsChart = signal<ChartConfiguration<'line'> | null>(null);

  // Chart signals: Gateway
  readonly gwCpuChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly gwSpuChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly gwWanChart = signal<ChartConfiguration<'line'> | null>(null);

  get ap(): APScopeSummary | null {
    return this.summary()?.ap ?? null;
  }

  get sw(): SwitchScopeSummary | null {
    return this.summary()?.switch ?? null;
  }

  get gw(): GatewayScopeSummary | null {
    return this.summary()?.gateway ?? null;
  }

  ngOnInit(): void {
    this.siteSearchCtrl.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((v) => this.searchTerm.set(typeof v === 'string' ? v : ''));
    this.loadData();
    this.telemetryService
      .subscribeToOrg()
      .pipe(debounceTime(5000), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.refreshSummary());
  }

  loadData(): void {
    this.loading.set(true);
    forkJoin({
      summary: this.telemetryService.getScopeSummary(),
      sites: this.telemetryService.getScopeSites(),
    }).subscribe({
      next: ({ summary, sites }) => {
        this.summary.set(summary);
        this.sites.set(sites.sites);
        this.loading.set(false);
        this.loadCharts();
      },
      error: () => this.loading.set(false),
    });
  }

  private refreshSummary(): void {
    forkJoin({
      summary: this.telemetryService.getScopeSummary(),
      sites: this.telemetryService.getScopeSites(),
    }).subscribe({
      next: ({ summary, sites }) => {
        this.summary.set(summary);
        this.sites.set(sites.sites);
      },
    });
  }

  setTimeRange(tr: TimeRange): void {
    this.timeRange.set(tr);
    this.loadCharts();
  }

  selectSite(site: ScopeSite): void {
    this.router.navigate(['/telemetry/site', site.site_id]);
  }

  displaySiteName(site: ScopeSite | string): string {
    if (!site) return '';
    if (typeof site === 'string') return site;
    return site.site_name;
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

  reportingOk(active: number, total: number): boolean {
    return total > 0 && active === total;
  }

  loadCharts(): void {
    const tr = this.timeRange();

    if (this.hasAP()) {
      this.loadLineChart(
        { measurement: 'device_summary', field: 'cpu_util', agg: 'mean', timeRange: tr },
        { measurement: 'device_summary', field: 'mem_usage', agg: 'mean', timeRange: tr },
        'Avg CPU %',
        'Avg Memory %',
        this.apCpuChart,
      );
      this.loadSingleChart(
        { measurement: 'device_summary', field: 'num_clients', agg: 'sum', timeRange: tr },
        'Total Clients',
        this.apClientsChart,
      );
      this.loadSingleChart(
        { measurement: 'radio_stats', field: 'util_all', agg: 'mean', timeRange: tr },
        'Avg Radio Util %',
        this.apBandChart,
      );
    }

    if (this.hasSwitch()) {
      this.loadLineChart(
        { measurement: 'device_summary', field: 'cpu_util', agg: 'mean', timeRange: tr },
        { measurement: 'device_summary', field: 'mem_usage', agg: 'mean', timeRange: tr },
        'Avg CPU %',
        'Avg Memory %',
        this.swCpuChart,
      );
      this.loadSingleChart(
        { measurement: 'device_summary', field: 'poe_draw_total', agg: 'sum', timeRange: tr },
        'PoE Draw (W)',
        this.swPoeChart,
      );
      this.loadSingleChart(
        { measurement: 'device_summary', field: 'num_clients', agg: 'sum', timeRange: tr },
        'Wired Clients',
        this.swClientsChart,
      );
    }

    if (this.hasGateway()) {
      this.loadLineChart(
        { measurement: 'gateway_health', field: 'cpu_idle', agg: 'mean', timeRange: tr },
        { measurement: 'gateway_health', field: 'mem_usage', agg: 'mean', timeRange: tr },
        'Avg CPU Idle %',
        'Avg Memory %',
        this.gwCpuChart,
      );
      this.loadLineChart(
        { measurement: 'gateway_spu', field: 'spu_cpu', agg: 'mean', timeRange: tr },
        { measurement: 'gateway_spu', field: 'spu_sessions', agg: 'mean', timeRange: tr },
        'SPU CPU %',
        'SPU Sessions',
        this.gwSpuChart,
      );
      this.loadLineChart(
        { measurement: 'gateway_wan', field: 'tx_bytes', agg: 'sum', timeRange: tr },
        { measurement: 'gateway_wan', field: 'rx_bytes', agg: 'sum', timeRange: tr },
        'TX Bytes',
        'RX Bytes',
        this.gwWanChart,
      );
    }
  }

  private loadLineChart(
    params1: { measurement: string; field: string; agg: string; timeRange: TimeRange },
    params2: { measurement: string; field: string; agg: string; timeRange: TimeRange },
    label1: string,
    label2: string,
    target: ReturnType<typeof signal<ChartConfiguration<'line'> | null>>,
  ): void {
    forkJoin({
      d1: this.telemetryService.queryAggregate(params1),
      d2: this.telemetryService.queryAggregate(params2),
    }).subscribe({
      next: ({ d1, d2 }) => target.set(this.buildDualLineConfig(d1, d2, label1, label2)),
      error: () => target.set(null),
    });
  }

  private loadSingleChart(
    params: { measurement: string; field: string; agg: string; timeRange: TimeRange },
    label: string,
    target: ReturnType<typeof signal<ChartConfiguration<'line'> | null>>,
  ): void {
    this.telemetryService.queryAggregate(params).subscribe({
      next: (result) => target.set(this.buildSingleLineConfig(result, label)),
      error: () => target.set(null),
    });
  }

  private buildDualLineConfig(
    d1: AggregateResult,
    d2: AggregateResult,
    l1: string,
    l2: string,
  ): ChartConfiguration<'line'> {
    return {
      type: 'line',
      data: {
        datasets: [
          {
            label: l1,
            data: d1.points.map((p) => ({ x: new Date(p._time).getTime(), y: p._value })),
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
          },
          {
            label: l2,
            data: d2.points.map((p) => ({ x: new Date(p._time).getTime(), y: p._value })),
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
            borderDash: [5, 3],
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { type: 'time', display: true },
          y: { beginAtZero: true },
        },
        plugins: {
          legend: { position: 'bottom' },
        },
      },
    };
  }

  private buildSingleLineConfig(
    result: AggregateResult,
    label: string,
  ): ChartConfiguration<'line'> {
    return {
      type: 'line',
      data: {
        datasets: [
          {
            label,
            data: result.points.map((p) => ({ x: new Date(p._time).getTime(), y: p._value })),
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
        scales: {
          x: { type: 'time', display: true },
          y: { beginAtZero: true },
        },
        plugins: {
          legend: { position: 'bottom' },
        },
      },
    };
  }
}
