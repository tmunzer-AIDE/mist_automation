import { Component, Input } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-empty-state',
  standalone: true,
  imports: [MatIconModule],
  template: `
    <div class="empty-state">
      <div class="icon-circle">
        <mat-icon class="empty-icon">{{ icon }}</mat-icon>
      </div>
      <h3>{{ title }}</h3>
      @if (message) {
        <p>{{ message }}</p>
      }
      <div class="empty-actions">
        <ng-content></ng-content>
      </div>
    </div>
  `,
  styles: [
    `
      @keyframes fade-slide-up {
        from {
          opacity: 0;
          transform: translateY(8px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }
      .empty-state {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 64px 24px;
        text-align: center;
        animation: fade-slide-up 200ms ease-out;
      }
      .icon-circle {
        width: 80px;
        height: 80px;
        border-radius: 50%;
        background: var(--mat-sys-surface-container);
        display: flex;
        align-items: center;
        justify-content: center;
        margin-bottom: 16px;
      }
      .empty-icon {
        font-size: 48px;
        width: 48px;
        height: 48px;
        color: var(--mat-sys-on-surface-variant);
      }
      h3 {
        margin: 0 0 8px;
        font-size: 16px;
        font-weight: 600;
      }
      p {
        margin: 0 0 24px;
        color: var(--mat-sys-on-surface-variant);
        font-size: 14px;
        max-width: 400px;
      }
    `,
  ],
})
export class EmptyStateComponent {
  @Input() icon = 'inbox';
  @Input({ required: true }) title!: string;
  @Input() message?: string;
}
