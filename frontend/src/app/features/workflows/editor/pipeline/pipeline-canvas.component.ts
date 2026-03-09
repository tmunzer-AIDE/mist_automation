import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
  PipelineBlock,
  WorkflowAction,
  ConditionBranch,
} from '../../../../core/models/workflow.model';

/** Identifies a block within a condition branch or for-each loop body. */
export interface BranchBlockRef {
  blockIndex: number;
  branchIndex: number; // -1 = else branch, 0 = loop body (for for_each)
  actionIndex: number;
}

@Component({
  selector: 'app-pipeline-canvas',
  standalone: true,
  imports: [CommonModule, MatIconModule, MatButtonModule, MatTooltipModule],
  templateUrl: './pipeline-canvas.component.html',
  styleUrl: './pipeline-canvas.component.scss',
})
export class PipelineCanvasComponent {
  @Input() blocks: PipelineBlock[] = [];
  @Input() selectedIndex = -1;
  @Input() selectedBranch: BranchBlockRef | null = null;

  @Output() blockSelected = new EventEmitter<number>();
  @Output() blockRemoved = new EventEmitter<number>();
  @Output() addRequested = new EventEmitter<number>();

  @Output() branchBlockSelected = new EventEmitter<BranchBlockRef>();
  @Output() branchBlockRemoved = new EventEmitter<BranchBlockRef>();
  @Output() branchAddRequested = new EventEmitter<BranchBlockRef>();

  select(index: number): void {
    this.blockSelected.emit(index);
  }

  remove(event: Event, index: number): void {
    event.stopPropagation();
    this.blockRemoved.emit(index);
  }

  isConditionBlock(block: PipelineBlock): boolean {
    return block.kind === 'action' && (block.data as WorkflowAction).type === 'condition';
  }

  isForEachBlock(block: PipelineBlock): boolean {
    return block.kind === 'action' && (block.data as WorkflowAction).type === 'for_each';
  }

  getBranches(block: PipelineBlock): ConditionBranch[] {
    return (block.data as WorkflowAction).branches || [];
  }

  getElseActions(block: PipelineBlock): WorkflowAction[] {
    return (block.data as WorkflowAction).else_actions || [];
  }

  getLoopActions(block: PipelineBlock): WorkflowAction[] {
    return (block.data as WorkflowAction).loop_actions || [];
  }

  getLoopInfo(block: PipelineBlock): { loop_over: string; loop_variable: string } {
    const data = block.data as WorkflowAction;
    return {
      loop_over: data.loop_over || '',
      loop_variable: data.loop_variable || 'item',
    };
  }

  branchLabel(branchIndex: number): string {
    return branchIndex === 0 ? 'If' : 'Else if';
  }

  selectBranchAction(blockIndex: number, branchIndex: number, actionIndex: number): void {
    this.branchBlockSelected.emit({ blockIndex, branchIndex, actionIndex });
  }

  removeBranchAction(event: Event, blockIndex: number, branchIndex: number, actionIndex: number): void {
    event.stopPropagation();
    this.branchBlockRemoved.emit({ blockIndex, branchIndex, actionIndex });
  }

  addBranchAction(blockIndex: number, branchIndex: number, actionIndex: number): void {
    this.branchAddRequested.emit({ blockIndex, branchIndex, actionIndex });
  }

  isBranchActionSelected(blockIndex: number, branchIndex: number, actionIndex: number): boolean {
    if (!this.selectedBranch) return false;
    return (
      this.selectedBranch.blockIndex === blockIndex &&
      this.selectedBranch.branchIndex === branchIndex &&
      this.selectedBranch.actionIndex === actionIndex
    );
  }

  getActionMeta(action: WorkflowAction): { icon: string; color: string } {
    const META: Record<string, { icon: string; color: string }> = {
      mist_api_get: { icon: 'cloud_download', color: '#1976d2' },
      mist_api_post: { icon: 'cloud_upload', color: '#1976d2' },
      mist_api_put: { icon: 'edit', color: '#1976d2' },
      mist_api_delete: { icon: 'delete', color: '#d32f2f' },
      webhook: { icon: 'send', color: '#7b1fa2' },
      slack: { icon: 'chat', color: '#e91e63' },
      servicenow: { icon: 'confirmation_number', color: '#388e3c' },
      pagerduty: { icon: 'notifications_active', color: '#f57c00' },
      delay: { icon: 'schedule', color: '#616161' },
      condition: { icon: 'call_split', color: '#0097a7' },
      set_variable: { icon: 'data_object', color: '#795548' },
      for_each: { icon: 'loop', color: '#4527a0' },
    };
    return META[action.type] || { icon: 'play_arrow', color: '#455a64' };
  }
}
