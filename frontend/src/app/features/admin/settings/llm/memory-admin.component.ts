import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { forkJoin } from 'rxjs';
import {
  ConsolidationLogDetail,
  ConsolidationLogSummary,
  MemoryStats,
} from '../../../../core/models/llm.model';
import { LlmService } from '../../../../core/services/llm.service';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';

@Component({
  selector: 'app-memory-admin',
  standalone: true,
  imports: [
    DatePipe,
    DecimalPipe,
    MatButtonModule,
    MatCardModule,
    MatExpansionModule,
    MatIconModule,
    MatProgressBarModule,
    MatSnackBarModule,
    MatTooltipModule,
  ],
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    } @else {
      <!-- Stats card -->
      @if (stats()) {
        <mat-card>
          <mat-card-header>
            <mat-card-title>Memory Stats</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <div class="stats-row">
              <div class="stat-item">
                <span class="stat-value">{{ stats()!.total_entries }}</span>
                <span class="stat-label">Total Entries</span>
              </div>
              <div class="stat-item">
                <span class="stat-value">{{ stats()!.users_with_memories }}</span>
                <span class="stat-label">Users with Memories</span>
              </div>
              <div class="stat-item">
                <span class="stat-value">{{ stats()!.avg_entries_per_user }}</span>
                <span class="stat-label">Avg per User</span>
              </div>
            </div>
          </mat-card-content>
        </mat-card>
      }

      <!-- Consolidation Logs card -->
      <mat-card>
        <mat-card-header>
          <mat-card-title>Consolidation Logs</mat-card-title>
          <button mat-icon-button matTooltip="Refresh" (click)="load()">
            <mat-icon>refresh</mat-icon>
          </button>
        </mat-card-header>
        <mat-card-content>
          @if (logs().length === 0) {
            <p class="empty-hint">No consolidation runs yet.</p>
          } @else {
            <mat-accordion>
              @for (log of logs(); track log.id) {
                <mat-expansion-panel (afterExpand)="loadDetail(log.id)">
                  <mat-expansion-panel-header>
                    <mat-panel-title>
                      {{ log.run_at | date: 'medium' }}
                    </mat-panel-title>
                    <mat-panel-description>
                      <span class="log-meta">
                        {{ log.user_email }}
                        <span class="separator">|</span>
                        {{ log.entries_before }} → {{ log.entries_after }} entries
                        <span class="separator">|</span>
                        @if (log.actions_summary.merged > 0) {
                          <span class="action-badge merge">{{ log.actions_summary.merged }} merged</span>
                        }
                        @if (log.actions_summary.deleted > 0) {
                          <span class="action-badge delete">{{ log.actions_summary.deleted }} deleted</span>
                        }
                        @if (log.actions_summary.kept > 0) {
                          <span class="action-badge keep">{{ log.actions_summary.kept }} kept</span>
                        }
                      </span>
                    </mat-panel-description>
                  </mat-expansion-panel-header>

                  @if (detailLoading().has(log.id)) {
                    <mat-progress-bar mode="indeterminate"></mat-progress-bar>
                  } @else if (details().get(log.id); as detail) {
                    <div class="detail-section">
                      <div class="detail-meta">
                        <span class="meta-item">
                          <strong>Model:</strong> {{ detail.llm_model || '—' }}
                        </span>
                        <span class="meta-item">
                          <strong>Tokens:</strong> {{ detail.llm_tokens_used | number }}
                        </span>
                      </div>

                      <div class="actions-list">
                        @for (action of detail.actions; track $index) {
                          <div class="action-item" [class]="'action-' + getActionType(action)">
                            <div class="action-header">
                              <span class="action-type-badge" [class]="getActionType(action)">
                                {{ getActionType(action) }}
                              </span>
                              <span class="action-keys">{{ getActionKeys(action).join(', ') }}</span>
                            </div>
                            @if (getActionType(action) === 'merge') {
                              <div class="action-merge-detail">
                                → {{ getActionField(action, 'new_key') }}: {{ getActionField(action, 'new_value') }}
                              </div>
                            }
                            @if (getActionField(action, 'reason')) {
                              <div class="action-reason">{{ getActionField(action, 'reason') }}</div>
                            }
                          </div>
                        }
                      </div>
                    </div>
                  }
                </mat-expansion-panel>
              }
            </mat-accordion>

            @if (total() > logs().length) {
              <div class="load-more">
                <button mat-button (click)="loadMore()" [disabled]="loadingMore()">
                  @if (loadingMore()) {
                    Loading…
                  } @else {
                    Load More ({{ logs().length }} / {{ total() }})
                  }
                </button>
              </div>
            }
          }
        </mat-card-content>
      </mat-card>
    }
  `,
  styles: [
    `
      mat-card {
        margin-bottom: 16px;
      }
      mat-card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
      .empty-hint {
        color: var(--mat-sys-on-surface-variant);
        font-size: 13px;
        padding: 16px;
        text-align: center;
      }

      /* Stats */
      .stats-row {
        display: flex;
        gap: 32px;
        padding: 8px 0;
      }
      .stat-item {
        display: flex;
        flex-direction: column;
        align-items: center;
      }
      .stat-value {
        font-size: 24px;
        font-weight: 600;
        color: var(--mat-sys-primary);
      }
      .stat-label {
        font-size: 12px;
        color: var(--mat-sys-on-surface-variant);
        margin-top: 2px;
      }

      /* Log panel header */
      .log-meta {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        flex-wrap: wrap;
      }
      .separator {
        color: var(--mat-sys-outline);
      }
      .action-badge {
        font-size: 11px;
        font-weight: 600;
        padding: 1px 6px;
        border-radius: 8px;
      }
      .action-badge.merge {
        background: var(--app-info-bg, rgba(33, 150, 243, 0.12));
        color: var(--app-info, #2196f3);
      }
      .action-badge.delete {
        background: var(--app-error-bg, rgba(244, 67, 54, 0.12));
        color: var(--app-error, #f44336);
      }
      .action-badge.keep {
        background: var(--app-success-bg, rgba(76, 175, 80, 0.12));
        color: var(--app-success, #4caf50);
      }

      /* Detail section */
      .detail-section {
        padding: 8px 0;
      }
      .detail-meta {
        display: flex;
        gap: 24px;
        margin-bottom: 12px;
        font-size: 13px;
      }
      .meta-item strong {
        color: var(--mat-sys-on-surface-variant);
      }

      /* Actions list */
      .actions-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .action-item {
        padding: 8px 12px;
        border-radius: 8px;
        border-left: 3px solid var(--app-neutral, #888);
        background: var(--mat-sys-surface-variant, rgba(0, 0, 0, 0.04));
      }
      .action-item.action-merge {
        border-left-color: var(--app-info, #2196f3);
      }
      .action-item.action-delete {
        border-left-color: var(--app-error, #f44336);
      }
      .action-item.action-keep {
        border-left-color: var(--app-success, #4caf50);
      }
      .action-header {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .action-type-badge {
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        padding: 1px 6px;
        border-radius: 6px;
      }
      .action-type-badge.merge {
        background: var(--app-info-bg, rgba(33, 150, 243, 0.12));
        color: var(--app-info, #2196f3);
      }
      .action-type-badge.delete {
        background: var(--app-error-bg, rgba(244, 67, 54, 0.12));
        color: var(--app-error, #f44336);
      }
      .action-type-badge.keep {
        background: var(--app-success-bg, rgba(76, 175, 80, 0.12));
        color: var(--app-success, #4caf50);
      }
      .action-keys {
        font-family: monospace;
        font-size: 12px;
      }
      .action-merge-detail {
        font-size: 12px;
        margin-top: 4px;
        padding-left: 4px;
        color: var(--mat-sys-on-surface-variant);
        font-family: monospace;
      }
      .action-reason {
        font-size: 12px;
        margin-top: 4px;
        color: var(--mat-sys-on-surface-variant);
        font-style: italic;
      }

      /* Load more */
      .load-more {
        text-align: center;
        padding: 12px 0 4px;
      }
    `,
  ],
})
export class MemoryAdminComponent implements OnInit {
  private readonly llmService = inject(LlmService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);

  loading = signal(true);
  loadingMore = signal(false);
  stats = signal<MemoryStats | null>(null);
  logs = signal<ConsolidationLogSummary[]>([]);
  total = signal(0);
  details = signal<Map<string, ConsolidationLogDetail>>(new Map());
  detailLoading = signal<Set<string>>(new Set());

  private page = 1;
  private readonly pageSize = 25;

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.page = 1;

    forkJoin({
      stats: this.llmService.getMemoryStats(),
      logs: this.llmService.listConsolidationLogs(1, this.pageSize),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ stats, logs }) => {
          this.stats.set(stats);
          this.logs.set(logs.logs);
          this.total.set(logs.total);
          this.loading.set(false);
        },
        error: (err) => {
          this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
          this.loading.set(false);
        },
      });
  }

  loadMore(): void {
    this.loadingMore.set(true);
    this.page++;

    this.llmService
      .listConsolidationLogs(this.page, this.pageSize)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.logs.update((prev) => [...prev, ...result.logs]);
          this.total.set(result.total);
          this.loadingMore.set(false);
        },
        error: (err) => {
          this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
          this.loadingMore.set(false);
        },
      });
  }

  loadDetail(logId: string): void {
    if (this.details().has(logId)) return;

    this.detailLoading.update((s) => new Set([...s, logId]));

    this.llmService
      .getConsolidationLog(logId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (detail) => {
          this.details.update((m) => {
            const next = new Map(m);
            next.set(logId, detail);
            return next;
          });
          this.detailLoading.update((s) => {
            const next = new Set(s);
            next.delete(logId);
            return next;
          });
        },
        error: (err) => {
          this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
          this.detailLoading.update((s) => {
            const next = new Set(s);
            next.delete(logId);
            return next;
          });
        },
      });
  }

  getActionType(action: Record<string, unknown>): string {
    return (action['action'] as string) || 'unknown';
  }

  getActionKeys(action: Record<string, unknown>): string[] {
    return (action['keys'] as string[]) || [];
  }

  getActionField(action: Record<string, unknown>, field: string): string {
    return (action[field] as string) || '';
  }
}
