import { Component, inject, OnInit, signal } from '@angular/core';
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
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { ConfirmDialogComponent } from '../../../shared/components/confirm-dialog/confirm-dialog.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { WorkflowService } from '../../../core/services/workflow.service';
import { WorkflowResponse, WorkflowType } from '../../../core/models/workflow.model';
import { TopbarService } from '../../../core/services/topbar.service';

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
    MatProgressBarModule,
    EmptyStateComponent,
    StatusBadgeComponent,
    DateTimePipe,
  ],
  templateUrl: './workflow-list.component.html',
  styleUrl: './workflow-list.component.scss',
})
export class WorkflowListComponent implements OnInit {
  private readonly workflowService = inject(WorkflowService);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly topbarService = inject(TopbarService);

  workflows = signal<WorkflowResponse[]>([]);
  total = signal(0);
  pageSize = signal(25);
  pageIndex = signal(0);
  loading = signal(true);
  workflowTypeFilter = signal<WorkflowType | undefined>(undefined);

  displayedColumns = ['name', 'type', 'trigger', 'status', 'executions', 'last_execution', 'actions'];

  ngOnInit(): void {
    this.topbarService.setTitle('Workflows');
    this.loadWorkflows();
  }

  setTypeFilter(type: WorkflowType | undefined): void {
    this.workflowTypeFilter.set(type);
    this.pageIndex.set(0);
    this.loadWorkflows();
  }

  loadWorkflows(): void {
    this.loading.set(true);
    this.workflowService
      .list(this.pageIndex() * this.pageSize(), this.pageSize(), undefined, this.workflowTypeFilter())
      .subscribe({
      next: (res) => {
        this.workflows.set(res.workflows);
        this.total.set(res.total);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
      },
    });
  }

  onPage(event: PageEvent): void {
    this.pageIndex.set(event.pageIndex);
    this.pageSize.set(event.pageSize);
    this.loadWorkflows();
  }

  createWorkflow(): void {
    this.router.navigate(['/workflows/new']);
  }

  createSubflow(): void {
    this.router.navigate(['/workflows/new'], { queryParams: { type: 'subflow' } });
  }

  editWorkflow(workflow: WorkflowResponse): void {
    this.router.navigate(['/workflows', workflow.id]);
  }

  deleteWorkflow(event: Event, workflow: WorkflowResponse): void {
    event.stopPropagation();
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: 'Delete Workflow',
        message: `Delete workflow "${workflow.name}"?`,
        confirmText: 'Delete',
        warn: true,
      },
    });
    ref.afterClosed().subscribe((confirmed) => {
      if (confirmed) {
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
    });
  }

  runWorkflow(event: Event, workflow: WorkflowResponse): void {
    event.stopPropagation();
    if (workflow.status !== 'enabled') {
      this.snackBar.open('Workflow must be enabled before running', 'OK', { duration: 3000 });
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
    this.workflowService.update(workflow.id, { status: newStatus }).subscribe({
      next: () => {
        this.workflows.update((list) =>
          list.map((w) => (w.id === workflow.id ? { ...w, status: newStatus } : w)),
        );
      },
      error: () => {
        this.snackBar.open('Failed to update status', 'OK', {
          duration: 5000,
        });
      },
    });
  }

  exportWorkflow(event: Event, workflow: WorkflowResponse): void {
    event.stopPropagation();
    this.workflowService.exportWorkflow(workflow);
  }

  async importWorkflow(): Promise<void> {
    const data = await this.workflowService.importWorkflowFromFile();
    if (!data) {
      this.snackBar.open('Invalid workflow file or import cancelled', 'OK', { duration: 3000 });
      return;
    }
    this.workflowService.create(data).subscribe({
      next: (response) => {
        this.snackBar.open(`Workflow "${response.name}" imported`, 'OK', { duration: 3000 });
        this.router.navigate(['/workflows', response.id]);
      },
      error: (err) => {
        this.snackBar.open(
          'Import failed: ' + (err?.error?.detail || 'Unknown error'),
          'OK',
          { duration: 5000 }
        );
      },
    });
  }

  getTriggerLabel(workflow: WorkflowResponse): string {
    if (workflow.workflow_type === 'subflow') {
      return 'Sub-Flow Input';
    }
    const triggerNode = workflow.nodes?.find((n) => n.type === 'trigger');
    if (!triggerNode) return '\u2014';
    const config = triggerNode.config || {};
    if (config['trigger_type'] === 'cron') {
      return `Cron: ${config['cron_expression'] || ''}`;
    }
    if (config['trigger_type'] === 'manual') {
      return 'Manual';
    }
    return `Webhook: ${config['webhook_topic'] || config['webhook_type'] || 'any'}`;
  }
}
