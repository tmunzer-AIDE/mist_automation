import { Component, ChangeDetectorRef, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ApiService } from '../../../core/services/api.service';
import { BackupJobListResponse, BackupJobResponse } from '../../../core/models/backup.model';
import { PageHeaderComponent } from '../../../shared/components/page-header/page-header.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { RelativeTimePipe } from '../../../shared/pipes/relative-time.pipe';
import { FileSizePipe } from '../../../shared/pipes/file-size.pipe';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';

@Component({
  selector: 'app-backup-timeline',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    PageHeaderComponent,
    StatusBadgeComponent,
    RelativeTimePipe,
    FileSizePipe,
    EmptyStateComponent,
  ],
  templateUrl: './backup-timeline.component.html',
  styleUrl: './backup-timeline.component.scss',
})
export class BackupTimelineComponent {
  private readonly api = inject(ApiService);
  private readonly fb = inject(FormBuilder);
  private readonly cdr = inject(ChangeDetectorRef);

  entries: BackupJobResponse[] = [];
  loading = false;
  loaded = false;

  filterForm = this.fb.group({
    org_id: ['', Validators.required],
    site_id: [''],
  });

  loadTimeline(): void {
    if (this.filterForm.invalid) return;
    this.loading = true;
    const { org_id, site_id } = this.filterForm.getRawValue();

    this.api
      .get<BackupJobListResponse>('/backups', {
        org_id: org_id!,
        site_id: site_id || undefined,
        limit: 100,
      })
      .subscribe({
        next: (res) => {
          this.entries = res.backups;
          this.loading = false;
          this.loaded = true;
          this.cdr.detectChanges();
        },
        error: () => {
          this.loading = false;
          this.loaded = true;
          this.cdr.detectChanges();
        },
      });
  }
}
