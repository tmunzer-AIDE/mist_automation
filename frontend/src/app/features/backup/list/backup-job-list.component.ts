import { Component, ChangeDetectorRef, inject, OnInit } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { MatTableModule } from '@angular/material/table';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { BaseChartDirective } from 'ng2-charts';
import { ChartConfiguration } from 'chart.js/auto';
import { ApiService } from '../../../core/services/api.service';
import {
  BackupJobResponse,
  BackupJobListResponse,
  BackupJobStatsResponse,
} from '../../../core/models/backup.model';
import { PageHeaderComponent } from '../../../shared/components/page-header/page-header.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { BackupCreateDialogComponent } from './backup-create-dialog.component';
import { BackupChartCardComponent } from '../shared/backup-chart-card.component';

@Component({
  selector: 'app-backup-job-list',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatTableModule,
    MatPaginatorModule,
    MatButtonModule,
    MatIconModule,
    MatDialogModule,
    MatProgressBarModule,
    MatSnackBarModule,
    BaseChartDirective,
    PageHeaderComponent,
    EmptyStateComponent,
    StatusBadgeComponent,
    BackupChartCardComponent,
    DatePipe,
  ],
  templateUrl: './backup-job-list.component.html',
  styleUrl: './backup-job-list.component.scss',
})
export class BackupJobListComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);
  private readonly cdr = inject(ChangeDetectorRef);

  // ── Job table ────────────────────────────────────────────────────────
  jobs: BackupJobResponse[] = [];
  jobsTotal = 0;
  jobsPageSize = 10;
  jobsPageIndex = 0;
  loadingJobs = true;
  jobColumns = ['status', 'backup_type', 'object_count', 'size', 'created_at'];

  // ── Chart ────────────────────────────────────────────────────────────
  chartConfig: ChartConfiguration<'bar'> | null = null;

  ngOnInit(): void {
    this.loadJobs();
    this.loadCharts();
  }

  // ── Data loading ─────────────────────────────────────────────────────

  loadJobs(): void {
    this.loadingJobs = true;
    const params: Record<string, string | number> = {
      skip: this.jobsPageIndex * this.jobsPageSize,
      limit: this.jobsPageSize,
    };
    this.api.get<BackupJobListResponse>('/backups', params).subscribe({
      next: (res) => {
        this.jobs = res.backups;
        this.jobsTotal = res.total;
        this.loadingJobs = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.loadingJobs = false;
        this.cdr.detectChanges();
      },
    });
  }

  private loadCharts(): void {
    const completed = '#2563eb';   // vivid blue
    const failed = '#ef4444';      // vivid red
    const webhooks = '#8b5cf6';    // vivid violet
    const durationLine = '#f59e0b'; // vivid amber
    const gridColor = '#e2e8f0';

    this.api.get<BackupJobStatsResponse>('/backups/stats/jobs').subscribe({
      next: (res) => {
        const labels = res.days.map((d) => d.date.slice(5));

        this.chartConfig = {
          type: 'bar',
          data: {
            labels,
            datasets: [
              {
                label: 'Webhook events',
                data: res.days.map((d) => d.webhook_events),
                backgroundColor: webhooks,
                borderRadius: 2,
                stack: 'jobs',
                order: 1,
                yAxisID: 'y',
              },
              {
                label: 'Completed',
                data: res.days.map((d) => d.completed),
                backgroundColor: completed,
                borderRadius: 2,
                stack: 'jobs',
                order: 1,
                yAxisID: 'y',
              },
              {
                label: 'Failed',
                data: res.days.map((d) => d.failed),
                backgroundColor: failed,
                borderRadius: 2,
                stack: 'jobs',
                order: 1,
                yAxisID: 'y',
              },
              {
                label: 'Avg duration (s)',
                data: res.days.map((d) => d.avg_duration_seconds),
                type: 'line' as const,
                borderColor: durationLine,
                backgroundColor: 'transparent',
                fill: false,
                pointRadius: 2,
                tension: 0.3,
                borderWidth: 2,
                order: 0,
                yAxisID: 'y1',
              } as any,
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: true } },
            scales: {
              x: {
                grid: { display: false },
                ticks: { maxTicksLimit: 15, font: { size: 10 } },
              },
              y: {
                position: 'left',
                stacked: true,
                beginAtZero: true,
                grid: { color: gridColor },
                ticks: { precision: 0, font: { size: 10 } },
                title: { display: true, text: 'Count', font: { size: 11 } },
              },
              y1: {
                position: 'right',
                beginAtZero: true,
                grid: { drawOnChartArea: false },
                ticks: { font: { size: 10 } },
                title: { display: true, text: 'Duration (s)', font: { size: 11 } },
              },
            },
          },
        };
        this.cdr.detectChanges();
      },
    });
  }

  // ── Pagination ───────────────────────────────────────────────────────

  onJobsPage(event: PageEvent): void {
    this.jobsPageIndex = event.pageIndex;
    this.jobsPageSize = event.pageSize;
    this.loadJobs();
  }

  // ── Actions ──────────────────────────────────────────────────────────

  viewJobDetail(job: BackupJobResponse): void {
    this.router.navigate(['/backup', job.id]);
  }

  navigateToBackups(): void {
    this.router.navigate(['/backup']);
  }

  openCreateDialog(): void {
    const ref = this.dialog.open(BackupCreateDialogComponent, { width: '500px' });
    ref.afterClosed().subscribe((result) => {
      if (result) {
        this.snackBar.open('Backup job created', 'OK', { duration: 3000 });
        setTimeout(() => this.loadJobs(), 2000);
      }
    });
  }
}
