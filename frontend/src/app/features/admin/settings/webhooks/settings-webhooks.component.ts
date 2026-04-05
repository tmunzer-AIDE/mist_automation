import { Component, inject, OnInit, signal } from '@angular/core';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatCheckboxModule } from '@angular/material/checkbox';
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
    ReactiveFormsModule,
    MatCardModule,
    MatCheckboxModule,
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
            <mat-card-title>IP Allowlist</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <p class="hint-text">
              Restrict incoming webhooks to specific IP addresses or CIDR ranges.
              Leave empty to allow all sources.
            </p>

            @if (!mistIpsExpanded()) {
              <button
                mat-stroked-button
                type="button"
                (click)="loadMistIps()"
                [disabled]="loadingMistIps()"
                class="mist-ips-btn"
              >
                <mat-icon>cloud_download</mat-icon>
                {{ loadingMistIps() ? 'Loading...' : 'Load Mist Cloud IPs' }}
              </button>
            } @else {
              <div class="mist-ips-panel">
                <p class="hint-text">Select Mist cloud regions to add their webhook source IPs:</p>
                <div class="region-grid">
                  @for (region of mistRegions(); track region.name) {
                    <label class="region-item">
                      <mat-checkbox
                        [checked]="region.selected"
                        (change)="toggleRegion(region.name)"
                      >
                        <span class="region-name">{{ region.name }}</span>
                        <span class="region-ips">{{ region.ips.join(', ') }}</span>
                      </mat-checkbox>
                    </label>
                  }
                </div>
                <div class="action-row">
                  <button mat-flat-button type="button" (click)="addSelectedMistIps()">
                    <mat-icon>add</mat-icon> Add Selected
                  </button>
                  <button mat-stroked-button type="button" (click)="mistIpsExpanded.set(false)">
                    Cancel
                  </button>
                </div>
              </div>
            }

            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Allowed IPs / CIDRs</mat-label>
              <textarea
                matInput
                formControlName="webhook_ip_whitelist"
                rows="5"
                placeholder="One IP or CIDR per line, e.g.&#10;192.168.1.0/24&#10;10.0.0.1"
              ></textarea>
              <mat-hint>One IP address or CIDR range per line</mat-hint>
            </mat-form-field>
          </mat-card-content>
          <mat-card-actions align="end">
            <button mat-flat-button (click)="saveIpAllowlist()" [disabled]="saving()">
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
      .full-width {
        width: 100%;
      }
      .smee-badge {
        margin-left: 12px;
      }
      .mist-ips-btn {
        margin-bottom: 16px;
      }
      .mist-ips-panel {
        margin-bottom: 16px;
        padding: 12px;
        border: 1px solid var(--mat-sys-outline-variant, #c4c7c5);
        border-radius: 8px;
      }
      .region-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
        gap: 4px;
        margin-bottom: 12px;
      }
      .region-item {
        display: block;
      }
      .region-name {
        font-weight: 500;
        margin-right: 8px;
      }
      .region-ips {
        font-size: 12px;
        color: var(--mat-sys-on-surface-variant);
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
  loadingMistIps = signal(false);
  mistIpsExpanded = signal(false);
  mistRegions = signal<{ name: string; ips: string[]; selected: boolean }[]>([]);

  form = this.fb.group({
    webhook_secret: [''],
    webhook_ip_whitelist: [''],
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
      webhook_ip_whitelist: s.webhook_ip_whitelist?.join('\n') || '',
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

  saveIpAllowlist(): void {
    this.saving.set(true);
    const raw = this.form.value.webhook_ip_whitelist || '';
    const webhook_ip_whitelist = raw
      .split('\n')
      .map((line: string) => line.trim())
      .filter((line: string) => line.length > 0);
    this.settingsService.save({ webhook_ip_whitelist }).subscribe({
      next: () => {
        this.saving.set(false);
        this.snackBar.open('IP allowlist saved', 'OK', { duration: 3000 });
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

  loadMistIps(): void {
    this.loadingMistIps.set(true);
    this.api.get<Record<string, string[]>>('/admin/mist-webhook-ips').subscribe({
      next: (data) => {
        this.mistRegions.set(
          Object.entries(data).map(([name, ips]) => ({ name, ips, selected: false }))
        );
        this.mistIpsExpanded.set(true);
        this.loadingMistIps.set(false);
      },
      error: (err) => {
        this.loadingMistIps.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  toggleRegion(name: string): void {
    this.mistRegions.update((regions) =>
      regions.map((r) => (r.name === name ? { ...r, selected: !r.selected } : r))
    );
  }

  addSelectedMistIps(): void {
    const selected = this.mistRegions().filter((r) => r.selected);
    if (!selected.length) {
      this.snackBar.open('Select at least one region', 'OK', { duration: 3000 });
      return;
    }
    const newIps = selected.flatMap((r) => r.ips);
    const current = (this.form.value.webhook_ip_whitelist || '')
      .split('\n')
      .map((l: string) => l.trim())
      .filter((l: string) => l.length > 0);
    const existing = new Set(current);
    const toAdd = newIps.filter((ip) => !existing.has(ip));
    if (toAdd.length) {
      const merged = [...current, ...toAdd].join('\n');
      this.form.patchValue({ webhook_ip_whitelist: merged });
    }
    this.mistIpsExpanded.set(false);
    this.snackBar.open(`Added ${toAdd.length} IP(s) from ${selected.length} region(s)`, 'OK', {
      duration: 3000,
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
