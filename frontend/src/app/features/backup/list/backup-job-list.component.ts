import { Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
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
import { TopbarService } from '../../../core/services/topbar.service';
import {
  BackupJobResponse,
  BackupJobListResponse,
  BackupJobStatsResponse,
} from '../../../core/models/backup.model';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { BackupCreateDialogComponent } from './backup-create-dialog.component';
import { BackupChartCardComponent } from '../shared/backup-chart-card.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import {
  CHART_COLORS,
  baseChartOptions,
  barDataset,
  lineDataset,
} from '../../../shared/utils/chart-defaults';

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
    EmptyStateComponent,
    StatusBadgeComponent,
    BackupChartCardComponent,
    DateTimePipe,
  ],
  templateUrl: './backup-job-list.component.html',
  styleUrl: './backup-job-list.component.scss',
})
export class BackupJobListComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);
  private readonly topbarService = inject(TopbarService);

  // ── Job table ────────────────────────────────────────────────────────
  jobs = signal<BackupJobResponse[]>([]);
  jobsTotal = signal(0);
  jobsPageSize = 25;
  jobsPageIndex = 0;
  loadingJobs = signal(true);
  jobColumns = ['status', 'backup_type', 'object_count', 'size', 'created_at'];

  // ── Chart ────────────────────────────────────────────────────────────
  chartConfig = signal<ChartConfiguration<'bar'> | null>(null);

  ngOnInit(): void {
    this.topbarService.setTitle('Backup Jobs');
    this.loadJobs();
    this.loadCharts();
  }

  // ── Data loading ─────────────────────────────────────────────────────

  loadJobs(): void {
    this.loadingJobs.set(true);
    const params: Record<string, string | number> = {
      skip: this.jobsPageIndex * this.jobsPageSize,
      limit: this.jobsPageSize,
    };
    this.api.get<BackupJobListResponse>('/backups', params).subscribe({
      next: (res) => {
        this.jobs.set(res.backups);
        this.jobsTotal.set(res.total);
        this.loadingJobs.set(false);
      },
      error: () => {
        this.loadingJobs.set(false);
      },
    });
  }

  private loadCharts(): void {
    this.api.get<BackupJobStatsResponse>('/backups/stats/jobs').subscribe({
      next: (res) => {
        const labels = res.days.map((d) => d.date.slice(5));

        this.chartConfig.set({
          type: 'bar',
          data: {
            labels,
            datasets: [
              barDataset(
                'Webhook events',
                res.days.map((d) => d.webhook_events),
                CHART_COLORS.webhooks,
              ),
              barDataset(
                'Completed',
                res.days.map((d) => d.completed),
                CHART_COLORS.completed,
              ),
              barDataset(
                'Failed',
                res.days.map((d) => d.failed),
                CHART_COLORS.failed,
              ),
              lineDataset(
                'Avg duration (s)',
                res.days.map((d) => d.avg_duration_seconds ?? 0),
                CHART_COLORS.durationLine,
              ),
            ],
          },
          options: baseChartOptions('Count', 'Duration (s)'),
        });
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
