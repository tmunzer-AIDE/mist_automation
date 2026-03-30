import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { PowerSchedule, PowerSchedulingService } from '../power-scheduling.service';

@Component({
  selector: 'app-power-scheduling-list',
  standalone: true,
  imports: [MatButtonModule, MatCardModule, MatChipsModule, MatIconModule, MatProgressSpinnerModule],
  templateUrl: './power-scheduling-list.component.html',
  styleUrl: './power-scheduling-list.component.scss',
})
export class PowerSchedulingListComponent implements OnInit {
  private readonly service = inject(PowerSchedulingService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  schedules = signal<PowerSchedule[]>([]);
  loading = signal(true);

  activeCount = computed(
    () => this.schedules().filter((s) => s.current_status === 'OFF_HOURS').length,
  );

  ngOnInit(): void {
    this.service
      .listSchedules()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => {
          this.schedules.set(data);
          this.loading.set(false);
        },
        error: () => this.loading.set(false),
      });
  }

  openDetail(siteId: string): void {
    this.router.navigate(['/power-scheduling', siteId]);
  }
}
