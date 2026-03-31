import {
  Component,
  DestroyRef,
  OnDestroy,
  OnInit,
  TemplateRef,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { DAY_SHORTS, PowerSchedule, PowerSchedulingService } from '../power-scheduling.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { PowerScheduleFormDialogComponent } from '../power-schedule-form-dialog.component';
import { extractErrorMessage } from '../../../shared/utils/error.utils';

@Component({
  selector: 'app-power-scheduling-list',
  standalone: true,
  imports: [
    MatButtonModule,
    MatDialogModule,
    MatIconModule,
    MatProgressBarModule,
    MatSnackBarModule,
    MatTooltipModule,
    EmptyStateComponent,
  ],
  templateUrl: './power-scheduling-list.component.html',
  styleUrl: './power-scheduling-list.component.scss',
})
export class PowerSchedulingListComponent implements OnInit, OnDestroy {
  private readonly service = inject(PowerSchedulingService);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly topbarService = inject(TopbarService);
  private readonly destroyRef = inject(DestroyRef);

  @ViewChild('topbarActions', { static: true }) topbarActions!: TemplateRef<unknown>;

  readonly dayIndices = [0, 1, 2, 3, 4, 5, 6];
  readonly dayShorts = DAY_SHORTS;

  schedules = signal<PowerSchedule[]>([]);
  loading = signal(true);
  togglingIds = signal<Set<string>>(new Set());

  activeCount = computed(
    () => this.schedules().filter((s) => s.current_status === 'OFF_HOURS').length,
  );

  ngOnInit(): void {
    this.topbarService.setTitle('AP Power Scheduling');
    this.topbarService.setActions(this.topbarActions);
    this.loadSchedules();
  }

  ngOnDestroy(): void {
    this.topbarService.clearActions();
  }

  loadSchedules(): void {
    this.loading.set(true);
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

  onToggleChange(schedule: PowerSchedule, newEnabled: boolean): void {
    if (this.togglingIds().has(schedule.site_id)) return;
    this.togglingIds.update((ids) => new Set([...ids, schedule.site_id]));

    // Optimistic update
    this.schedules.update((list) =>
      list.map((s) => (s.site_id === schedule.site_id ? { ...s, enabled: newEnabled } : s)),
    );

    const body = {
      site_name: schedule.site_name,
      windows: schedule.windows,
      grace_period_minutes: schedule.grace_period_minutes,
      neighbor_rssi_threshold_dbm: schedule.neighbor_rssi_threshold_dbm,
      roam_rssi_threshold_dbm: schedule.roam_rssi_threshold_dbm,
      critical_ap_macs: schedule.critical_ap_macs,
      enabled: newEnabled,
    };

    this.service.updateSchedule(schedule.site_id, body).subscribe({
      next: (updated) => {
        this.schedules.update((list) =>
          list.map((s) => (s.site_id === updated.site_id ? updated : s)),
        );
        this.togglingIds.update((ids) => {
          const next = new Set(ids);
          next.delete(schedule.site_id);
          return next;
        });
      },
      error: (err) => {
        // Revert optimistic update
        this.schedules.update((list) =>
          list.map((s) => (s.site_id === schedule.site_id ? { ...s, enabled: !newEnabled } : s)),
        );
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
        this.togglingIds.update((ids) => {
          const next = new Set(ids);
          next.delete(schedule.site_id);
          return next;
        });
      },
    });
  }

  openAddDialog(): void {
    const ref = this.dialog.open(PowerScheduleFormDialogComponent, {
      data: { mode: 'create' },
      width: '580px',
    });
    ref
      .afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((result) => {
        if (result) this.loadSchedules();
      });
  }

  openDetail(siteId: string): void {
    this.router.navigate(['/power-scheduling', siteId]);
  }
}
