import {
  Component,
  DestroyRef,
  Input,
  OnChanges,
  SimpleChanges,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DecimalPipe, DatePipe, UpperCasePipe } from '@angular/common';
import { Subscription } from 'rxjs';
import { TelemetryService } from '../../../telemetry.service';
import { DeviceLiveEvent } from '../../../models';

const MAX_LOG_ROWS = 100;

@Component({
  selector: 'app-device-live-log',
  standalone: true,
  imports: [DecimalPipe, DatePipe, UpperCasePipe],
  templateUrl: './device-live-log.component.html',
  styleUrl: './device-live-log.component.scss',
})
export class DeviceLiveLogComponent implements OnChanges {
  @Input() mac = '';
  private readonly telemetryService = inject(TelemetryService);
  private readonly destroyRef = inject(DestroyRef);
  private wsSub?: Subscription;

  readonly entries = signal<DeviceLiveEvent[]>([]);

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['mac'] && this.mac) {
      this.subscribeToDevice(this.mac);
    }
  }

  private subscribeToDevice(mac: string): void {
    this.wsSub?.unsubscribe();
    this.entries.set([]);
    this.wsSub = this.telemetryService
      .subscribeToDevice(mac)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((event) => {
        this.entries.update((prev) => {
          const next = [event, ...prev];
          return next.length > MAX_LOG_ROWS ? next.slice(0, MAX_LOG_ROWS) : next;
        });
      });
  }
}
