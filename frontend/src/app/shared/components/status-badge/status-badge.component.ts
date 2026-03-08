import { Component, Input } from '@angular/core';
import { MatChipsModule } from '@angular/material/chips';

@Component({
  selector: 'app-status-badge',
  standalone: true,
  imports: [MatChipsModule],
  template: `
    <mat-chip [class]="'status-' + normalizedStatus" highlighted>
      {{ status }}
    </mat-chip>
  `,
  styles: [`
    .status-completed, .status-succeeded, .status-connected, .status-healthy, .status-enabled, .status-active {
      --mat-chip-elevated-container-color: #e8f5e9;
      --mat-chip-label-text-color: #2e7d32;
    }
    .status-pending, .status-draft, .status-in_progress, .status-running {
      --mat-chip-elevated-container-color: #fff3e0;
      --mat-chip-label-text-color: #e65100;
    }
    .status-failed, .status-error, .status-inactive, .status-stopped {
      --mat-chip-elevated-container-color: #ffebee;
      --mat-chip-label-text-color: #c62828;
    }
    .status-manual, .status-scheduled {
      --mat-chip-elevated-container-color: #e3f2fd;
      --mat-chip-label-text-color: #1565c0;
    }
  `],
})
export class StatusBadgeComponent {
  @Input({ required: true }) status!: string;

  get normalizedStatus(): string {
    return (this.status || '').toLowerCase().replace(/\s+/g, '_');
  }
}
