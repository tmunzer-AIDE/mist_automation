import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-status-badge',
  standalone: true,
  template: `
    <span class="badge" [class]="'badge-' + normalizedStatus">
      <span class="dot"></span>
      {{ status }}
    </span>
  `,
  styles: [
    `
      .badge {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        font-size: 12px;
        font-weight: 500;
        padding: 3px 10px 3px 8px;
        border-radius: 6px;
        text-transform: capitalize;
        letter-spacing: 0.2px;
      }
      .dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        flex-shrink: 0;
      }

      .badge-completed,
      .badge-succeeded,
      .badge-success,
      .badge-connected,
      .badge-healthy,
      .badge-enabled,
      .badge-active {
        background: var(--app-success-bg);
        color: var(--app-success);
        .dot {
          background: var(--app-success-badge);
        }
      }
      .badge-pending,
      .badge-draft,
      .badge-in_progress,
      .badge-running {
        background: var(--app-warning-bg);
        color: var(--app-warning);
        .dot {
          background: var(--app-warning);
        }
      }
      .badge-failed,
      .badge-error,
      .badge-timeout,
      .badge-cancelled,
      .badge-inactive,
      .badge-stopped,
      .badge-deleted {
        background: var(--app-error-status-bg);
        color: var(--app-error-status);
        .dot {
          background: var(--app-spinner-disconnected);
        }
      }
      .badge-filtered,
      .badge-partial,
      .badge-manual,
      .badge-scheduled {
        background: var(--app-info-bg);
        color: var(--app-info-chip);
        .dot {
          background: var(--app-info-badge);
        }
      }
    `,
  ],
})
export class StatusBadgeComponent {
  @Input({ required: true }) status!: string;

  get normalizedStatus(): string {
    return (this.status || '').toLowerCase().replace(/\s+/g, '_');
  }
}
