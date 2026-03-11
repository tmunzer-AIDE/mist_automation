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
      .badge-connected,
      .badge-healthy,
      .badge-enabled,
      .badge-active {
        background: #ecfdf5;
        color: #047857;
        .dot {
          background: #10b981;
        }
      }
      .badge-pending,
      .badge-draft,
      .badge-in_progress,
      .badge-running {
        background: #fffbeb;
        color: #b45309;
        .dot {
          background: #f59e0b;
        }
      }
      .badge-failed,
      .badge-error,
      .badge-inactive,
      .badge-stopped,
      .badge-deleted {
        background: #fef2f2;
        color: #b91c1c;
        .dot {
          background: #ef4444;
        }
      }
      .badge-manual,
      .badge-scheduled {
        background: #eff6ff;
        color: #1d4ed8;
        .dot {
          background: #3b82f6;
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
