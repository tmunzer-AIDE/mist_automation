import { Component, inject, OnInit, signal } from '@angular/core';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { Store } from '@ngrx/store';
import { AuthService } from '../../../core/services/auth.service';
import { AuthActions } from '../../../core/state/auth/auth.actions';
import { ThemeService, ThemePreference } from '../../../core/services/theme.service';
import { extractErrorMessage } from '../../../shared/utils/error.utils';

@Component({
  selector: 'app-general-profile',
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
  ],
  template: `
    <mat-card>
      <mat-card-header>
        <mat-card-title>General Settings</mat-card-title>
      </mat-card-header>
      <mat-card-content>
        <form [formGroup]="form" (ngSubmit)="onSubmit()" class="general-form">
          <div class="name-row">
            <mat-form-field appearance="outline">
              <mat-label>First Name</mat-label>
              <input matInput formControlName="first_name" />
            </mat-form-field>
            <mat-form-field appearance="outline">
              <mat-label>Last Name</mat-label>
              <input matInput formControlName="last_name" />
            </mat-form-field>
          </div>

          <mat-form-field appearance="outline">
            <mat-label>Timezone</mat-label>
            <mat-select formControlName="timezone">
              @for (tz of timezones; track tz) {
                <mat-option [value]="tz">{{ tz }}</mat-option>
              }
            </mat-select>
          </mat-form-field>

          <button mat-flat-button type="submit" [disabled]="!form.dirty || saving()">
            {{ saving() ? 'Saving...' : 'Save' }}
          </button>
        </form>
      </mat-card-content>
    </mat-card>

    <mat-card class="appearance-card">
      <mat-card-header>
        <mat-card-title>Appearance</mat-card-title>
      </mat-card-header>
      <mat-card-content>
        <div class="appearance-form">
          <mat-form-field appearance="outline">
            <mat-label>Theme</mat-label>
            <mat-icon matPrefix>palette</mat-icon>
            <mat-select
              [value]="themeService.preference()"
              (selectionChange)="themeService.setPreference($event.value)"
            >
              <mat-option value="auto">Auto (System)</mat-option>
              <mat-option value="light">Light</mat-option>
              <mat-option value="dark">Dark</mat-option>
            </mat-select>
          </mat-form-field>
        </div>
      </mat-card-content>
    </mat-card>
  `,
  styles: [
    `
      mat-card {
        max-width: 500px;
      }
      .general-form {
        display: flex;
        flex-direction: column;
        gap: 4px;
        padding-top: 16px;
      }
      .name-row {
        display: flex;
        gap: 12px;
      }
      .name-row mat-form-field {
        flex: 1;
      }
      .appearance-card {
        margin-top: 24px;
      }
      .appearance-form {
        padding-top: 16px;
      }
      mat-form-field {
        width: 100%;
      }
    `,
  ],
})
export class GeneralProfileComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly store = inject(Store);
  readonly themeService = inject(ThemeService);

  saving = signal(false);

  timezones = [
    'UTC',
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'America/Sao_Paulo',
    'Europe/London',
    'Europe/Paris',
    'Europe/Berlin',
    'Europe/Zurich',
    'Asia/Dubai',
    'Asia/Kolkata',
    'Asia/Singapore',
    'Asia/Tokyo',
    'Asia/Shanghai',
    'Australia/Sydney',
    'Pacific/Auckland',
  ];

  form = this.fb.group({
    first_name: [''],
    last_name: [''],
    timezone: ['UTC'],
  });

  ngOnInit(): void {
    this.authService.me().subscribe({
      next: (user) => {
        this.form.patchValue({
          first_name: user.first_name ?? '',
          last_name: user.last_name ?? '',
          timezone: user.timezone,
        });
        this.form.markAsPristine();
      },
    });
  }

  onSubmit(): void {
    if (!this.form.dirty) return;
    this.saving.set(true);

    const val = this.form.value;
    this.authService.updateProfile({
      first_name: val.first_name || undefined,
      last_name: val.last_name || undefined,
      timezone: val.timezone!,
    }).subscribe({
      next: (user) => {
        this.store.dispatch(AuthActions.loadUserSuccess({ user }));
        this.saving.set(false);
        this.form.markAsPristine();
        this.snackBar.open('Profile updated', 'OK', { duration: 3000 });
      },
      error: (err) => {
        this.saving.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }
}
