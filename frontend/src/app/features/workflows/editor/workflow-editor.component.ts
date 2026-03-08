import { Component, ChangeDetectorRef, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatTableModule } from '@angular/material/table';
import { MatExpansionModule } from '@angular/material/expansion';
import { PageHeaderComponent } from '../../../shared/components/page-header/page-header.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { RelativeTimePipe } from '../../../shared/pipes/relative-time.pipe';
import { WorkflowService } from '../../../core/services/workflow.service';
import {
  PipelineBlock,
  WorkflowResponse,
  WorkflowExecution,
  ActionType,
} from '../../../core/models/workflow.model';
import { PipelineCanvasComponent } from './pipeline/pipeline-canvas.component';
import { BlockConfigPanelComponent } from './config/block-config-panel.component';
import {
  BlockPaletteDialogComponent,
  BlockOption,
} from './palette/block-palette-dialog.component';

@Component({
  selector: 'app-workflow-editor',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatSnackBarModule,
    MatDialogModule,
    MatTableModule,
    MatExpansionModule,
    PageHeaderComponent,
    StatusBadgeComponent,
    RelativeTimePipe,
    PipelineCanvasComponent,
    BlockConfigPanelComponent,
  ],
  templateUrl: './workflow-editor.component.html',
  styleUrl: './workflow-editor.component.scss',
})
export class WorkflowEditorComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly workflowService = inject(WorkflowService);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly cdr = inject(ChangeDetectorRef);

  workflowId: string | null = null;
  workflowName = '';
  workflowDescription = '';
  blocks: PipelineBlock[] = [];
  selectedBlockIndex = -1;
  loading = true;
  saving = false;

  // Execution history
  executions: WorkflowExecution[] = [];
  executionsTotal = 0;
  executionColumns = ['status', 'trigger_type', 'started_at', 'duration', 'actions_executed'];

  get isEditMode(): boolean {
    return !!this.workflowId;
  }

  get selectedBlock(): PipelineBlock | null {
    return this.selectedBlockIndex >= 0 ? this.blocks[this.selectedBlockIndex] : null;
  }

  get canSave(): boolean {
    return this.workflowName.trim().length > 0 && this.blocks.length > 0 && !this.saving;
  }

  get pageTitle(): string {
    return this.isEditMode ? 'Edit Workflow' : 'New Workflow';
  }

  ngOnInit(): void {
    this.workflowId = this.route.snapshot.paramMap.get('id');
    if (this.workflowId) {
      this.loadWorkflow(this.workflowId);
    } else {
      this.blocks = [this.workflowService.createDefaultTriggerBlock()];
      this.loading = false;
    }
  }

  private loadWorkflow(id: string): void {
    this.loading = true;
    this.workflowService.get(id).subscribe({
      next: (wf: WorkflowResponse) => {
        this.workflowName = wf.name;
        this.workflowDescription = wf.description || '';
        this.blocks = this.workflowService.toPipelineBlocks(wf);
        this.loading = false;
        this.cdr.detectChanges();
        this.loadExecutions();
      },
      error: () => {
        this.snackBar.open('Failed to load workflow', 'OK', { duration: 5000 });
        this.loading = false;
        this.cdr.detectChanges();
      },
    });
  }

  private loadExecutions(): void {
    if (!this.workflowId) return;
    this.workflowService.getExecutions(this.workflowId, 0, 10).subscribe({
      next: (res) => {
        this.executions = res.executions;
        this.executionsTotal = res.total;
        this.cdr.detectChanges();
      },
    });
  }

  selectBlock(index: number): void {
    this.selectedBlockIndex = index;
  }

  removeBlock(index: number): void {
    this.blocks.splice(index, 1);
    if (this.selectedBlockIndex === index) {
      this.selectedBlockIndex = -1;
    } else if (this.selectedBlockIndex > index) {
      this.selectedBlockIndex--;
    }
    this.blocks = [...this.blocks];
  }

  addBlock(atIndex: number): void {
    const ref = this.dialog.open(BlockPaletteDialogComponent, {
      width: '480px',
      maxHeight: '80vh',
    });
    ref.afterClosed().subscribe((option: BlockOption | undefined) => {
      if (!option) return;
      const block = this.workflowService.createBlockForType(
        option.kind,
        option.actionType as ActionType | undefined
      );
      this.blocks.splice(atIndex, 0, block);
      this.blocks = [...this.blocks];
      this.selectedBlockIndex = atIndex;
      this.cdr.detectChanges();
    });
  }

  onConfigChanged(updated: PipelineBlock): void {
    if (this.selectedBlockIndex >= 0) {
      this.blocks[this.selectedBlockIndex] = updated;
      this.blocks = [...this.blocks];
    }
  }

  save(): void {
    this.saving = true;
    const pipelineData = this.workflowService.fromPipelineBlocks(this.blocks);
    const payload = {
      name: this.workflowName,
      description: this.workflowDescription || undefined,
      ...pipelineData,
    };

    const obs = this.workflowId
      ? this.workflowService.update(this.workflowId, payload)
      : this.workflowService.create({
          ...payload,
          actions: pipelineData.actions.length > 0 ? pipelineData.actions : [{ name: 'placeholder', type: 'webhook' }],
        });

    obs.subscribe({
      next: () => {
        this.saving = false;
        this.snackBar.open('Workflow saved', 'OK', { duration: 3000 });
        this.router.navigate(['/workflows']);
      },
      error: () => {
        this.saving = false;
        this.snackBar.open('Failed to save workflow', 'OK', { duration: 5000 });
        this.cdr.detectChanges();
      },
    });
  }

  run(): void {
    if (!this.workflowId) return;
    this.workflowService.execute(this.workflowId).subscribe({
      next: () => {
        this.snackBar.open('Workflow execution queued', 'OK', { duration: 3000 });
        setTimeout(() => this.loadExecutions(), 2000);
      },
      error: (err) => {
        this.snackBar.open(
          err.error?.detail || 'Failed to run workflow',
          'OK',
          { duration: 5000 }
        );
      },
    });
  }

  cancel(): void {
    this.router.navigate(['/workflows']);
  }

  formatDuration(ms: number | null): string {
    if (!ms) return '—';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }
}
