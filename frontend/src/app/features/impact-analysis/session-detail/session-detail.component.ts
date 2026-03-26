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
  effect,
} from '@angular/core';
import { SlicePipe, TitleCasePipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ImpactAnalysisService } from '../../../core/services/impact-analysis.service';
import { LlmService } from '../../../core/services/llm.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { GlobalChatService } from '../../../core/services/global-chat.service';
import { WebSocketService } from '../../../core/services/websocket.service';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import {
  SessionDetailResponse,
  TimelineEntryResponse,
  ChatMessage,
} from '../models/impact-analysis.model';
import {
  deviceTypeIcon as _deviceTypeIcon,
  formatDeviceType as _formatDeviceType,
} from '../utils/device-type.utils';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { ImpactChatPanelComponent } from './impact-chat-panel.component';
import { ImpactDataPanelComponent } from './impact-data-panel.component';

function renderMarkdown(md: string): string {
  const raw = marked.parse(md, { async: false }) as string;
  return DOMPurify.sanitize(raw);
}

let chatMsgCounter = 0;

@Component({
  selector: 'app-session-detail',
  standalone: true,
  imports: [
    SlicePipe,
    TitleCasePipe,
    MatIconModule,
    MatButtonModule,
    MatProgressBarModule,
    MatTooltipModule,
    MatSnackBarModule,
    StatusBadgeComponent,
    DateTimePipe,
    ImpactChatPanelComponent,
    ImpactDataPanelComponent,
  ],
  templateUrl: './session-detail.component.html',
  styleUrl: './session-detail.component.scss',
})
export class SessionDetailComponent implements OnInit, OnDestroy {
  @ViewChild('actions', { static: true }) actionsTpl!: TemplateRef<unknown>;

  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly service = inject(ImpactAnalysisService);
  private readonly llmService = inject(LlmService);
  private readonly topbarService = inject(TopbarService);
  private readonly globalChatService = inject(GlobalChatService);
  private readonly wsService = inject(WebSocketService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);

  session = signal<SessionDetailResponse | null>(null);
  loading = signal(true);
  cancelling = signal(false);
  reanalyzing = signal(false);
  llmEnabled = signal(false);
  timeProgress = signal(0);

  private sessionId = '';
  private progressInterval: ReturnType<typeof setInterval> | null = null;

  isActive = computed(() => {
    const s = this.session()?.status;
    return (
      s === 'monitoring' ||
      s === 'validating' ||
      s === 'baseline_capture' ||
      s === 'awaiting_config' ||
      s === 'pending' ||
      s === 'running'
    );
  });

  isCompleted = computed(() => this.session()?.status === 'completed');

  impactSeverity = computed(() => this.session()?.impact_severity ?? 'none');
  hasImpact = computed(() => this.impactSeverity() !== 'none');

  verdictSummary = computed(() => {
    const assessment = this.session()?.ai_assessment;
    if (!assessment) return '';
    return (assessment['summary'] as string) ?? '';
  });

  chatMessages = computed<ChatMessage[]>(() => {
    const timeline = this.session()?.timeline ?? [];
    // Find the index of the last ai_analysis entry (only show the latest one)
    let lastAnalysisIdx = -1;
    for (let i = timeline.length - 1; i >= 0; i--) {
      if (timeline[i].type === 'ai_analysis') {
        lastAnalysisIdx = i;
        break;
      }
    }
    return timeline
      .map((entry, idx) => this._timelineToChat(entry, idx, lastAnalysisIdx))
      .filter((msg): msg is ChatMessage => msg !== null);
  });

