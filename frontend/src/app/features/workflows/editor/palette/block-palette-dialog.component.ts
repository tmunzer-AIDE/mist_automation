import { Component, inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';

export interface BlockPaletteDialogData {
  actionsOnly?: boolean;
}

// Re-export for backward compatibility
export type { BlockOption } from './block-categories';

import { BLOCK_CATEGORIES, BlockCategory } from './block-categories';

@Component({
  selector: 'app-block-palette-dialog',
  standalone: true,
  imports: [MatDialogModule, MatIconModule, MatButtonModule],
  templateUrl: './block-palette-dialog.component.html',
  styleUrl: './block-palette-dialog.component.scss',
})
export class BlockPaletteDialogComponent {
  private readonly dialogRef = inject(MatDialogRef<BlockPaletteDialogComponent>);
  private readonly dialogData: BlockPaletteDialogData | null = inject(MAT_DIALOG_DATA, {
    optional: true,
  });

  readonly categories: BlockCategory[] = BLOCK_CATEGORIES;

  selectOption(option: import('./block-categories').BlockOption): void {
    this.dialogRef.close(option);
  }
}
