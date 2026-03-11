import { Component, EventEmitter, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { BLOCK_CATEGORIES, BlockCategory } from './block-categories';

@Component({
  selector: 'app-block-palette-sidebar',
  standalone: true,
  imports: [CommonModule, MatIconModule, MatTooltipModule],
  templateUrl: './block-palette-sidebar.component.html',
  styleUrl: './block-palette-sidebar.component.scss',
})
export class BlockPaletteSidebarComponent {
  readonly categories: BlockCategory[] = BLOCK_CATEGORIES;

  @Output() blockSelected = new EventEmitter<string>();

  onDragStart(event: DragEvent, actionType: string): void {
    event.dataTransfer?.setData('text/plain', actionType);
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'copy';
    }
  }
}
