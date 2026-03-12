import { Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialog } from '@angular/material/dialog';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { DurationPipe } from '../../../shared/pipes/duration.pipe';
import { WorkflowExecution } from '../../../core/models/workflow.model';
import { WorkflowService } from '../../../core/services/workflow.service';
import { ExecutionDetailDialogComponent } from './execution-detail-dialog.component';

@Component({
  selector: 'app-executions-list-dialog',
  standalone: true,
  imports: [
    CommonModule,
    MatDialogModule,
    MatTableModule,
    MatButtonModule,
    MatProgressBarModule,
    StatusBadgeComponent,
    DateTimePipe,
    DurationPipe,
  ],
  template: `
    <h2 mat-dialog-title>Executions ({{ total() }})</h2>
    <mat-dialog-content>
      @if (loading()) {
        <mat-progress-bar mode="indeterminate" />
      } @else {
        <table mat-table [dataSource]="executions()">
          <ng-container matColumnDef="status">
            <th mat-header-cell *matHeaderCellDef>Status</th>
            <td mat-cell *matCellDef="let ex">
              <app-status-badge [status]="ex.status"></app-status-badge>
            </td>
          </ng-container>

          <ng-container matColumnDef="trigger_type">
            <th mat-header-cell *matHeaderCellDef>Trigger</th>
            <td mat-cell *matCellDef="let ex">{{ ex.trigger_type }}</td>
          </ng-container>

          <ng-container matColumnDef="started_at">
            <th mat-header-cell *matHeaderCellDef>Started</th>
            <td mat-cell *matCellDef="let ex">{{ ex.started_at | dateTime }}</td>
          </ng-container>

          <ng-container matColumnDef="duration">
            <th mat-header-cell *matHeaderCellDef>Duration</th>
            <td mat-cell *matCellDef="let ex">{{ ex.duration_ms | duration }}</td>
          </ng-container>

          <ng-container matColumnDef="nodes_executed">
            <th mat-header-cell *matHeaderCellDef>Nodes</th>
            <td mat-cell *matCellDef="let ex">
              {{ ex.nodes_succeeded }}/{{ ex.nodes_executed }}
              @if (ex.nodes_failed > 0) {
                <span class="failure-count">({{ ex.nodes_failed }} failed)</span>
              }
            </td>
          </ng-container>

          <tr mat-header-row *matHeaderRowDef="columns"></tr>
          <tr
            mat-row
            *matRowDef="let ex; columns: columns"
            class="clickable-row"
            (click)="viewExecution(ex)"
          ></tr>
        </table>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-flat-button mat-dialog-close>Close</button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .failure-count {
        color: var(--mat-sys-error);
        font-size: 12px;
        margin-left: 4px;
      }
      .clickable-row {
        cursor: pointer;
        transition: background 0.15s;
        &:hover {
          background: var(--mat-sys-surface-variant);
        }
      }
    `,
  ],
})
export class ExecutionsListDialogComponent implements OnInit {
  readonly workflowId: string = inject(MAT_DIALOG_DATA);
  private readonly dialog = inject(MatDialog);
  private readonly workflowService = inject(WorkflowService);

  columns = ['status', 'trigger_type', 'started_at', 'duration', 'nodes_executed'];
  executions = signal<WorkflowExecution[]>([]);
  total = signal(0);
  loading = signal(true);

  ngOnInit(): void {
    this.workflowService.getExecutions(this.workflowId, 0, 50).subscribe({
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

  viewExecution(ex: WorkflowExecution): void {
    this.dialog.open(ExecutionDetailDialogComponent, {
      width: '900px',
      maxHeight: '90vh',
      data: { workflowId: this.workflowId, execution: ex },
    });
  }

}
