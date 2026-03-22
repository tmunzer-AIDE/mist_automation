import { Component, DestroyRef, EventEmitter, Input, OnChanges, Output, SimpleChanges, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { EMPTY, Subject, debounceTime, switchMap } from 'rxjs';
import { WorkflowService } from '../../../core/services/workflow.service';

export interface WorkflowSuggestion {
  id: string;
  message: string;
  action_type?: string;
  target_node_id?: string;
  priority: number;
}

@Component({
  selector: 'app-suggestions-bar',
  standalone: true,
  imports: [MatButtonModule, MatIconModule],
  template: `
    @if (visibleSuggestions().length > 0) {
      <div class="suggestions-bar">
        <mat-icon class="bar-icon">tips_and_updates</mat-icon>
        @for (s of visibleSuggestions(); track s.id) {
          <span class="suggestion-text">{{ s.message }}</span>
          <button class="dismiss-btn" (click)="dismiss(s.id)" aria-label="Dismiss">
            <mat-icon>close</mat-icon>
          </button>
        }
      </div>
    }
  `,
  styles: [
    `
      .suggestions-bar {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 12px;
        background: var(--mat-sys-primary-container, #e3f2fd);
        border-bottom: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
        font-size: 12px;
        color: var(--mat-sys-on-primary-container, #1565c0);
        min-height: 32px;
      }

      .bar-icon {
        font-size: 16px;
        width: 16px;
        height: 16px;
        flex-shrink: 0;
      }

      .suggestion-text {
        flex: 1;
        line-height: 1.3;
      }

      .dismiss-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 20px;
        height: 20px;
        padding: 0;
        border: none;
        border-radius: 50%;
        background: transparent;
        cursor: pointer;
        flex-shrink: 0;
        color: inherit;
        opacity: 0.7;

        &:hover {
          opacity: 1;
          background: rgba(0, 0, 0, 0.08);
        }

        mat-icon {
          font-size: 14px;
          width: 14px;
          height: 14px;
        }
      }
    `,
  ],
})
export class SuggestionsBarComponent implements OnChanges {
  @Input() workflowId: string | null = null;
  @Input() graphVersion = 0; // Incremented on graph changes to trigger refresh

  @Output() suggestionApplied = new EventEmitter<WorkflowSuggestion>();

  private readonly workflowService = inject(WorkflowService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly refresh$ = new Subject<void>();
  private dismissedIds = new Set<string>();

  allSuggestions = signal<WorkflowSuggestion[]>([]);
  visibleSuggestions = signal<WorkflowSuggestion[]>([]);

  constructor() {
    this.refresh$
      .pipe(
        debounceTime(1000),
        switchMap(() =>
          this.workflowId ? this.workflowService.getSuggestions(this.workflowId) : EMPTY
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (res) => {
          this.allSuggestions.set(res.suggestions);
          this.updateVisible();
        },
        error: () => {
          this.allSuggestions.set([]);
          this.visibleSuggestions.set([]);
        },
      });
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['workflowId']) {
      this.dismissedIds.clear();
    }
    if (changes['workflowId'] || changes['graphVersion']) {
      if (this.workflowId) {
        this.refresh$.next();
      }
    }
  }

  dismiss(id: string): void {
    this.dismissedIds.add(id);
    this.updateVisible();
  }

  private updateVisible(): void {
    const filtered = this.allSuggestions()
      .filter((s) => !this.dismissedIds.has(s.id))
      .slice(0, 2); // Show max 2
    this.visibleSuggestions.set(filtered);
  }
}
