import { Component, inject, OnInit, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ApiService } from '../../../core/services/api.service';
import { TopbarService } from '../../../core/services/topbar.service';
import {
  BackupJobResponse,
  BackupLogEntry,
  BackupLogListResponse,
} from '../../../core/models/backup.model';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { FileSizePipe } from '../../../shared/pipes/file-size.pipe';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { RestoreDialogComponent } from './restore-dialog.component';

@Component({
  selector: 'app-backup-detail',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatButtonModule,
    MatIconModule,
    MatDialogModule,
    MatSnackBarModule,
    MatProgressBarModule,
    StatusBadgeComponent,
    FileSizePipe,
    DateTimePipe,
  ],
  templateUrl: './backup-detail.component.html',
  styleUrl: './backup-detail.component.scss',
})
export class BackupDetailComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly topbarService = inject(TopbarService);

  backup = signal<BackupJobResponse | null>(null);
  loading = signal(true);
  jsonExpanded = false;
  webhookExpanded = false;

  // Execution logs
  logs = signal<BackupLogEntry[]>([]);
  logsTotal = signal(0);
  logsLoading = signal(false);
  logLevelFilter: string | null = null;

  ngOnInit(): void {
    this.topbarService.setTitle('Backup Job');
    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.api.get<BackupJobResponse>(`/backups/${id}`).subscribe({
        next: (b) => {
          this.backup.set(b);
          this.topbarService.setTitle(`Backup: ${b.backup_type} — ${b.id.slice(0, 8)}`);
          this.loading.set(false);
          this.loadLogs();
        },
        error: () => {
          this.loading.set(false);
        },
      });
    }
  }

  openRestore(): void {
    const b = this.backup();
    if (!b) return;
    const ref = this.dialog.open(RestoreDialogComponent, {
      width: '450px',
      data: { backupId: b.id },
    });
    ref.afterClosed().subscribe((result) => {
      if (result) {
        this.snackBar.open('Restore initiated', 'OK', { duration: 3000 });
      }
    });
  }

  loadLogs(): void {
    const b = this.backup();
    if (!b) return;
    this.logsLoading.set(true);
    let url = `/backups/${b.id}/logs?limit=500`;
    if (this.logLevelFilter) {
      url += `&level=${this.logLevelFilter}`;
    }
    this.api.get<BackupLogListResponse>(url).subscribe({
      next: (res) => {
        this.logs.set(res.logs);
        this.logsTotal.set(res.total);
        this.logsLoading.set(false);
      },
      error: () => {
        this.logsLoading.set(false);
      },
    });
  }

  filterLogs(level: string | null): void {
    this.logLevelFilter = level;
    this.loadLogs();
  }

  logWarningCount = computed(() => this.logs().filter((l) => l.level === 'warning').length);

  logErrorCount = computed(() => this.logs().filter((l) => l.level === 'error').length);

  getLevelIcon(level: string): string {
    switch (level) {
      case 'error':
        return 'error';
      case 'warning':
        return 'warning';
      default:
        return 'info';
    }
  }

  formatJson(data: unknown): string {
    return JSON.stringify(data, null, 2);
  }
}
