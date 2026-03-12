import { Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatDividerModule } from '@angular/material/divider';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../../../core/services/api.service';
import { SmeeStatus } from '../../../../core/models/admin.model';
import { StatusBadgeComponent } from '../../../../shared/components/status-badge/status-badge.component';
import { SettingsService } from '../settings.service';
import { SystemSettings } from '../../../../core/models/admin.model';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';

@Component({
  selector: 'app-settings-webhooks',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatSnackBarModule,
    MatProgressBarModule,
    MatSlideToggleModule,
    MatDividerModule,
    MatTooltipModule,
    StatusBadgeComponent,
  ],
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    } @else {
      <form [formGroup]="form" class="tab-form">
        <mat-card>
          <mat-card-header>
            <mat-card-title>Webhook Secret</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <div class="secret-row">
              <mat-form-field appearance="outline">
                <mat-label>Webhook Secret</mat-label>
                <input
                  matInput
                  [type]="secretVisible ? 'text' : 'password'"
                  formControlName="webhook_secret"
                  placeholder="Leave empty to keep current"
                />
                <button
                  mat-icon-button
                  matSuffix
                  type="button"
                  (click)="secretVisible = !secretVisible"
                  [matTooltip]="secretVisible ? 'Hide' : 'Show'"
                >
                  <mat-icon>{{ secretVisible ? 'visibility_off' : 'visibility' }}</mat-icon>
                </button>
                <mat-hint>Used to verify Mist webhook signatures (HMAC-SHA256)</mat-hint>
              </mat-form-field>
              <button
                mat-stroked-button
                type="button"
                (click)="generateSecret()"
                matTooltip="Generate a random secret"
              >
                <mat-icon>casino</mat-icon> Generate
              </button>
            </div>
          </mat-card-content>
          <mat-card-actions align="end">
            <button mat-flat-button (click)="saveWebhook()" [disabled]="saving()">
              <mat-icon>save</mat-icon> {{ saving() ? 'Saving...' : 'Save' }}
            </button>
          </mat-card-actions>
        </mat-card>

        <mat-card>
          <mat-card-header>
            <mat-card-title>
              Smee.io
              @if (smeeStatus()) {
                <app-status-badge
                  [status]="smeeStatus()!.running ? 'connected' : 'stopped'"
                  class="smee-badge"
                ></app-status-badge>
              }
            </mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <p class="hint-text">
              Smee.io acts as a webhook proxy for development. It receives webhooks at a public URL
              and forwards them to this application.
            </p>

            <mat-slide-toggle formControlName="smee_enabled"
              >Enable Smee.io forwarding</mat-slide-toggle
            >

            <mat-form-field appearance="outline">
              <mat-label>Smee Channel URL</mat-label>
              <input
                matInput
                formControlName="smee_channel_url"
                placeholder="https://smee.io/your-channel-id"
              />
              <mat-hint>
                Get a new channel at
                <a href="https://smee.io" target="_blank" rel="noopener">smee.io</a>
              </mat-hint>
            </mat-form-field>

            <div class="action-row">
              @if (smeeStatus()?.running) {
                <button
                  mat-stroked-button
                  color="warn"
                  (click)="stopSmee()"
                  [disabled]="smeeAction()"
                >
                  <mat-icon>stop</mat-icon> Stop
                </button>
              } @else {
                <button
                  mat-stroked-button
                  (click)="startSmee()"
                  [disabled]="smeeAction() || !form.value.smee_channel_url"
                >
                  <mat-icon>play_arrow</mat-icon> Start
                </button>
              }
            </div>
          </mat-card-content>
          <mat-card-actions align="end">
            <button mat-flat-button (click)="saveSmee()" [disabled]="saving()">
              <mat-icon>save</mat-icon> {{ saving() ? 'Saving...' : 'Save' }}
            </button>
          </mat-card-actions>
        </mat-card>
      </form>
    }
  `,
  styles: [
    `
      .secret-row {
        display: flex;
        align-items: flex-start;
        gap: 12px;
      }
      .secret-row mat-form-field {
        flex: 1;
      }
      .secret-row button {
        margin-top: 4px;
      }
      .action-row {
        display: flex;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
        padding-top: 8px;
      }
      .hint-text {
        font-size: 13px;
        color: var(--mat-sys-on-surface-variant);
        margin: 0 0 12px;
        line-height: 1.5;
      }
      .hint-text a {
        color: var(--mat-sys-primary);
      }
      .smee-badge {
        margin-left: 12px;
      }
    `,
  ],
})
export class SettingsWebhooksComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly settingsService = inject(SettingsService);
  private readonly fb = inject(FormBuilder);
  private readonly snackBar = inject(MatSnackBar);

  loading = signal(true);
  saving = signal(false);
  secretVisible = false;
  smeeAction = signal(false);
  smeeStatus = signal<SmeeStatus | null>(null);

  form = this.fb.group({
    webhook_secret: [''],
    smee_enabled: [false],
    smee_channel_url: [''],
  });

  ngOnInit(): void {
    const cached = this.settingsService.current;
    if (cached) {
      this.populateForm(cached);
      this.loading.set(false);
    } else {
      this.settingsService.load().subscribe({
        next: (s) => {
          this.populateForm(s);
          this.loading.set(false);
        },
        error: () => {
          this.loading.set(false);
        },
      });
    }
    this.loadSmeeStatus();
  }

  private populateForm(s: SystemSettings): void {
    this.form.patchValue({
      webhook_secret: s.webhook_secret || '',
      smee_enabled: s.smee_enabled,
      smee_channel_url: s.smee_channel_url || '',
    });
  }

  generateSecret(): void {
    const bytes = new Uint8Array(32);
    crypto.getRandomValues(bytes);
    const secret = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
    this.form.patchValue({ webhook_secret: secret });
  }

  saveWebhook(): void {
    this.saving.set(true);
    const secret = this.form.value.webhook_secret;
    if (!secret) {
      this.saving.set(false);
      return;
    }
    this.settingsService.save({ webhook_secret: secret }).subscribe({
      next: () => {
        this.saving.set(false);
        this.form.patchValue({ webhook_secret: '' });
        this.snackBar.open('Webhook secret saved', 'OK', { duration: 3000 });
      },
      error: (err) => {
        this.saving.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  saveSmee(): void {
    this.saving.set(true);
    const updates: Record<string, unknown> = {
      smee_enabled: this.form.value.smee_enabled,
    };
    if (this.form.value.smee_channel_url) {
      updates['smee_channel_url'] = this.form.value.smee_channel_url;
    }
    this.settingsService.save(updates).subscribe({
      next: () => {
        this.saving.set(false);
        this.snackBar.open('Smee settings saved', 'OK', { duration: 3000 });
        this.loadSmeeStatus();
      },
      error: (err) => {
        this.saving.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  startSmee(): void {
    this.smeeAction.set(true);
    const url = this.form.value.smee_channel_url;
    this.api
      .post<{ status: string }>('/webhooks/smee/start', url ? { smee_channel_url: url } : {})
      .subscribe({
        next: () => {
          this.smeeAction.set(false);
          this.snackBar.open('Smee client started', 'OK', { duration: 3000 });
          this.loadSmeeStatus();
        },
        error: (err) => {
          this.smeeAction.set(false);
          this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
        },
      });
  }

  stopSmee(): void {
    this.smeeAction.set(true);
    this.api.post<{ status: string }>('/webhooks/smee/stop').subscribe({
      next: () => {
        this.smeeAction.set(false);
        this.snackBar.open('Smee client stopped', 'OK', { duration: 3000 });
        this.loadSmeeStatus();
      },
      error: (err) => {
        this.smeeAction.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  private loadSmeeStatus(): void {
    this.api.get<SmeeStatus>('/webhooks/smee/status').subscribe({
      next: (status) => {
        this.smeeStatus.set(status);
      },
    });
  }
}
