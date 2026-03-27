import { Component, inject, OnInit, signal } from '@angular/core';
import { Router } from '@angular/router';
import { MatTableModule } from '@angular/material/table';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../../core/services/api.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { GlobalChatService } from '../../../core/services/global-chat.service';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { ConfirmDialogComponent } from '../../../shared/components/confirm-dialog/confirm-dialog.component';
import { ReportCreateDialogComponent } from '../report-create/report-create-dialog.component';

interface ReportJob {
  id: string;
  report_type: string;
  site_id: string;
  site_name: string;
  status: string;
  progress: { current_step: string; completed: number; total: number; details: string };
  error: string | null;
  created_by: string;
  created_at: string;
  completed_at: string | null;
}

interface ReportListResponse {
  reports: ReportJob[];
  total: number;
}

@Component({
  selector: 'app-report-list',
  standalone: true,
  imports: [
    MatTableModule,
    MatPaginatorModule,
    MatButtonModule,
    MatIconModule,
    MatDialogModule,
    MatProgressBarModule,
    MatSnackBarModule,
    MatTooltipModule,
    StatusBadgeComponent,
    EmptyStateComponent,
    DateTimePipe,
  ],
  templateUrl: './report-list.component.html',
  styleUrl: './report-list.component.scss',
})
export class ReportListComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);
  private readonly topbarService = inject(TopbarService);
  private readonly globalChatService = inject(GlobalChatService);

  reports = signal<ReportJob[]>([]);
  total = signal(0);
  loading = signal(true);
  pageSize = 25;
  pageIndex = 0;
  displayedColumns = ['status', 'site_name', 'report_type', 'created_at', 'actions'];

  ngOnInit(): void {
    this.topbarService.setTitle('Reports');
    this.globalChatService.setContext({ page: 'Reports' });
    this.loadReports();
  }

  loadReports(): void {
    this.loading.set(true);
    this.api
      .get<ReportListResponse>('/reports/validation', {
        skip: this.pageIndex * this.pageSize,
        limit: this.pageSize,
      })
      .subscribe({
        next: (res) => {
          this.reports.set(res.reports);
          this.total.set(res.total);
          this.loading.set(false);
        },
        error: () => this.loading.set(false),
      });
  }

  onPage(event: PageEvent): void {
    this.pageIndex = event.pageIndex;
    this.pageSize = event.pageSize;
    this.loadReports();
  }

  viewReport(report: ReportJob): void {
    this.router.navigate(['/reports', report.id]);
  }

  openCreateDialog(): void {
    const ref = this.dialog.open(ReportCreateDialogComponent, { width: '450px' });
    ref.afterClosed().subscribe((reportId: string | undefined) => {
      if (reportId) {
        this.router.navigate(['/reports', reportId]);
      }
    });
  }

  deleteReport(event: Event, report: ReportJob): void {
    event.stopPropagation();
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: { title: 'Delete Report', message: `Delete the report for site "${report.site_name}"?` },
    });
    ref.afterClosed().subscribe((confirmed) => {
      if (confirmed) {
        this.api.delete(`/reports/validation/${report.id}`).subscribe({
          next: () => {
            this.snackBar.open('Report deleted', 'OK', { duration: 3000 });
            this.loadReports();
          },
          error: () => this.snackBar.open('Failed to delete report', 'OK', { duration: 3000 }),
        });
      }
    });
  }

  formatReportType(type: string): string {
    return type
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }
}
