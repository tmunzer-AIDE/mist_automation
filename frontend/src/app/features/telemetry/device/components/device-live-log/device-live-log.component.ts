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
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatIconButton } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { Subscription } from 'rxjs';
import { TelemetryService } from '../../../telemetry.service';
import { DeviceLiveEvent } from '../../../models';

const MAX_LOG_ROWS = 100;

@Component({
  selector: 'app-device-live-log',
  standalone: true,
  imports: [DecimalPipe, DatePipe, UpperCasePipe, MatButtonToggleModule, MatIconButton, MatIconModule],
  templateUrl: './device-live-log.component.html',
  styleUrl: './device-live-log.component.scss',
})
export class DeviceLiveLogComponent implements OnChanges {
  @Input() mac = '';
  private readonly telemetryService = inject(TelemetryService);
  private readonly destroyRef = inject(DestroyRef);
  private wsSub?: Subscription;

  readonly entries = signal<DeviceLiveEvent[]>([]);
  readonly viewMode = signal<'formatted' | 'raw'>('formatted');
  readonly expandedRows = signal<Set<number>>(new Set());
  readonly copiedIndex = signal<number | null>(null);

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

  setViewMode(mode: 'formatted' | 'raw'): void {
    this.viewMode.set(mode);
  }

  toggleExpand(index: number): void {
    const expanded = new Set(this.expandedRows());
    if (expanded.has(index)) {
      expanded.delete(index);
    } else {
      expanded.add(index);
    }
    this.expandedRows.set(expanded);
  }

  isExpanded(index: number): boolean {
    return this.expandedRows().has(index);
  }

  formatJson(obj: Record<string, unknown> | undefined): string {
    return obj ? JSON.stringify(obj, null, 2) : '{}';
  }

  copyJson(entry: DeviceLiveEvent, index: number, event: MouseEvent): void {
    event.stopPropagation();
    navigator.clipboard.writeText(this.formatJson(entry.raw)).then(() => {
      this.copiedIndex.set(index);
      setTimeout(() => this.copiedIndex.set(null), 2000);
    });
  }
}
