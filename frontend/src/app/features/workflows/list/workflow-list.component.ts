import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterModule } from '@angular/router';
import { MatTableModule } from '@angular/material/table';
import { MatSortModule, Sort, SortDirection } from '@angular/material/sort';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatMenuModule } from '@angular/material/menu';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { SkeletonLoaderComponent } from '../../../shared/components/skeleton-loader/skeleton-loader.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { ConfirmDialogComponent } from '../../../shared/components/confirm-dialog/confirm-dialog.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { WorkflowService } from '../../../core/services/workflow.service';
import { LlmService } from '../../../core/services/llm.service';
import {
  computeAutoTags,
  isAutoTag,
  WorkflowResponse,
  WorkflowType,
} from '../../../core/models/workflow.model';
import { TopbarService } from '../../../core/services/topbar.service';
import { AiIconComponent } from '../../../shared/components/ai-icon/ai-icon.component';
import { GlobalChatService } from '../../../core/services/global-chat.service';
import { WorkflowAiDialogComponent } from './workflow-ai-dialog.component';
import { RecipePickerDialogComponent } from './recipe-picker-dialog.component';

@Component({
  selector: 'app-workflow-list',
  standalone: true,
  imports: [
    RouterModule,
    MatTableModule,
    MatSortModule,
    MatPaginatorModule,
    MatButtonModule,
    MatIconModule,
    MatSnackBarModule,
    MatMenuModule,
    MatDialogModule,
    MatTooltipModule,
    SkeletonLoaderComponent,
    EmptyStateComponent,
    StatusBadgeComponent,
    AiIconComponent,
    DateTimePipe,
  ],
  templateUrl: './workflow-list.component.html',
  styleUrl: './workflow-list.component.scss',
})
export class WorkflowListComponent implements OnInit {
  private readonly workflowService = inject(WorkflowService);
  private readonly llmService = inject(LlmService);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly topbarService = inject(TopbarService);
  private readonly globalChatService = inject(GlobalChatService);
  private readonly destroyRef = inject(DestroyRef);

  llmAvailable = signal(false);
  workflows = signal<WorkflowResponse[]>([]);
  total = signal(0);
  pageSize = signal(25);
  pageIndex = signal(0);
  loading = signal(true);
  workflowTypeFilter = signal<WorkflowType | undefined>(undefined);
  sortActive = signal('name');
  sortDirection = signal<SortDirection>('asc');

  displayedColumns = ['name', 'trigger', 'status', 'executions', 'last_execution', 'actions'];

  tagFilter = signal<string[]>([]);

  getAutoTags(wf: WorkflowResponse): string[] {
    return computeAutoTags(wf.nodes);
  }

  addTagFilter(tag: string): void {
    if (!this.tagFilter().includes(tag)) {
      this.tagFilter.update((t) => [...t, tag]);
      this.pageIndex.set(0);
      this.loadWorkflows();
    }
  }

  removeTagFilter(tag: string): void {
    this.tagFilter.update((t) => t.filter((v) => v !== tag));
    this.pageIndex.set(0);
    this.loadWorkflows();
  }

  ngOnInit(): void {
    this.topbarService.setTitle('Workflows');
    this.globalChatService.setContext({ page: 'Workflow List', details: { view: 'All workflows' } });
    this.llmService.getStatus().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (s) => this.llmAvailable.set(s.enabled),
      error: () => this.llmAvailable.set(false),
    });
    this.loadWorkflows();
  }

  setTypeFilter(type: WorkflowType | undefined): void {
    this.workflowTypeFilter.set(type);
    this.pageIndex.set(0);
    this.loadWorkflows();
  }

  loadWorkflows(): void {
    this.loading.set(true);
    const sortDir = this.sortDirection() || 'asc';
    const manualTags = this.tagFilter().filter((t) => !isAutoTag(t));
    const autoTags = this.tagFilter().filter((t) => isAutoTag(t));
    const tagsParam = manualTags.length > 0 ? manualTags.join(',') : undefined;
    this.workflowService
      .list(
        this.pageIndex() * this.pageSize(),
        this.pageSize(),
        undefined,
        this.workflowTypeFilter(),
        this.sortActive(),
        sortDir,
        tagsParam
      )
      .subscribe({
        next: (res) => {
          let workflows = res.workflows;
          if (autoTags.length > 0) {
            workflows = workflows.filter((wf) => {
              const wfAutoTags = computeAutoTags(wf.nodes);
              return autoTags.every((t) => wfAutoTags.includes(t));
            });
          }
          this.workflows.set(workflows);
          this.total.set(res.total);
          this.loading.set(false);
        },
        error: () => {
          this.loading.set(false);
        },
      });
  }

  onSort(sort: Sort): void {
    this.sortActive.set(sort.active);
    this.sortDirection.set(sort.direction);
    this.pageIndex.set(0);
    this.loadWorkflows();
  }

  onPage(event: PageEvent): void {
    this.pageIndex.set(event.pageIndex);
    this.pageSize.set(event.pageSize);
    this.loadWorkflows();
  }

  totalActiveEvents(wf: WorkflowResponse): number {
    return (wf.active_windows ?? []).reduce((sum, w) => sum + w.event_count, 0);
  }

  createWorkflow(): void {
    const ref = this.dialog.open(RecipePickerDialogComponent, {
      width: '620px',
      maxHeight: '85vh',
      data: { llmAvailable: this.llmAvailable() },
    });
    ref.afterClosed().pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
      if (result === 'ai') {
        this.createWithAI();
      } else {
        this.loadWorkflows();
      }
    });
  }

  createSubflow(): void {
    this.router.navigate(['/workflows/new'], { queryParams: { type: 'subflow' } });
  }

  createWithAI(): void {
    const ref = this.dialog.open(WorkflowAiDialogComponent, {
      width: '600px',
      maxHeight: '80vh',
    });
    ref.afterClosed().pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => this.loadWorkflows());
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

  duplicateWorkflow(event: Event, workflow: WorkflowResponse): void {
    event.stopPropagation();
    this.workflowService.duplicate(workflow.id).subscribe({
      next: (response) => {
        this.snackBar.open(`Workflow duplicated as "${response.name}"`, 'OK', { duration: 3000 });
        this.loadWorkflows();
      },
      error: () => {
        this.snackBar.open('Failed to duplicate workflow', 'OK', { duration: 5000 });
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
