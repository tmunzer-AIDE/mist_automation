import { Component, DestroyRef, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe, NgClass } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { Subscription, debounceTime, forkJoin, skip } from 'rxjs';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatTableModule } from '@angular/material/table';
import { BaseChartDirective } from 'ng2-charts';
import { SkeletonLoaderComponent } from '../../../shared/components/skeleton-loader/skeleton-loader.component';
import { Chart, registerables } from 'chart.js';
import type { ChartConfiguration } from 'chart.js';
import 'chartjs-adapter-date-fns';
import { TelemetryService } from '../telemetry.service';
import { TelemetryNavService } from '../telemetry-nav.service';
import { getChartColor, getTopicColors } from '../../../shared/utils/chart-defaults';
import { ToMbpsPipe } from '../../../shared/pipes/to-mbps.pipe';
import type {
  ClientListResponse,
  ClientSiteSummary,
  ClientStatRecord,
  AggregateResult,
  ScopeSite,
} from '../models';

Chart.register(...registerables);

@Component({
  selector: 'app-telemetry-clients',
  standalone: true,
  imports: [
    DecimalPipe,
    DatePipe,
    NgClass,
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatPaginatorModule,
    MatTableModule,
    BaseChartDirective,
    SkeletonLoaderComponent,
    ToMbpsPipe,
  ],
  templateUrl: './telemetry-clients.component.html',
  styleUrl: './telemetry-clients.component.scss',
})
export class TelemetryClientsComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly telemetryService = inject(TelemetryService);
  readonly nav = inject(TelemetryNavService);
  private readonly navTimeRange$ = toObservable(this.nav.timeRange);

  readonly siteId = signal('');
  readonly siteName = signal('');
  readonly loading = signal(false);
  readonly summary = signal<ClientSiteSummary | null>(null);
  readonly clientsResponse = signal<ClientListResponse | null>(null);

  readonly searchCtrl = new FormControl('');
  private readonly searchTerm = signal('');

  readonly clientColumns = ['identity', 'ap_mac', 'band', 'rssi', 'snr', 'tx_mbps', 'rx_mbps', 'auth', 'last_seen'];
  readonly activeBand = signal<'' | '24' | '5' | '6'>('');
  readonly pageIndex = signal(0);
  readonly pageSize = signal(25);

  readonly filteredClients = computed(() => {
    const all = this.clientsResponse()?.clients ?? [];
    const term = this.searchTerm().toLowerCase();
    const band = this.activeBand();
    return all
      .filter((c: ClientStatRecord) => {
        if (band && c.band !== band) return false;
        if (!term) return true;
        return (
          (c.hostname || '').toLowerCase().includes(term) ||
          c.mac.toLowerCase().includes(term) ||
          (c.ap_mac || '').includes(term) ||
          (c.manufacture || '').toLowerCase().includes(term)
        );
      })
      .sort((a, b) => (a.hostname || a.mac).localeCompare(b.hostname || b.mac));
  });

  readonly pagedClients = computed(() => {
    const start = this.pageIndex() * this.pageSize();
    return this.filteredClients().slice(start, start + this.pageSize());
  });

  readonly bandEntries = computed(() => {
    const counts = this.summary()?.band_counts ?? {};
    return ['24', '5', '6']
      .filter((b) => b in counts)
      .map((band) => ({
        label: band === '24' ? '2.4G' : band === '5' ? '5G' : '6G',
        count: counts[band],
      }));
  });

  readonly countsByBand = computed(() => {
    const all = this.clientsResponse()?.clients ?? [];
    return {
      b24: all.filter((c: ClientStatRecord) => c.band === '24').length,
      b5: all.filter((c: ClientStatRecord) => c.band === '5').length,
      b6: all.filter((c: ClientStatRecord) => c.band === '6').length,
    };
  });

  readonly bandSplitChart = computed((): ChartConfiguration<'doughnut'> | null => {
    const s = this.summary();
    if (!s) return null;
    const entries = ['24', '5', '6'].filter((k) => (s.band_counts?.[k] ?? 0) > 0);
    if (!entries.length) return null;
    return this._buildDoughnutChart(
      entries.map((k) => this.bandLabel(k)),
      entries.map((k) => s.band_counts[k]),
    );
  });

  readonly protoSplitChart = computed((): ChartConfiguration<'doughnut'> | null => {
    const s = this.summary();
    if (!s) return null;
    const entries = Object.entries(s.proto_counts ?? {}).filter(([, count]) => count > 0);
    if (!entries.length) return null;
    return this._buildDoughnutChart(
      entries.map(([proto]) => proto.toUpperCase()),
      entries.map(([, count]) => count),
    );
  });

  readonly countChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly rssiChart = signal<ChartConfiguration<'line'> | null>(null);

  private wsSub?: Subscription;

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id') ?? '';
      this.siteId.set(id);
      this._loadAll();
      this._subscribeWs(id);
    });

    this.searchCtrl.valueChanges
      .pipe(debounceTime(200), takeUntilDestroyed(this.destroyRef))
      .subscribe((v) => {
        this.searchTerm.set(v ?? '');
        this.pageIndex.set(0);
      });

    // React to time range changes from nav service
    this.navTimeRange$
      .pipe(skip(1), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this._loadCharts());
  }

  ngOnDestroy(): void {
    this.wsSub?.unsubscribe();
  }

  toggleBand(band: '' | '24' | '5' | '6'): void {
    this.activeBand.set(this.activeBand() === band ? '' : band);
    this.pageIndex.set(0);
  }

  onPage(event: PageEvent): void {
    this.pageIndex.set(event.pageIndex);
    this.pageSize.set(event.pageSize);
  }

  navigateToClient(mac: string): void {
    this.router.navigate(['/telemetry/site', this.siteId(), 'client', mac]);
  }

  private _loadAll(): void {
    const siteId = this.siteId();
    if (!siteId) return;
    this.loading.set(true);

    forkJoin({
      summary: this.telemetryService.getSiteClientsSummary(siteId),
      clients: this.telemetryService.getSiteClients(siteId),
      sites: this.telemetryService.getScopeSites(),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ summary, clients, sites }) => {
          this.summary.set(summary);
          this.clientsResponse.set(clients);
          const site = sites.sites.find((s: ScopeSite) => s.site_id === siteId);
          if (site) this.siteName.set(site.site_name);
          this.loading.set(false);
          this._loadCharts();
        },
        error: () => this.loading.set(false),
      });
  }

  private _loadCharts(): void {
    const siteId = this.siteId();
    if (!siteId) return;
    const tr = this.nav.timeRange();

    forkJoin({
      count: this.telemetryService.queryAggregate({
        siteId,
        measurement: 'client_stats',
        field: 'rssi',
        agg: 'count',
        timeRange: tr,
      }),
      rssi: this.telemetryService.queryAggregate({
        siteId,
        measurement: 'client_stats',
        field: 'rssi',
        agg: 'mean',
        timeRange: tr,
      }),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(({ count, rssi }) => {
        this.countChart.set(this._buildLineChart(count, 'Clients', getChartColor('objects')));
        this.rssiChart.set(this._buildLineChart(rssi, 'Avg RSSI (dBm)', getChartColor('completed')));
      });
  }

  private _buildLineChart(
    result: AggregateResult,
    label: string,
    color: string,
  ): ChartConfiguration<'line'> {
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
        scales: { x: { type: 'time', display: true }, y: { beginAtZero: label === 'Clients' } },
      },
    };
  }

  private _buildDoughnutChart(labels: string[], values: number[]): ChartConfiguration<'doughnut'> {
    const palette = getTopicColors();
    return {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{ data: values, backgroundColor: palette.slice(0, values.length), borderWidth: 0 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        plugins: { legend: { position: 'bottom' } },
      },
    };
  }

  bandLabel(band: string): string {
    if (band === '24') return '2.4G';
    if (band === '5') return '5G';
    if (band === '6') return '6G';
    return band;
  }

  bandClass(band: string): string {
    if (band === '24') return 'band-24';
    if (band === '5') return 'band-5';
    if (band === '6') return 'band-6';
    return '';
  }

  authLabel(authType: string): string {
    return authType === 'eap' ? '802.1X' : 'PSK';
  }

  rssiClass(rssi: number | null): string {
    if (rssi == null) return '';
    if (rssi > -60) return 'ok';
    if (rssi >= -75) return 'warn';
    return 'crit';
  }

  snrClass(snr: number | null): string {
    if (snr == null) return '';
    if (snr > 25) return 'ok';
    if (snr >= 15) return 'warn';
    return 'crit';
  }

  private _subscribeWs(siteId: string): void {
    this.wsSub?.unsubscribe();
    this.wsSub = this.telemetryService
      .subscribeToSite(siteId)
      .pipe(debounceTime(5000))
      .subscribe(() => {
        this.telemetryService
          .getSiteClientsSummary(siteId)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe((s) => this.summary.set(s));
        this.telemetryService
          .getSiteClients(siteId)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe((c) => this.clientsResponse.set(c));
      });
  }
}
