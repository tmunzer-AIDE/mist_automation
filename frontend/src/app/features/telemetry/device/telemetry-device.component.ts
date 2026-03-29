import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { TelemetryService } from '../telemetry.service';
import { LatestStats, TimeRange } from '../models';
import { DeviceLiveLogComponent } from './components/device-live-log/device-live-log.component';

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

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const mac = params.get('mac') ?? '';
      this.mac.set(mac);
      if (mac) {
        this.loadDevice(mac);
      }
    });
  }

  private loadDevice(mac: string): void {
    this.loading.set(true);
    this.telemetryService.getLatestStats(mac).subscribe({
      next: (data) => {
        this.latestStats.set(data);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }
}
