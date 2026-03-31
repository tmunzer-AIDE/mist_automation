import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { Router } from '@angular/router';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { EMPTY, Observable, Subject, debounceTime, forkJoin, map, switchMap, tap } from 'rxjs';
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
import { TopbarService } from '../../../core/services/topbar.service';
import {
  TimeRange,
  ScopeSummary,
  ScopeSite,
  APScopeSummary,
  SwitchScopeSummary,
  GatewayScopeSummary,
  BandSummary,
  AggregateResult,
  type ClientSiteSummary,
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
  private readonly topbarService = inject(TopbarService);

  readonly timeRange = signal<TimeRange>('6h');
  readonly loading = signal(false);
  readonly summary = signal<ScopeSummary | null>(null);
  readonly sites = signal<ScopeSite[]>([]);
  readonly clientSummary = signal<ClientSiteSummary | null>(null);

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

  readonly clientBandEntries = computed(() => {
    const counts = this.clientSummary()?.band_counts ?? {};
    return ['24', '5', '6']
      .filter((b) => b in counts)
      .map((band) => ({
        label: band === '24' ? '2.4G' : band === '5' ? '5G' : '6G',
        count: counts[band],
      }));
  });

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

  private readonly chartLoad$ = new Subject<void>();

  ngOnInit(): void {
    this.topbarService.setTitle('Telemetry');
    this.siteSearchCtrl.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((v) => this.searchTerm.set(typeof v === 'string' ? v : ''));

    this.chartLoad$
      .pipe(switchMap(() => this.buildChartsObservable()), takeUntilDestroyed(this.destroyRef))
      .subscribe();

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
      clientSummary: this.telemetryService.getSiteClientsSummary(),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ summary, sites, clientSummary }) => {
          this.summary.set(summary);
          this.sites.set(sites.sites);
          this.clientSummary.set(clientSummary);
          this.loading.set(false);
          this.chartLoad$.next();
        },
        error: () => this.loading.set(false),
      });
  }

  private refreshSummary(): void {
    forkJoin({
      summary: this.telemetryService.getScopeSummary(),
      sites: this.telemetryService.getScopeSites(),
      clientSummary: this.telemetryService.getSiteClientsSummary(),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ summary, sites, clientSummary }) => {
          this.summary.set(summary);
          this.sites.set(sites.sites);
          this.clientSummary.set(clientSummary);
        },
        error: (err) => console.error('Failed to refresh telemetry scope summary:', err),
      });
  }

  setTimeRange(tr: TimeRange): void {
    this.timeRange.set(tr);
    this.chartLoad$.next();
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

  private buildChartsObservable(): Observable<void> {
    const tr = this.timeRange();
    const tasks: Observable<unknown>[] = [];

    if (this.hasAP()) {
      tasks.push(
        forkJoin({
          d1: this.telemetryService.queryAggregate({
            measurement: 'device_summary',
            field: 'cpu_util',
            agg: 'mean',
            timeRange: tr,
            deviceType: 'ap',
          }),
          d2: this.telemetryService.queryAggregate({
            measurement: 'device_summary',
            field: 'mem_usage',
            agg: 'mean',
            timeRange: tr,
            deviceType: 'ap',
          }),
        }).pipe(tap(({ d1, d2 }) => this.apCpuChart.set(this.buildDualLineConfig(d1, d2, 'Avg CPU %', 'Avg Memory %')))),
        this.telemetryService
          .queryAggregate({
            measurement: 'device_summary',
            field: 'num_clients',
            agg: 'sum',
            timeRange: tr,
            deviceType: 'ap',
          })
          .pipe(tap((result) => this.apClientsChart.set(this.buildSingleLineConfig(result, 'Total Clients')))),
        this.telemetryService
          .queryAggregate({
            measurement: 'radio_stats',
            field: 'util_all',
            agg: 'mean',
            timeRange: tr,
            groupBy: 'band',
          })
          .pipe(tap((result) => this.apBandChart.set(this.buildBandLineConfig(result)))),
      );
    }

    if (this.hasSwitch()) {
      tasks.push(
        forkJoin({
          d1: this.telemetryService.queryAggregate({
            measurement: 'device_summary',
            field: 'cpu_util',
            agg: 'mean',
            timeRange: tr,
            deviceType: 'switch',
          }),
          d2: this.telemetryService.queryAggregate({
            measurement: 'device_summary',
            field: 'mem_usage',
            agg: 'mean',
            timeRange: tr,
            deviceType: 'switch',
          }),
        }).pipe(tap(({ d1, d2 }) => this.swCpuChart.set(this.buildDualLineConfig(d1, d2, 'Avg CPU %', 'Avg Memory %')))),
        this.telemetryService
          .queryAggregate({
            measurement: 'device_summary',
            field: 'poe_draw_total',
            agg: 'sum',
            timeRange: tr,
            deviceType: 'switch',
          })
          .pipe(tap((result) => this.swPoeChart.set(this.buildSingleLineConfig(result, 'PoE Draw (W)')))),
        this.telemetryService
          .queryAggregate({
            measurement: 'device_summary',
            field: 'num_clients',
            agg: 'sum',
            timeRange: tr,
            deviceType: 'switch',
          })
          .pipe(tap((result) => this.swClientsChart.set(this.buildSingleLineConfig(result, 'Wired Clients')))),
      );
    }

    if (this.hasGateway()) {
      tasks.push(
        forkJoin({
          d1: this.telemetryService.queryAggregate({
            measurement: 'gateway_health',
            field: 'cpu_idle',
            agg: 'mean',
            timeRange: tr,
          }),
          d2: this.telemetryService.queryAggregate({
            measurement: 'gateway_health',
            field: 'mem_usage',
            agg: 'mean',
            timeRange: tr,
          }),
        }).pipe(
          tap(({ d1, d2 }) => this.gwCpuChart.set(this.buildDualLineConfig(d1, d2, 'Avg CPU Idle %', 'Avg Memory %'))),
        ),
        forkJoin({
          d1: this.telemetryService.queryAggregate({
            measurement: 'gateway_spu',
            field: 'spu_cpu',
            agg: 'mean',
            timeRange: tr,
          }),
          d2: this.telemetryService.queryAggregate({
            measurement: 'gateway_spu',
            field: 'spu_sessions',
            agg: 'mean',
            timeRange: tr,
          }),
        }).pipe(tap(({ d1, d2 }) => this.gwSpuChart.set(this.buildDualLineConfig(d1, d2, 'SPU CPU %', 'SPU Sessions')))),
        forkJoin({
          d1: this.telemetryService.queryAggregate({
            measurement: 'gateway_wan',
            field: 'tx_bytes',
            agg: 'sum',
            timeRange: tr,
          }),
          d2: this.telemetryService.queryAggregate({
            measurement: 'gateway_wan',
            field: 'rx_bytes',
            agg: 'sum',
            timeRange: tr,
          }),
        }).pipe(tap(({ d1, d2 }) => this.gwWanChart.set(this.buildDualLineConfig(d1, d2, 'TX Bytes', 'RX Bytes')))),
      );
    }

    if (tasks.length === 0) return EMPTY;
    return forkJoin(tasks).pipe(
      tap({ error: () => {} }),
      map(() => undefined as void),
    );
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

  private buildBandLineConfig(result: AggregateResult): ChartConfiguration<'line'> {
    const bandLabels: Record<string, string> = { band_24: '2.4G', band_5: '5G', band_6: '6G' };
    const bandMap = new Map<string, { x: number; y: number }[]>();
    for (const point of result.points) {
      const band = (point['band'] as string) ?? 'unknown';
      if (!bandMap.has(band)) bandMap.set(band, []);
      bandMap.get(band)!.push({ x: new Date(point._time).getTime(), y: point._value });
    }
    return {
      type: 'line',
      data: {
        datasets: Array.from(bandMap.entries()).map(([band, data]) => ({
          label: bandLabels[band] ?? band,
          data,
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { type: 'time', display: true },
          y: { beginAtZero: true },
        },
        plugins: { legend: { position: 'bottom' } },
      },
    };
  }
}
