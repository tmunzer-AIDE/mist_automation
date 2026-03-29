import {
  Component,
  DestroyRef,
  OnInit,
  OnDestroy,
  TemplateRef,
  ViewChild,
  inject,
  signal,
  computed,
} from '@angular/core';
import { DatePipe, TitleCasePipe } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatCardModule } from '@angular/material/card';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatTableModule } from '@angular/material/table';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { HttpClient } from '@angular/common/http';
import { ApiService } from '../../../core/services/api.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { WebSocketService } from '../../../core/services/websocket.service';
import {
  getCheckValue,
  getCheckStatus,
  getWanPorts,
  getDeviceOverallStatus,
  getCableTestSummary,
  getCableTestStatus,
  isCableStatusOk,
  statusLabel,
  DeviceResult,
  SwitchResult,
  DeviceCheck,
  WanPort,
  VcMember,
  CableTestResult,
} from '../../../shared/utils/device-status.utils';

interface ReportDetail {
  id: string;
  report_type: string;
  site_id: string;
  site_name: string;
  status: string;
  progress: {
    current_step: string;
    completed: number;
    total: number;
    details: string;
    overall_completed?: number;
    overall_total?: number;
    steps?: ProgressStep[];
  };
  error: string | null;
  result: ReportResult | null;
  created_by: string;
  created_at: string;
  completed_at: string | null;
}

interface DeviceSummary {
  total: number;
  failed: number;
}

interface SiteInfo {
  site_name: string;
  site_address: string;
  site_groups: string[];
  templates: { type: string; name: string; id?: string }[];
  org_wlans: { ssid: string; template_id?: string }[];
  site_wlans: { ssid: string }[];
  device_summary: {
    aps: DeviceSummary;
    switches: DeviceSummary;
    gateways: DeviceSummary;
  };
}

interface ReportResult {
  site_info: SiteInfo;
  template_variables: TemplateVarCheck[];
  aps: DeviceResult[];
  switches: SwitchResult[];
  gateways: GatewayResult[];
  summary: { pass: number; fail: number; warn: number; info: number };
}

interface TemplateVarCheck {
  template_type: string;
  template_name: string;
  variable: string;
  defined: boolean;
  status: string;
  value?: string;
}

interface GroupedVariable {
  variable: string;
  value: string;
  status: string;
  occurrences: TemplateVarCheck[];
}

interface GatewayWanPort {
  interface: string;
  name: string;
  up: boolean;
  wan_type: string;
}

interface GatewayLanPort {
  interface: string;
  network: string;
  up: boolean;
}

interface GatewayNetwork {
  name: string;
  gateway_ip: string;
  dhcp_status: string;
  dhcp_pool: string;
  dhcp_relay_servers: string[];
}

interface GatewayResult extends DeviceResult {
  wan_ports: GatewayWanPort[];
  lan_ports: GatewayLanPort[];
  networks: GatewayNetwork[];
}

type StepStatus = 'pending' | 'running' | 'completed';

interface ProgressStep {
  id: string;
  label: string;
  status: StepStatus;
  message: string;
}

interface WsProgressMessage {
  type: string;
  channel: string;
  data: {
    status: string;
    overall_completed: number;
    overall_total: number;
    steps: ProgressStep[];
  };
}

@Component({
  selector: 'app-report-detail',
  standalone: true,
  imports: [
    DatePipe,
    TitleCasePipe,
    MatCardModule,
    MatDialogModule,
    MatTableModule,
    MatExpansionModule,
    MatIconModule,
    MatButtonModule,
    MatProgressBarModule,
    MatProgressSpinnerModule,
    MatChipsModule,
    MatTooltipModule,
  ],
  templateUrl: './report-detail.component.html',
  styleUrl: './report-detail.component.scss',
})
export class ReportDetailComponent implements OnInit, OnDestroy {
  @ViewChild('actions', { static: true }) actionsTpl!: TemplateRef<unknown>;

