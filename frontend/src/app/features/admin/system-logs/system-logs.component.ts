import {
  Component,
  computed,
  DestroyRef,
  inject,
  OnDestroy,
  OnInit,
  signal,
  TemplateRef,
  ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ReactiveFormsModule, FormControl } from '@angular/forms';
import { MatAutocompleteModule, MatAutocompleteSelectedEvent } from '@angular/material/autocomplete';
import { MatBadgeModule } from '@angular/material/badge';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { UpperCasePipe } from '@angular/common';
import { ApiService } from '../../../core/services/api.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { WebSocketService } from '../../../core/services/websocket.service';

interface LogEntry {
  timestamp: string;
  level: string;
  event: string;
  logger: string;
  extra: Record<string, string>;
}

interface WsLogMessage {
  type: string;
  channel: string;
  data: LogEntry;
}

const ALL_LEVELS = ['debug', 'info', 'warning', 'error', 'critical'];

@Component({
  selector: 'app-system-logs',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatAutocompleteModule,
    MatBadgeModule,
    MatButtonModule,
    MatChipsModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatProgressSpinnerModule,
    MatSnackBarModule,
    MatTooltipModule,
    UpperCasePipe,
  ],
  templateUrl: './system-logs.component.html',
  styleUrl: './system-logs.component.scss',
})
export class SystemLogsComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private topbar = inject(TopbarService);
  private ws = inject(WebSocketService);
  private snackBar = inject(MatSnackBar);
  private destroyRef = inject(DestroyRef);

  @ViewChild('actions', { static: true }) actionsRef!: TemplateRef<unknown>;

  logs = signal<LogEntry[]>([]);
  loading = signal(false);
  connected = signal(false);
  expandedIndex = signal<number | null>(null);

  // Pause pattern (same as webhook monitor)
  paused = signal(false);
  pauseBuffer = signal<LogEntry[]>([]);

  // Filters as signals so computed() reacts
  selectedLevels = signal<string[]>([]);
  selectedLoggers = signal<string[]>([]);

  levelFilter = new FormControl<string[]>([]);
  loggerFilter = new FormControl<string[]>([]);

  allLevels = ALL_LEVELS;
  levelSearch = signal('');
  loggerSearch = signal('');

  filteredLevels = computed(() => {
    const q = this.levelSearch().toLowerCase();
    return q ? ALL_LEVELS.filter((l) => l.includes(q)) : ALL_LEVELS;
  });

  availableLoggers = computed(() => {
    const loggers = new Set<string>();
    for (const log of this.logs()) {
      if (log.logger) loggers.add(log.logger);
    }
    return [...loggers].sort();
  });

  filteredLoggerOptions = computed(() => {
    const q = this.loggerSearch().toLowerCase();
    const all = this.availableLoggers();
    return q ? all.filter((l) => l.toLowerCase().includes(q)) : all;
  });

  filteredLogs = computed(() => {
    const levels = new Set(this.selectedLevels());
    const loggers = new Set(this.selectedLoggers());
    return this.logs().filter((log) => {
      if (levels.size > 0 && !levels.has(log.level)) return false;
      if (loggers.size > 0 && !loggers.has(log.logger)) return false;
      return true;
    });
  });

  ngOnInit(): void {
    this.topbar.setTitle('System Logs');
    this.topbar.setActions(this.actionsRef);
    this.ws.connected$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((c) => this.connected.set(c));
    this.loadHistory();
    this.subscribeToLogs();
  }

  ngOnDestroy(): void {
    this.topbar.clearActions();
  }

  private loadHistory(): void {
    this.loading.set(true);
    this.api
      .get<{ logs: LogEntry[] }>('/admin/system-logs')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          // Reverse so newest is at the top
          this.logs.set([...res.logs].reverse());
          this.loading.set(false);
        },
        error: () => this.loading.set(false),
      });
  }

  private subscribeToLogs(): void {
    this.ws
      .subscribe<WsLogMessage>('logs:system')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((msg) => {
        if (msg.type === 'log_entry' && msg.data) {
          if (this.paused()) {
            this.pauseBuffer.update((buf) => [msg.data, ...buf]);
          } else {
            // Prepend — newest at top
            this.logs.update((prev) => [msg.data, ...prev]);
          }
        }
      });
  }

  togglePause(): void {
    const wasPaused = this.paused();
    this.paused.set(!wasPaused);

    if (wasPaused) {
      // Resuming — flush buffer into logs (newest first)
      const buffered = this.pauseBuffer();
      if (buffered.length > 0) {
        this.logs.update((prev) => [...buffered, ...prev]);
        this.pauseBuffer.set([]);
      }
    }
  }

  addLevel(event: MatAutocompleteSelectedEvent): void {
    const value = event.option.value;
    const current = this.selectedLevels();
    if (!current.includes(value)) {
      const updated = [...current, value];
      this.selectedLevels.set(updated);
      this.levelFilter.setValue(updated);
    }
    this.levelSearch.set('');
  }

  removeLevel(level: string): void {
    const updated = this.selectedLevels().filter((l) => l !== level);
    this.selectedLevels.set(updated);
    this.levelFilter.setValue(updated);
  }

  addLogger(event: MatAutocompleteSelectedEvent): void {
    const value = event.option.value;
    const current = this.selectedLoggers();
    if (!current.includes(value)) {
      const updated = [...current, value];
      this.selectedLoggers.set(updated);
      this.loggerFilter.setValue(updated);
    }
    this.loggerSearch.set('');
  }

  removeLogger(logger: string): void {
    const updated = this.selectedLoggers().filter((l) => l !== logger);
    this.selectedLoggers.set(updated);
    this.loggerFilter.setValue(updated);
  }

  clearLogs(): void {
    this.logs.set([]);
    this.pauseBuffer.set([]);
  }

  copyJson(): void {
    const json = JSON.stringify(this.filteredLogs(), null, 2);
    navigator.clipboard.writeText(json).then(() => {
      this.snackBar.open('Copied to clipboard', '', { duration: 2000 });
    });
  }

  exportJson(): void {
    const json = JSON.stringify(this.filteredLogs(), null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `system_logs_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  levelClass(level: string): string {
    switch (level) {
      case 'error':
      case 'critical':
        return 'level-error';
      case 'warning':
        return 'level-warning';
      case 'debug':
        return 'level-debug';
      default:
        return 'level-info';
    }
  }

  formatTime(ts: string): string {
    if (!ts) return '';
    const d = new Date(ts);
    return d.toLocaleString('en-US', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      fractionalSecondDigits: 3,
      hour12: false,
    });
  }

  toggleExpand(index: number): void {
    this.expandedIndex.set(this.expandedIndex() === index ? null : index);
  }

  hasExtra(extra: Record<string, string>): boolean {
    return !!extra && Object.keys(extra).length > 0;
  }

  extraEntries(extra: Record<string, string>): [string, string][] {
    if (!extra) return [];
    return Object.entries(extra);
  }
}
