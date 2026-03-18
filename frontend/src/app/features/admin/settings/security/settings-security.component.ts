import { Component, inject, OnInit, signal } from '@angular/core';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { SettingsService } from '../settings.service';
import { SystemSettings } from '../../../../core/models/admin.model';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';

@Component({
  selector: 'app-settings-security',
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
    MatSlideToggleModule,
  ],
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    } @else {
      <form [formGroup]="form" class="tab-form">
        <mat-card>
          <mat-card-header>
            <mat-card-title>Password Policy</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <mat-form-field appearance="outline">
              <mat-label>Minimum Password Length</mat-label>
              <input
                matInput
                type="number"
                formControlName="min_password_length"
                min="6"
                max="128"
              />
            </mat-form-field>

            <div class="toggle-group">
              <mat-slide-toggle formControlName="require_uppercase"
                >Require uppercase letters</mat-slide-toggle
              >
              <mat-slide-toggle formControlName="require_lowercase"
                >Require lowercase letters</mat-slide-toggle
              >
              <mat-slide-toggle formControlName="require_digits">Require digits</mat-slide-toggle>
              <mat-slide-toggle formControlName="require_special_chars"
                >Require special characters</mat-slide-toggle
              >
            </div>
          </mat-card-content>
        </mat-card>

        <mat-card>
          <mat-card-header>
            <mat-card-title>Session Management</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <mat-form-field appearance="outline">
              <mat-label>Session Timeout (hours)</mat-label>
              <input matInput type="number" formControlName="session_timeout_hours" min="1" />
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Max Concurrent Sessions</mat-label>
              <input matInput type="number" formControlName="max_concurrent_sessions" min="1" />
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
      .toggle-group {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 8px 0;
      }
    `,
  ],
})
export class SettingsSecurityComponent implements OnInit {
  private readonly settingsService = inject(SettingsService);
  private readonly fb = inject(FormBuilder);
  private readonly snackBar = inject(MatSnackBar);

  loading = signal(true);
  saving = signal(false);

  form = this.fb.group({
    min_password_length: [8],
    require_uppercase: [true],
    require_lowercase: [true],
    require_digits: [true],
    require_special_chars: [false],
    session_timeout_hours: [24],
    max_concurrent_sessions: [5],
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
  }

  private populateForm(s: SystemSettings): void {
    this.form.patchValue({
      min_password_length: s.min_password_length,
      require_uppercase: s.require_uppercase,
      require_lowercase: s.require_lowercase,
      require_digits: s.require_digits,
      require_special_chars: s.require_special_chars,
      session_timeout_hours: s.session_timeout_hours,
      max_concurrent_sessions: s.max_concurrent_sessions,
    });
  }

  save(): void {
    this.saving.set(true);
    this.settingsService.save(this.form.getRawValue()).subscribe({
      next: () => {
        this.saving.set(false);
        this.snackBar.open('Security settings saved', 'OK', { duration: 3000 });
      },
      error: (err) => {
        this.saving.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }
}
