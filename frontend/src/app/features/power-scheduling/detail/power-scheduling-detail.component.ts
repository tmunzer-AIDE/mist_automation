import { Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { DatePipe, JsonPipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTableModule } from '@angular/material/table';
import {
  PowerSchedule,
  ScheduleLog,
  ScheduleStatus,
  PowerSchedulingService,
} from '../power-scheduling.service';

@Component({
  selector: 'app-power-scheduling-detail',
  standalone: true,
  imports: [
    DatePipe,
    JsonPipe,
    MatButtonModule,
    MatCardModule,
    MatChipsModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatTableModule,
  ],
  templateUrl: './power-scheduling-detail.component.html',
  styleUrl: './power-scheduling-detail.component.scss',
})
export class PowerSchedulingDetailComponent implements OnInit {
  private readonly service = inject(PowerSchedulingService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  siteId = signal('');
  schedule = signal<PowerSchedule | null>(null);
  status = signal<ScheduleStatus | null>(null);
  logs = signal<ScheduleLog[]>([]);
  loading = signal(true);

  logColumns = ['timestamp', 'event_type', 'ap_mac', 'details'];

  ngOnInit(): void {
    const siteId = this.route.snapshot.paramMap.get('siteId') ?? '';
    this.siteId.set(siteId);
    this.loadData(siteId);
  }

  loadData(siteId: string): void {
    this.service
      .getStatus(siteId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({ next: (s) => this.status.set(s) });
    this.service
      .getLogs(siteId, { limit: 50 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (l) => {
          this.logs.set(l);
          this.loading.set(false);
        },
        error: () => this.loading.set(false),
      });
  }

  trigger(action: 'start' | 'end'): void {
    this.service
      .trigger(this.siteId(), action)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.loadData(this.siteId()));
  }
}
