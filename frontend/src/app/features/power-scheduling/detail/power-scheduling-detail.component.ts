import {
  Component,
  DestroyRef,
  OnDestroy,
  OnInit,
  TemplateRef,
  ViewChild,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize } from 'rxjs';
import { Router, ActivatedRoute } from '@angular/router';
import { DatePipe, JsonPipe } from '@angular/common';
import { WebSocketService } from '../../../core/services/websocket.service';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
  DAY_LABELS,
  DAY_SHORTS,
  PowerSchedule,
  ScheduleLog,
  ScheduleStatus,
  PowerSchedulingService,
} from '../power-scheduling.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { ConfirmDialogComponent } from '../../../shared/components/confirm-dialog/confirm-dialog.component';
import { PowerScheduleFormDialogComponent } from '../power-schedule-form-dialog.component';
import { extractErrorMessage } from '../../../shared/utils/error.utils';

@Component({
  selector: 'app-power-scheduling-detail',
  standalone: true,
  imports: [
    DatePipe,
    JsonPipe,
    MatButtonModule,
    MatDialogModule,
    MatIconModule,
    MatProgressBarModule,
    MatSnackBarModule,
    MatTableModule,
    MatTooltipModule,
  ],
  templateUrl: './power-scheduling-detail.component.html',
  styleUrl: './power-scheduling-detail.component.scss',
})
export class PowerSchedulingDetailComponent implements OnInit, OnDestroy {
  private readonly service = inject(PowerSchedulingService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly topbarService = inject(TopbarService);
  private readonly wsService = inject(WebSocketService);
  private readonly destroyRef = inject(DestroyRef);

  @ViewChild('topbarActions', { static: true }) topbarActions!: TemplateRef<unknown>;

  siteId = signal('');
  schedule = signal<PowerSchedule | null>(null);
  status = signal<ScheduleStatus | null>(null);
  logs = signal<ScheduleLog[]>([]);
  loading = signal(true);

  readonly dayIndices = [0, 1, 2, 3, 4, 5, 6];
  readonly dayShorts = DAY_SHORTS;

  logColumns = ['timestamp', 'event_type', 'ap_mac', 'details'];

  ngOnInit(): void {
    const siteId = this.route.snapshot.paramMap.get('siteId') ?? '';
    this.siteId.set(siteId);
    this.topbarService.setActions(this.topbarActions);
    this.loadSchedule(siteId);
    this.loadStatus(siteId);
    this.loadLogs(siteId);
    this.subscribeToWs(siteId);
  }

  ngOnDestroy(): void {
    this.topbarService.clearActions();
  }

  loadSchedule(siteId: string): void {
    this.service
      .getSchedule(siteId)
      .pipe(takeUntilDestroyed(this.destroyRef), finalize(() => this.loading.set(false)))
      .subscribe({
        next: (s) => {
          this.schedule.set(s);
          this.topbarService.setTitle(s.site_name);
        },
        error: () => this.topbarService.setTitle(siteId),
      });
  }

  loadStatus(siteId: string): void {
    this.service
      .getStatus(siteId)
      .pipe(takeUntilDestroyed(this.destroyRef), finalize(() => this.loading.set(false)))
      .subscribe({ next: (s) => this.status.set(s) });
  }

  loadLogs(siteId: string): void {
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
      .subscribe({
        error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
      });
  }

  openEdit(): void {
    const ref = this.dialog.open(PowerScheduleFormDialogComponent, {
      data: { mode: 'edit', schedule: this.schedule() },
      width: '580px',
    });
    ref
      .afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((result: PowerSchedule | undefined) => {
        if (result) this.schedule.set(result);
      });
  }

  deleteSchedule(): void {
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: 'Delete Schedule',
        message: `Remove power scheduling for ${this.schedule()?.site_name ?? this.siteId()}? This will re-enable all disabled APs.`,
      },
    });
    ref
      .afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((confirmed: boolean) => {
        if (!confirmed) return;
        this.service
          .deleteSchedule(this.siteId())
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: () => this.router.navigate(['/power-scheduling']),
            error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
          });
      });
  }

  private subscribeToWs(siteId: string): void {
    this.wsService
      .subscribe<{ type: string; data: Record<string, unknown> }>(`power_scheduling:${siteId}`)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((msg) => {
        if (msg.type === 'status_update') {
          this.status.set(msg.data as unknown as ScheduleStatus);
          this.schedule.update((s) =>
            s ? { ...s, current_status: msg.data['current_status'] as PowerSchedule['current_status'] } : s,
          );
        } else if (msg.type === 'log_entry') {
          this.logs.update((l) => [msg.data as unknown as ScheduleLog, ...l]);
        }
      });
  }

  formatDays(days: number[]): string {
    return days.map((d) => DAY_LABELS[d]).join(', ');
  }

  detailSummary(details: Record<string, unknown> | null | undefined): string {
    if (!details || typeof details !== 'object') return '—';
    const keys = Object.keys(details);
    return keys.length ? keys.join(', ') : '—';
  }
}
