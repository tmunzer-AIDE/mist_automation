import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-page-header',
  standalone: true,
  template: `
    <div class="page-header">
      <div class="page-header-text">
        <h1>{{ title }}</h1>
        @if (subtitle) {
          <span class="subtitle">{{ subtitle }}</span>
        }
      </div>
      <div class="page-header-actions">
        <ng-content></ng-content>
      </div>
    </div>
  `,
  styles: [`
    .page-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      flex-wrap: wrap;
      gap: 12px;
    }
    .page-header-text {
      display: flex;
      align-items: baseline;
      gap: 12px;
    }
    h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 600;
      letter-spacing: -0.3px;
    }
    .subtitle {
      color: var(--mat-sys-on-surface-variant);
      font-size: 13px;
    }
    .page-header-actions {
      display: flex;
      gap: 8px;
    }
  `],
})
export class PageHeaderComponent {
  @Input({ required: true }) title!: string;
  @Input() subtitle?: string;
}
