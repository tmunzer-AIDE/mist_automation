import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatTableModule } from '@angular/material/table';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSelectModule } from '@angular/material/select';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { ConfirmDialogComponent } from '../../../shared/components/confirm-dialog/confirm-dialog.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { DurationPipe } from '../../../shared/pipes/duration.pipe';
import { WorkflowService } from '../../../core/services/workflow.service';
import { WorkflowExecution } from '../../../core/models/workflow.model';
import { TopbarService } from '../../../core/services/topbar.service';
import { ExecutionDetailDialogComponent } from '../editor/execution-detail-dialog.component';

@Component({
  selector: 'app-execution-list',
  standalone: true,
  imports: [
    FormsModule,
    MatTableModule,
    MatPaginatorModule,
    MatButtonModule,
    MatIconModule,
    MatSelectModule,
    MatFormFieldModule,
    MatSnackBarModule,
    MatDialogModule,
    MatTooltipModule,
    MatProgressBarModule,
    EmptyStateComponent,
    StatusBadgeComponent,
    DateTimePipe,
    DurationPipe,
  ],
  template: `
    <div class="filters-bar">
      <mat-form-field appearance="outline" class="filter-field">
        <mat-label>Status</mat-label>
        <mat-select [(value)]="statusFilter" (selectionChange)="applyFilters()">
          <mat-option [value]="''">All</mat-option>
          <mat-option value="pending">Pending</mat-option>
          <mat-option value="running">Running</mat-option>
          <mat-option value="success">Success</mat-option>
          <mat-option value="failed">Failed</mat-option>
          <mat-option value="cancelled">Cancelled</mat-option>
          <mat-option value="timeout">Timeout</mat-option>
          <mat-option value="filtered">Filtered</mat-option>
          <mat-option value="partial">Partial</mat-option>
        </mat-select>
      </mat-form-field>

      <mat-form-field appearance="outline" class="filter-field">
        <mat-label>Trigger</mat-label>
        <mat-select [(value)]="triggerFilter" (selectionChange)="applyFilters()">
          <mat-option [value]="''">All</mat-option>
          <mat-option value="webhook">Webhook</mat-option>
          <mat-option value="cron">Cron</mat-option>
          <mat-option value="manual">Manual</mat-option>
          <mat-option value="simulation">Simulation</mat-option>
        </mat-select>
      </mat-form-field>
    </div>

    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    } @else if (executions().length === 0) {
      <app-empty-state
        icon="history"
        title="No executions yet"
        message="Run a workflow to see execution history here."
      ></app-empty-state>
    } @else {
      <div class="table-card">
        <table mat-table [dataSource]="executions()">
          <!-- Status -->
          <ng-container matColumnDef="status">
            <th mat-header-cell *matHeaderCellDef>Status</th>
            <td mat-cell *matCellDef="let ex">
              <app-status-badge [status]="ex.status"></app-status-badge>
            </td>
          </ng-container>

          <!-- Workflow Name -->
          <ng-container matColumnDef="workflow_name">
            <th mat-header-cell *matHeaderCellDef>Workflow</th>
            <td mat-cell *matCellDef="let ex">{{ ex.workflow_name }}</td>
          </ng-container>

          <!-- Trigger Type -->
          <ng-container matColumnDef="trigger_type">
            <th mat-header-cell *matHeaderCellDef>Trigger</th>
            <td mat-cell *matCellDef="let ex">{{ ex.trigger_type }}</td>
          </ng-container>

          <!-- Started At -->
          <ng-container matColumnDef="started_at">
            <th mat-header-cell *matHeaderCellDef>Started</th>
            <td mat-cell *matCellDef="let ex">{{ ex.started_at | dateTime }}</td>
          </ng-container>

          <!-- Duration -->
          <ng-container matColumnDef="duration">
            <th mat-header-cell *matHeaderCellDef>Duration</th>
            <td mat-cell *matCellDef="let ex">{{ ex.duration_ms | duration }}</td>
          </ng-container>

          <!-- Nodes -->
          <ng-container matColumnDef="nodes">
            <th mat-header-cell *matHeaderCellDef>Nodes</th>
            <td mat-cell *matCellDef="let ex">
              {{ ex.nodes_succeeded }}/{{ ex.nodes_executed }}
              @if (ex.nodes_failed > 0) {
                <span class="failure-count">({{ ex.nodes_failed }} failed)</span>
              }
            </td>
          </ng-container>

          <!-- Actions -->
          <ng-container matColumnDef="actions">
            <th mat-header-cell *matHeaderCellDef></th>
            <td mat-cell *matCellDef="let ex" class="actions-cell">
              @if (ex.status === 'pending' || ex.status === 'running') {
                <button
                  mat-icon-button
                  matTooltip="Cancel execution"
                  (click)="cancelExecution($event, ex)"
                >
                  <mat-icon>cancel</mat-icon>
                </button>
              }
            </td>
          </ng-container>

          <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
          <tr
            mat-row
            *matRowDef="let ex; columns: displayedColumns"
            class="clickable-row"
            (click)="viewExecution(ex)"
          ></tr>
        </table>

        <mat-paginator
          [length]="total()"
          [pageSize]="pageSize()"
          [pageIndex]="pageIndex()"
          [pageSizeOptions]="[25, 50, 100]"
          (page)="onPage($event)"
          showFirstLastButtons
        ></mat-paginator>
      </div>
    }
  `,
  styles: [
    `
      .filters-bar {
        display: flex;
        gap: 16px;
        margin-bottom: 16px;
      }
      .filter-field {
        width: 180px;
      }
      .failure-count {
        color: var(--mat-sys-error);
        font-size: 12px;
        margin-left: 4px;
      }
      .actions-cell {
        width: 48px;
        text-align: right;
      }
    `,
  ],
})
export class ExecutionListComponent implements OnInit {
  private readonly workflowService = inject(WorkflowService);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly topbarService = inject(TopbarService);

