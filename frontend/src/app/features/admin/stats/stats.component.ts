import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DatePipe, DecimalPipe } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ApiService } from '../../../core/services/api.service';
import { AdminService } from '../../../core/services/admin.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { WebSocketService } from '../../../core/services/websocket.service';
import { SystemHealth, SystemStats, WorkerStatus } from '../../../core/models/admin.model';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
@Component({
  selector: 'app-stats',
  standalone: true,
  imports: [
    DatePipe,
    DecimalPipe,
    MatCardModule,
    MatExpansionModule,
    MatIconModule,
    MatProgressBarModule,
    StatusBadgeComponent,
  ],
  templateUrl: './stats.component.html',
  styleUrl: './stats.component.scss',
})
export class StatsComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly adminService = inject(AdminService);
  private readonly topbarService = inject(TopbarService);
  private readonly wsService = inject(WebSocketService);
  private readonly destroyRef = inject(DestroyRef);

  stats = signal<SystemStats | null>(null);
  workerStatus = signal<WorkerStatus | null>(null);
  loading = signal(true);

  health = signal<SystemHealth | null>(null);
  healthLoading = signal(true);

  servicesUp = computed(() => {
    const h = this.health();
    if (!h) return '—';
    const svc = h.services;
    const checks = [svc.mongodb.status, svc.redis.status, svc.influxdb.status, svc.mist_websocket.status];
    const up = checks.filter((s) => s === 'connected' || s === 'running' || s === 'active').length;
    return `${up}/${checks.length}`;
  });

  overallStatusClass = computed(() => {
    const h = this.health();
    if (!h) return '';
    return h.overall_status === 'operational'
      ? 'status-ok'
      : h.overall_status === 'degraded'
        ? 'status-warn'
        : 'status-error';
  });

  overallStatusText = computed(() => {
    const h = this.health();
    if (!h) return '';
    return h.overall_status === 'operational'
      ? 'All Systems Operational'
      : h.overall_status === 'degraded'
        ? 'Degraded Performance'
        : 'Service Disruption';
  });

  ngOnInit(): void {
    this.topbarService.setTitle('System Stats');
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
        this.workerStatus.set(w);
      },
      error: () => {},
    });

    // System health
    this.adminService.getSystemHealth().subscribe({
      next: (h) => {
        this.health.set(h);
        this.healthLoading.set(false);
      },
      error: () => this.healthLoading.set(false),
    });

    this.wsService
      .subscribe<{ type: string; data?: SystemHealth }>('system:health')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((msg) => {
        if (msg.type === 'health_update' && msg.data) {
          this.health.set(msg.data);
        }
      });
  }
}
