import { DatePipe, DecimalPipe, TitleCasePipe } from '@angular/common';
import { Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { LlmUsageDashboard } from '../../../core/models/llm.model';
import { LlmService } from '../../../core/services/llm.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { extractErrorMessage } from '../../../shared/utils/error.utils';

interface WindowOption {
  hours: number;
  label: string;
}

@Component({
  selector: 'app-llm-usage',
  standalone: true,
  imports: [
    DatePipe,
    DecimalPipe,
    TitleCasePipe,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatProgressBarModule,
    MatSnackBarModule,
    MatTooltipModule,
  ],
  templateUrl: './llm-usage.component.html',
  styleUrl: './llm-usage.component.scss',
})
export class LlmUsageComponent implements OnInit {
  private readonly llmService = inject(LlmService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);
  private readonly topbarService = inject(TopbarService);

  readonly windowOptions: WindowOption[] = [
    { hours: 24, label: '24h' },
    { hours: 72, label: '3d' },
    { hours: 168, label: '7d' },
  ];

  loading = signal(true);
  selectedHours = signal(24);
  dashboard = signal<LlmUsageDashboard | null>(null);

  ngOnInit(): void {
    this.topbarService.setTitle('LLM Usage');
    this.load();
  }

  setWindow(hours: number): void {
    if (this.selectedHours() === hours) {
      return;
    }
    this.selectedHours.set(hours);
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.llmService
      .getUsageDashboard(this.selectedHours())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (dashboard) => {
          this.dashboard.set(dashboard);
          this.loading.set(false);
        },
        error: (err) => {
          this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
          this.loading.set(false);
        },
      });
  }

  formatMs(value: number | null): string {
    if (value === null || value === undefined) {
      return '—';
    }
    return `${Math.round(value)} ms`;
  }
}
