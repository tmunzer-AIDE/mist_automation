import { TitleCasePipe } from '@angular/common';
import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { debounceTime, distinctUntilChanged } from 'rxjs';
import { LlmService } from '../../../core/services/llm.service';
import { MemoryEntry } from '../../../core/models/llm.model';
import {
  ConfirmDialogComponent,
  ConfirmDialogData,
} from '../../../shared/components/confirm-dialog/confirm-dialog.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { extractErrorMessage } from '../../../shared/utils/error.utils';

const CATEGORIES = ['general', 'network', 'preference', 'troubleshooting'] as const;
const MAX_MEMORIES = 100;

@Component({
  selector: 'app-memory',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatSelectModule,
    MatSnackBarModule,
    MatTableModule,
    MatTooltipModule,
    TitleCasePipe,
    EmptyStateComponent,
    DateTimePipe,
  ],
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    }

    <div class="memory-header">
      <h2>My Memories ({{ total() }} / {{ maxMemories }})</h2>
      @if (total() > 0) {
        <button mat-stroked-button color="warn" (click)="confirmDeleteAll()">
          <mat-icon>delete_sweep</mat-icon>
          Delete All
        </button>
      }
    </div>

    <div class="filters">
      <mat-form-field appearance="outline" class="search-field">
        <mat-label>Search</mat-label>
        <mat-icon matPrefix>search</mat-icon>
        <input matInput [formControl]="searchControl" placeholder="Search memories..." />
        @if (searchControl.value) {
          <button matSuffix mat-icon-button (click)="searchControl.setValue('')">
            <mat-icon>close</mat-icon>
          </button>
        }
      </mat-form-field>

      <mat-form-field appearance="outline" class="category-field">
        <mat-label>Category</mat-label>
        <mat-select [formControl]="categoryControl">
          <mat-option value="">All</mat-option>
          @for (cat of categories; track cat) {
            <mat-option [value]="cat">{{ cat | titlecase }}</mat-option>
          }
        </mat-select>
      </mat-form-field>
    </div>

    @if (!loading() && memories().length === 0) {
      <app-empty-state
        icon="psychology"
        title="No memories"
        message="Memories are created automatically during AI conversations."
      ></app-empty-state>
    } @else if (memories().length > 0) {
      <div class="table-container">
        <table mat-table [dataSource]="memories()">
          <ng-container matColumnDef="key">
            <th mat-header-cell *matHeaderCellDef>Key</th>
            <td mat-cell *matCellDef="let m">{{ m.key }}</td>
          </ng-container>

          <ng-container matColumnDef="value">
            <th mat-header-cell *matHeaderCellDef>Value</th>
            <td mat-cell *matCellDef="let m" [matTooltip]="m.value" matTooltipShowDelay="300">
              {{ truncate(m.value, 80) }}
            </td>
          </ng-container>

          <ng-container matColumnDef="category">
            <th mat-header-cell *matHeaderCellDef>Category</th>
            <td mat-cell *matCellDef="let m">
              <span class="category-badge category-{{ m.category }}">
                {{ m.category | titlecase }}
              </span>
            </td>
          </ng-container>

          <ng-container matColumnDef="updated_at">
            <th mat-header-cell *matHeaderCellDef>Updated</th>
            <td mat-cell *matCellDef="let m">{{ m.updated_at | dateTime: 'short' }}</td>
          </ng-container>

          <ng-container matColumnDef="actions">
            <th mat-header-cell *matHeaderCellDef></th>
            <td mat-cell *matCellDef="let m">
              <button
                mat-icon-button
                color="warn"
                matTooltip="Delete"
                (click)="confirmDelete(m)"
              >
                <mat-icon>delete</mat-icon>
              </button>
            </td>
          </ng-container>

          <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
          <tr mat-row *matRowDef="let row; columns: displayedColumns"></tr>
        </table>
      </div>
    }
  `,
  styles: [
    `
      .memory-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 16px;
      }
      .memory-header h2 {
        margin: 0;
        font-size: 20px;
        font-weight: 500;
      }
      .filters {
        display: flex;
        gap: 12px;
        margin-bottom: 8px;
      }
      .search-field {
        flex: 1;
        max-width: 400px;
      }
      .category-field {
        width: 200px;
      }
      .table-container {
        overflow-x: auto;
      }
      table {
        width: 100%;
      }
      .category-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 500;
        background: var(--app-neutral-bg, rgba(0, 0, 0, 0.08));
        color: var(--app-neutral-fg, inherit);
      }
      .category-general {
        background: var(--app-info-bg, rgba(33, 150, 243, 0.12));
        color: var(--app-info-fg, #1976d2);
      }
      .category-network {
        background: var(--app-purple-bg, rgba(156, 39, 176, 0.12));
        color: var(--app-purple-fg, #7b1fa2);
      }
      .category-preference {
        background: var(--app-success-bg, rgba(76, 175, 80, 0.12));
        color: var(--app-success-fg, #388e3c);
      }
      .category-troubleshooting {
        background: var(--app-warning-bg, rgba(255, 152, 0, 0.12));
        color: var(--app-warning-fg, #f57c00);
      }
    `,
  ],
})
export class MemoryComponent implements OnInit {
  private readonly llmService = inject(LlmService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);
  private readonly destroyRef = inject(DestroyRef);

  readonly categories = CATEGORIES;
  readonly maxMemories = MAX_MEMORIES;
  readonly displayedColumns = ['key', 'value', 'category', 'updated_at', 'actions'];

  loading = signal(true);
  memories = signal<MemoryEntry[]>([]);
  total = signal(0);

  searchControl = new FormControl('', { nonNullable: true });
  categoryControl = new FormControl('', { nonNullable: true });

  ngOnInit(): void {
    this.loadMemories();

    this.searchControl.valueChanges
      .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.loadMemories());

    this.categoryControl.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.loadMemories());
  }

  loadMemories(): void {
    this.loading.set(true);
    const category = this.categoryControl.value || undefined;
    const search = this.searchControl.value || undefined;

    this.llmService.listMemories(category, search).subscribe({
      next: (res) => {
        this.memories.set(res.entries);
        this.total.set(res.total);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  confirmDelete(memory: MemoryEntry): void {
    const ref = this.dialog.open<ConfirmDialogComponent, ConfirmDialogData, boolean>(
      ConfirmDialogComponent,
      {
        data: {
          title: 'Delete Memory',
          message: `Delete memory "${memory.key}"? This cannot be undone.`,
          warn: true,
        },
      },
    );
    ref.afterClosed().subscribe((confirmed) => {
      if (confirmed) this.deleteMemory(memory);
    });
  }

  confirmDeleteAll(): void {
    const ref = this.dialog.open<ConfirmDialogComponent, ConfirmDialogData, boolean>(
      ConfirmDialogComponent,
      {
        data: {
          title: 'Delete All Memories',
          message: `Delete all ${this.total()} memories? This cannot be undone.`,
          warn: true,
          confirmText: 'Delete All',
        },
      },
    );
    ref.afterClosed().subscribe((confirmed) => {
      if (confirmed) this.deleteAllMemories();
    });
  }

  truncate(value: string, maxLength: number): string {
    return value.length > maxLength ? value.substring(0, maxLength) + '...' : value;
  }

  private deleteMemory(memory: MemoryEntry): void {
    this.llmService.deleteMemory(memory.id).subscribe({
      next: () => {
        this.snackBar.open(`Memory "${memory.key}" deleted`, 'OK', { duration: 3000 });
        this.loadMemories();
      },
      error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
    });
  }

  private deleteAllMemories(): void {
    this.llmService.deleteAllMemories().subscribe({
      next: (res) => {
        this.snackBar.open(`${res.count} memories deleted`, 'OK', { duration: 3000 });
        this.loadMemories();
      },
      error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
    });
  }
}
