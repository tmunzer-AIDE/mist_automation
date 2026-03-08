import { Component, ChangeDetectorRef, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ApiService } from '../../../core/services/api.service';
import { BackupJobResponse } from '../../../core/models/backup.model';
import { PageHeaderComponent } from '../../../shared/components/page-header/page-header.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { LoadingSpinnerComponent } from '../../../shared/components/loading-spinner/loading-spinner.component';
import { FileSizePipe } from '../../../shared/pipes/file-size.pipe';
import { RelativeTimePipe } from '../../../shared/pipes/relative-time.pipe';
import { RestoreDialogComponent } from './restore-dialog.component';

@Component({
  selector: 'app-backup-detail',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatDialogModule,
    MatSnackBarModule,
    MatProgressBarModule,
    PageHeaderComponent,
    StatusBadgeComponent,
    LoadingSpinnerComponent,
    FileSizePipe,
    RelativeTimePipe,
  ],
  templateUrl: './backup-detail.component.html',
  styleUrl: './backup-detail.component.scss',
})
export class BackupDetailComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly cdr = inject(ChangeDetectorRef);

  backup: BackupJobResponse | null = null;
  loading = true;
  jsonExpanded = false;

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.api.get<BackupJobResponse>(`/backups/${id}`).subscribe({
        next: (b) => {
          this.backup = b;
          this.loading = false;
          this.cdr.detectChanges();
        },
        error: () => {
          this.loading = false;
          this.cdr.detectChanges();
        },
      });
    }
  }

  openRestore(): void {
    if (!this.backup) return;
    const ref = this.dialog.open(RestoreDialogComponent, {
      width: '450px',
      data: { backupId: this.backup.id },
    });
    ref.afterClosed().subscribe((result) => {
      if (result) {
        this.snackBar.open('Restore initiated', 'OK', { duration: 3000 });
      }
    });
  }

  formatJson(data: unknown): string {
    return JSON.stringify(data, null, 2);
  }
}
