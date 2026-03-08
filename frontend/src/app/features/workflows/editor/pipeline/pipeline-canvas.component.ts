import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { PipelineBlock } from '../../../../core/models/workflow.model';

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

  @Output() blockSelected = new EventEmitter<number>();
  @Output() blockRemoved = new EventEmitter<number>();
  @Output() addRequested = new EventEmitter<number>();

  select(index: number): void {
    this.blockSelected.emit(index);
  }

  remove(event: Event, index: number): void {
    event.stopPropagation();
    this.blockRemoved.emit(index);
  }
}
