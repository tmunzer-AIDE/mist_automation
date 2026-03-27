import { Component, inject, OnInit, signal } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ApiService } from '../../../core/services/api.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { GlobalChatService } from '../../../core/services/global-chat.service';
import { SystemStats, WorkerStatus } from '../../../core/models/admin.model';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
@Component({
  selector: 'app-stats',
  standalone: true,
  imports: [
    MatCardModule,
    MatIconModule,
    MatProgressBarModule,
    StatusBadgeComponent,
  ],
  templateUrl: './stats.component.html',
  styleUrl: './stats.component.scss',
})
export class StatsComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly topbarService = inject(TopbarService);
  private readonly globalChatService = inject(GlobalChatService);

  stats = signal<SystemStats | null>(null);
  workerStatus = signal<WorkerStatus | null>(null);
  loading = signal(true);

  ngOnInit(): void {
    this.topbarService.setTitle('System Stats');
    this.globalChatService.setContext({ page: 'Admin > System Stats' });
    this.api.get<SystemStats>('/admin/stats').subscribe({
      next: (s) => {
        this.stats.set(s);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
      },
    });

    this.api.get<WorkerStatus>('/admin/workers/status').subscribe({
      next: (w) => {
        if (w.scheduler.status == "running") w.scheduler.status = "active";
        this.workerStatus.set(w)
      },
      error: () => {},
    });
  }
}
