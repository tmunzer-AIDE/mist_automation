import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-page-header',
  standalone: true,
  template: `
    <div class="page-header">
      <div class="page-header-text">
        @if (title) {
          <h1 class="page-title">{{ title }}</h1>
        }
        @if (subtitle) {
          <span class="subtitle">{{ subtitle }}</span>
        }
      </div>
      <div class="page-header-actions">
        <ng-content></ng-content>
      </div>
    </div>
  `,
  styles: [
    `
      .page-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 24px;
        padding-bottom: 20px;
        border-bottom: 1px solid var(--mat-sys-outline-variant);
        flex-wrap: wrap;
        gap: 12px;
      }
      .page-header-text {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      .page-title {
        margin: 0;
        font-family: var(--app-font-display);
        font-size: var(--app-text-xl);
        font-weight: 600;
        color: var(--mat-sys-on-surface);
        letter-spacing: -0.2px;
      }
      .subtitle {
        color: var(--mat-sys-on-surface-variant);
        font-size: var(--app-text-base);
      }
      .page-header-actions {
        display: flex;
        gap: 8px;
      }
    `,
  ],
})
export class PageHeaderComponent {
  @Input() title?: string;
  @Input() subtitle?: string;
}
