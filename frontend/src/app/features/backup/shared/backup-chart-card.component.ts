import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-backup-chart-card',
  standalone: true,
  template: `
    <div class="chart-card">
      <h3>{{ title }}</h3>
      <ng-content></ng-content>
    </div>
  `,
  styles: [
    `
      .chart-card {
        flex: 1;
        min-width: 0;
        padding: 16px;
        border-radius: var(--app-radius);
        background: var(--mat-sys-surface-container-low);
        border: 1px solid var(--mat-sys-outline-variant);
      }
      h3 {
        margin: 0 0 12px;
        font-size: 14px;
        font-weight: 600;
        color: var(--mat-sys-on-surface-variant);
      }
    `,
  ],
})
export class BackupChartCardComponent {
  @Input({ required: true }) title!: string;
}
