import { Component, ChangeDetectorRef, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatDividerModule } from '@angular/material/divider';
import { SettingsService } from '../settings.service';

@Component({
  selector: 'app-settings-integrations',
  standalone: true,
  imports: [
    CommonModule, ReactiveFormsModule,
    MatCardModule, MatFormFieldModule, MatInputModule,
    MatButtonModule, MatIconModule, MatSnackBarModule,
    MatProgressBarModule, MatDividerModule,
  ],
  template: `
    @if (loading) {
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
              <input matInput formControlName="slack_webhook_url" placeholder="https://hooks.slack.com/services/..." />
            </mat-form-field>
          </mat-card-content>
        </mat-card>

        <mat-card>
          <mat-card-header>
            <mat-card-title>ServiceNow</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <mat-form-field appearance="outline">
              <mat-label>Instance URL</mat-label>
              <input matInput formControlName="servicenow_instance_url" placeholder="https://instance.service-now.com" />
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Username</mat-label>
              <input matInput formControlName="servicenow_username" />
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Password</mat-label>
              <input matInput type="password" formControlName="servicenow_password"
                     placeholder="Leave empty to keep current" />
            </mat-form-field>
          </mat-card-content>
        </mat-card>

        <mat-card>
          <mat-card-header>
            <mat-card-title>PagerDuty</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <mat-form-field appearance="outline">
              <mat-label>Integration Key</mat-label>
              <input matInput type="password" formControlName="pagerduty_api_key"
                     placeholder="Leave empty to keep current" />
            </mat-form-field>
          </mat-card-content>
          <mat-card-actions align="end">
            <button mat-flat-button (click)="save()" [disabled]="saving">
              <mat-icon>save</mat-icon> {{ saving ? 'Saving...' : 'Save' }}
            </button>
          </mat-card-actions>
        </mat-card>
      </form>
    }
  `,
  styles: [`
    .tab-form { display: flex; flex-direction: column; gap: 24px; }
    mat-card-content { display: flex; flex-direction: column; gap: 4px; padding-top: 16px; }
    mat-form-field { width: 100%; max-width: 500px; }
  `],
})
export class SettingsIntegrationsComponent implements OnInit {
  private readonly settingsService = inject(SettingsService);
  private readonly fb = inject(FormBuilder);
  private readonly snackBar = inject(MatSnackBar);
  private readonly cdr = inject(ChangeDetectorRef);

  loading = true;
  saving = false;

  form = this.fb.group({
    slack_webhook_url: [''],
    servicenow_instance_url: [''],
    servicenow_username: [''],
    servicenow_password: [''],
    pagerduty_api_key: [''],
  });

  ngOnInit(): void {
    this.settingsService.load().subscribe({
      next: (s) => {
        this.form.patchValue({
          slack_webhook_url: s.slack_webhook_url || '',
          servicenow_instance_url: s.servicenow_instance_url || '',
          servicenow_username: s.servicenow_username || '',
        });
        this.loading = false;
        this.cdr.detectChanges();
      },
      error: () => { this.loading = false; this.cdr.detectChanges(); },
    });
  }

  save(): void {
    this.saving = true;
    const values = this.form.getRawValue();
    const updates: Record<string, unknown> = {};
    Object.entries(values).forEach(([k, v]) => {
      if (v !== '' && v !== null) updates[k] = v;
    });

    this.settingsService.save(updates).subscribe({
      next: () => {
        this.saving = false;
        this.snackBar.open('Integration settings saved', 'OK', { duration: 3000 });
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.saving = false;
        this.snackBar.open(err.message, 'OK', { duration: 5000 });
        this.cdr.detectChanges();
      },
    });
  }
}
