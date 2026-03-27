import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule, ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ApiService } from '../../../../core/services/api.service';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';

interface TelemetrySettings {
  telemetry_enabled: boolean;
  influxdb_url: string | null;
  influxdb_token_set: boolean;
  influxdb_org: string | null;
  influxdb_bucket: string | null;
  telemetry_retention_days: number;
}

interface TelemetryStatus {
  enabled: boolean;
  influxdb: {
    connected: boolean;
    writes_ok: number;
    writes_error: number;
    last_write_at: number | null;
  } | null;
  cache_size: number;
  websocket: {
    connections: number;
    sites_subscribed: number;
  } | null;
  ingestion: {
    events_received: number;
    events_written: number;
    events_dropped: number;
  } | null;
}

interface ReconnectResponse {
  reconnected: boolean;
  connections: number;
  sites: number;
  message: string;
}

@Component({
  selector: 'app-settings-telemetry',
  standalone: true,
  imports: [
    FormsModule,
    ReactiveFormsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatIconModule,
    MatProgressBarModule,
    MatSlideToggleModule,
    MatSnackBarModule,
  ],
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    } @else {
      <div class="tab-form wide">
        <mat-card>
          <mat-card-header>
            <mat-card-title>Telemetry Pipeline</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <div class="toggle-row">
              <mat-slide-toggle
                [ngModel]="telemetryEnabled()"
                (ngModelChange)="toggleTelemetry($event)"
                [disabled]="saving()"
              >
                Enable Telemetry Collection
              </mat-slide-toggle>
            </div>
            <p class="hint-text">
              When enabled, device stats are streamed via Mist WebSockets and stored in InfluxDB for
              time-series analysis and impact monitoring.
            </p>
          </mat-card-content>
        </mat-card>

        @if (telemetryEnabled()) {
          <mat-card>
            <mat-card-header>
              <mat-card-title>InfluxDB Connection</mat-card-title>
            </mat-card-header>
            <mat-card-content>
              <form [formGroup]="form">
                <mat-form-field appearance="outline">
                  <mat-label>InfluxDB URL</mat-label>
                  <input
                    matInput
                    formControlName="influxdb_url"
                    placeholder="http://localhost:8086"
                  />
                </mat-form-field>

                <mat-form-field appearance="outline">
                  <mat-label>Organization</mat-label>
                  <input
                    matInput
                    formControlName="influxdb_org"
                    placeholder="mist_automation"
                  />
                </mat-form-field>

                <mat-form-field appearance="outline">
                  <mat-label>Bucket</mat-label>
                  <input
                    matInput
                    formControlName="influxdb_bucket"
                    placeholder="mist_telemetry"
                  />
                </mat-form-field>

                <mat-form-field appearance="outline">
                  <mat-label>API Token</mat-label>
                  <input
                    matInput
                    type="password"
                    formControlName="influxdb_token"
                    placeholder="Leave empty to keep current"
                  />
                  @if (tokenSet()) {
                    <mat-hint>Token configured — leave empty to keep</mat-hint>
                  }
                </mat-form-field>

                <mat-form-field appearance="outline">
                  <mat-label>Retention (days)</mat-label>
                  <input
                    matInput
                    type="number"
                    formControlName="telemetry_retention_days"
                    min="1"
                    max="365"
                  />
                  <mat-hint>How long to keep telemetry data in InfluxDB (1–365 days)</mat-hint>
                </mat-form-field>

                <div class="action-row">
                  <button
                    mat-stroked-button
                    (click)="reconnect()"
                    [disabled]="reconnecting() || saving()"
                  >
                    <mat-icon>sync</mat-icon>
                    {{ reconnecting() ? 'Reconnecting...' : 'Test & Reconnect' }}
                  </button>
                  @if (reconnectResult()) {
                    <span class="reconnect-result" [class.ok]="reconnectResult()!.reconnected" [class.fail]="!reconnectResult()!.reconnected">
                      <mat-icon>{{ reconnectResult()!.reconnected ? 'check_circle' : 'error' }}</mat-icon>
                      {{ reconnectResult()!.message }}
                    </span>
                  }
                </div>
              </form>
            </mat-card-content>
            <mat-card-actions align="end">
              <button mat-flat-button (click)="save()" [disabled]="saving()">
                <mat-icon>save</mat-icon> {{ saving() ? 'Saving...' : 'Save' }}
              </button>
            </mat-card-actions>
          </mat-card>

          <mat-card>
            <mat-card-header>
              <mat-card-title>Pipeline Status</mat-card-title>
              <button mat-icon-button (click)="loadStatus()" [disabled]="statusLoading()">
                <mat-icon>refresh</mat-icon>
              </button>
            </mat-card-header>
            <mat-card-content>
              @if (statusLoading()) {
                <mat-progress-bar mode="indeterminate"></mat-progress-bar>
              } @else if (status()) {
                <div class="status-grid">
                  <div class="status-item">
                    <span class="status-label">InfluxDB</span>
                    @if (status()!.influxdb) {
                      <span class="status-value" [class.ok]="status()!.influxdb!.connected" [class.fail]="!status()!.influxdb!.connected">
                        {{ status()!.influxdb!.connected ? 'Connected' : 'Disconnected' }}
                      </span>
                    } @else {
                      <span class="status-value fail">Not initialized</span>
                    }
                  </div>
                  <div class="status-item">
                    <span class="status-label">Cache entries</span>
                    <span class="status-value">{{ status()!.cache_size }}</span>
                  </div>
                  @if (status()!.websocket) {
                    <div class="status-item">
                      <span class="status-label">WS connections</span>
                      <span class="status-value">{{ status()!.websocket!.connections }}</span>
                    </div>
                    <div class="status-item">
                      <span class="status-label">Sites subscribed</span>
                      <span class="status-value">{{ status()!.websocket!.sites_subscribed }}</span>
                    </div>
                  }
                  @if (status()!.ingestion) {
                    <div class="status-item">
                      <span class="status-label">Events received</span>
                      <span class="status-value">{{ status()!.ingestion!.events_received }}</span>
                    </div>
                    <div class="status-item">
                      <span class="status-label">Events written</span>
                      <span class="status-value ok">{{ status()!.ingestion!.events_written }}</span>
                    </div>
                    <div class="status-item">
                      <span class="status-label">Events dropped</span>
                      <span class="status-value" [class.fail]="status()!.ingestion!.events_dropped > 0">
                        {{ status()!.ingestion!.events_dropped }}
                      </span>
                    </div>
                  }
                </div>
              } @else {
                <p class="hint-text">Failed to load status.</p>
              }
            </mat-card-content>
          </mat-card>
        }
      </div>
    }
  `,
  styles: [
    `
      .toggle-row {
        margin-bottom: 8px;
      }
      .hint-text {
        color: var(--mat-sys-on-surface-variant);
        font-size: 13px;
        margin: 4px 0 0;
      }
      .action-row {
        display: flex;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
        margin-top: 4px;
      }
      .reconnect-result {
        display: flex;
        align-items: center;
        gap: 4px;
        font-size: 13px;
        &.ok { color: var(--app-success, #4caf50); }
        &.fail { color: var(--mat-sys-error); }
        mat-icon { font-size: 16px; width: 16px; height: 16px; }
      }
      .status-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
        gap: 12px;
        padding: 8px 0;
      }
      .status-item {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .status-label {
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--mat-sys-on-surface-variant);
      }
      .status-value {
        font-size: 14px;
        font-weight: 500;
        &.ok { color: var(--app-success, #4caf50); }
        &.fail { color: var(--mat-sys-error); }
      }
      mat-card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
    `,
  ],
})
export class SettingsTelemetryComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly fb = inject(FormBuilder);
  private readonly snackBar = inject(MatSnackBar);

  loading = signal(true);
  saving = signal(false);
  telemetryEnabled = signal(false);
  tokenSet = signal(false);
  reconnecting = signal(false);
  reconnectResult = signal<ReconnectResponse | null>(null);
  statusLoading = signal(false);
  status = signal<TelemetryStatus | null>(null);

  form = this.fb.group({
    influxdb_url: [''],
    influxdb_org: [''],
    influxdb_bucket: [''],
    influxdb_token: [''],
    telemetry_retention_days: [30],
  });

  ngOnInit(): void {
    this.api.get<TelemetrySettings>('/telemetry/settings').subscribe({
      next: (s) => {
        this.telemetryEnabled.set(s.telemetry_enabled);
        this.tokenSet.set(s.influxdb_token_set);
        this.form.patchValue({
          influxdb_url: s.influxdb_url || '',
          influxdb_org: s.influxdb_org || '',
          influxdb_bucket: s.influxdb_bucket || '',
          telemetry_retention_days: s.telemetry_retention_days,
        });
        this.loading.set(false);
        if (s.telemetry_enabled) {
          this.loadStatus();
        }
      },
      error: () => this.loading.set(false),
    });
  }

  toggleTelemetry(enabled: boolean): void {
    this.saving.set(true);
    this.api.put<TelemetrySettings>('/telemetry/settings', { telemetry_enabled: enabled }).subscribe({
      next: (s) => {
        this.telemetryEnabled.set(s.telemetry_enabled);
        this.saving.set(false);
        this.snackBar.open(enabled ? 'Telemetry enabled' : 'Telemetry disabled', 'OK', {
          duration: 3000,
        });
        if (enabled) {
          this.loadStatus();
        }
      },
      error: (err) => {
        this.saving.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  save(): void {
    this.saving.set(true);
    const v = this.form.getRawValue();
    const updates: Record<string, unknown> = {};
    if (v.influxdb_url !== null) updates['influxdb_url'] = v.influxdb_url || null;
    if (v.influxdb_org !== null) updates['influxdb_org'] = v.influxdb_org || null;
    if (v.influxdb_bucket !== null) updates['influxdb_bucket'] = v.influxdb_bucket || null;
    if (v.influxdb_token) updates['influxdb_token'] = v.influxdb_token;
    if (v.telemetry_retention_days !== null)
      updates['telemetry_retention_days'] = v.telemetry_retention_days;

    this.api.put<TelemetrySettings>('/telemetry/settings', updates).subscribe({
      next: (s) => {
        this.tokenSet.set(s.influxdb_token_set);
        this.form.patchValue({ influxdb_token: '' });
        this.saving.set(false);
        this.snackBar.open('Telemetry settings saved', 'OK', { duration: 3000 });
      },
      error: (err) => {
        this.saving.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  reconnect(): void {
    this.reconnecting.set(true);
    this.reconnectResult.set(null);
    this.api.post<ReconnectResponse>('/telemetry/reconnect', {}).subscribe({
      next: (result) => {
        this.reconnectResult.set(result);
        this.reconnecting.set(false);
        this.loadStatus();
      },
      error: (err) => {
        this.reconnectResult.set({
          reconnected: false,
          connections: 0,
          sites: 0,
          message: extractErrorMessage(err),
        });
        this.reconnecting.set(false);
      },
    });
  }

  loadStatus(): void {
    this.statusLoading.set(true);
    this.api.get<TelemetryStatus>('/telemetry/status').subscribe({
      next: (s) => {
        this.status.set(s);
        this.statusLoading.set(false);
      },
      error: () => {
        this.status.set(null);
        this.statusLoading.set(false);
      },
    });
  }
}
