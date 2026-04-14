import { Component, DestroyRef, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { Subscription, debounceTime, forkJoin, map, skip } from 'rxjs';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatTableModule } from '@angular/material/table';
import { BaseChartDirective } from 'ng2-charts';
import { Chart, registerables } from 'chart.js';
import type { ChartConfiguration } from 'chart.js';
import 'chartjs-adapter-date-fns';
import { SkeletonLoaderComponent } from '../../../shared/components/skeleton-loader/skeleton-loader.component';
import { TelemetryService } from '../telemetry.service';
import { TelemetryNavService } from '../telemetry-nav.service';
import {
  ScopeSummary,
  ScopeDevices,
  DeviceSummaryRecord,
  APScopeSummary,
  SwitchScopeSummary,
  GatewayScopeSummary,
  AggregateResult,
} from '../models';
import { getChartColor } from '../../../shared/utils/chart-defaults';

Chart.register(...registerables);

@Component({
  selector: 'app-telemetry-site-devices',
  standalone: true,
  imports: [
    DecimalPipe,
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatPaginatorModule,
    MatTableModule,
    BaseChartDirective,
    SkeletonLoaderComponent,
  ],
  templateUrl: './telemetry-site-devices.component.html',
  styleUrl: './telemetry-site-devices.component.scss',
})
export class TelemetrySiteDevicesComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly telemetryService = inject(TelemetryService);
  readonly nav = inject(TelemetryNavService);
  private readonly navTimeRange$ = toObservable(this.nav.timeRange);

  readonly siteId = signal('');
  readonly loading = signal(false);
  readonly summary = signal<ScopeSummary | null>(null);
  readonly devices = signal<ScopeDevices | null>(null);
  readonly activeType = signal<'' | 'ap' | 'switch' | 'gateway'>('');
  readonly pageIndex = signal(0);
  readonly pageSize = signal(25);

  readonly cpuChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly memoryChart = signal<ChartConfiguration<'line'> | null>(null);

  readonly searchCtrl = new FormControl('');
  private readonly searchTerm = signal('');

  private wsSub?: Subscription;

  // ── KPI getters ──────────────────────────────────────────────────────────

  get ap(): APScopeSummary | null { return this.summary()?.ap ?? null; }
  get sw(): SwitchScopeSummary | null { return this.summary()?.switch ?? null; }
  get gw(): GatewayScopeSummary | null { return this.summary()?.gateway ?? null; }

  readonly deviceCounts = computed(() => {
    const devs = this.devices()?.devices ?? [];
    return {
      ap: devs.filter((d) => d.device_type === 'ap').length,
      switch: devs.filter((d) => d.device_type === 'switch').length,
      gateway: devs.filter((d) => d.device_type === 'gateway').length,
    };
  });

  readonly typeDoughnut = computed((): ChartConfiguration<'doughnut'> | null => {
    const counts = this.deviceCounts();
    const activeType = this.activeType();
    const types = (
      activeType
        ? [activeType]
        : (['ap', 'switch', 'gateway'] as const).filter((type) => counts[type] > 0)
    ) as Array<'ap' | 'switch' | 'gateway'>;
    if (!types.length) return null;

    const labels = types.map((type) => this.typeLabel(type));
    const values = types.map((type) => counts[type]);
    const colors = types.map((type) => this.typeColor(type));

    return this.buildDoughnutChart(labels, values, colors);
  });

  readonly reportingDoughnut = computed((): ChartConfiguration<'doughnut'> | null => {
    const devs = this.filteredByType();
    if (!devs.length) return null;
    const active = devs.filter((d) => d.fresh).length;
    const stale = devs.length - active;
    return this.buildDoughnutChart(['Active', 'Stale'], [active, stale], [
      getChartColor('completed'),
      getChartColor('failed'),
    ]);
  });

  // ── Filtered device list ─────────────────────────────────────────────────

  readonly filteredByType = computed(() => {
    const type = this.activeType();
    const devs = this.devices()?.devices ?? [];
    if (!type) return devs;
    return devs.filter((d) => d.device_type === type);
  });

  readonly filteredDevices = computed(() => {
    const term = this.searchTerm().toLowerCase();
    const devs = this.filteredByType();
    return devs
      .filter(
        (d) =>
          !term ||
          d.name.toLowerCase().includes(term) ||
          d.mac.includes(term) ||
          d.model.toLowerCase().includes(term),
      )
      .sort((a, b) => (a.name || a.mac).localeCompare(b.name || b.mac));
  });

  readonly pagedDevices = computed(() => {
    const start = this.pageIndex() * this.pageSize();
    return this.filteredDevices().slice(start, start + this.pageSize());
  });

  // ── Table columns ────────────────────────────────────────────────────────

  readonly displayedColumns = ['identity', 'device_type', 'model', 'cpu_util', 'memory', 'key_metric', 'last_seen'];

  // ── Lifecycle ────────────────────────────────────────────────────────────

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id') ?? '';
      this.siteId.set(id);
      if (id) {
        this.loadData();
        this.nav.loadSiteDevices(id);
        this._subscribeWs(id);
      }
    });

    this.searchCtrl.valueChanges
      .pipe(debounceTime(200), takeUntilDestroyed(this.destroyRef))
      .subscribe((v) => {
        this.searchTerm.set(v ?? '');
        this.pageIndex.set(0);
      });

    this.navTimeRange$
      .pipe(skip(1), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.loadCharts());
  }

  ngOnDestroy(): void {
    this.wsSub?.unsubscribe();
  }

  // ── Data loading ─────────────────────────────────────────────────────────

  loadData(): void {
    const siteId = this.siteId();
    if (!siteId) return;
    this.loading.set(true);

    forkJoin({
      summary: this.telemetryService.getScopeSummary(siteId),
      devices: this.telemetryService.getScopeDevices(siteId),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ summary, devices }) => {
          this.summary.set(summary);
          this.devices.set(devices);
          this.loading.set(false);
          this.loadCharts();
          // Update nav device list too
          this.nav.loadSiteDevices(siteId);
        },
        error: () => this.loading.set(false),
      });
  }

  private _subscribeWs(siteId: string): void {
    this.wsSub?.unsubscribe();
    this.wsSub = this.telemetryService
      .subscribeToSite(siteId)
      .pipe(debounceTime(5000))
      .subscribe(() => {
        forkJoin({
          summary: this.telemetryService.getScopeSummary(siteId),
          devices: this.telemetryService.getScopeDevices(siteId),
        }).subscribe({
          next: ({ summary, devices }) => {
            this.summary.set(summary);
            this.devices.set(devices);
            this.loadCharts();
          },
        });
      });
  }

  // ── User actions ─────────────────────────────────────────────────────────

  setType(type: '' | 'ap' | 'switch' | 'gateway'): void {
    this.activeType.set(this.activeType() === type ? '' : type);
    this.pageIndex.set(0);
    this.loadCharts();
  }

  onPage(event: PageEvent): void {
    this.pageIndex.set(event.pageIndex);
    this.pageSize.set(event.pageSize);
  }

  navigateToDevice(device: DeviceSummaryRecord): void {
    this.router.navigate(['/telemetry/device', device.mac]);
  }

  formatLastSeen(ts: number | null): string {
    if (!ts) return '\u2014';
    const diff = Math.floor(Date.now() / 1000 - ts);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return `${Math.floor(diff / 3600)}h ago`;
  }

  cpuClass(value: number | null | undefined): string {
    if (value == null) return '';
    if (value > 80) return 'crit';
    if (value > 40) return 'warn';
    return '';
  }

  memoryClass(value: number | null | undefined): string {
    if (value == null) return '';
    if (value > 90) return 'crit';
    if (value > 70) return 'warn';
    return '';
  }

  keyMetricLabel(device: DeviceSummaryRecord): string {
    if (device.device_type === 'ap') {
      return `${device.num_clients ?? 0} clients`;
    }
    if (device.device_type === 'switch') {
      const up = device.ports_up;
      const total = device.ports_total;
      return up != null && total != null ? `${up}/${total} ports up` : '\u2014';
    }
    if (device.device_type === 'gateway') {
      const up = device.wan_links_up;
      const total = device.wan_links_total;
      return up != null && total != null ? `${up}/${total} WAN` : '\u2014';
    }
    return '\u2014';
  }

  typeLabel(type: string): string {
    if (type === 'ap') return 'AP';
    if (type === 'switch') return 'Switch';
    return 'Gateway';
  }

  private typeColor(type: 'ap' | 'switch' | 'gateway'): string {
    if (type === 'ap') return getChartColor('objects');
    if (type === 'switch') return getChartColor('completed');
    return getChartColor('duration');
  }

  private loadCharts(): void {
    const siteId = this.siteId();
    if (!siteId) return;

    const selected = this.activeType();
    const counts = this.deviceCounts();
    const visibleTypes = (
      selected
        ? [selected]
        : (['ap', 'switch', 'gateway'] as const).filter((type) => counts[type] > 0)
    ) as Array<'ap' | 'switch' | 'gateway'>;

    if (!visibleTypes.length) {
      this.cpuChart.set(null);
      this.memoryChart.set(null);
      return;
    }

    const cpuQueries = visibleTypes.map((type) => this.querySeries(type, 'cpu'));
    const memoryQueries = visibleTypes.map((type) => this.querySeries(type, 'memory'));

    forkJoin(cpuQueries)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((series) => this.cpuChart.set(this.buildSeriesChart(series, 'cpu')));

    forkJoin(memoryQueries)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((series) => this.memoryChart.set(this.buildSeriesChart(series, 'memory')));
  }

  private querySeries(
    type: 'ap' | 'switch' | 'gateway',
    metric: 'cpu' | 'memory',
  ) {
    const siteId = this.siteId();
    const timeRange = this.nav.timeRange();

    if (type === 'gateway') {
      const field = metric === 'cpu' ? 'cpu_idle' : 'mem_usage';
      return this.telemetryService
        .queryAggregate({
          siteId,
          measurement: 'gateway_health',
          field,
          agg: 'mean',
          timeRange,
        })
        .pipe(map((result) => ({ type, result })));
    }

    const field = metric === 'cpu' ? 'cpu_util' : 'mem_usage';
    return this.telemetryService
      .queryAggregate({
        siteId,
        measurement: 'device_summary',
        field,
        agg: 'mean',
        timeRange,
        deviceType: type,
      })
      .pipe(map((result) => ({ type, result })));
  }

  private buildSeriesChart(
    series: Array<{ type: 'ap' | 'switch' | 'gateway'; result: AggregateResult }>,
    metric: 'cpu' | 'memory',
  ): ChartConfiguration<'line'> {
    return {
      type: 'line',
      data: {
        datasets: series.map(({ type, result }) => ({
          label: this.typeLabel(type),
          data: result.points.map((point) => ({
            x: new Date(point._time).getTime(),
            y:
              metric === 'cpu' && type === 'gateway'
                ? Math.max(0, 100 - point._value)
                : point._value,
          })),
          borderColor: this.typeColor(type),
          backgroundColor: this.typeColor(type) + '22',
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        scales: {
          x: { type: 'time', display: true },
          y: { beginAtZero: true },
        },
        plugins: { legend: { position: 'bottom' } },
      },
    };
  }

  private buildDoughnutChart(
    labels: string[],
    values: number[],
    colors: string[],
  ): ChartConfiguration<'doughnut'> {
    return {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{ data: values, backgroundColor: colors, borderWidth: 0 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        plugins: { legend: { position: 'bottom' } },
      },
    };
  }
}
