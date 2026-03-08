import { Component, ChangeDetectorRef, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ApiService } from '../../../../core/services/api.service';
import { MistConnectionResult } from '../../../../core/models/admin.model';
import { StatusBadgeComponent } from '../../../../shared/components/status-badge/status-badge.component';
import { SettingsService } from '../settings.service';

const CLOUD_REGIONS = [
  { value: 'global_01', label: 'Global 01 (api.mist.com)' },
  { value: 'global_02', label: 'Global 02 (api.gc1.mist.com)' },
  { value: 'global_03', label: 'Global 03 (api.ac2.mist.com)' },
  { value: 'global_04', label: 'Global 04 (api.gc2.mist.com)' },
  { value: 'global_05', label: 'Global 05 (api.gc4.mist.com)' },
  { value: 'emea_01', label: 'EMEA 01 (api.eu.mist.com)' },
  { value: 'emea_02', label: 'EMEA 02 (api.gc3.mist.com)' },
  { value: 'emea_03', label: 'EMEA 03 (api.ac6.mist.com)' },
  { value: 'emea_04', label: 'EMEA 04 (api.gc6.mist.com)' },
  { value: 'apac_01', label: 'APAC 01 (api.ac5.mist.com)' },
  { value: 'apac_02', label: 'APAC 02 (api.gc5.mist.com)' },
  { value: 'apac_03', label: 'APAC 03 (api.gc7.mist.com)' },
];

@Component({
  selector: 'app-settings-mist',
  standalone: true,
  imports: [
    CommonModule, ReactiveFormsModule,
    MatCardModule, MatFormFieldModule, MatInputModule, MatSelectModule,
    MatButtonModule, MatIconModule, MatSnackBarModule, MatProgressBarModule,
    StatusBadgeComponent,
  ],
  template: `
    @if (loading) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    } @else {
      <form [formGroup]="form" class="tab-form">
        <mat-card>
          <mat-card-header>
            <mat-card-title>Mist API Configuration</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <mat-form-field appearance="outline">
              <mat-label>Organization ID</mat-label>
              <input matInput formControlName="mist_org_id" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" />
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Cloud Region</mat-label>
              <mat-select formControlName="mist_cloud_region">
                @for (region of cloudRegions; track region.value) {
                  <mat-option [value]="region.value">{{ region.label }}</mat-option>
                }
              </mat-select>
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>API Token</mat-label>
              <input matInput type="password" formControlName="mist_api_token"
                     placeholder="Leave empty to keep current" />
              <mat-hint>Leave empty to keep the existing token</mat-hint>
            </mat-form-field>

            <div class="action-row">
              <button mat-stroked-button (click)="testConnection()" [disabled]="testingConnection">
                <mat-icon>wifi_tethering</mat-icon>
                {{ testingConnection ? 'Testing...' : 'Test Connection' }}
              </button>
              @if (connectionResult) {
                <app-status-badge [status]="connectionResult.status"></app-status-badge>
                @if (connectionResult.error) {
                  <span class="error-text">{{ connectionResult.error }}</span>
                }
              }
            </div>
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
    .action-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .error-text { color: var(--mat-sys-error); font-size: 13px; }
  `],
})
export class SettingsMistComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly settingsService = inject(SettingsService);
  private readonly fb = inject(FormBuilder);
  private readonly snackBar = inject(MatSnackBar);
  private readonly cdr = inject(ChangeDetectorRef);

  cloudRegions = CLOUD_REGIONS;
  loading = true;
  saving = false;
  testingConnection = false;
  connectionResult: MistConnectionResult | null = null;

  form = this.fb.group({
    mist_org_id: [''],
    mist_cloud_region: ['global_01'],
    mist_api_token: [''],
  });

  ngOnInit(): void {
    this.settingsService.load().subscribe({
      next: (s) => {
        this.form.patchValue({
          mist_org_id: s.mist_org_id || '',
          mist_cloud_region: s.mist_cloud_region,
        });
        this.loading = false;
        this.cdr.detectChanges();
      },
      error: () => { this.loading = false; this.cdr.detectChanges(); },
    });
  }

  save(): void {
    this.saving = true;
    const v = this.form.getRawValue();
    const updates: Record<string, unknown> = {};
    if (v.mist_org_id) updates['mist_org_id'] = v.mist_org_id;
    if (v.mist_cloud_region) updates['mist_cloud_region'] = v.mist_cloud_region;
    if (v.mist_api_token) updates['mist_api_token'] = v.mist_api_token;

    this.settingsService.save(updates).subscribe({
      next: () => {
        this.saving = false;
        this.snackBar.open('Mist settings saved', 'OK', { duration: 3000 });
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.saving = false;
        this.snackBar.open(err.message, 'OK', { duration: 5000 });
        this.cdr.detectChanges();
      },
    });
  }

  testConnection(): void {
    this.testingConnection = true;
    this.connectionResult = null;
    this.api.post<MistConnectionResult>('/admin/mist/test-connection').subscribe({
      next: (result) => {
        this.connectionResult = result;
        this.testingConnection = false;
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.connectionResult = { status: 'failed', error: err.message };
        this.testingConnection = false;
        this.cdr.detectChanges();
      },
    });
  }
}
