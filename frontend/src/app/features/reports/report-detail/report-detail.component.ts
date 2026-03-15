import {
  Component,
  DestroyRef,
  OnInit,
  TemplateRef,
  ViewChild,
  inject,
  signal,
  computed,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../../core/services/api.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { WebSocketService } from '../../../core/services/websocket.service';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';

interface ReportDetail {
  id: string;
  report_type: string;
  site_id: string;
  site_name: string;
  status: string;
  progress: { current_step: string; completed: number; total: number; details: string };
  error: string | null;
  result: ReportResult | null;
  created_by: string;
  created_at: string;
  completed_at: string | null;
}

interface SiteInfo {
  site_name: string;
  site_address: string;
  site_groups: string[];
  templates: { type: string; name: string }[];
  org_wlans: { ssid: string; template_id?: string }[];
  site_wlans: { ssid: string }[];
}

interface ReportResult {
  site_info: SiteInfo;
  template_variables: TemplateVarCheck[];
  aps: DeviceResult[];
  switches: SwitchResult[];
  gateways: DeviceResult[];
  summary: { pass: number; fail: number; warn: number; info: number };
}

interface TemplateVarCheck {
  template_type: string;
  template_name: string;
  variable: string;
  defined: boolean;
  status: string;
}

interface DeviceCheck {
  check: string;
  status: string;
  value: string;
  ports?: WanPort[];
}

interface WanPort {
  port: string;
  up: boolean;
  speed: number;
  full_duplex: boolean;
}

interface DeviceResult {
  device_id: string;
  name: string;
  mac: string;
  model: string;
  checks: DeviceCheck[];
}

interface VcMember {
  member_id: string;
  mac: string;
  serial: string;
  model: string;
  firmware: string;
  status: string;
  vc_ports_up: number;
  checks: DeviceCheck[];
}

interface CableTestResult {
  port: string;
  status: string;
  pairs: { pair: string; status: string; length: string }[];
  raw?: string[];
}

interface SwitchResult extends DeviceResult {
  virtual_chassis: { status: string; members: VcMember[]; message?: string } | null;
  cable_tests: CableTestResult[];
}

interface WsProgressMessage {
  type: string;
  channel: string;
  data: {
    status: string;
    step: string;
    message: string;
    completed: number;
    total: number;
  };
}

@Component({
  selector: 'app-report-detail',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatTableModule,
    MatExpansionModule,
    MatIconModule,
    MatButtonModule,
    MatProgressBarModule,
    MatChipsModule,
    MatTooltipModule,
    StatusBadgeComponent,
  ],
  templateUrl: './report-detail.component.html',
  styleUrl: './report-detail.component.scss',
})
export class ReportDetailComponent implements OnInit {
  @ViewChild('actions', { static: true }) actionsTpl!: TemplateRef<unknown>;

  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(ApiService);
  private readonly topbarService = inject(TopbarService);
  private readonly wsService = inject(WebSocketService);
  private readonly destroyRef = inject(DestroyRef);

  report = signal<ReportDetail | null>(null);
  loading = signal(true);
  progressMessages = signal<string[]>([]);
  progressPercent = computed(() => {
    const r = this.report();
    if (!r || !r.progress?.total) return 0;
    return Math.round((r.progress.completed / r.progress.total) * 100);
  });

  isCompleted = computed(() => this.report()?.status === 'completed');
  isRunning = computed(() => {
    const s = this.report()?.status;
    return s === 'pending' || s === 'running';
  });

  private reportId = '';

  ngOnInit(): void {
    this.reportId = this.route.snapshot.paramMap.get('id') ?? '';
    this.topbarService.setTitle('Report Details');
    this.loadReport();
  }

  loadReport(): void {
    this.loading.set(true);
    this.api.get<ReportDetail>(`/reports/validation/${this.reportId}`).subscribe({
      next: (report) => {
        this.report.set(report);
        this.loading.set(false);
        this.topbarService.setTitle(`Report: ${report.site_name}`);

        if (report.status === 'pending' || report.status === 'running') {
          this.subscribeToProgress();
        }
        if (report.status === 'completed') {
          this.topbarService.setActions(this.actionsTpl);
        }
      },
      error: () => this.loading.set(false),
    });
  }

  private subscribeToProgress(): void {
    this.wsService
      .subscribe<WsProgressMessage>(`report:${this.reportId}`)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((msg) => {
        if (msg.type === 'report_progress' && msg.data) {
          this.progressMessages.update((msgs) => [...msgs, msg.data.message]);
          const current = this.report();
          if (current) {
            this.report.set({
              ...current,
              status: msg.data.status,
              progress: {
                current_step: msg.data.step,
                completed: msg.data.completed,
                total: msg.data.total,
                details: msg.data.message,
              },
            });
          }
        } else if (msg.type === 'report_complete') {
          // Reload the full report with results
          this.loadReport();
        }
      });
  }

  exportPdf(): void {
    window.open(`/api/v1/reports/validation/${this.reportId}/export/pdf`, '_blank');
  }

  exportCsv(): void {
    window.open(`/api/v1/reports/validation/${this.reportId}/export/csv`, '_blank');
  }

  getCheckValue(device: DeviceResult, checkName: string): string {
    return device.checks.find((c) => c.check === checkName)?.value ?? '';
  }

  getCheckStatus(device: DeviceResult, checkName: string): string {
    return device.checks.find((c) => c.check === checkName)?.status ?? 'info';
  }

  getWanPorts(device: DeviceResult): WanPort[] {
    const check = device.checks.find((c) => c.check === 'wan_port_status');
    return (check?.ports as WanPort[]) ?? [];
  }

  isCableStatusOk(status: string): boolean {
    const s = status.toLowerCase();
    return s === 'normal' || s === 'ok' || s === 'pass' || s === 'passed';
  }

  statusIcon(status: string): string {
    switch (status) {
      case 'pass':
        return 'check_circle';
      case 'fail':
        return 'cancel';
      case 'warn':
        return 'warning';
      case 'error':
        return 'error';
      default:
        return 'info';
    }
  }
}
