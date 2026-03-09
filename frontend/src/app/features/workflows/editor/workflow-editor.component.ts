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
  WorkflowAction,
  ActionType,
} from '../../../core/models/workflow.model';
import { PipelineCanvasComponent, BranchBlockRef } from './pipeline/pipeline-canvas.component';
import { BlockConfigPanelComponent } from './config/block-config-panel.component';
import {
  BlockPaletteDialogComponent,
  BlockOption,
} from './palette/block-palette-dialog.component';
import { ExecutionDetailDialogComponent } from './execution-detail-dialog.component';

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
  selectedBranch: BranchBlockRef | null = null;
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
    if (this.selectedBranch) {
      return this.getSelectedBranchBlock();
    }
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

  // ── Main pipeline block operations ──────────────────────────

  selectBlock(index: number): void {
    this.selectedBlockIndex = index;
    this.selectedBranch = null;
  }

  removeBlock(index: number): void {
    this.blocks.splice(index, 1);
    if (this.selectedBlockIndex === index) {
      this.selectedBlockIndex = -1;
      this.selectedBranch = null;
    } else if (this.selectedBlockIndex > index) {
      this.selectedBlockIndex--;
    }
    this.blocks = [...this.blocks];
  }

  addBlock(atIndex: number): void {
    this.openPaletteDialog((block) => {
      this.blocks.splice(atIndex, 0, block);
      this.blocks = [...this.blocks];
      this.selectedBlockIndex = atIndex;
      this.selectedBranch = null;
      this.cdr.detectChanges();
    });
  }

  onConfigChanged(updated: PipelineBlock): void {
    if (this.selectedBranch) {
      this.updateBranchAction(updated);
    } else if (this.selectedBlockIndex >= 0) {
      this.blocks[this.selectedBlockIndex] = updated;
      this.blocks = [...this.blocks];
    }
  }

  // ── Branch / loop block operations ────────────────────────────

  selectBranchBlock(ref: BranchBlockRef): void {
    this.selectedBranch = ref;
    this.selectedBlockIndex = ref.blockIndex;
  }

  removeBranchBlock(ref: BranchBlockRef): void {
    const parentBlock = this.blocks[ref.blockIndex];
    const parentAction = parentBlock.data as WorkflowAction;

    if (parentAction.type === 'for_each') {
      // For-each: loop body actions
      parentAction.loop_actions?.splice(ref.actionIndex, 1);
    } else if (ref.branchIndex === -1) {
      // Condition: else branch
      parentAction.else_actions?.splice(ref.actionIndex, 1);
    } else {
      // Condition: if/else-if branch
      parentAction.branches?.[ref.branchIndex]?.actions.splice(ref.actionIndex, 1);
    }

    // Clear selection if this was selected
    if (
      this.selectedBranch &&
      this.selectedBranch.blockIndex === ref.blockIndex &&
      this.selectedBranch.branchIndex === ref.branchIndex &&
      this.selectedBranch.actionIndex === ref.actionIndex
    ) {
      this.selectedBranch = null;
    }

    this.blocks = [...this.blocks];
  }

  addBranchBlock(ref: BranchBlockRef): void {
    this.openPaletteDialog((block) => {
      const parentBlock = this.blocks[ref.blockIndex];
      const parentAction = parentBlock.data as WorkflowAction;
      const newAction = block.data as WorkflowAction;

      if (parentAction.type === 'for_each') {
        // For-each: loop body
        if (!parentAction.loop_actions) parentAction.loop_actions = [];
        parentAction.loop_actions.splice(ref.actionIndex, 0, newAction);
      } else if (ref.branchIndex === -1) {
        // Condition: else branch
        if (!parentAction.else_actions) parentAction.else_actions = [];
        parentAction.else_actions.splice(ref.actionIndex, 0, newAction);
      } else {
        // Condition: if/else-if branch
        const branch = parentAction.branches?.[ref.branchIndex];
        if (branch) {
          branch.actions.splice(ref.actionIndex, 0, newAction);
        }
      }

      this.selectedBranch = ref;
      this.selectedBlockIndex = ref.blockIndex;
      this.blocks = [...this.blocks];
      this.cdr.detectChanges();
    }, true);
  }

  // ── Helpers ─────────────────────────────────────────────────

  private getSelectedBranchBlock(): PipelineBlock | null {
    if (!this.selectedBranch) return null;

    const parentBlock = this.blocks[this.selectedBranch.blockIndex];
    const parentAction = parentBlock.data as WorkflowAction;
    let action: WorkflowAction | undefined;

    if (parentAction.type === 'for_each') {
      // For-each: loop body actions
      action = parentAction.loop_actions?.[this.selectedBranch.actionIndex];
    } else if (this.selectedBranch.branchIndex === -1) {
      action = parentAction.else_actions?.[this.selectedBranch.actionIndex];
    } else {
      action = parentAction.branches?.[this.selectedBranch.branchIndex]?.actions[this.selectedBranch.actionIndex];
    }

    if (!action) return null;

    const META: Record<string, { label: string; icon: string; color: string }> = {
      mist_api_get: { label: 'Mist API GET', icon: 'cloud_download', color: '#1976d2' },
      mist_api_post: { label: 'Mist API POST', icon: 'cloud_upload', color: '#1976d2' },
      mist_api_put: { label: 'Mist API PUT', icon: 'edit', color: '#1976d2' },
      mist_api_delete: { label: 'Mist API DELETE', icon: 'delete', color: '#d32f2f' },
      webhook: { label: 'Webhook', icon: 'send', color: '#7b1fa2' },
      slack: { label: 'Slack', icon: 'chat', color: '#e91e63' },
      servicenow: { label: 'ServiceNow', icon: 'confirmation_number', color: '#388e3c' },
      pagerduty: { label: 'PagerDuty', icon: 'notifications_active', color: '#f57c00' },
      delay: { label: 'Delay', icon: 'schedule', color: '#616161' },
      condition: { label: 'Condition', icon: 'call_split', color: '#0097a7' },
      set_variable: { label: 'Set Variable', icon: 'data_object', color: '#795548' },
      for_each: { label: 'For Each', icon: 'loop', color: '#4527a0' },
    };
    const meta = META[action.type] || { label: action.type, icon: 'play_arrow', color: '#455a64' };

    return {
      id: `branch_${this.selectedBranch.blockIndex}_${this.selectedBranch.branchIndex}_${this.selectedBranch.actionIndex}`,
      kind: 'action',
      data: action,
      label: action.name || meta.label,
      icon: meta.icon,
      color: meta.color,
    };
  }

  private updateBranchAction(updated: PipelineBlock): void {
    if (!this.selectedBranch) return;

    const parentBlock = this.blocks[this.selectedBranch.blockIndex];
    const parentAction = parentBlock.data as WorkflowAction;
    const updatedAction = updated.data as WorkflowAction;

    if (parentAction.type === 'for_each') {
      if (parentAction.loop_actions) {
        parentAction.loop_actions[this.selectedBranch.actionIndex] = updatedAction;
      }
    } else if (this.selectedBranch.branchIndex === -1) {
      if (parentAction.else_actions) {
        parentAction.else_actions[this.selectedBranch.actionIndex] = updatedAction;
      }
    } else {
      const branch = parentAction.branches?.[this.selectedBranch.branchIndex];
      if (branch) {
        branch.actions[this.selectedBranch.actionIndex] = updatedAction;
      }
    }

    this.blocks = [...this.blocks];
  }

  private openPaletteDialog(onSelect: (block: PipelineBlock) => void, actionsOnly = false): void {
    const ref = this.dialog.open(BlockPaletteDialogComponent, {
      width: '480px',
      maxHeight: '80vh',
      data: { actionsOnly },
    });
    ref.afterClosed().subscribe((option: BlockOption | undefined) => {
      if (!option) return;
      const block = this.workflowService.createBlockForType(
        option.kind,
        option.actionType as ActionType | undefined
      );
      onSelect(block);
    });
  }

  // ── Save / Run / Cancel ─────────────────────────────────────

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

  viewExecution(ex: WorkflowExecution): void {
    if (!this.workflowId) return;
    this.dialog.open(ExecutionDetailDialogComponent, {
      width: '900px',
      maxHeight: '90vh',
      data: { workflowId: this.workflowId, execution: ex },
    });
  }

  formatDuration(ms: number | null): string {
    if (!ms) return '—';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }
}
