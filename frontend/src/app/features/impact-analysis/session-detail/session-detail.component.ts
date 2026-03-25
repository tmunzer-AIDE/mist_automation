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
import { TitleCasePipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ImpactAnalysisService } from '../../../core/services/impact-analysis.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { GlobalChatService } from '../../../core/services/global-chat.service';
import { WebSocketService } from '../../../core/services/websocket.service';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import {
  SessionDetailResponse,
  VALIDATION_CHECK_LABELS,
} from '../models/impact-analysis.model';
import {
  deviceTypeIcon as _deviceTypeIcon,
  formatDeviceType as _formatDeviceType,
} from '../utils/device-type.utils';
import DOMPurify from 'dompurify';
import { marked } from 'marked';

function renderMarkdown(md: string): string {
  const raw = marked.parse(md, { async: false }) as string;
  return DOMPurify.sanitize(raw);
}

interface TimelineEntry {
  type: 'config_change' | 'incident';
  timestamp: string;
  event_type: string;
  device_name: string;
  device_mac: string;
  webhook_event_id?: string | null;
  severity?: string;
  is_revert?: boolean;
  resolved?: boolean;
  resolved_at?: string | null;
  config_diff?: string | null;
  device_model?: string;
  firmware_version?: string;
  commit_user?: string;
  commit_method?: string;
}

@Component({
  selector: 'app-session-detail',
  standalone: true,
  imports: [
    TitleCasePipe,
    MatCardModule,
    MatTableModule,
    MatExpansionModule,
    MatIconModule,
    MatButtonModule,
    MatProgressBarModule,
    MatChipsModule,
    MatTooltipModule,
    MatSnackBarModule,
    StatusBadgeComponent,
    DateTimePipe,
  ],
  templateUrl: './session-detail.component.html',
  styleUrl: './session-detail.component.scss',
})
export class SessionDetailComponent implements OnInit, OnDestroy {
  @ViewChild('actions', { static: true }) actionsTpl!: TemplateRef<unknown>;

  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly service = inject(ImpactAnalysisService);
  private readonly topbarService = inject(TopbarService);
  private readonly globalChatService = inject(GlobalChatService);
  private readonly wsService = inject(WebSocketService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);

  session = signal<SessionDetailResponse | null>(null);
  loading = signal(true);
  cancelling = signal(false);
  reanalyzing = signal(false);

  aiAssessmentHtml = signal('');

  isActive = computed(() => {
    const s = this.session()?.status;
    return (
      s === 'monitoring' ||
      s === 'baseline_capture' ||
      s === 'analyzing' ||
      s === 'pending' ||
      s === 'running'
    );
  });

  isCompleted = computed(() => this.session()?.status === 'completed');

  progressMode = computed<'determinate' | 'indeterminate'>(() => {
    const s = this.session();
    if (!s) return 'indeterminate';
    return s.progress?.percent > 0 ? 'determinate' : 'indeterminate';
  });

  progressPercent = computed(() => this.session()?.progress?.percent ?? 0);

  severityClass = computed(() => {
    const severity = this.session()?.ai_assessment?.['severity'];
    switch (severity) {
      case 'critical':
        return 'severity-critical';
      case 'warning':
        return 'severity-warning';
      case 'info':
        return 'severity-info';
      case 'none':
        return 'severity-none';
      default:
        return '';
    }
  });

  baselineMetrics = computed(() => {
    const baseline = this.session()?.sle_data?.baseline as Record<string, unknown> | undefined;
    const metrics = baseline?.['metrics'] as Record<string, Record<string, unknown>> | undefined;
    if (!metrics) return [];
    return Object.entries(metrics).map(([name, data]) => ({
      name: name.replace(/-/g, ' '),
      summary: data?.['summary'],
      hasSiteTrend: !!data?.['site_trend'],
      hasDeviceTrend: !!data?.['device_trend'],
      siteTrendPoints: Array.isArray(data?.['site_trend']) ? (data['site_trend'] as unknown[]).length : 0,
      deviceTrendPoints: Array.isArray(data?.['device_trend']) ? (data['device_trend'] as unknown[]).length : 0,
    }));
  });

  deltaMetrics = computed(() => {
    const delta = this.session()?.sle_data?.delta as Record<string, unknown> | undefined;
    const metrics = delta?.['metrics'] as Array<{
      name: string; baseline_value: number; current_value: number;
      change_percent: number; degraded: boolean; status: string;
    }> | undefined;
    return metrics ?? [];
  });

  sleOverallDegraded = computed(() => {
    const delta = this.session()?.sle_data?.delta as Record<string, unknown> | undefined;
    return (delta?.['overall_degraded'] as boolean) ?? false;
  });

  sleSnapshotCount = computed(() => this.session()?.sle_data?.snapshots?.length ?? 0);

  validationChecks = computed(() => {
    const results = this.session()?.validation_results;
    if (!results || typeof results !== 'object') return [];
    return Object.entries(results)
      .filter(([key]) => key !== 'overall_status')
      .map(([key, value]: [string, unknown]) => {
        const v = value as Record<string, unknown> | null;
        return {
          name: key,
          label: VALIDATION_CHECK_LABELS[key] || key.replace(/_/g, ' '),
          status: (v?.['status'] as string) || 'unknown',
          details: Array.isArray(v?.['details']) ? (v['details'] as string[]) : [],
        };
      });
  });

