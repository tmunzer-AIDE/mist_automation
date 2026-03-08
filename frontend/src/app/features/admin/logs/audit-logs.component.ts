import { Component, ChangeDetectorRef, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MatTableModule } from '@angular/material/table';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ApiService } from '../../../core/services/api.service';
import { AuditLogEntry, AuditLogListResponse } from '../../../core/models/admin.model';
import { PageHeaderComponent } from '../../../shared/components/page-header/page-header.component';
import { RelativeTimePipe } from '../../../shared/pipes/relative-time.pipe';

const EVENT_TYPES = [
  'user_login', 'user_logout', 'user_created', 'user_updated', 'user_deleted',
  'settings_updated', 'workflow_created', 'workflow_updated', 'workflow_deleted',
  'backup_created', 'backup_restored',
];

@Component({
  selector: 'app-audit-logs',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatTableModule,
    MatPaginatorModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    PageHeaderComponent,
    RelativeTimePipe,
  ],
  templateUrl: './audit-logs.component.html',
  styleUrl: './audit-logs.component.scss',
})
export class AuditLogsComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly fb = inject(FormBuilder);
  private readonly cdr = inject(ChangeDetectorRef);

  logs: AuditLogEntry[] = [];
  total = 0;
  pageSize = 50;
  pageIndex = 0;
  loading = true;
  eventTypes = EVENT_TYPES;
  displayedColumns = ['timestamp', 'event_type', 'user_email', 'source_ip', 'details'];

  filterForm = this.fb.group({
    event_type: [''],
    user_id: [''],
  });

  ngOnInit(): void {
    this.loadLogs();
  }

  loadLogs(): void {
    this.loading = true;
    const filters = this.filterForm.getRawValue();
    this.api
      .get<AuditLogListResponse>('/admin/logs', {
        skip: this.pageIndex * this.pageSize,
        limit: this.pageSize,
        event_type: filters.event_type || undefined,
        user_id: filters.user_id || undefined,
      })
      .subscribe({
        next: (res) => {
          this.logs = res.logs;
          this.total = res.total;
          this.loading = false;
          this.cdr.detectChanges();
        },
        error: () => {
          this.loading = false;
          this.cdr.detectChanges();
        },
      });
  }

  onPage(event: PageEvent): void {
    this.pageIndex = event.pageIndex;
    this.pageSize = event.pageSize;
    this.loadLogs();
  }

  applyFilters(): void {
    this.pageIndex = 0;
    this.loadLogs();
  }

  clearFilters(): void {
    this.filterForm.reset();
    this.pageIndex = 0;
    this.loadLogs();
  }
}
