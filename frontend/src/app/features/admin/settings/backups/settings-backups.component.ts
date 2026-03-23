import { Component, inject, OnInit, signal } from '@angular/core';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatDividerModule } from '@angular/material/divider';
import { SettingsService } from '../settings.service';
import { SystemSettings } from '../../../../core/models/admin.model';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';

@Component({
  selector: 'app-settings-backups',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatSnackBarModule,
    MatProgressBarModule,
    MatSlideToggleModule,
    MatDividerModule,
  ],
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    } @else {
      <form [formGroup]="form" class="tab-form">
        <mat-card>
          <mat-card-header>
            <mat-card-title>Backup Configuration</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <mat-slide-toggle formControlName="backup_enabled"
              >Enable automatic backups</mat-slide-toggle
            >

            <h3 class="subsection-title">Schedule</h3>
            <div class="schedule-row">
              <mat-form-field appearance="outline">
                <mat-label>Frequency</mat-label>
                <mat-select formControlName="schedule_frequency">
                  <mat-option value="daily">Daily</mat-option>
                  <mat-option value="weekly">Weekly</mat-option>
                  <mat-option value="monthly">Monthly</mat-option>
                </mat-select>
              </mat-form-field>

              @if (form.value.schedule_frequency === 'weekly') {
                <mat-form-field appearance="outline">
                  <mat-label>Day of Week</mat-label>
                  <mat-select formControlName="schedule_day_of_week">
                    <mat-option value="0">Monday</mat-option>
                    <mat-option value="1">Tuesday</mat-option>
                    <mat-option value="2">Wednesday</mat-option>
                    <mat-option value="3">Thursday</mat-option>
                    <mat-option value="4">Friday</mat-option>
                    <mat-option value="5">Saturday</mat-option>
                    <mat-option value="6">Sunday</mat-option>
                  </mat-select>
                </mat-form-field>
              }

              @if (form.value.schedule_frequency === 'monthly') {
                <mat-form-field appearance="outline">
                  <mat-label>Day of Month</mat-label>
                  <mat-select formControlName="schedule_day_of_month">
                    @for (d of daysOfMonth; track d) {
                      <mat-option [value]="d">{{ d }}</mat-option>
                    }
                  </mat-select>
                </mat-form-field>
              }

              <mat-form-field appearance="outline">
                <mat-label>Time (UTC)</mat-label>
                <mat-select formControlName="schedule_hour">
                  @for (h of hours; track h.value) {
                    <mat-option [value]="h.value">{{ h.label }}</mat-option>
                  }
                </mat-select>
              </mat-form-field>
            </div>
            <p class="schedule-preview">
              Cron: <code>{{ cronPreview }}</code>
            </p>

            <mat-form-field appearance="outline">
              <mat-label>Backup Retention (days)</mat-label>
              <input matInput type="number" formControlName="backup_retention_days" min="1" />
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Execution Retention (days)</mat-label>
              <input matInput type="number" formControlName="execution_retention_days" min="1" />
              <mat-hint>Workflow execution logs older than this will be purged</mat-hint>
            </mat-form-field>

            <mat-divider></mat-divider>

            <h3 class="subsection-title">Git Integration</h3>
            <mat-slide-toggle formControlName="backup_git_enabled"
              >Enable Git backup</mat-slide-toggle
            >

            <mat-form-field appearance="outline">
              <mat-label>Repository URL</mat-label>
              <input
                matInput
                formControlName="backup_git_repo_url"
                placeholder="https://github.com/org/repo.git"
              />
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Branch</mat-label>
              <input matInput formControlName="backup_git_branch" />
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Author Name</mat-label>
              <input matInput formControlName="backup_git_author_name" />
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Author Email</mat-label>
              <input matInput formControlName="backup_git_author_email" />
            </mat-form-field>
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
      .subsection-title {
        font-size: 14px;
        font-weight: 500;
        margin: 16px 0 8px;
        color: var(--mat-sys-on-surface-variant);
      }
      mat-divider {
        margin: 16px 0;
      }
      .schedule-row {
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
      }
      .schedule-row mat-form-field {
        flex: 1;
        min-width: 140px;
        max-width: 200px;
      }
      .schedule-preview {
        margin: -4px 0 8px;
        font-size: 12px;
        color: var(--mat-sys-on-surface-variant);
      }
      .schedule-preview code {
        background: var(--mat-sys-surface-container);
        padding: 2px 6px;
        border-radius: 4px;
      }
    `,
  ],
})
export class SettingsBackupsComponent implements OnInit {
  private readonly settingsService = inject(SettingsService);
  private readonly fb = inject(FormBuilder);
  private readonly snackBar = inject(MatSnackBar);

  loading = signal(true);
  saving = signal(false);

  hours = Array.from({ length: 24 }, (_, i) => ({
    value: String(i),
    label: `${i.toString().padStart(2, '0')}:00`,
  }));

  daysOfMonth = Array.from({ length: 28 }, (_, i) => String(i + 1));

  form = this.fb.group({
    backup_enabled: [true],
    schedule_frequency: ['daily'],
    schedule_hour: ['2'],
    schedule_day_of_week: ['0'],
    schedule_day_of_month: ['1'],
    backup_retention_days: [90],
    execution_retention_days: [90],
    backup_git_enabled: [false],
    backup_git_repo_url: [''],
    backup_git_branch: ['main'],
    backup_git_author_name: [''],
    backup_git_author_email: [''],
  });

  get cronPreview(): string {
    return this.buildCron();
  }

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
  }

  private populateForm(s: SystemSettings): void {
    const parsed = this.parseCron(s.backup_full_schedule_cron || '0 2 * * *');
    this.form.patchValue({
      backup_enabled: s.backup_enabled,
      schedule_frequency: parsed.frequency,
      schedule_hour: parsed.hour,
      schedule_day_of_week: parsed.dayOfWeek,
      schedule_day_of_month: parsed.dayOfMonth,
      backup_retention_days: s.backup_retention_days,
      execution_retention_days: s.execution_retention_days,
      backup_git_enabled: s.backup_git_enabled,
      backup_git_repo_url: s.backup_git_repo_url || '',
      backup_git_branch: s.backup_git_branch,
      backup_git_author_name: s.backup_git_author_name,
      backup_git_author_email: s.backup_git_author_email,
    });
  }

  save(): void {
    this.saving.set(true);
    const values = this.form.getRawValue();
    const updates: Record<string, unknown> = {
      backup_enabled: values.backup_enabled,
      backup_full_schedule_cron: this.buildCron(),
      backup_retention_days: values.backup_retention_days,
      execution_retention_days: values.execution_retention_days,
      backup_git_enabled: values.backup_git_enabled,
      backup_git_branch: values.backup_git_branch,
    };
    if (values.backup_git_repo_url) updates['backup_git_repo_url'] = values.backup_git_repo_url;
    if (values.backup_git_author_name)
      updates['backup_git_author_name'] = values.backup_git_author_name;
    if (values.backup_git_author_email)
      updates['backup_git_author_email'] = values.backup_git_author_email;

    this.settingsService.save(updates).subscribe({
      next: () => {
        this.saving.set(false);
        this.snackBar.open('Backup settings saved', 'OK', { duration: 3000 });
      },
      error: (err) => {
        this.saving.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  private buildCron(): string {
    const v = this.form.value;
    const hour = v.schedule_hour || '2';

    switch (v.schedule_frequency) {
      case 'weekly':
        return `0 ${hour} * * ${v.schedule_day_of_week || '0'}`;
      case 'monthly':
        return `0 ${hour} ${v.schedule_day_of_month || '1'} * *`;
      default: // daily
        return `0 ${hour} * * *`;
    }
  }

  private parseCron(cron: string): {
    frequency: string;
    hour: string;
    dayOfWeek: string;
    dayOfMonth: string;
  } {
    const parts = cron.split(' ');
    if (parts.length !== 5) {
      return { frequency: 'daily', hour: '2', dayOfWeek: '0', dayOfMonth: '1' };
    }

    const [, hour, dayOfMonth, , dayOfWeek] = parts;

    if (dayOfWeek !== '*') {
      return { frequency: 'weekly', hour, dayOfWeek, dayOfMonth: '1' };
    }
    if (dayOfMonth !== '*') {
      return { frequency: 'monthly', hour, dayOfWeek: '0', dayOfMonth };
    }
    return { frequency: 'daily', hour, dayOfWeek: '0', dayOfMonth: '1' };
  }
}
