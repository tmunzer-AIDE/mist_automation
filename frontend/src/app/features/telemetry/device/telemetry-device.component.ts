import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { BaseChartDirective } from 'ng2-charts';
import { Chart, registerables } from 'chart.js';
import type { ChartConfiguration } from 'chart.js';
import 'chartjs-adapter-date-fns';
import { TelemetryService } from '../telemetry.service';
import { LatestStats, TimeRange } from '../models';
import { DeviceLiveLogComponent } from './components/device-live-log/device-live-log.component';

Chart.register(...registerables);

@Component({
  selector: 'app-telemetry-device',
  standalone: true,
  imports: [
    DecimalPipe,
    RouterModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatTableModule,
    BaseChartDirective,
    DeviceLiveLogComponent,
  ],
  templateUrl: './telemetry-device.component.html',
  styleUrl: './telemetry-device.component.scss',
})
export class TelemetryDeviceComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly telemetryService = inject(TelemetryService);

  readonly mac = signal('');
  readonly timeRange = signal<TimeRange>('1h');
  readonly loading = signal(false);
  readonly latestStats = signal<LatestStats | null>(null);

  readonly siteName = signal('');
  readonly siteId = signal('');

  readonly cpuMemChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly chart2 = signal<ChartConfiguration<'line'> | null>(null);
  readonly chart3 = signal<ChartConfiguration<'line'> | null>(null);

  readonly timeRanges: TimeRange[] = ['1h', '6h', '24h'];

  readonly deviceType = computed<'ap' | 'switch' | 'gateway' | null>(() => {
    const stats = this.latestStats()?.stats;
    if (!stats) return null;
    const t = stats['type'] as string | undefined;
    if (t === 'switch' || t === 'gateway') return t;
    const model = stats['model'] as string | undefined;
    if (model?.startsWith('AP')) return 'ap';
    return null;
  });

  readonly deviceName = computed(() => {
    const stats = this.latestStats()?.stats;
    return (stats?.['name'] as string) || (stats?.['hostname'] as string) || this.mac();
  });

  readonly isAP = computed(() => this.deviceType() === 'ap');
  readonly isSwitch = computed(() => this.deviceType() === 'switch');
  readonly isGateway = computed(() => this.deviceType() === 'gateway');

  readonly numClients = computed(() => {
    return (this.latestStats()?.stats?.['num_clients'] as number) ?? 0;
  });

  readonly uptime = computed(() => {
    return (this.latestStats()?.stats?.['uptime'] as number) ?? 0;
  });

  readonly haState = computed(() => {
    return (this.latestStats()?.stats?.['ha_state'] as string) ?? '\u2014';
  });

  readonly cpuUtil = computed(() => {
    const stats = this.latestStats()?.stats;
    if (!stats) return 0;
    const cpu_stat = stats['cpu_stat'] as any;
    return 100 - (cpu_stat?.idle ?? 100);
  });

  readonly memUsage = computed(() => {
    const stats = this.latestStats()?.stats;
    if (!stats) return 0;
    const mem = stats['memory_stat'] as any;
    if (mem?.mem_total_kb && mem?.mem_used_kb) {
      return Math.round((mem.mem_used_kb / mem.mem_total_kb) * 100);
    }
    return mem?.usage ?? 0;
  });

  readonly portRows = computed(() => {
    const if_stat = this.latestStats()?.stats?.['if_stat'] as Record<string, any> | undefined;
    if (!if_stat) return [];
    return Object.entries(if_stat)
      .filter(([_, pd]) => pd.up)
      .map(([k, pd]) => ({
        port_id: pd.port_id ?? k,
        speed: pd.speed ?? 0,
        tx_pkts: pd.tx_pkts ?? 0,
        rx_pkts: pd.rx_pkts ?? 0,
      }));
  });

  readonly moduleRows = computed(() => {
    const mods = this.latestStats()?.stats?.['module_stat'] as any[] | undefined;
    if (!mods?.length) return [];
    return mods.map((m: any) => ({
      fpc_idx: m._idx ?? 0,
      vc_role: m.vc_role ?? '',
      temp_max: Math.max(...(m.temperatures ?? []).map((t: any) => t.celsius ?? 0), 0),
      poe_draw: m.poe?.power_draw ?? 0,
      vc_links_count: (m.vc_links ?? []).length,
      mem_usage: m.memory_stat?.usage ?? 0,
    }));
  });

  readonly dhcpRows = computed(() => {
    const dhcpd = this.latestStats()?.stats?.['dhcpd_stat'] as Record<string, any> | undefined;
    if (!dhcpd) return [];
    return Object.entries(dhcpd).map(([name, s]) => ({
      network_name: name,
      num_ips: s.num_ips ?? 0,
      num_leased: s.num_leased ?? 0,
      utilization_pct: s.num_ips ? Math.round((s.num_leased / s.num_ips) * 100) : 0,
    }));
  });

  readonly poeTotalDraw = computed(() => {
    const mods = this.latestStats()?.stats?.['module_stat'] as any[] | undefined;
    if (!mods?.length) return 0;
    return mods.reduce((sum: number, m: any) => sum + (m.poe?.power_draw ?? 0), 0);
  });

  readonly portColumns = ['port_id', 'speed', 'tx_pkts', 'rx_pkts'];
  readonly moduleColumns = [
    'fpc_idx',
    'vc_role',
    'temp_max',
    'poe_draw',
    'vc_links_count',
    'mem_usage',
  ];
  readonly dhcpColumns = ['network_name', 'leased', 'utilization_pct'];

  readonly wanRows = computed(() => {
    const stats = this.latestStats()?.stats;
    if (!stats) return [];
    const ifStat = stats['if_stat'];
    if (!ifStat || typeof ifStat !== 'object') return [];
    return Object.entries(ifStat as Record<string, Record<string, unknown>>)
      .filter(([, data]) => data['port_usage'] === 'wan')
      .map(([key, data]) => ({
        port_id: (data['port_id'] as string) || key,
        wan_name: (data['wan_name'] as string) || '',
        up: !!data['up'],
        tx_bytes: (data['tx_bytes'] as number) || 0,
        rx_bytes: (data['rx_bytes'] as number) || 0,
        tx_pkts: (data['tx_pkts'] as number) || 0,
        rx_pkts: (data['rx_pkts'] as number) || 0,
      }));
  });

  readonly spuRow = computed(() => {
    const stats = this.latestStats()?.stats;
    if (!stats) return null;
    const spuStat = stats['spu_stat'];
    if (!Array.isArray(spuStat) || !spuStat.length) return null;
    const spu = spuStat[0];
    return {
      spu_cpu: spu['spu_cpu'] ?? 0,
      spu_sessions: spu['spu_current_session'] ?? 0,
      spu_max_sessions: spu['spu_max_session'] ?? 0,
      spu_memory: spu['spu_memory'] ?? 0,
    };
  });

  readonly clusterRow = computed(() => {
    const stats = this.latestStats()?.stats;
    if (!stats) return null;
    const cluster = stats['cluster_config'];
    if (!cluster || typeof cluster !== 'object') return null;
    const cc = cluster as Record<string, unknown>;
    const controlLink = cc['control_link_info'] as Record<string, unknown> | undefined;
    const fabricLink = cc['fabric_link_info'] as Record<string, unknown> | undefined;
    return {
      status: (cc['status'] as string) || '',
      operational: (cc['operational'] as string) || '',
      primary_health: (cc['primary_node_health'] as string) || '',
      secondary_health: (cc['secondary_node_health'] as string) || '',
      control_link_up: controlLink
        ? ((controlLink['status'] as string) || '').toLowerCase() === 'up'
        : false,
      fabric_link_up: fabricLink
        ? (
            (fabricLink['Status'] as string) ||
            (fabricLink['status'] as string) ||
            ''
          ).toLowerCase() === 'up'
        : false,
    };
  });

  readonly resourceRows = computed(() => {
    const stats = this.latestStats()?.stats;
    if (!stats) return [];
    const moduleStat = stats['module_stat'];
    if (!Array.isArray(moduleStat) || !moduleStat.length) return [];
    const resources = moduleStat[0]['network_resources'];
    if (!Array.isArray(resources)) return [];
    return resources.map((r: Record<string, unknown>) => ({
      resource_type: (r['type'] as string) || '',
      count: (r['count'] as number) || 0,
      limit: (r['limit'] as number) || 0,
      utilization_pct:
        (r['limit'] as number) > 0
          ? Math.round(((r['count'] as number) / (r['limit'] as number)) * 1000) / 10
          : 0,
    }));
  });

  readonly wanColumns = [
    'port_id',
    'wan_name',
    'status',
    'tx_bytes',
    'rx_bytes',
    'tx_pkts',
    'rx_pkts',
  ];
  readonly spuColumns = ['spu_cpu', 'spu_sessions', 'spu_max_sessions', 'spu_memory'];
  readonly clusterColumns = [
    'status',
    'operational',
    'primary_health',
    'secondary_health',
    'control_link',
    'fabric_link',
  ];
  readonly resourceColumns = ['resource_type', 'count', 'limit', 'utilization_pct'];

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const mac = params.get('mac') ?? '';
      this.mac.set(mac);
      if (mac) {
        this.loadDevice(mac);
      }
    });
  }

  setTimeRange(tr: TimeRange): void {
    this.timeRange.set(tr);
    this.loadCharts();
  }

  private loadDevice(mac: string): void {
    this.loading.set(true);
    this.telemetryService.getLatestStats(mac).subscribe({
      next: (data) => {
        this.latestStats.set(data);
        this.loading.set(false);

        const stats = data.stats || {};
        this.siteId.set((stats['site_id'] as string) || '');

        this.telemetryService.getScopeSites().subscribe({
          next: (res) => {
            const site = res.sites.find((s) => s.site_id === this.siteId());
            if (site) this.siteName.set(site.site_name);
          },
        });

        this.loadCharts();
      },
      error: () => this.loading.set(false),
    });
  }

  private loadCharts(): void {
    const mac = this.mac();
    const tr = this.timeRange();
    const startMap: Record<string, string> = { '1h': '-1h', '6h': '-6h', '24h': '-24h' };
    const start = startMap[tr] || '-6h';
    const end = 'now()';

    this.telemetryService.queryRange(mac, 'device_summary', start, end).subscribe({
      next: (result) => {
        this.cpuMemChart.set(
          this.buildDeviceChart(result.points, 'cpu_util', 'mem_usage', 'CPU %', 'Memory %'),
        );
      },
      error: () => this.cpuMemChart.set(null),
    });

    const type = this.deviceType();
    if (type === 'ap') {
      this.telemetryService.queryRange(mac, 'device_summary', start, end).subscribe({
        next: (r) =>
          this.chart2.set(this.buildDeviceSingleChart(r.points, 'num_clients', 'Clients')),
      });
      this.telemetryService.queryRange(mac, 'radio_stats', start, end).subscribe({
        next: (r) =>
          this.chart3.set(this.buildDeviceSingleChart(r.points, 'util_all', 'Utilization %')),
      });
    } else if (type === 'switch') {
      this.telemetryService.queryRange(mac, 'device_summary', start, end).subscribe({
        next: (r) =>
          this.chart2.set(this.buildDeviceSingleChart(r.points, 'num_clients', 'Clients')),
      });
      this.telemetryService.queryRange(mac, 'device_summary', start, end).subscribe({
        next: (r) =>
          this.chart3.set(this.buildDeviceSingleChart(r.points, 'poe_draw_total', 'PoE Draw (W)')),
      });
    } else if (type === 'gateway') {
      this.telemetryService.queryRange(mac, 'gateway_wan', start, end).subscribe({
        next: (r) =>
          this.chart2.set(
            this.buildDeviceChart(r.points, 'tx_bytes', 'rx_bytes', 'TX Bytes', 'RX Bytes'),
          ),
      });
      this.telemetryService.queryRange(mac, 'gateway_spu', start, end).subscribe({
        next: (r) =>
          this.chart3.set(
            this.buildDeviceChart(r.points, 'spu_cpu', 'spu_sessions', 'SPU CPU', 'Sessions'),
          ),
      });
    }
  }

  private buildDeviceChart(
    points: Record<string, unknown>[],
    f1: string,
    f2: string,
    l1: string,
    l2: string,
  ): ChartConfiguration<'line'> {
    return {
      type: 'line',
      data: {
        labels: points.map((p) => new Date(p['_time'] as string)),
        datasets: [
          {
            label: l1,
            data: points.map((p) => p[f1] as number),
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
          },
          {
            label: l2,
            data: points.map((p) => p[f2] as number),
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
        scales: { x: { type: 'time', display: true }, y: { beginAtZero: true } },
        plugins: { legend: { position: 'bottom' } },
      },
    };
  }

  private buildDeviceSingleChart(
    points: Record<string, unknown>[],
    field: string,
    label: string,
  ): ChartConfiguration<'line'> {
    return {
      type: 'line',
      data: {
        labels: points.map((p) => new Date(p['_time'] as string)),
        datasets: [
          {
            label,
            data: points.map((p) => p[field] as number),
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
        scales: { x: { type: 'time', display: true }, y: { beginAtZero: true } },
        plugins: { legend: { position: 'bottom' } },
      },
    };
  }
}
