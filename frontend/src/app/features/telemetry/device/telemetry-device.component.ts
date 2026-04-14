import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe, NgClass } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { skip } from 'rxjs';
import { MatButtonModule } from '@angular/material/button';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatIconModule } from '@angular/material/icon';
import { MatTableModule } from '@angular/material/table';
import { BaseChartDirective } from 'ng2-charts';
import { Chart, registerables } from 'chart.js';
import type { ChartConfiguration } from 'chart.js';
import 'chartjs-adapter-date-fns';
import { TelemetryService } from '../telemetry.service';
import { TelemetryNavService } from '../telemetry-nav.service';
import { LatestStats } from '../models';
import { getChartColor } from '../../../shared/utils/chart-defaults';
import { DeviceLiveLogComponent } from './components/device-live-log/device-live-log.component';

Chart.register(...registerables);

interface RadioInfo {
  band: string;
  label: string;
  channel: number;
  bandwidth: number;
  power: number;
  num_clients: number;
  num_wlans: number;
  util_all: number;
  noise_floor: number;
}

interface PortInfo {
  port_id: string;
  up: boolean;
  speed: number;
  tx_bytes: number;
  rx_bytes: number;
  tx_pkts: number;
  rx_pkts: number;
  tx_bps: number;
  rx_bps: number;
  tx_errors: number;
  rx_errors: number;
  lldp_system_name: string;
  lldp_system_desc: string;
  lldp_port_desc: string;
  poe_allocated: number;
}

interface PoeInfo {
  power_src: string;
  power_avail: number;
  power_needed: number;
  power_constrained: boolean;
}

interface RadioBandCharts {
  traffic: ChartConfiguration<'line'> | null;
  util: ChartConfiguration<'line'> | null;
}

interface InterfaceTrafficChart {
  interfaceId: string;
  label: string;
  chart: ChartConfiguration<'line'>;
}

