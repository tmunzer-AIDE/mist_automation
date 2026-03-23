import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatDividerModule } from '@angular/material/divider';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { SettingsService } from '../settings.service';
import { ApiService } from '../../../../core/services/api.service';
import { IntegrationTestResult, SystemSettings } from '../../../../core/models/admin.model';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';

@Component({
  selector: 'app-settings-integrations',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatSnackBarModule,
    MatProgressBarModule,
    MatDividerModule,
    MatSlideToggleModule,
  ],
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    } @else {
      <form [formGroup]="form" class="tab-form">
        <mat-card>
          <mat-card-header>
            <mat-card-title>Slack</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <mat-form-field appearance="outline">
              <mat-label>Webhook URL</mat-label>
              <input
                matInput
                formControlName="slack_webhook_url"
                placeholder="https://hooks.slack.com/services/..."
              />
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Signing Secret</mat-label>
              <input
                matInput
                type="password"
                formControlName="slack_signing_secret"
                placeholder="Leave empty to keep current"
              />
            </mat-form-field>
            <p class="field-help">
              Found in your <b>Slack App</b> settings under
              <b>Basic Information &rarr; App Credentials &rarr; Signing Secret</b>.
              Used to verify that interactive requests (e.g. approval buttons from
              <code>wait_for_callback</code> nodes) genuinely originate from Slack.
            </p>
          </mat-card-content>
          <mat-card-actions align="end">
            <button mat-stroked-button (click)="testSlack()" [disabled]="testingSlack()">
              {{ testingSlack() ? 'Testing...' : 'Test Connection' }}
            </button>
          </mat-card-actions>
        </mat-card>

        <mat-card>
          <mat-card-header>
            <mat-card-title>ServiceNow</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <mat-form-field appearance="outline">
              <mat-label>Instance URL</mat-label>
              <input
                matInput
                formControlName="servicenow_instance_url"
                placeholder="https://instance.service-now.com"
              />
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Username</mat-label>
              <input matInput formControlName="servicenow_username" />
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Password</mat-label>
              <input
                matInput
                type="password"
                formControlName="servicenow_password"
                placeholder="Leave empty to keep current"
              />
            </mat-form-field>
          </mat-card-content>
          <mat-card-actions align="end">
            <button mat-stroked-button (click)="testServiceNow()" [disabled]="testingServiceNow()">
              {{ testingServiceNow() ? 'Testing...' : 'Test Connection' }}
            </button>
          </mat-card-actions>
        </mat-card>

        <mat-card>
          <mat-card-header>
            <mat-card-title>PagerDuty</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <mat-form-field appearance="outline">
              <mat-label>Integration Key</mat-label>
              <input
                matInput
                type="password"
                formControlName="pagerduty_api_key"
                placeholder="Leave empty to keep current"
              />
            </mat-form-field>
          </mat-card-content>
          <mat-card-actions align="end">
            <button mat-stroked-button (click)="testPagerDuty()" [disabled]="testingPagerDuty()">
              {{ testingPagerDuty() ? 'Testing...' : 'Test Connection' }}
            </button>
          </mat-card-actions>
        </mat-card>

        <mat-card>
          <mat-card-header>
            <mat-card-title>Email / SMTP</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <div class="smtp-row">
              <mat-form-field appearance="outline" class="smtp-host">
                <mat-label>SMTP Host</mat-label>
                <input matInput formControlName="smtp_host" placeholder="smtp.example.com" />
              </mat-form-field>

              <mat-form-field appearance="outline" class="smtp-port">
                <mat-label>Port</mat-label>
                <input matInput type="number" formControlName="smtp_port" />
              </mat-form-field>
            </div>

            <mat-form-field appearance="outline">
              <mat-label>From Address</mat-label>
              <input matInput formControlName="smtp_from_email" placeholder="noreply@example.com" />
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Username</mat-label>
              <input matInput formControlName="smtp_username" />
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Password</mat-label>
              <input
                matInput
                type="password"
                formControlName="smtp_password"
                placeholder="Leave empty to keep current"
              />
            </mat-form-field>

            <mat-slide-toggle formControlName="smtp_use_tls">Use TLS</mat-slide-toggle>
          </mat-card-content>
          <mat-card-actions align="end">
            <button mat-flat-button (click)="save()" [disabled]="saving()">
              <mat-icon>save</mat-icon> {{ saving() ? 'Saving...' : 'Save' }}
            </button>
          </mat-card-actions>
        </mat-card>
      </form>
    }
  `,
  styles: [
    `
      .field-help {
        font-size: 12px;
        color: var(--app-neutral, #6b7280);
        margin: -8px 0 16px;
        line-height: 1.5;
      }
      .field-help code {
        background: rgba(0, 0, 0, 0.06);
        padding: 1px 4px;
        border-radius: 3px;
        font-size: 11px;
      }
      .smtp-row {
        display: flex;
        gap: 16px;
      }
      .smtp-host {
        flex: 1;
      }
      .smtp-port {
        width: 120px;
      }
    `,
  ],
})
export class SettingsIntegrationsComponent implements OnInit {
  private readonly settingsService = inject(SettingsService);
  private readonly fb = inject(FormBuilder);
  private readonly snackBar = inject(MatSnackBar);
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);

  loading = signal(true);
  saving = signal(false);
  testingSlack = signal(false);
  testingServiceNow = signal(false);
  testingPagerDuty = signal(false);

  form = this.fb.group({
    slack_webhook_url: [''],
    slack_signing_secret: [''],
    servicenow_instance_url: [''],
    servicenow_username: [''],
    servicenow_password: [''],
    pagerduty_api_key: [''],
    smtp_host: [''],
    smtp_port: [587],
    smtp_from_email: [''],
    smtp_username: [''],
    smtp_password: [''],
    smtp_use_tls: [true],
  });

  ngOnInit(): void {
    const cached = this.settingsService.current;
    if (cached) {
      this.populateForm(cached);
      this.loading.set(false);
    } else {
      this.settingsService.load().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
        next: (s) => {
          this.populateForm(s);
          this.loading.set(false);
        },
        error: () => {
          this.loading.set(false);
        },
      });
    }
  }

  private populateForm(s: SystemSettings): void {
    this.form.patchValue({
      slack_webhook_url: s.slack_webhook_url || '',
      servicenow_instance_url: s.servicenow_instance_url || '',
      servicenow_username: s.servicenow_username || '',
      smtp_host: s.smtp_host || '',
      smtp_port: s.smtp_port || 587,
      smtp_from_email: s.smtp_from_email || '',
      smtp_username: s.smtp_username || '',
      smtp_use_tls: s.smtp_use_tls ?? true,
    });
  }

  save(): void {
    this.saving.set(true);
    const values = this.form.getRawValue();
    const updates: Record<string, unknown> = {};
    Object.entries(values).forEach(([k, v]) => {
      if (v !== '' && v !== null && v !== undefined) updates[k] = v;
    });

    this.settingsService.save(updates).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: () => {
        this.saving.set(false);
        this.snackBar.open('Integration settings saved', 'OK', { duration: 3000 });
      },
      error: (err) => {
        this.saving.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  testSlack(): void {
    this.testingSlack.set(true);
    const url = this.form.value.slack_webhook_url;
    this.api.post<IntegrationTestResult>('/admin/integrations/test-slack', url ? { slack_webhook_url: url } : {}).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (r) => {
        this.testingSlack.set(false);
        this.snackBar.open(r.status === 'connected' ? 'Slack connection successful' : (r.error ?? 'Failed'), 'OK', { duration: 3000 });
      },
      error: (err) => {
        this.testingSlack.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  testServiceNow(): void {
    this.testingServiceNow.set(true);
    const v = this.form.value;
    const body: Record<string, string> = {};
    if (v.servicenow_instance_url) body['servicenow_instance_url'] = v.servicenow_instance_url;
    if (v.servicenow_username) body['servicenow_username'] = v.servicenow_username;
    if (v.servicenow_password) body['servicenow_password'] = v.servicenow_password;
    this.api.post<IntegrationTestResult>('/admin/integrations/test-servicenow', body).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (r) => {
        this.testingServiceNow.set(false);
        this.snackBar.open(r.status === 'connected' ? 'ServiceNow connection successful' : (r.error ?? 'Failed'), 'OK', { duration: 3000 });
      },
      error: (err) => {
        this.testingServiceNow.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  testPagerDuty(): void {
    this.testingPagerDuty.set(true);
    const key = this.form.value.pagerduty_api_key;
    this.api.post<IntegrationTestResult>('/admin/integrations/test-pagerduty', key ? { pagerduty_api_key: key } : {}).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (r) => {
        this.testingPagerDuty.set(false);
        this.snackBar.open(r.status === 'connected' ? 'PagerDuty key valid' : (r.error ?? 'Failed'), 'OK', { duration: 3000 });
      },
      error: (err) => {
        this.testingPagerDuty.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }
}