  ngOnInit(): void {
    this.sessionId = this.route.snapshot.paramMap.get('id') ?? '';
    this.topbarService.setTitle('Impact Analysis');
    this.loadSession();
    this.llmService.getStatus().subscribe({
      next: (status) => this.llmEnabled.set(status.enabled),
      error: () => this.llmEnabled.set(false),
    });
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

        if (this.isActive()) {
          this.subscribeToProgress();
        }
        // Always start time progress for active sessions — works for both
        // pre-monitoring (uses backend percent) and monitoring (uses timestamps)
        if (this.isActive() && !this.progressInterval) {
          this.startTimeProgress();
        }
        if (this.isCompleted()) {
          this.topbarService.setActions(this.actionsTpl);
          this.stopTimeProgress();
          this.timeProgress.set(100);
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

  onChatMessageSent(): void {
    // Reload session to get updated timeline with chat entries
    this.loadSession();
  }

  deviceTypeIcon = _deviceTypeIcon;
  formatDeviceType = _formatDeviceType;

  private startTimeProgress(): void {
    this.stopTimeProgress();
    this.updateTimeProgress();
    this.progressInterval = setInterval(() => this.updateTimeProgress(), 1000);
  }

  private stopTimeProgress(): void {
    if (this.progressInterval) {
      clearInterval(this.progressInterval);
      this.progressInterval = null;
    }
  }

  private updateTimeProgress(): void {
    const s = this.session();
    if (!s) {
      this.timeProgress.set(0);
      return;
    }

    // Once monitoring_started_at and monitoring_ends_at are set, use them
    // for accurate time-based progress. Before that, use created_at as start
    // and estimate based on the session's progress.percent from the backend.
    if (s.monitoring_started_at && s.monitoring_ends_at) {
      const start = new Date(s.monitoring_started_at).getTime();
      const end = new Date(s.monitoring_ends_at).getTime();
      const now = Date.now();
      const percent = Math.min(100, Math.max(0, ((now - start) / (end - start)) * 100));
      this.timeProgress.set(Math.round(percent));
    } else if (s.progress?.percent > 0) {
      // Pre-monitoring phases: use backend-reported percent
      this.timeProgress.set(s.progress.percent);
    } else {
      this.timeProgress.set(0);
    }
  }

  private _timelineToChat(
    entry: TimelineEntryResponse,
    idx: number,
    lastAnalysisIdx: number,
  ): ChatMessage | null {
    // Skip status_change entries — narration messages already describe each phase
    if (entry.type === 'status_change') return null;

    // Only show the latest ai_analysis entry (earlier ones are superseded)
    if (entry.type === 'ai_analysis' && idx !== lastAnalysisIdx) return null;

    const id = `tl-${chatMsgCounter++}`;
    const timestamp = entry.timestamp;

    switch (entry.type) {
      case 'ai_narration':
        return {
          id,
          role: 'ai',
          type: 'narration',
          content: entry.title,
          html: renderMarkdown(entry.title),
          timestamp,
          severity: entry.severity || undefined,
        };

      case 'ai_analysis': {
        // Use full summary from session.ai_assessment (timeline entry truncates to 500 chars)
        const fullSummary =
          (this.session()?.ai_assessment?.['summary'] as string) ||
          (entry.data['summary'] as string) ||
          entry.title;
        return {
          id,
          role: 'ai',
          type: 'analysis',
          content: fullSummary,
          html: renderMarkdown(fullSummary),
          timestamp,
          severity: entry.severity || undefined,
        };
      }

      case 'chat_message': {
        const role = entry.data['role'] as string;
        const content = (entry.data['content'] as string) || entry.title;
        return {
          id,
          role: role === 'user' ? 'user' : 'ai',
          type: 'chat',
          content,
          html: role === 'user' ? '' : renderMarkdown(content),
          timestamp,
        };
      }

      default:
        // System events: config_change, validation, webhook_event, sle_check
        return {
          id,
          role: 'system',
          type: 'event',
          content: entry.title,
          html: '',
          timestamp,
          severity: entry.severity || undefined,
        };
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
            if (current && msg.data) {
              const updated = {
                ...current,
                status: (msg.data['status'] as string) || current.status,
                progress: (msg.data['progress'] as { phase: string; message: string; percent: number }) ||
                  current.progress,
                polls_completed: (msg.data['polls_completed'] as number) ?? current.polls_completed,
                polls_total: (msg.data['polls_total'] as number) ?? current.polls_total,
                incident_count: (msg.data['incident_count'] as number) ?? current.incident_count,
                monitoring_started_at:
                  (msg.data['monitoring_started_at'] as string) ?? current.monitoring_started_at,
                monitoring_ends_at:
                  (msg.data['monitoring_ends_at'] as string) ?? current.monitoring_ends_at,
              };
              this.session.set(updated);
              // Start time progress if monitoring just started
              if (updated.monitoring_started_at && !this.progressInterval) {
                this.startTimeProgress();
              }
            }
            break;
          case 'incident_added':
          case 'incident_resolved':
            this.loadSession();
            break;
          case 'sle_snapshot':
            if (current) {
              this.session.set({
                ...current,
                polls_completed: (msg.data?.['poll_number'] as number) ?? current.polls_completed,
              });
            }
            break;
          case 'timeline_entry':
            if (current && msg.data) {
              const entry = msg.data as unknown as TimelineEntryResponse;
              this.session.set({
                ...current,
                timeline: [...current.timeline, entry],
              });
            }
            break;
          case 'validation_completed':
          case 'ai_analysis_completed':
            this.loadSession();
            break;
          case 'impact_severity_changed':
            if (current && msg.data) {
              this.session.set({
                ...current,
                impact_severity: (msg.data['severity'] as string) || current.impact_severity,
              });
            }
            break;
          case 'session_failed':
            this.loadSession();
            break;
        }
      });
  }

  ngOnDestroy(): void {
    this.topbarService.clearActions();
    this.stopTimeProgress();
  }
}
