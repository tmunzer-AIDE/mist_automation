import { Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { AuthService } from '../../../core/services/auth.service';

@Component({
  selector: 'app-general-profile',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatSelectModule,
    MatButtonModule,
    MatSnackBarModule,
  ],
  template: `
    <mat-card>
      <mat-card-header>
        <mat-card-title>General Settings</mat-card-title>
      </mat-card-header>
      <mat-card-content>
        <form [formGroup]="form" (ngSubmit)="onSubmit()" class="general-form">
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
    timezone: ['UTC'],
  });

  ngOnInit(): void {
    this.authService.me().subscribe({
      next: (user) => {
        this.form.patchValue({ timezone: user.timezone });
        this.form.markAsPristine();
      },
    });
  }

  onSubmit(): void {
    if (!this.form.dirty) return;
    this.saving.set(true);

    this.authService.updateProfile({ timezone: this.form.value.timezone! }).subscribe({
      next: () => {
        this.saving.set(false);
        this.form.markAsPristine();
        this.snackBar.open('Profile updated', 'OK', { duration: 3000 });
      },
      error: (err) => {
        this.saving.set(false);
        this.snackBar.open(err.message || 'Update failed', 'OK', { duration: 5000 });
      },
    });
  }
}
