import { Component, DestroyRef, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { debounceTime, distinctUntilChanged } from 'rxjs';
import { MatTableModule } from '@angular/material/table';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { SkeletonLoaderComponent } from '../../../shared/components/skeleton-loader/skeleton-loader.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { TopbarService } from '../../../core/services/topbar.service';
import { DigitalTwinService } from '../digital-twin.service';
import { TwinSessionSummary } from '../models/twin-session.model';

@Component({
  selector: 'app-digital-twin-session-list',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatTableModule,
    MatPaginatorModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatTooltipModule,
    SkeletonLoaderComponent,
    StatusBadgeComponent,
    EmptyStateComponent,
    DateTimePipe,
  ],
  templateUrl: './session-list.component.html',
  styleUrl: './session-list.component.scss',
})
export class SessionListComponent implements OnInit, OnDestroy {
  private readonly service = inject(DigitalTwinService);
  private readonly router = inject(Router);
  private readonly topbarService = inject(TopbarService);
  private readonly destroyRef = inject(DestroyRef);

  sessions = signal<TwinSessionSummary[]>([]);
  total = signal(0);
  loading = signal(true);
  pageSize = 25;
  pageIndex = 0;

  statusFilter = new FormControl<string>('');
  sourceFilter = new FormControl<string>('');
  searchControl = new FormControl<string>('');

  readonly statusOptions = [
    { value: 'awaiting_approval', label: 'Awaiting Approval' },
    { value: 'validating', label: 'Validating' },
    { value: 'deployed', label: 'Deployed' },
    { value: 'rejected', label: 'Rejected' },
    { value: 'failed', label: 'Failed' },
  ];

  readonly sourceOptions = [
    { value: 'llm_chat', label: 'LLM Chat' },
    { value: 'workflow', label: 'Workflow' },
    { value: 'backup_restore', label: 'Backup Restore' },
  ];

  readonly displayedColumns = ['status', 'source', 'severity', 'checks', 'writes', 'created_at'];

  ngOnInit(): void {
    this.topbarService.setTitle('Digital Twin');
    this.loadSessions();

    this.searchControl.valueChanges
      .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.pageIndex = 0;
        this.loadSessions();
      });
  }

  ngOnDestroy(): void {
    this.topbarService.clearActions();
  }

  loadSessions(): void {
    this.loading.set(true);
    const params: Record<string, string | number> = {
      skip: this.pageIndex * this.pageSize,
      limit: this.pageSize,
    };
    const status = this.statusFilter.value;
    if (status) params['status'] = status;
    const source = this.sourceFilter.value;
    if (source) params['source'] = source;
    const search = this.searchControl.value?.trim();
    if (search) params['search'] = search;

    this.service.listSessions(params).subscribe({
      next: (res) => {
        this.sessions.set(res.sessions);
        this.total.set(res.total);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  onStatusChange(): void {
    this.pageIndex = 0;
    this.loadSessions();
  }

  onSourceChange(): void {
    this.pageIndex = 0;
    this.loadSessions();
  }

  onPage(event: PageEvent): void {
    this.pageIndex = event.pageIndex;
    this.pageSize = event.pageSize;
    this.loadSessions();
  }

  viewSession(session: TwinSessionSummary): void {
    this.router.navigate(['/digital-twin', session.id]);
  }

  severityClass(severity: string): string {
    switch (severity) {
      case 'critical':
        return 'severity-critical';
      case 'error':
        return 'severity-error';
      case 'warning':
        return 'severity-warning';
      case 'info':
        return 'severity-info';
      default:
        return 'severity-clean';
    }
  }

  severityLabel(severity: string): string {
    if (!severity || severity === 'clean' || severity === 'info') {
      return severity === 'info' ? 'Info' : 'Safe';
    }
    return severity.charAt(0).toUpperCase() + severity.slice(1);
  }

  sourceLabel(source: string): string {
    return this.sourceOptions.find((o) => o.value === source)?.label ?? source;
  }

  failedCount(session: TwinSessionSummary): number {
    if (!session.prediction_report) return 0;
    return (session.prediction_report.errors ?? 0) + (session.prediction_report.critical ?? 0);
  }

  warnCount(session: TwinSessionSummary): number {
    return session.prediction_report?.warnings ?? 0;
  }
}
