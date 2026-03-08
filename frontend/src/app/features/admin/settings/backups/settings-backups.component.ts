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
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatDividerModule } from '@angular/material/divider';
import { SettingsService } from '../settings.service';

@Component({
  selector: 'app-settings-backups',
  standalone: true,
  imports: [
    CommonModule, ReactiveFormsModule,
    MatCardModule, MatFormFieldModule, MatInputModule,
    MatButtonModule, MatIconModule, MatSnackBarModule,
    MatProgressBarModule, MatSlideToggleModule, MatDividerModule,
  ],
  template: `
    @if (loading) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    } @else {
      <form [formGroup]="form" class="tab-form">
        <mat-card>
          <mat-card-header>
            <mat-card-title>Backup Configuration</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <mat-slide-toggle formControlName="backup_enabled">Enable automatic backups</mat-slide-toggle>

            <mat-form-field appearance="outline">
              <mat-label>Full Backup Schedule (cron)</mat-label>
              <input matInput formControlName="backup_full_schedule_cron" placeholder="0 2 * * *" />
              <mat-hint>Cron expression for full backup schedule</mat-hint>
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Retention (days)</mat-label>
              <input matInput type="number" formControlName="backup_retention_days" min="1" />
            </mat-form-field>

            <mat-divider></mat-divider>

            <h3 class="subsection-title">Git Integration</h3>
            <mat-slide-toggle formControlName="backup_git_enabled">Enable Git backup</mat-slide-toggle>

            <mat-form-field appearance="outline">
              <mat-label>Repository URL</mat-label>
              <input matInput formControlName="backup_git_repo_url" placeholder="https://github.com/org/repo.git" />
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
    .subsection-title { font-size: 14px; font-weight: 500; margin: 16px 0 8px; color: var(--mat-sys-on-surface-variant); }
    mat-divider { margin: 16px 0; }
  `],
})
export class SettingsBackupsComponent implements OnInit {
  private readonly settingsService = inject(SettingsService);
  private readonly fb = inject(FormBuilder);
  private readonly snackBar = inject(MatSnackBar);
  private readonly cdr = inject(ChangeDetectorRef);

  loading = true;
  saving = false;

  form = this.fb.group({
    backup_enabled: [true],
    backup_full_schedule_cron: ['0 2 * * *'],
    backup_retention_days: [90],
    backup_git_enabled: [false],
    backup_git_repo_url: [''],
    backup_git_branch: ['main'],
    backup_git_author_name: [''],
    backup_git_author_email: [''],
  });

  ngOnInit(): void {
    this.settingsService.load().subscribe({
      next: (s) => {
        this.form.patchValue({
          backup_enabled: s.backup_enabled,
          backup_full_schedule_cron: s.backup_full_schedule_cron,
          backup_retention_days: s.backup_retention_days,
          backup_git_enabled: s.backup_git_enabled,
          backup_git_repo_url: s.backup_git_repo_url || '',
          backup_git_branch: s.backup_git_branch,
          backup_git_author_name: s.backup_git_author_name,
          backup_git_author_email: s.backup_git_author_email,
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
        this.snackBar.open('Backup settings saved', 'OK', { duration: 3000 });
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