@Component({
  selector: 'app-telemetry-device',
  standalone: true,
  imports: [
    DecimalPipe,
    NgClass,
    MatButtonModule,
    MatExpansionModule,
    MatIconModule,
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
  readonly nav = inject(TelemetryNavService);
  private readonly navTimeRange$ = toObservable(this.nav.timeRange);

  readonly mac = signal('');
  readonly loading = signal(false);
  readonly latestStats = signal<LatestStats | null>(null);

  readonly siteName = signal('');
  readonly siteId = signal('');

  readonly cpuMemChart = signal<ChartConfiguration<'line'> | null>(null);
  readonly chart2 = signal<ChartConfiguration<'line'> | null>(null);
  readonly chart3 = signal<ChartConfiguration<'line'> | null>(null);
  readonly switchInterfaceCharts = signal<InterfaceTrafficChart[]>([]);
  readonly gatewayInterfaceCharts = signal<InterfaceTrafficChart[]>([]);
  readonly gatewayLanCharts = signal<InterfaceTrafficChart[]>([]);

  // Per-band charts: keyed by band string (e.g. 'band_24')
  readonly radioCharts = signal<Record<string, RadioBandCharts>>({});

  // Band display order and labels
  readonly BAND_ORDER = ['band_6', 'band_5', 'band_24'];
  readonly BAND_LABELS: Record<string, string> = {
    band_6: '6 GHz',
    band_5: '5 GHz',
    band_24: '2.4 GHz',
  };

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
    // AP: direct cpu_util field
    const directCpu = stats['cpu_util'] as number | undefined;
    if (directCpu !== undefined) return directCpu;
    // SW/GW: 100 - cpu_stat.idle
    const cpu_stat = stats['cpu_stat'] as any;
    return 100 - (cpu_stat?.idle ?? 100);
  });

  readonly memUsage = computed(() => {
    const stats = this.latestStats()?.stats;
    if (!stats) return 0;
    // AP: direct mem_total_kb / mem_used_kb fields
    const memTotal = stats['mem_total_kb'] as number | undefined;
    const memUsed = stats['mem_used_kb'] as number | undefined;
    if (memTotal && memUsed) return Math.round((memUsed / memTotal) * 100);
    // SW/GW: memory_stat object
    const mem = stats['memory_stat'] as any;
    if (mem?.mem_total_kb && mem?.mem_used_kb) {
      return Math.round((mem.mem_used_kb / mem.mem_total_kb) * 100);
    }
    return mem?.usage ?? 0;
  });

  // ── Shared header computeds ─────────────────────────────────────────────

  readonly deviceModel = computed(() => (this.latestStats()?.stats?.['model'] as string) || '');
  readonly deviceFirmware = computed(() => {
    const stats = this.latestStats()?.stats;
    return (stats?.['version'] as string) || (stats?.['fw_version'] as string) || '';
  });
  readonly deviceIp = computed(() => (this.latestStats()?.stats?.['ip'] as string) || '');

  readonly deviceTypeLabel = computed(() => {
    const t = this.deviceType();
    if (t === 'ap') return 'AP';
    if (t === 'switch') return 'SW';
    if (t === 'gateway') return 'GW';
    return '';
  });

  // ── AP-specific computed signals ────────────────────────────────────────

  readonly apModel = computed(() => this.deviceModel());
  readonly apIp = computed(() => this.deviceIp());
  readonly apNumWlans = computed(() => (this.latestStats()?.stats?.['num_wlans'] as number) ?? 0);

  readonly formattedUptime = computed(() => {
    const u = (this.latestStats()?.stats?.['uptime'] as number) ?? 0;
    const d = Math.floor(u / 86400);
    const h = Math.floor((u % 86400) / 3600);
    const m = Math.floor((u % 3600) / 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  });

  // Switch-specific KPI computeds
  readonly portsUp = computed(() => {
    const ifStat = this.latestStats()?.stats?.['if_stat'] as Record<string, any> | undefined;
    if (!ifStat) return null;
    const entries = Object.values(ifStat);
    const up = entries.filter((p) => p.up).length;
    return { up, total: entries.length };
  });

  // Gateway-specific KPI computeds
  readonly wanLinks = computed(() => {
    const stats = this.latestStats()?.stats;
    if (!stats) return null;
    const ifStat = stats['if_stat'] as Record<string, any> | undefined;
    if (!ifStat) return null;
    const wanPorts = Object.values(ifStat).filter((p) => p['port_usage'] === 'wan');
    return { up: wanPorts.filter((p) => p['up']).length, total: wanPorts.length };
  });

  readonly spuSessions = computed(() => {
    const spuStat = this.latestStats()?.stats?.['spu_stat'];
    if (!Array.isArray(spuStat) || !spuStat.length) return null;
    return (spuStat[0]['spu_current_session'] as number) ?? null;
  });

  readonly apRadios = computed<RadioInfo[]>(() => {
    const radioStat = this.latestStats()?.stats?.['radio_stat'] as
      | Record<string, any>
      | undefined;
    if (!radioStat) return [];
    return this.BAND_ORDER.filter((band) => radioStat[band]).map((band) => {
      const d = radioStat[band];
      return {
        band,
        label: this.BAND_LABELS[band] || band,
        channel: (d.channel as number) ?? 0,
        bandwidth: (d.bandwidth as number) ?? 0,
        power: (d.power as number) ?? 0,
        num_clients: (d.num_clients as number) ?? 0,
        num_wlans: (d.num_wlans as number) ?? 0,
        util_all: (d.util_all as number) ?? 0,
        noise_floor: (d.noise_floor as number) ?? 0,
      };
    });
  });

  readonly apPortStats = computed<PortInfo[]>(() => {
    const portStat = this.latestStats()?.stats?.['port_stat'] as
      | Record<string, any>
      | undefined;
    const lldpStats = this.latestStats()?.stats?.['lldp_stats'] as
      | Record<string, any>
      | undefined;
    if (!portStat) return [];
    return Object.entries(portStat)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([port_id, d]) => {
        const lldp = lldpStats?.[port_id];
        return {
          port_id,
          up: !!(d.up),
          speed: (d.speed as number) ?? 0,
          tx_bytes: (d.tx_bytes as number) ?? 0,
          rx_bytes: (d.rx_bytes as number) ?? 0,
          tx_pkts: (d.tx_pkts as number) ?? 0,
          rx_pkts: (d.rx_pkts as number) ?? 0,
          tx_bps: (d.tx_bps as number) ?? 0,
          rx_bps: (d.rx_bps as number) ?? 0,
          tx_errors: (d.tx_errors as number) ?? 0,
          rx_errors: (d.rx_errors as number) ?? 0,
          lldp_system_name: (lldp?.system_name as string) || '',
          lldp_system_desc: (lldp?.system_desc as string) || '',
          lldp_port_desc: (lldp?.port_desc as string) || '',
          poe_allocated: (lldp?.power_allocated as number) ?? 0,
        };
      });
  });

  readonly apPoeInfo = computed<PoeInfo | null>(() => {
    const stats = this.latestStats()?.stats;
    if (!stats || !stats['power_src']) return null;
    return {
      power_src: (stats['power_src'] as string) || '',
      power_avail: (stats['power_avail'] as number) ?? 0,
      power_needed: (stats['power_needed'] as number) ?? 0,
      power_constrained: !!(stats['power_constrained']),
    };
  });

  // ── Switch/gateway computed signals ─────────────────────────────────────

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

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const mac = params.get('mac') ?? '';
      this.mac.set(mac);
      if (mac) {
        this.loadDevice(mac);
      }
    });

    // React to time range changes from nav service
    this.navTimeRange$
      .pipe(skip(1), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.loadCharts());
  }

  private loadDevice(mac: string): void {
    this.loading.set(true);
    this.telemetryService.getLatestStats(mac).subscribe({
      next: (data) => {
        this.latestStats.set(data);
        this.loading.set(false);

        const stats = data.stats || {};
        this.siteId.set((stats['site_id'] as string) || '');
        this.nav.setDetailContext({
          title: this.deviceName(),
          kind: this.deviceType(),
          stale: !data.fresh,
          siteId: this.siteId(),
          siteName: this.siteName(),
        });

        this.telemetryService.getScopeSites().subscribe({
          next: (res) => {
            const site = res.sites.find((s) => s.site_id === this.siteId());
            if (site) this.siteName.set(site.site_name);
            this.nav.setDetailContext({
              title: this.deviceName(),
              kind: this.deviceType(),
              stale: !data.fresh,
              siteId: this.siteId(),
              siteName: this.siteName(),
            });
          },
        });

        this.loadCharts();
      },
      error: () => this.loading.set(false),
    });
  }

  private loadCharts(): void {
    const mac = this.mac();
    const tr = this.nav.timeRange();
    const startMap: Record<string, string> = { '1h': '-1h', '6h': '-6h', '24h': '-24h' };
    const start = startMap[tr] || '-6h';
    const end = 'now()';
    const type = this.deviceType();

    this.chart2.set(null);
    this.chart3.set(null);
    this.switchInterfaceCharts.set([]);
    this.gatewayInterfaceCharts.set([]);

    if (type === 'ap') {
      this.telemetryService.queryRange(mac, 'device_summary', start, end).subscribe({
        next: (r) => this.cpuMemChart.set(
          this.buildDeviceChart(r.points, 'cpu_util', 'mem_usage', 'CPU %', 'Memory %'),
        ),
        error: () => this.cpuMemChart.set(null),
      });
      this.telemetryService.queryRange(mac, 'device_summary', start, end).subscribe({
        next: (r) => this.chart2.set(this.buildDeviceSingleChart(r.points, 'num_clients', 'Clients')),
      });
      this.radioCharts.set({});
      this.telemetryService.queryRange(mac, 'radio_stats', start, end).subscribe({
        next: (r) => {
          const byBand: Record<string, Record<string, unknown>[]> = {};
          for (const p of r.points) {
            const band = (p['band'] as string) || 'unknown';
            if (!byBand[band]) byBand[band] = [];
            byBand[band].push(p);
          }
          const charts: Record<string, RadioBandCharts> = {};
          for (const [band, points] of Object.entries(byBand)) {
            charts[band] = {
              traffic: this.buildRadioTrafficChart(points),
              util: this.buildRadioUtilChart(points),
            };
          }
          this.radioCharts.set(charts);
        },
        error: () => this.radioCharts.set({}),
      });
    } else if (type === 'switch') {
      this.telemetryService.queryRange(mac, 'device_summary', start, end).subscribe({
        next: (r) => this.cpuMemChart.set(
          this.buildDeviceChart(r.points, 'cpu_util', 'mem_usage', 'CPU %', 'Memory %'),
        ),
        error: () => this.cpuMemChart.set(null),
      });
      this.telemetryService.queryRange(mac, 'device_summary', start, end).subscribe({
        next: (r) => this.chart2.set(this.buildDeviceSingleChart(r.points, 'num_clients', 'Clients')),
      });
      this.telemetryService.queryRange(mac, 'device_summary', start, end).subscribe({
        next: (r) => this.chart3.set(this.buildDeviceSingleChart(r.points, 'poe_draw_total', 'PoE Draw (W)')),
      });
      this.telemetryService.queryRange(mac, 'port_stats', start, end).subscribe({
        next: (r) => this.switchInterfaceCharts.set(this.buildPerInterfaceCharts(r.points, false)),
        error: () => this.switchInterfaceCharts.set([]),
      });
    } else if (type === 'gateway') {
      // Gateways use gateway_health (cpu_idle field) — not device_summary
      this.telemetryService.queryRange(mac, 'gateway_health', start, end).subscribe({
        next: (r) => this.cpuMemChart.set(this.buildGatewayCpuMemChart(r.points)),
        error: () => this.cpuMemChart.set(null),
      });
      this.telemetryService.queryRange(mac, 'gateway_wan', start, end).subscribe({
        next: (r) => this.chart2.set(this.buildWanMbpsChart(r.points)),
      });
      this.telemetryService.queryRange(mac, 'gateway_spu', start, end).subscribe({
        next: (r) => this.chart3.set(this.buildGatewaySpuChart(r.points)),
      });
      this.telemetryService.queryRange(mac, 'gateway_wan', start, end).subscribe({
        next: (r) => this.gatewayInterfaceCharts.set(this.buildPerInterfaceCharts(r.points, true)),
        error: () => this.gatewayInterfaceCharts.set([]),
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
    const c1 = getChartColor('duration'); // amber — CPU
    const c2 = getChartColor('failed');   // red — Memory
    return {
      type: 'line',
      data: {
        labels: points.map((p) => new Date(p['_time'] as string)),
        datasets: [
          {
            label: l1,
            data: points.map((p) => p[f1] as number),
            borderColor: c1,
            backgroundColor: c1 + '22',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.4,
            fill: true,
          },
          {
            label: l2,
            data: points.map((p) => p[f2] as number),
            borderColor: c2,
            backgroundColor: c2 + '22',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.4,
            fill: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        scales: {
          x: { type: 'time', display: true, ticks: { maxTicksLimit: 6 } },
          y: { beginAtZero: true, max: 100 },
        },
        plugins: { legend: { position: 'bottom' } },
      },
    };
  }

  private buildDeviceSingleChart(
    points: Record<string, unknown>[],
    field: string,
    label: string,
  ): ChartConfiguration<'line'> {
    const color = getChartColor('completed');
    return {
      type: 'line',
      data: {
        labels: points.map((p) => new Date(p['_time'] as string)),
        datasets: [
          {
            label,
            data: points.map((p) => p[field] as number),
            borderColor: color,
            backgroundColor: color + '22',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.4,
            fill: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        scales: {
          x: { type: 'time', display: true, ticks: { maxTicksLimit: 6 } },
          y: { beginAtZero: true },
        },
        plugins: { legend: { position: 'bottom' } },
      },
    };
  }

  private buildWanMbpsChart(points: Record<string, unknown>[]): ChartConfiguration<'line'> {
    const txColor = getChartColor('objects');
    const rxColor = getChartColor('completed');
    return {
      type: 'line',
      data: {
        labels: points.map((p) => new Date(p['_time'] as string)),
        datasets: [
          {
            label: 'TX Mbps',
            data: this.toRates(points, 'tx_bytes', 8 / 1_000_000),
            borderColor: txColor,
            backgroundColor: txColor + '22',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.4,
            fill: true,
          },
          {
            label: 'RX Mbps',
            data: this.toRates(points, 'rx_bytes', 8 / 1_000_000),
            borderColor: rxColor,
            backgroundColor: rxColor + '22',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.4,
            fill: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        scales: {
          x: { type: 'time', display: true, ticks: { maxTicksLimit: 6 } },
          y: { beginAtZero: true, title: { display: true, text: 'Mbps' } },
        },
        plugins: { legend: { position: 'bottom' } },
      },
    };
  }

  /** Derive per-second rates from consecutive cumulative counter values.
   *  Returns n-1 values (first point dropped — no previous to diff against).
   *  Yields 0 when the previous value is 0/null (counter not yet initialized
   *  or field absent in older InfluxDB rows) to avoid false spikes. */
  private toRates(
    points: Record<string, unknown>[],
    field: string,
    scale = 1,
  ): number[] {
    return points.slice(1).map((p, i) => {
      const prev = points[i]; // slice(1) shifts index by 1
      const prevVal = (prev[field] as number) ?? 0;
      if (prevVal === 0) return 0; // uninitialized counter — skip
      const delta = ((p[field] as number) ?? 0) - prevVal;
      if (delta <= 0) return 0; // clamp counter resets
      const dtSec =
        (new Date(p['_time'] as string).getTime() -
          new Date(prev['_time'] as string).getTime()) /
        1000;
      if (dtSec <= 0) return 0;
      return (delta * scale) / dtSec;
    });
  }

  private buildPerInterfaceCharts(
    points: Record<string, unknown>[],
    useBytesForRate: boolean,
  ): InterfaceTrafficChart[] {
    const byInterface = new Map<string, Record<string, unknown>[]>();
    const labels = new Map<string, string>();

    for (const point of points) {
      const interfaceId = ((point['port_id'] as string) || '').trim();
      if (!interfaceId) continue;
      if (!byInterface.has(interfaceId)) byInterface.set(interfaceId, []);
      byInterface.get(interfaceId)!.push(point);

      const wanName = ((point['wan_name'] as string) || '').trim();
      if (wanName) {
        labels.set(interfaceId, `${interfaceId} · ${wanName}`);
      } else {
        labels.set(interfaceId, interfaceId);
      }
    }

    const txField = useBytesForRate ? 'tx_bytes' : 'tx_pkts';
    const rxField = useBytesForRate ? 'rx_bytes' : 'rx_pkts';
    const scale = useBytesForRate ? 8 / 1_000_000 : 1;
    const yAxisLabel = useBytesForRate ? 'Mbps' : 'pps';

    const result: InterfaceTrafficChart[] = [];
    for (const [interfaceId, interfacePoints] of byInterface.entries()) {
      if (interfacePoints.length < 2) continue;

      const sorted = [...interfacePoints].sort(
        (a, b) =>
          new Date(a['_time'] as string).getTime() - new Date(b['_time'] as string).getTime(),
      );

      result.push({
        interfaceId,
        label: labels.get(interfaceId) || interfaceId,
        chart: {
          type: 'line',
          data: {
            labels: sorted.slice(1).map((point) => new Date(point['_time'] as string)),
            datasets: [
              {
                label: `TX ${yAxisLabel}`,
                data: this.toRates(sorted, txField, scale),
                borderColor: getChartColor('objects'),
                backgroundColor: getChartColor('objects') + '22',
                borderWidth: 1.8,
                pointRadius: 0,
                tension: 0.4,
                fill: true,
              },
              {
                label: `RX ${yAxisLabel}`,
                data: this.toRates(sorted, rxField, scale),
                borderColor: getChartColor('completed'),
                backgroundColor: getChartColor('completed') + '22',
                borderWidth: 1.8,
                pointRadius: 0,
                tension: 0.4,
                fill: true,
              },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            interaction: { mode: 'index', intersect: false },
            scales: {
              x: { type: 'time', display: true, ticks: { maxTicksLimit: 6, font: { size: 10 } } },
              y: {
                beginAtZero: true,
                title: { display: true, text: yAxisLabel, font: { size: 10 } },
                ticks: { font: { size: 10 } },
              },
            },
            plugins: {
              legend: { position: 'bottom', labels: { font: { size: 10 }, boxWidth: 12 } },
            },
          },
        },
      });
    }

    return result.sort((a, b) => a.interfaceId.localeCompare(b.interfaceId));
  }

  private buildRadioTrafficChart(
    points: Record<string, unknown>[],
  ): ChartConfiguration<'line'> {
    const labels = points.slice(1).map((p) => new Date(p['_time'] as string));
    return {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'TX Mbps',
            data: this.toRates(points, 'tx_bytes', 8 / 1_000_000),
            borderColor: '#60a5fa',
            backgroundColor: 'transparent',
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.3,
            yAxisID: 'y',
          },
          {
            label: 'RX Mbps',
            data: this.toRates(points, 'rx_bytes', 8 / 1_000_000),
            borderColor: '#4ade80',
            backgroundColor: 'transparent',
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.3,
            yAxisID: 'y',
          },
          {
            label: 'TX pps',
            data: this.toRates(points, 'tx_pkts'),
            borderColor: '#a78bfa',
            backgroundColor: 'transparent',
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.4,
            yAxisID: 'y1',
          },
          {
            label: 'RX pps',
            data: this.toRates(points, 'rx_pkts'),
            borderColor: '#fb923c',
            backgroundColor: 'transparent',
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.4,
            yAxisID: 'y1',
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { type: 'time', display: true, ticks: { maxTicksLimit: 6, font: { size: 10 } } },
          y: {
            beginAtZero: true,
            position: 'left',
            title: { display: true, text: 'Mbps', font: { size: 10 } },
            ticks: { font: { size: 10 } },
          },
          y1: {
            beginAtZero: true,
            position: 'right',
            grid: { drawOnChartArea: false },
            title: { display: true, text: 'pps', font: { size: 10 } },
            ticks: { font: { size: 10 } },
          },
        },
        plugins: {
          legend: { position: 'bottom', labels: { font: { size: 10 }, boxWidth: 12 } },
        },
      },
    };
  }

  /** Gateway CPU/Memory from gateway_health measurement (cpu_idle field → invert to cpu_util). */
  private buildGatewayCpuMemChart(points: Record<string, unknown>[]): ChartConfiguration<'line'> {
    const cpuColor = getChartColor('duration');
    const memColor = getChartColor('failed');
    return {
      type: 'line',
      data: {
        labels: points.map((p) => new Date(p['_time'] as string)),
        datasets: [
          {
            label: 'CPU %',
            data: points.map((p) => Math.round((100 - ((p['cpu_idle'] as number) ?? 100)) * 10) / 10),
            borderColor: cpuColor,
            backgroundColor: cpuColor + '22',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.4,
            fill: true,
          },
          {
            label: 'Memory %',
            data: points.map((p) => (p['mem_usage'] as number) ?? 0),
            borderColor: memColor,
            backgroundColor: memColor + '22',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.4,
            fill: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        scales: {
          x: { type: 'time', display: true, ticks: { maxTicksLimit: 6 } },
          y: { beginAtZero: true, max: 100 },
        },
        plugins: { legend: { position: 'bottom' } },
      },
    };
  }

  /** SPU sessions + CPU% (dual y-axis) from gateway_spu measurement.
   *  spu_cpu is stored as a 0–1 fraction — multiply by 100 for display. */
  private buildGatewaySpuChart(points: Record<string, unknown>[]): ChartConfiguration<'line'> {
    const sessColor = getChartColor('completed');
    const cpuColor = getChartColor('duration');
    return {
      type: 'line',
      data: {
        labels: points.map((p) => new Date(p['_time'] as string)),
        datasets: [
          {
            label: 'Sessions',
            data: points.map((p) => (p['spu_sessions'] as number) ?? 0),
            borderColor: sessColor,
            backgroundColor: sessColor + '22',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.4,
            fill: true,
            yAxisID: 'y',
          },
          {
            label: 'SPU CPU %',
            data: points.map((p) => Math.round(((p['spu_cpu'] as number) ?? 0) * 1000) / 10),
            borderColor: cpuColor,
            backgroundColor: 'transparent',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.4,
            yAxisID: 'y1',
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { type: 'time', display: true, ticks: { maxTicksLimit: 6, font: { size: 10 } } },
          y: {
            beginAtZero: true,
            position: 'left',
            title: { display: true, text: 'Sessions', font: { size: 10 } },
            ticks: { font: { size: 10 } },
          },
          y1: {
            beginAtZero: true,
            max: 100,
            position: 'right',
            grid: { drawOnChartArea: false },
            title: { display: true, text: 'CPU %', font: { size: 10 } },
            ticks: { font: { size: 10 } },
          },
        },
        plugins: {
          legend: { position: 'bottom', labels: { font: { size: 10 }, boxWidth: 12 } },
        },
      },
    };
  }

  private buildRadioUtilChart(
    points: Record<string, unknown>[],
  ): ChartConfiguration<'line'> {
    const labels = points.map((p) => new Date(p['_time'] as string));
    const utilFields: { key: string; label: string; color: string }[] = [
      { key: 'util_tx', label: 'TX', color: '#4ade80' },
      { key: 'util_rx_in_bss', label: 'RX (BSS)', color: '#60a5fa' },
      { key: 'util_rx_other_bss', label: 'RX (Other BSS)', color: '#818cf8' },
      { key: 'util_unknown_wifi', label: 'Unknown WiFi', color: '#f59e0b' },
      { key: 'util_non_wifi', label: 'Non-WiFi', color: '#ef4444' },
      { key: 'util_undecodable_wifi', label: 'Undecodable', color: '#f97316' },
    ];
    return {
      type: 'line',
      data: {
        labels,
        datasets: utilFields.map(({ key, label, color }) => ({
          label,
          data: points.map((p) => (p[key] as number) ?? 0),
          borderColor: color,
          backgroundColor: color + '99',
          borderWidth: 1,
          pointRadius: 0,
          tension: 0.3,
          fill: true,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { type: 'time', display: true, ticks: { maxTicksLimit: 6, font: { size: 10 } } },
          y: {
            beginAtZero: true,
            max: 100,
            stacked: true,
            title: { display: true, text: '%', font: { size: 10 } },
            ticks: { font: { size: 10 } },
          },
        },
        plugins: {
          legend: { position: 'bottom', labels: { font: { size: 10 }, boxWidth: 12 } },
        },
      },
    };
  }
}
