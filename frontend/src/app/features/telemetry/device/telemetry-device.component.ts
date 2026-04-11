import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { skip } from 'rxjs';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTableModule } from '@angular/material/table';
import { BaseChartDirective } from 'ng2-charts';
import { Chart, registerables } from 'chart.js';
import type { ChartConfiguration } from 'chart.js';
import 'chartjs-adapter-date-fns';
import { TelemetryService } from '../telemetry.service';
import { TelemetryNavService } from '../telemetry-nav.service';
import { LatestStats } from '../models';
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

@Component({
  selector: 'app-telemetry-device',
  standalone: true,
  imports: [
    DecimalPipe,
    MatButtonModule,
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

  // ── AP-specific computed signals ────────────────────────────────────────

  readonly apModel = computed(() => (this.latestStats()?.stats?.['model'] as string) || '');
  readonly apIp = computed(() => (this.latestStats()?.stats?.['ip'] as string) || '');
  readonly apNumWlans = computed(() => (this.latestStats()?.stats?.['num_wlans'] as number) ?? 0);

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
    const tr = this.nav.timeRange();
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

      // Per-band charts: query radio_stats once and split by band tag
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
        animation: { duration: 0 },
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
        animation: { duration: 0 },
        scales: { x: { type: 'time', display: true }, y: { beginAtZero: true } },
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
            tension: 0.3,
            borderDash: [4, 2],
            yAxisID: 'y1',
          },
          {
            label: 'RX pps',
            data: this.toRates(points, 'rx_pkts'),
            borderColor: '#fb923c',
            backgroundColor: 'transparent',
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.3,
            borderDash: [4, 2],
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
