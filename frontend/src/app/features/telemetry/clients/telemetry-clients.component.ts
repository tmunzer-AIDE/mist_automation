import { Component, DestroyRef, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe, DatePipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { Subscription, debounceTime, forkJoin, skip } from 'rxjs';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatTableModule } from '@angular/material/table';
import { BaseChartDirective } from 'ng2-charts';
import { SkeletonLoaderComponent } from '../../../shared/components/skeleton-loader/skeleton-loader.component';
import { Chart, registerables } from 'chart.js';
import type { ChartConfiguration } from 'chart.js';
import 'chartjs-adapter-date-fns';
import { TelemetryService } from '../telemetry.service';
import { TelemetryNavService } from '../telemetry-nav.service';
import { getChartColor } from '../../../shared/utils/chart-defaults';
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
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatTableModule,
    BaseChartDirective,
    SkeletonLoaderComponent,
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

  readonly clientColumns = [
    'hostname',
    'mac',
    'ap_mac',
    'band',
    'channel',
    'rssi',
    'snr',
    'tx_bps',
    'rx_bps',
    'tx_rate',
    'manufacture',
    'auth_type',
    'last_seen',
  ];

  readonly activeAuthType = signal('');

  readonly filteredClients = computed(() => {
    const all = this.clientsResponse()?.clients ?? [];
    const term = this.searchTerm().toLowerCase();
    const auth = this.activeAuthType();
    return all.filter((c: ClientStatRecord) => {
      if (auth && c.auth_type !== auth) return false;
      if (!term) return true;
      return (
        (c.hostname || '').toLowerCase().includes(term) ||
        c.mac.includes(term) ||
        (c.ap_mac || '').includes(term) ||
        (c.manufacture || '').toLowerCase().includes(term)
      );
    });
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

  readonly countsByAuth = computed(() => {
    const all = this.clientsResponse()?.clients ?? [];
    return {
      psk: all.filter((c: ClientStatRecord) => c.auth_type === 'psk').length,
      eap: all.filter((c: ClientStatRecord) => c.auth_type === 'eap').length,
    };
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
      .subscribe((v) => this.searchTerm.set(v ?? ''));

    // React to time range changes from nav service
    this.navTimeRange$
      .pipe(skip(1), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this._loadCharts());
  }

  ngOnDestroy(): void {
    this.wsSub?.unsubscribe();
  }

  toggleAuthType(auth: string): void {
    this.activeAuthType.set(this.activeAuthType() === auth ? '' : auth);
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
        scales: { x: { type: 'time', display: true }, y: { beginAtZero: false } },
      },
    };
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
