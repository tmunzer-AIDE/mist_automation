import { Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatTableModule } from '@angular/material/table';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSelectModule } from '@angular/material/select';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
  ImpactAnalysisService,
  SessionListResponse,
} from '../../../core/services/impact-analysis.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { GlobalChatService } from '../../../core/services/global-chat.service';
import { WebSocketService } from '../../../core/services/websocket.service';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { SessionResponse } from '../models/impact-analysis.model';
import {
  deviceTypeIcon as _deviceTypeIcon,
  formatDeviceType as _formatDeviceType,
} from '../utils/device-type.utils';

@Component({
  selector: 'app-session-list',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatTableModule,
    MatPaginatorModule,
    MatButtonModule,
    MatIconModule,
    MatSelectModule,
    MatFormFieldModule,
    MatChipsModule,
    MatProgressBarModule,
    MatTooltipModule,
    StatusBadgeComponent,
    EmptyStateComponent,
    DateTimePipe,
  ],
  templateUrl: './session-list.component.html',
  styleUrl: './session-list.component.scss',
})
export class SessionListComponent implements OnInit {
  private readonly service = inject(ImpactAnalysisService);
  private readonly router = inject(Router);
  private readonly topbarService = inject(TopbarService);
  private readonly globalChatService = inject(GlobalChatService);
  private readonly wsService = inject(WebSocketService);
  private readonly destroyRef = inject(DestroyRef);

  sessions = signal<SessionResponse[]>([]);
  total = signal(0);
  loading = signal(true);
  pageSize = 25;
  pageIndex = 0;

  statusFilter = new FormControl<string>('');
  activeDeviceType = signal<string>('');

  displayedColumns = [
    'status',
    'device_name',
    'device_type',
    'site_name',
    'config_change_count',
    'progress',
    'created_at',
    'has_impact',
  ];

  readonly deviceTypes = ['ap', 'switch', 'gateway'];

  ngOnInit(): void {
    this.topbarService.setTitle('Impact Analysis');
    this.globalChatService.setContext({ page: 'Impact Analysis', details: { view: 'Session list' } });
    this.loadSessions();
    this.subscribeToSummary();
  }

  loadSessions(): void {
    this.loading.set(true);
    const params: Record<string, string | number> = {
      skip: this.pageIndex * this.pageSize,
      limit: this.pageSize,
    };
    const status = this.statusFilter.value;
    if (status) params['status'] = status;
    const deviceType = this.activeDeviceType();
    if (deviceType) params['device_type'] = deviceType;

    this.service.getSessions(params).subscribe({
      next: (res: SessionListResponse) => {
        this.sessions.set(res.sessions);
        this.total.set(res.total);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  onPage(event: PageEvent): void {
    this.pageIndex = event.pageIndex;
    this.pageSize = event.pageSize;
    this.loadSessions();
  }

  onStatusChange(): void {
    this.pageIndex = 0;
    this.loadSessions();
  }

  toggleDeviceType(type: string): void {
    this.activeDeviceType.set(this.activeDeviceType() === type ? '' : type);
    this.pageIndex = 0;
    this.loadSessions();
  }

  viewSession(session: SessionResponse): void {
    this.router.navigate(['/impact-analysis', session.id]);
  }

  formatDeviceType = _formatDeviceType;

  deviceTypeIcon = _deviceTypeIcon;

  progressText(session: SessionResponse): string {
    if (session.status === 'completed' || session.status === 'cancelled') {
      return session.status;
    }
    if (session.polls_total > 0) {
      return `${session.polls_completed} / ${session.polls_total}`;
    }
    return session.status;
  }

  progressPercent(session: SessionResponse): number {
    if (session.status === 'completed') return 100;
    if (session.polls_total <= 0) return 0;
    return Math.round((session.polls_completed / session.polls_total) * 100);
  }

  private subscribeToSummary(): void {
    this.wsService
      .subscribe<{ type: string; data: unknown }>('impact:summary')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((msg) => {
        if (msg.type === 'summary_update') {
          this.loadSessions();
        }
      });
  }
}
