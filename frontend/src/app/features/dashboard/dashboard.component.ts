import {
  Component,
  computed,
  DestroyRef,
  inject,
  OnDestroy,
  OnInit,
  signal,
  TemplateRef,
  ViewChild,
} from '@angular/core';
import { Router, RouterModule } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { Store } from '@ngrx/store';
import { SkeletonLoaderComponent } from '../../shared/components/skeleton-loader/skeleton-loader.component';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { filter, take, switchMap, catchError } from 'rxjs';
import { of } from 'rxjs';
import { BaseChartDirective } from 'ng2-charts';
import { ChartConfiguration } from 'chart.js/auto';
import { selectCurrentUser } from '../../core/state/auth/auth.selectors';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { ImpactAnalysisService } from '../../core/services/impact-analysis.service';
import { TopbarService } from '../../core/services/topbar.service';
import { GlobalChatService } from '../../core/services/global-chat.service';
import { LlmService } from '../../core/services/llm.service';
import { WebSocketService } from '../../core/services/websocket.service';
import { HealthResponse } from '../../core/models/session.model';
import { UserResponse } from '../../core/models/user.model';
import { SessionSummary } from '../impact-analysis/models/impact-analysis.model';
import { StatusBadgeComponent } from '../../shared/components/status-badge/status-badge.component';
import { AiIconComponent } from '../../shared/components/ai-icon/ai-icon.component';
import { AiSummaryPanelComponent } from '../../shared/components/ai-summary-panel/ai-summary-panel.component';
import { DateTimePipe } from '../../shared/pipes/date-time.pipe';
import { extractErrorMessage } from '../../shared/utils/error.utils';
import {
  DashboardStats,
  DashboardActivity,
  RecentActivityItem,
} from './models/dashboard.model';
import {
  getChartColor,
  baseChartOptions,
  barDataset,
  lineDataset,
} from '../../shared/utils/chart-defaults';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    RouterModule,
    MatIconModule,
    MatButtonModule,
    SkeletonLoaderComponent,
    BaseChartDirective,
    StatusBadgeComponent,
    AiIconComponent,
    AiSummaryPanelComponent,
    DateTimePipe,
  ],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent implements OnInit, OnDestroy {
  private readonly store = inject(Store);
  private readonly api = inject(ApiService);
  private readonly authService = inject(AuthService);
  private readonly impactService = inject(ImpactAnalysisService);
  private readonly wsService = inject(WebSocketService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly router = inject(Router);
  private readonly topbarService = inject(TopbarService);
  private readonly globalChat = inject(GlobalChatService);
  private readonly llmService = inject(LlmService);

  @ViewChild('topbarActions', { static: true }) topbarActions!: TemplateRef<unknown>;

  // AI Summary
  llmAvailable = signal(false);
  aiPanelOpen = signal(false);
  aiLoading = signal(false);
  aiSummary = signal<string | null>(null);
  aiError = signal<string | null>(null);
  aiThreadId = signal<string | null>(null);

  user = signal<UserResponse | null>(null);
  stats = signal<DashboardStats | null>(null);
  health = signal<HealthResponse | null>(null);
  impactSummary = signal<SessionSummary | null>(null);
  loading = signal(true);
  chartConfig = signal<ChartConfiguration<'bar'> | null>(null);

  // Role-based computed signals
  isAdmin = computed(() => this.user()?.roles.includes('admin') ?? false);
  hasAutomation = computed(() => {
    const r = this.user()?.roles ?? [];
    return r.includes('admin') || r.includes('automation');
  });
  hasBackup = computed(() => {
    const r = this.user()?.roles ?? [];
    return r.includes('admin') || r.includes('backup');
  });
  hasReports = computed(() => {
    const r = this.user()?.roles ?? [];
    return r.includes('admin') || r.includes('post_deployment');
  });
  hasImpactAnalysis = computed(() => {
    const r = this.user()?.roles ?? [];
    return r.includes('admin') || r.includes('impact_analysis');
  });
  hasAnyModuleRole = computed(
    () =>
      this.hasAutomation() || this.hasBackup() || this.hasReports() || this.hasImpactAnalysis(),
  );

  recentItems = computed(() => this.stats()?.recent ?? []);
  highlights = computed(() => this.stats()?.highlights ?? []);
  displayName = computed(() => {
    const u = this.user();
    return u?.first_name ?? u?.email?.split('@')[0] ?? 'there';
  });
  statsWindowDays = computed(() => this.stats()?.stats_window_days ?? 7);

  ngOnInit(): void {
    this.topbarService.setTitle('Dashboard');
    this.topbarService.setActions(this.topbarActions);
    this.globalChat.setContext({ page: 'Dashboard', details: { view: 'System overview' } });
    this.llmService.getStatus().subscribe({
      next: (s) => this.llmAvailable.set(s.enabled),
      error: () => {},
    });
    this.authService.checkHealth().subscribe({
      next: (h) => this.health.set(h),
    });

    this.store
      .select(selectCurrentUser)
      .pipe(
        filter((u): u is UserResponse => u !== null),
        take(1),
        switchMap((u) => {
          this.user.set(u);
          this.loadImpactSummary(u);
          return this.api
            .get<DashboardStats>('/dashboard/stats')
            .pipe(catchError(() => of(null)));
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((data) => {
        this.stats.set(data);
        if (data?.activity) {
          this.buildChart(data.activity);
        }
        this.loading.set(false);
      });
  }

  navigateTo(route: string): void {
    this.router.navigate([route]);
  }

  recentIcon(item: RecentActivityItem): string {
    switch (item.type) {
      case 'execution':
        return 'play_circle';
      case 'backup':
        return 'backup';
      case 'report':
        return 'assessment';
    }
  }

  recentRoute(item: RecentActivityItem): void {
    switch (item.type) {
      case 'execution':
        this.router.navigate(['/workflows']);
        break;
      case 'backup':
        this.router.navigate(['/backup', item.id]);
        break;
      case 'report':
        this.router.navigate(['/reports', item.id]);
        break;
    }
  }

  private loadImpactSummary(user: UserResponse): void {
    const roles = user.roles ?? [];
    if (!roles.includes('admin') && !roles.includes('impact_analysis')) {
      return;
    }
    this.impactService
      .getSummary()
      .pipe(catchError(() => of(null)))
      .subscribe((summary) => this.impactSummary.set(summary));

    this.wsService
      .subscribe<{ type: string }>('impact:summary')
      .pipe(
        filter((msg) => msg.type === 'summary_update'),
        switchMap(() => this.impactService.getSummary()),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((summary) => this.impactSummary.set(summary));
  }

  private buildChart(activity: DashboardActivity): void {
    const labels = activity.labels;
    const datasets: ChartConfiguration<'bar'>['data']['datasets'] = [];

    if (activity.executions) {
      datasets.push(
        barDataset(
          'Exec. succeeded',
          activity.executions.succeeded,
          getChartColor('completed'),
          'executions',
        ),
      );
      datasets.push(
        barDataset(
          'Exec. failed',
          activity.executions.failed,
          getChartColor('failed'),
          'executions',
        ),
      );
    }

    if (activity.backups) {
      datasets.push(
        barDataset(
          'Backups OK',
          activity.backups.completed,
          getChartColor('objects'),
          'backups',
        ),
      );
      datasets.push(
        barDataset(
          'Backups failed',
          activity.backups.failed,
          getChartColor('backup-fail'),
          'backups',
        ),
      );
    }

    if (activity.webhooks) {
      datasets.push(
        lineDataset('Webhooks', activity.webhooks.received, getChartColor('webhooks')),
      );
    }

    const hasLine = !!activity.webhooks;
    const options = baseChartOptions('Count', hasLine ? 'Webhooks' : '');
    if (!hasLine && options?.scales) {
      (options.scales as Record<string, unknown>)['y1'] = { display: false };
    }

    this.chartConfig.set({ type: 'bar', data: { labels, datasets }, options });
  }

  ngOnDestroy(): void {
    this.topbarService.clearActions();
  }

  summarize(): void {
    this.aiPanelOpen.set(true);
    this.aiLoading.set(true);
    this.aiSummary.set(null);
    this.aiError.set(null);

    this.llmService.summarizeDashboard().subscribe({
      next: (res) => {
        this.aiThreadId.set(res.thread_id);
        this.aiSummary.set(res.summary);
        this.aiLoading.set(false);
      },
      error: (err) => {
        this.aiError.set(extractErrorMessage(err));
        this.aiLoading.set(false);
      },
    });
  }
}
