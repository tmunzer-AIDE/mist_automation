import { Component, ChangeDetectorRef, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ApiService } from '../../../core/services/api.service';
import { SystemStats, WorkerStatus } from '../../../core/models/admin.model';
import { PageHeaderComponent } from '../../../shared/components/page-header/page-header.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { LoadingSpinnerComponent } from '../../../shared/components/loading-spinner/loading-spinner.component';

@Component({
  selector: 'app-stats',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatIconModule,
    MatProgressBarModule,
    PageHeaderComponent,
    StatusBadgeComponent,
    LoadingSpinnerComponent,
  ],
  templateUrl: './stats.component.html',
  styleUrl: './stats.component.scss',
})
export class StatsComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly cdr = inject(ChangeDetectorRef);

  stats: SystemStats | null = null;
  workerStatus: WorkerStatus | null = null;
  loading = true;

  ngOnInit(): void {
    this.api.get<SystemStats>('/admin/stats').subscribe({
      next: (s) => {
        this.stats = s;
        this.loading = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.loading = false;
        this.cdr.detectChanges();
      },
    });

    this.api.get<WorkerStatus>('/admin/workers/status').subscribe({
      next: (w) => {
        this.workerStatus = w;
        this.cdr.detectChanges();
      },
      error: () => {},
    });
  }
}
