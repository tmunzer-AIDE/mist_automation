import { Component, DestroyRef, inject, OnDestroy, OnInit, signal, TemplateRef, ViewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MatTableModule } from '@angular/material/table';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../../core/services/api.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { AuditLogEntry, AuditLogListResponse } from '../../../core/models/admin.model';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';

const EVENT_TYPES = [
  'user_login',
  'user_logout',
  'user_created',
  'user_updated',
  'user_deleted',
  'settings_updated',
  'workflow_created',
  'workflow_updated',
  'workflow_deleted',
  'backup_created',
  'backup_restored',
  'password_changed',
];

@Component({
  selector: 'app-audit-logs',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatTableModule,
    MatPaginatorModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatSnackBarModule,
    MatTooltipModule,
    DateTimePipe,
  ],
  templateUrl: './audit-logs.component.html',
  styleUrl: './audit-logs.component.scss',
})
export class AuditLogsComponent implements OnInit, OnDestroy {
  @ViewChild('actions', { static: true }) actionsTpl!: TemplateRef<unknown>;

  private readonly api = inject(ApiService);
  private readonly fb = inject(FormBuilder);
  private readonly topbarService = inject(TopbarService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);

  logs = signal<AuditLogEntry[]>([]);
  total = signal(0);
  pageSize = signal(25);
  pageIndex = signal(0);
  loading = signal(true);
  exporting = signal(false);
  eventTypes = EVENT_TYPES;
  displayedColumns = ['timestamp', 'event_type', 'description', 'user_email', 'source_ip', 'success'];

  filterForm = this.fb.group({
    event_type: [''],
    user_id: [''],
    start_date: [''],
    end_date: [''],
  });

  ngOnInit(): void {
    this.topbarService.setTitle('Audit Logs');
    this.topbarService.setActions(this.actionsTpl);
    this.loadLogs();
  }

  ngOnDestroy(): void {
    this.topbarService.clearActions();
  }

  private buildFilterBody(): Record<string, string> {
    const f = this.filterForm.getRawValue();
    const body: Record<string, string> = {};
    if (f.event_type) body['event_type'] = f.event_type;
    if (f.user_id) body['user_id'] = f.user_id;
    if (f.start_date) body['start_date'] = new Date(f.start_date).toISOString();
    if (f.end_date) body['end_date'] = new Date(f.end_date + 'T23:59:59').toISOString();
    return body;
  }

  loadLogs(): void {
    this.loading.set(true);
    const filters = this.buildFilterBody();
    const params: Record<string, string | number | boolean | undefined> = {
      ...filters,
      skip: this.pageIndex() * this.pageSize(),
      limit: this.pageSize(),
    };

    this.api
      .get<AuditLogListResponse>('/admin/logs', params)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.logs.set(res.logs);
          this.total.set(res.total);
          this.loading.set(false);
        },
        error: () => {
          this.loading.set(false);
        },
      });
  }

  onPage(event: PageEvent): void {
    this.pageIndex.set(event.pageIndex);
    this.pageSize.set(event.pageSize);
    this.loadLogs();
  }

  applyFilters(): void {
    this.pageIndex.set(0);
    this.loadLogs();
  }

  clearFilters(): void {
    this.filterForm.reset();
    this.pageIndex.set(0);
    this.loadLogs();
  }

  exportCsv(): void {
    this.exporting.set(true);
    const body = this.buildFilterBody();

    this.api
      .postBlob('/admin/logs/export', body)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob: Blob) => {
          this.exporting.set(false);
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `audit_logs_${new Date().toISOString().slice(0, 10)}.csv`;
          a.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        },
        error: () => {
          this.exporting.set(false);
          this.snackBar.open('Export failed', 'OK', { duration: 5000 });
        },
      });
  }
}
