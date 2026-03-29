import { Component, DestroyRef, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe, DatePipe, TitleCasePipe } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin, debounceTime, Subscription } from 'rxjs';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { BaseChartDirective } from 'ng2-charts';
import { Chart, registerables } from 'chart.js';
import type { ChartConfiguration } from 'chart.js';
import 'chartjs-adapter-date-fns';
import { TelemetryService } from '../telemetry.service';
import {
  TimeRange,
  ScopeSummary,
  ScopeDevices,
  DeviceSummaryRecord,
  APScopeSummary,
  SwitchScopeSummary,
  GatewayScopeSummary,
  BandSummary,
  AggregateResult,
} from '../models';

Chart.register(...registerables);

@Component({
  selector: 'app-telemetry-site',
  standalone: true,
  imports: [
    DecimalPipe,
    DatePipe,
    TitleCasePipe,
    ReactiveFormsModule,
    RouterModule,
    MatAutocompleteModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatTableModule,
    BaseChartDirective,
  ],
  templateUrl: './telemetry-site.component.html',
  styleUrl: './telemetry-site.component.scss',
})
export class TelemetrySiteComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly telemetryService = inject(TelemetryService);

  readonly siteId = signal('');
  readonly siteName = signal('');
  readonly timeRange = signal<TimeRange>('6h');
  readonly loading = signal(false);
  readonly summary = signal<ScopeSummary | null>(null);
  readonly devices = signal<ScopeDevices | null>(null);
  readonly activeDeviceType = signal('');

  private wsSub?: Subscription;

  readonly deviceSearchCtrl = new FormControl('');
  private readonly searchTerm = signal('');

  readonly timeRanges: TimeRange[] = ['1h', '6h', '24h'];

  readonly deviceColumns = ['name', 'device_type', 'model', 'cpu_util', 'num_clients', 'last_seen'];

  // Chart signals
  readonly cpuChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly chart2 = signal<ChartConfiguration<'line'> | null>(null);
  readonly chart3 = signal<ChartConfiguration<'line'> | null>(null);

  readonly hasAP = computed(() => !!this.summary()?.ap);
  readonly hasSwitch = computed(() => !!this.summary()?.switch);
  readonly hasGateway = computed(() => !!this.summary()?.gateway);

  readonly deviceCounts = computed(() => {
    const devs = this.devices()?.devices ?? [];
    const counts = { ap: 0, switch: 0, gateway: 0 };
    for (const d of devs) {
      if (d.device_type === 'ap') counts.ap++;
      else if (d.device_type === 'switch') counts.switch++;
      else if (d.device_type === 'gateway') counts.gateway++;
    }
    return counts;
  });

  readonly filteredDevices = computed(() => {
    const term = this.searchTerm().toLowerCase();
    const all = this.devices()?.devices ?? [];
    if (!term) return all;
    return all.filter(
      (d) =>
        d.name.toLowerCase().includes(term) ||
        d.model.toLowerCase().includes(term) ||
        d.mac.toLowerCase().includes(term),
    );
  });

  readonly displayedDevices = computed(() => {
    const type = this.activeDeviceType();
    const devs = this.filteredDevices();
    if (!type) return devs;
    return devs.filter((d) => d.device_type === type);
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
    this.deviceSearchCtrl.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((v) => this.searchTerm.set(typeof v === 'string' ? v : ''));

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
  }

  private refreshSummary(siteId: string): void {
    forkJoin({
      summary: this.telemetryService.getScopeSummary(siteId),
      devices: this.telemetryService.getScopeDevices(siteId, this.activeDeviceType() || undefined),
    }).subscribe({
      next: ({ summary, devices }) => {
        this.summary.set(summary);
        this.devices.set(devices);
      },
      error: () => {},
    });
  }

  loadData(): void {
    const siteId = this.siteId();
    this.loading.set(true);
    forkJoin({
      summary: this.telemetryService.getScopeSummary(siteId),
      devices: this.telemetryService.getScopeDevices(siteId),
      sites: this.telemetryService.getScopeSites(),
    }).subscribe({
      next: ({ summary, devices, sites }) => {
        this.summary.set(summary);
        this.devices.set(devices);
        const site = sites.sites.find((s) => s.site_id === siteId);
        this.siteName.set(site?.site_name ?? siteId);
        this.loading.set(false);
        this.loadCharts();
      },
      error: () => this.loading.set(false),
    });
  }

  toggleDeviceType(type: string): void {
    this.activeDeviceType.set(this.activeDeviceType() === type ? '' : type);
    this.loadCharts();
  }

  setTimeRange(tr: TimeRange): void {
    this.timeRange.set(tr);
    this.loadCharts();
  }

  navigateToDevice(mac: string): void {
    this.router.navigate(['/telemetry/device', mac]);
  }

  selectDevice(device: DeviceSummaryRecord): void {
    this.navigateToDevice(device.mac);
  }

  displayDeviceName(device: DeviceSummaryRecord | string): string {
    if (!device) return '';
    if (typeof device === 'string') return device;
    return device.name || device.mac;
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
    const siteId = this.siteId();
    const active = this.activeDeviceType();

    // Determine which type to chart: explicit selection, or first available
    const chartType =
      active || (this.hasAP() ? 'ap' : this.hasSwitch() ? 'switch' : this.hasGateway() ? 'gateway' : '');

    this.cpuChart.set(null);
    this.chart2.set(null);
    this.chart3.set(null);

    if (chartType === 'ap') {
      this.loadLineChart(
        { measurement: 'device_summary', field: 'cpu_util', agg: 'mean', timeRange: tr, siteId },
        { measurement: 'device_summary', field: 'mem_usage', agg: 'mean', timeRange: tr, siteId },
        'Avg CPU %',
        'Avg Memory %',
        this.cpuChart,
      );
      this.loadSingleChart(
        { measurement: 'device_summary', field: 'num_clients', agg: 'sum', timeRange: tr, siteId },
        'Total Clients',
        this.chart2,
      );
      this.loadSingleChart(
        { measurement: 'radio_stats', field: 'util_all', agg: 'mean', timeRange: tr, siteId },
        'Avg Radio Util %',
        this.chart3,
      );
    } else if (chartType === 'switch') {
      this.loadLineChart(
        { measurement: 'device_summary', field: 'cpu_util', agg: 'mean', timeRange: tr, siteId },
        { measurement: 'device_summary', field: 'mem_usage', agg: 'mean', timeRange: tr, siteId },
        'Avg CPU %',
        'Avg Memory %',
        this.cpuChart,
      );
      this.loadSingleChart(
        {
          measurement: 'device_summary',
          field: 'poe_draw_total',
          agg: 'sum',
          timeRange: tr,
          siteId,
        },
        'PoE Draw (W)',
        this.chart2,
      );
      this.loadSingleChart(
        { measurement: 'device_summary', field: 'num_clients', agg: 'sum', timeRange: tr, siteId },
        'Wired Clients',
        this.chart3,
      );
    } else if (chartType === 'gateway') {
      this.loadLineChart(
        { measurement: 'gateway_health', field: 'cpu_idle', agg: 'mean', timeRange: tr, siteId },
        { measurement: 'gateway_health', field: 'mem_usage', agg: 'mean', timeRange: tr, siteId },
        'Avg CPU Idle %',
        'Avg Memory %',
        this.cpuChart,
      );
      this.loadLineChart(
        { measurement: 'gateway_spu', field: 'spu_cpu', agg: 'mean', timeRange: tr, siteId },
        { measurement: 'gateway_spu', field: 'spu_sessions', agg: 'mean', timeRange: tr, siteId },
        'SPU CPU %',
        'SPU Sessions',
        this.chart2,
      );
      this.loadLineChart(
        { measurement: 'gateway_wan', field: 'tx_bytes', agg: 'sum', timeRange: tr, siteId },
        { measurement: 'gateway_wan', field: 'rx_bytes', agg: 'sum', timeRange: tr, siteId },
        'TX Bytes',
        'RX Bytes',
        this.chart3,
      );
    }
  }

  private loadLineChart(
    params1: { measurement: string; field: string; agg: string; timeRange: TimeRange; siteId: string },
    params2: { measurement: string; field: string; agg: string; timeRange: TimeRange; siteId: string },
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
    params: { measurement: string; field: string; agg: string; timeRange: TimeRange; siteId: string },
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