  executions = signal<WorkflowExecution[]>([]);
  total = signal(0);
  pageSize = signal(25);
  pageIndex = signal(0);
  loading = signal(true);

  statusFilter = '';
  triggerFilter = '';

  displayedColumns = [
    'status',
    'workflow_name',
    'trigger_type',
    'started_at',
    'duration',
    'nodes',
    'actions',
  ];

  ngOnInit(): void {
    this.topbarService.setTitle('Executions');
    this.loadExecutions();
  }

  loadExecutions(): void {
    this.loading.set(true);
    const filters: { status?: string; trigger_type?: string } = {};
    if (this.statusFilter) filters.status = this.statusFilter;
    if (this.triggerFilter) filters.trigger_type = this.triggerFilter;

    this.workflowService
      .listAllExecutions(this.pageIndex() * this.pageSize(), this.pageSize(), filters)
      .subscribe({
        next: (res) => {
          this.executions.set(res.executions);
          this.total.set(res.total);
          this.loading.set(false);
        },
        error: () => {
          this.loading.set(false);
        },
      });
  }

  applyFilters(): void {
    this.pageIndex.set(0);
    this.loadExecutions();
  }

  onPage(event: PageEvent): void {
    this.pageIndex.set(event.pageIndex);
    this.pageSize.set(event.pageSize);
    this.loadExecutions();
  }

  viewExecution(ex: WorkflowExecution): void {
    this.dialog.open(ExecutionDetailDialogComponent, {
      width: '900px',
      maxHeight: '90vh',
      data: { workflowId: ex.workflow_id, execution: ex },
    });
  }

  cancelExecution(event: Event, ex: WorkflowExecution): void {
    event.stopPropagation();
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: 'Cancel Execution',
        message: `Cancel execution of "${ex.workflow_name}"?`,
        confirmText: 'Cancel Execution',
        warn: true,
      },
    });
    ref.afterClosed().subscribe((confirmed) => {
      if (confirmed) {
        this.workflowService.cancelExecution(ex.id).subscribe({
          next: () => {
            this.snackBar.open('Execution cancelled', 'OK', { duration: 3000 });
            this.loadExecutions();
          },
          error: () => {
            this.snackBar.open('Failed to cancel execution', 'OK', { duration: 5000 });
          },
        });
      }
    });
  }

}