  overallValidationStatus = computed(() => {
    const results = this.session()?.validation_results;
    return (results?.['overall_status'] as string) || 'unknown';
  });

  eventTimeline = computed((): TimelineEntry[] => {
    const s = this.session();
    if (!s) return [];
    const entries: TimelineEntry[] = [
      ...s.config_changes.map((c) => ({
        type: 'config_change' as const,
        timestamp: c.timestamp,
        event_type: c.event_type,
        device_name: c.device_name,
        device_mac: c.device_mac,
        webhook_event_id: c.webhook_event_id,
        config_diff: c.config_diff,
        device_model: c.device_model,
        firmware_version: c.firmware_version,
        commit_user: c.commit_user,
        commit_method: c.commit_method,
      })),
      ...s.incidents.map((i) => ({
        type: 'incident' as const,
        timestamp: i.timestamp,
        event_type: i.event_type,
        device_name: i.device_name,
        device_mac: i.device_mac,
        severity: i.severity,
        is_revert: i.is_revert,
        resolved: i.resolved,
        resolved_at: i.resolved_at,
      })),
    ];
    return entries.sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    );
  });

  private sessionId = '';

  ngOnInit(): void {
    this.sessionId = this.route.snapshot.paramMap.get('id') ?? '';
    this.topbarService.setTitle('Impact Analysis');
    this.loadSession();
  }

  loadSession(): void {
    this.loading.set(true);
    this.service.getSession(this.sessionId).subscribe({
      next: (session) => {
        this.session.set(session);
        this.loading.set(false);
        this.topbarService.setTitle(`Impact: ${session.device_name || session.device_mac}`);
        this.globalChatService.setContext({
          page: 'Impact Analysis Detail',
          details: { device: session.device_name || session.device_mac, status: session.status },
        });

        const rawMd = session.ai_assessment?.['raw_markdown'];
        if (rawMd) {
          this.aiAssessmentHtml.set(renderMarkdown(rawMd as string));
        }

        if (this.isActive()) {
          this.subscribeToProgress();
        }
        if (this.isCompleted()) {
          this.topbarService.setActions(this.actionsTpl);
        }
      },
      error: () => this.loading.set(false),
    });
  }

  cancelSession(): void {
    this.cancelling.set(true);
    this.service.cancelSession(this.sessionId).subscribe({
      next: () => {
        this.snackBar.open('Session cancelled', 'OK', { duration: 3000 });
        this.loadSession();
        this.cancelling.set(false);
      },
      error: () => {
        this.snackBar.open('Failed to cancel session', 'OK', { duration: 3000 });
        this.cancelling.set(false);
      },
    });
  }

  reanalyze(): void {
    this.reanalyzing.set(true);
    this.service.reanalyze(this.sessionId).subscribe({
      next: () => {
        this.snackBar.open('Re-analysis started', 'OK', { duration: 3000 });
        this.loadSession();
        this.reanalyzing.set(false);
      },
      error: () => {
        this.snackBar.open('Failed to start re-analysis', 'OK', { duration: 3000 });
        this.reanalyzing.set(false);
      },
    });
  }

  goBack(): void {
    this.router.navigate(['/impact-analysis']);
  }

  deviceTypeIcon = _deviceTypeIcon;

  formatDeviceType = _formatDeviceType;

  validationIcon(status: string): string {
    switch (status) {
      case 'pass':
        return 'check_circle';
      case 'fail':
        return 'cancel';
      case 'warn':
        return 'warning';
      default:
        return 'info';
    }
  }

  incidentSeverityClass(severity: string): string {
    switch (severity) {
      case 'critical':
        return 'incident-critical';
      case 'warning':
        return 'incident-warning';
      case 'info':
        return 'incident-info';
      default:
        return '';
    }
  }

  private subscribeToProgress(): void {
    this.wsService
      .subscribe<{ type: string; data?: Record<string, unknown> }>(`impact:${this.sessionId}`)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((msg) => {
        const current = this.session();
        switch (msg.type) {
          case 'session_update':
            // Real-time status/progress update
            if (current && msg.data) {
              this.session.set({
                ...current,
                status: (msg.data['status'] as string) || current.status,
                progress: (msg.data['progress'] as { phase: string; message: string; percent: number }) ||
                  current.progress,
                polls_completed: (msg.data['polls_completed'] as number) ?? current.polls_completed,
                polls_total: (msg.data['polls_total'] as number) ?? current.polls_total,
                incident_count: (msg.data['incident_count'] as number) ?? current.incident_count,
              });
            }
            break;
          case 'incident_added':
          case 'incident_resolved':
            // Reload to get the full updated incidents list
            this.loadSession();
            break;
          case 'sle_snapshot':
            // Poll data arrived — update snapshot count from backend poll_number
            if (current) {
              this.session.set({
                ...current,
                polls_completed: (msg.data?.['poll_number'] as number) ?? current.polls_completed,
              });
            }
            break;
          case 'session_failed':
            // Terminal state — reload to show final results
            this.loadSession();
            break;
        }
      });
  }

  ngOnDestroy(): void {
    this.topbarService.clearActions();
  }
}