  private readonly route = inject(ActivatedRoute);
  private readonly http = inject(HttpClient);
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);
  private readonly topbarService = inject(TopbarService);
  private readonly wsService = inject(WebSocketService);
  private readonly destroyRef = inject(DestroyRef);

  report = signal<ReportDetail | null>(null);
  loading = signal(true);
  progressSteps = signal<ProgressStep[]>([]);
  overallCompleted = signal(0);
  overallTotal = signal(0);

  progressMode = computed<'determinate' | 'indeterminate'>(() =>
    this.overallTotal() > 0 ? 'determinate' : 'indeterminate',
  );
  progressPercent = computed(() => {
    const total = this.overallTotal();
    if (total <= 0) return 0;
    return Math.round((this.overallCompleted() / total) * 100);
  });

  isCompleted = computed(() => this.report()?.status === 'completed');
  isRunning = computed(() => {
    const s = this.report()?.status;
    return s === 'pending' || s === 'running';
  });

  expandedVars = signal<Set<string>>(new Set());

  groupedVariables = computed<GroupedVariable[]>(() => {
    const r = this.report();
    if (!r?.result?.template_variables?.length) return [];

    const groups = new Map<string, GroupedVariable>();
    for (const check of r.result.template_variables) {
      const existing = groups.get(check.variable);
      if (existing) {
        existing.occurrences.push(check);
        if (check.status === 'fail') existing.status = 'fail';
      } else {
        groups.set(check.variable, {
          variable: check.variable,
          value: check.value ?? '',
          status: check.status,
          occurrences: [check],
        });
      }
    }
    return Array.from(groups.values());
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

        // Hydrate step state from persisted progress (reconnection case)
        if (
          (report.status === 'pending' || report.status === 'running') &&
          report.progress?.steps?.length
        ) {
          this.progressSteps.set(report.progress.steps);
          this.overallCompleted.set(report.progress.overall_completed ?? 0);
          this.overallTotal.set(report.progress.overall_total ?? 0);
        }

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
          this.progressSteps.set(msg.data.steps);
          this.overallCompleted.set(msg.data.overall_completed);
          this.overallTotal.set(msg.data.overall_total);
          const current = this.report();
          if (current) {
            const runningStep = msg.data.steps.find((s) => s.status === 'running');
            this.report.set({
              ...current,
              status: msg.data.status,
              progress: {
                current_step: runningStep?.id ?? '',
                completed: msg.data.overall_completed,
                total: msg.data.overall_total,
                details: runningStep?.message ?? '',
                overall_completed: msg.data.overall_completed,
                overall_total: msg.data.overall_total,
                steps: msg.data.steps,
              },
            });
          }
        } else if (msg.type === 'report_complete') {
          this.loadReport();
        }
      });
  }

  exportPdf(): void {
    this._downloadFile(
      `/api/v1/reports/validation/${this.reportId}/export/pdf`,
      `validation_${this.report()?.site_name || 'report'}.pdf`,
    );
  }

  exportCsv(): void {
    this._downloadFile(
      `/api/v1/reports/validation/${this.reportId}/export/csv`,
      `validation_${this.report()?.site_name || 'report'}.zip`,
    );
  }

  private _downloadFile(url: string, filename: string): void {
    this.api
      .getBlob(url.replace('/api/v1/', ''))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          const a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = filename;
          a.click();
          URL.revokeObjectURL(a.href);
        },
        error: (err) => {
          console.error('Failed to download file:', err);
        },
      });
  }

  getCheckValue(device: DeviceResult, checkName: string): string {
    return getCheckValue(device, checkName);
  }

  getCheckStatus(device: DeviceResult, checkName: string): string {
    return getCheckStatus(device, checkName);
  }

  getWanPorts(device: DeviceResult): WanPort[] {
    return getWanPorts(device);
  }

  openDeviceDetail(type: 'switch' | 'gateway', device: SwitchResult | GatewayResult): void {
    import('./device-detail-dialog.component').then((m) => {
      this.dialog.open(m.DeviceDetailDialogComponent, {
        data: { type, device },
        maxHeight: '90vh',
        panelClass: 'device-detail-dialog-panel',
      });
    });
  }

  toggleVariable(varName: string): void {
    this.expandedVars.update((set) => {
      const next = new Set(set);
      if (next.has(varName)) next.delete(varName);
      else next.add(varName);
      return next;
    });
  }

  isVarExpanded(varName: string): boolean {
    return this.expandedVars().has(varName);
  }

  getCableTestSummary(sw: SwitchResult): string {
    return getCableTestSummary(sw);
  }

  getCableTestStatus(sw: SwitchResult): string {
    return getCableTestStatus(sw);
  }

  getDeviceOverallStatus(device: DeviceResult | SwitchResult): string {
    return getDeviceOverallStatus(device);
  }

  isCableStatusOk(status: string): boolean {
    return isCableStatusOk(status);
  }

  statusLabel(status: string): string {
    return statusLabel(status);
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

  stepIcon(status: StepStatus): string {
    switch (status) {
      case 'completed':
        return 'check_circle';
      case 'pending':
        return 'radio_button_unchecked';
      default:
        return '';
    }
  }

  ngOnDestroy(): void {
    this.topbarService.clearActions();
  }
}
