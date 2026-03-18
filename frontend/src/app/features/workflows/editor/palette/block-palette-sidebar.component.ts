import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
  BLOCK_CATEGORIES,
  SUBFLOW_OUTPUT_BLOCK,
  BlockCategory,
} from './block-categories';
import { WorkflowType } from '../../../../core/models/workflow.model';

@Component({
  selector: 'app-block-palette-sidebar',
  standalone: true,
  imports: [MatIconModule, MatTooltipModule],
  templateUrl: './block-palette-sidebar.component.html',
  styleUrl: './block-palette-sidebar.component.scss',
})
export class BlockPaletteSidebarComponent implements OnChanges {
  @Input() workflowType: WorkflowType = 'standard';
  @Output() blockSelected = new EventEmitter<string>();

  categories: BlockCategory[] = BLOCK_CATEGORIES;

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['workflowType']) {
      this.rebuildCategories();
    }
  }

  onDragStart(event: DragEvent, actionType: string): void {
    event.dataTransfer?.setData('text/plain', actionType);
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'copy';
    }
  }

  private rebuildCategories(): void {
    if (this.workflowType === 'subflow') {
      // For subflow editing, add subflow_output to Sub-Flows category
      this.categories = BLOCK_CATEGORIES.map((cat) => {
        if (cat.name === 'Sub-Flows') {
          return {
            ...cat,
            options: [...cat.options, SUBFLOW_OUTPUT_BLOCK],
          };
        }
        return cat;
      });
    } else {
      this.categories = BLOCK_CATEGORIES;
    }
  }
}
