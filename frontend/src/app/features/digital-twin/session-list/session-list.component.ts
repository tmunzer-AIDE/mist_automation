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
import { LayerRollup, computeLayerRollup } from '../utils/layer-rollup';

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
    { value: 'mcp', label: 'MCP' },
    { value: 'workflow', label: 'Workflow' },
    { value: 'backup_restore', label: 'Backup Restore' },
  ];

  readonly displayedColumns = [
    'status',
    'source',
    'object',
    'sites',
    'severity',
    'layers',
    'created_at',
  ];

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
    const params: {
      skip: number;
      limit: number;
      status?: string;
      source?: string;
      search?: string;
    } = {
      skip: this.pageIndex * this.pageSize,
      limit: this.pageSize,
    };
    const status = this.statusFilter.value;
    if (status) params.status = status;
    const source = this.sourceFilter.value;
    if (source) params.source = source;
    const search = this.searchControl.value?.trim();
    if (search) params.search = search;

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

  layerRollupFor(summary: TwinSessionSummary): LayerRollup[] {
    return computeLayerRollup(summary.prediction_report);
  }

  sourceLabel(summary: TwinSessionSummary): string {
    switch (summary.source) {
      case 'mcp':
        return 'MCP';
      case 'workflow':
        return 'Workflow';
      case 'backup_restore':
        return 'Backup Restore';
      default:
        return summary.source;
    }
  }

  sourceSubLabel(summary: TwinSessionSummary): string | null {
    if (summary.source === 'mcp') return summary.source_ref ?? 'Internal Chat';
    return summary.source_ref;
  }

  objectTypeBadge(summary: TwinSessionSummary): string {
    if (summary.affected_object_types.length === 0) return '—';
    if (summary.affected_object_types.length === 1) return summary.affected_object_types[0];
    return 'multiple';
  }

  objectLabel(summary: TwinSessionSummary): string {
    return summary.affected_object_label ?? '—';
  }

  sitesLabel(summary: TwinSessionSummary): string {
    const count = summary.affected_sites.length;
    if (count === 0) return '—';
    return `${count} site${count === 1 ? '' : 's'}`;
  }

  sitesTooltip(summary: TwinSessionSummary): string {
    const names = summary.affected_site_labels ?? [];
    if (names.length === 0) return '';
    if (names.length <= 10) return names.join(', ');
    return `${names.slice(0, 10).join(', ')}, +${names.length - 10} more`;
  }
}
