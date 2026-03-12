import { Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Clipboard } from '@angular/cdk/clipboard';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTabsModule } from '@angular/material/tabs';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { StatusBadgeComponent } from '../status-badge/status-badge.component';
import { DateTimePipe } from '../../pipes/date-time.pipe';
import { WebhookEventService } from '../../../core/services/webhook-event.service';
import { WebhookEventDetail } from '../../../core/models/webhook-event.model';
import { getStatusClass } from '../../utils/http-status.utils';

@Component({
  selector: 'app-webhook-event-detail-dialog',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatIconModule,
    MatTabsModule,
    MatSnackBarModule,
    MatDialogModule,
    StatusBadgeComponent,
    DateTimePipe,
  ],
  template: `
    <h2 mat-dialog-title>
      @if (event()) {
        <span class="dialog-title">
          <span class="type-label">{{ event()!.webhook_type }}</span>
          <span class="id-label">{{ event()!.webhook_id }}</span>
        </span>
      } @else {
        Loading…
      }
    </h2>

    <mat-dialog-content>
      @if (loading()) {
        <div class="loading">Loading event details…</div>
      } @else if (event()) {
        <!-- Info grid -->
        <div class="info-grid">
          <div class="info-item">
            <span class="info-label">Received</span>
            <span class="info-value">{{ event()!.received_at | dateTime }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">Source IP</span>
            <span class="info-value">{{ event()!.source_ip || '—' }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">Site ID</span>
            <span class="info-value mono">{{ event()!.site_id || '—' }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">Org ID</span>
            <span class="info-value mono">{{ event()!.org_id || '—' }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">Signature</span>
            <span class="info-value">
              <app-status-badge
                [status]="event()!.signature_valid ? 'active' : 'failed'"
              ></app-status-badge>
            </span>
          </div>
          <div class="info-item">
            <span class="info-label">Routed To</span>
            <span class="info-value">
              <span class="route-chips">
                @for (target of event()!.routed_to; track target) {
                  <span class="route-chip" [class]="'chip-' + target">{{ target }}</span>
                }
              </span>
            </span>
          </div>
          <div class="info-item">
            <span class="info-label">Response</span>
            <span class="info-value">
              <span class="http-status" [class]="getStatusClass(event()!.response_status)">
                {{ event()!.response_status }}
              </span>
            </span>
          </div>
          <div class="info-item">
            <span class="info-label">Matched</span>
            <span class="info-value"
              >{{ event()!.matched_workflows.length }} workflow(s),
              {{ event()!.executions_triggered.length }} execution(s)</span
            >
          </div>
        </div>

        <!-- Tabs -->
        <mat-tab-group>
          <mat-tab label="Payload">
            <div class="tab-content">
              <div class="json-header">
                <button mat-icon-button (click)="copyJson(event()!.payload)">
                  <mat-icon>content_copy</mat-icon>
                </button>
              </div>
              <pre class="json-pre">{{ event()!.payload | json }}</pre>
            </div>
          </mat-tab>
          <mat-tab label="Headers">
            <div class="tab-content">
              <table class="headers-table">
                @for (entry of headerEntries(); track entry[0]) {
                  <tr>
                    <td class="header-key">{{ entry[0] }}</td>
                    <td class="header-value">{{ entry[1] }}</td>
                  </tr>
                }
              </table>
            </div>
          </mat-tab>
          <mat-tab label="Response">
            <div class="tab-content">
              <div class="response-status-line">
                <span class="http-status" [class]="getStatusClass(event()!.response_status)">
                  {{ event()!.response_status }}
                </span>
              </div>
              <pre class="json-pre">{{ event()!.response_body | json }}</pre>
            </div>
          </mat-tab>
        </mat-tab-group>
      }
    </mat-dialog-content>

    <mat-dialog-actions align="end">
      <button mat-stroked-button (click)="replay()" [disabled]="!event() || replaying()">
        <mat-icon>replay</mat-icon>
        @if (replaying()) {
          Replaying…
        } @else {
          Replay
        }
      </button>
      <button mat-flat-button mat-dialog-close>Close</button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .dialog-title {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .type-label {
        font-weight: 600;
        text-transform: capitalize;
      }
      .id-label {
        font-size: 12px;
        color: var(--mat-sys-on-surface-variant);
        font-family: monospace;
      }
      .loading {
        padding: 24px;
        color: var(--mat-sys-on-surface-variant);
      }
      .info-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
        margin-bottom: 20px;
      }
      .info-item {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .info-label {
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--mat-sys-on-surface-variant);
      }
      .info-value {
        font-size: 14px;
      }
      .mono {
        font-family: monospace;
        font-size: 12px;
      }
      .route-chips {
        display: flex;
        gap: 4px;
      }
      .route-chip {
        display: inline-block;
        font-size: 11px;
        font-weight: 500;
        padding: 2px 8px;
        border-radius: 4px;
        text-transform: capitalize;
      }
      .chip-automation {
        background: var(--app-info-chip-bg);
        color: var(--app-info-chip);
      }
      .chip-backup {
        background: var(--app-success-bg);
        color: var(--app-success);
      }
      .http-status {
        font-family: monospace;
        font-weight: 600;
        font-size: 13px;
        padding: 2px 8px;
        border-radius: 4px;
      }
      .tab-content {
        padding: 16px 0;
      }
      .json-header {
        display: flex;
        justify-content: flex-end;
      }
      .json-pre {
        background: var(--mat-sys-surface-container);
        border-radius: 8px;
        padding: 16px;
        font-size: 12px;
        font-family: monospace;
        overflow: auto;
        max-height: 400px;
        white-space: pre-wrap;
        word-break: break-all;
      }
      .headers-table {
        width: 100%;
        border-collapse: collapse;
      }
      .headers-table tr {
        border-bottom: 1px solid var(--mat-sys-outline-variant);
      }
      .header-key {
        font-weight: 500;
        font-family: monospace;
        font-size: 12px;
        padding: 6px 12px 6px 0;
        white-space: nowrap;
        vertical-align: top;
      }
      .header-value {
        font-family: monospace;
        font-size: 12px;
        padding: 6px 0;
        word-break: break-all;
        color: var(--mat-sys-on-surface-variant);
      }
      .response-status-line {
        margin-bottom: 12px;
      }
    `,
  ],
})
export class WebhookEventDetailDialogComponent implements OnInit {
  private readonly data: { eventId: string } = inject(MAT_DIALOG_DATA);
  private readonly dialogRef = inject(MatDialogRef<WebhookEventDetailDialogComponent>);
  private readonly webhookEventService = inject(WebhookEventService);
  private readonly clipboard = inject(Clipboard);
  private readonly snackBar = inject(MatSnackBar);

  event = signal<WebhookEventDetail | null>(null);
  headerEntries = signal<[string, string][]>([]);
  loading = signal(true);
  replaying = signal(false);

  ngOnInit(): void {
    this.webhookEventService.getEvent(this.data.eventId).subscribe({
      next: (ev) => {
        this.event.set(ev);
        this.headerEntries.set(Object.entries(ev.headers || {}));
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
      },
    });
  }

  copyJson(obj: unknown): void {
    this.clipboard.copy(JSON.stringify(obj, null, 2));
    this.snackBar.open('Copied to clipboard', 'OK', { duration: 2000 });
  }

  replay(): void {
    if (!this.event()) return;
    this.replaying.set(true);
    this.webhookEventService.replayEvent(this.event()!.id).subscribe({
      next: () => {
        this.replaying.set(false);
        this.snackBar.open('Event queued for replay', 'OK', { duration: 3000 });
      },
      error: () => {
        this.replaying.set(false);
        this.snackBar.open('Failed to replay event', 'OK', { duration: 5000 });
      },
    });
  }

  readonly getStatusClass = getStatusClass;
}
