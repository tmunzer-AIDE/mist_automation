import { Component, ChangeDetectorRef, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { MatTableModule } from '@angular/material/table';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatMenuModule } from '@angular/material/menu';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { PageHeaderComponent } from '../../../shared/components/page-header/page-header.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { RelativeTimePipe } from '../../../shared/pipes/relative-time.pipe';
import { WorkflowService } from '../../../core/services/workflow.service';
import { WorkflowResponse } from '../../../core/models/workflow.model';

@Component({
  selector: 'app-workflow-list',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatTableModule,
    MatPaginatorModule,
    MatButtonModule,
    MatIconModule,
    MatSnackBarModule,
    MatMenuModule,
    MatDialogModule,
    MatTooltipModule,
    PageHeaderComponent,
    EmptyStateComponent,
    StatusBadgeComponent,
    RelativeTimePipe,
  ],
  templateUrl: './workflow-list.component.html',
  styleUrl: './workflow-list.component.scss',
})
export class WorkflowListComponent implements OnInit {
  private readonly workflowService = inject(WorkflowService);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);
  private readonly cdr = inject(ChangeDetectorRef);

  workflows: WorkflowResponse[] = [];
  total = 0;
  pageSize = 25;
  pageIndex = 0;
  loading = true;

  displayedColumns = [
    'name',
    'trigger',
    'status',
    'executions',
    'last_execution',
    'actions',
  ];

  ngOnInit(): void {
    this.loadWorkflows();
  }

  loadWorkflows(): void {
    this.loading = true;
    this.workflowService
      .list(this.pageIndex * this.pageSize, this.pageSize)
      .subscribe({
        next: (res) => {
          this.workflows = res.workflows;
          this.total = res.total;
          this.loading = false;
          this.cdr.detectChanges();
        },
        error: () => {
          this.loading = false;
          this.cdr.detectChanges();
        },
      });
  }

  onPage(event: PageEvent): void {
    this.pageIndex = event.pageIndex;
    this.pageSize = event.pageSize;
    this.loadWorkflows();
  }

  createWorkflow(): void {
    this.router.navigate(['/workflows/new']);
  }

  editWorkflow(workflow: WorkflowResponse): void {
    this.router.navigate(['/workflows', workflow.id]);
  }

  deleteWorkflow(event: Event, workflow: WorkflowResponse): void {
    event.stopPropagation();
    if (!confirm(`Delete workflow "${workflow.name}"?`)) return;
    this.workflowService.remove(workflow.id).subscribe({
      next: () => {
        this.snackBar.open('Workflow deleted', 'OK', { duration: 3000 });
        this.loadWorkflows();
      },
      error: () => {
        this.snackBar.open('Failed to delete workflow', 'OK', {
          duration: 5000,
        });
      },
    });
  }

  runWorkflow(event: Event, workflow: WorkflowResponse): void {
    event.stopPropagation();
    if (workflow.status !== 'enabled') {
      this.snackBar.open(
        'Workflow must be enabled before running',
        'OK',
        { duration: 3000 }
      );
      return;
    }
    this.workflowService.execute(workflow.id).subscribe({
      next: () => {
        this.snackBar.open('Workflow execution queued', 'OK', {
          duration: 3000,
        });
      },
      error: () => {
        this.snackBar.open('Failed to run workflow', 'OK', { duration: 5000 });
      },
    });
  }

  toggleStatus(event: Event, workflow: WorkflowResponse): void {
    event.stopPropagation();
    const newStatus = workflow.status === 'enabled' ? 'disabled' : 'enabled';
    this.workflowService
      .update(workflow.id, { status: newStatus })
      .subscribe({
        next: () => {
          workflow.status = newStatus;
          this.cdr.detectChanges();
        },
        error: () => {
          this.snackBar.open('Failed to update status', 'OK', {
            duration: 5000,
          });
        },
      });
  }

  getTriggerLabel(workflow: WorkflowResponse): string {
    if (!workflow.trigger) return '—';
    if (workflow.trigger.type === 'webhook') {
      return `Webhook: ${workflow.trigger.webhook_topic || workflow.trigger.webhook_type || 'any'}`;
    }
    return `Cron: ${workflow.trigger.cron_expression || ''}`;
  }
}
