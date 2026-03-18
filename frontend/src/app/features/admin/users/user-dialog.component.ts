import { Component, inject, OnInit } from '@angular/core';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ApiService } from '../../../core/services/api.service';
import { AuthService } from '../../../core/services/auth.service';
import { UserResponse } from '../../../core/models/user.model';
import {
  passwordValidator,
  matchPasswordValidator,
} from '../../../shared/validators/password.validator';
import { extractErrorMessage } from '../../../shared/utils/error.utils';

interface DialogData {
  mode: 'create' | 'edit';
  user?: UserResponse;
}

const AVAILABLE_ROLES = ['admin', 'automation', 'backup'];
const TIMEZONES = [
  'UTC',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Asia/Tokyo',
  'Asia/Shanghai',
  'Australia/Sydney',
];

@Component({
  selector: 'app-user-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatCheckboxModule,
    MatSelectModule,
    MatSnackBarModule,
  ],
  template: `
    <h2 mat-dialog-title>{{ data.mode === 'create' ? 'Create User' : 'Edit User' }}</h2>
    <mat-dialog-content>
      <form [formGroup]="form" class="dialog-form">
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
          <mat-label>Email</mat-label>
          <input matInput type="email" formControlName="email" />
        </mat-form-field>

        @if (data.mode === 'create') {
          <mat-form-field appearance="outline">
            <mat-label>Password</mat-label>
            <input matInput type="password" formControlName="password" />
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Confirm Password</mat-label>
            <input matInput type="password" formControlName="confirmPassword" />
            @if (form.get('confirmPassword')?.hasError('passwordMismatch')) {
              <mat-error>Passwords do not match</mat-error>
            }
          </mat-form-field>
        }

        <mat-form-field appearance="outline">
          <mat-label>Roles</mat-label>
          <mat-select formControlName="roles" multiple>
            @for (role of availableRoles; track role) {
              <mat-option [value]="role">{{ role }}</mat-option>
            }
          </mat-select>
        </mat-form-field>

        <mat-form-field appearance="outline">
          <mat-label>Timezone</mat-label>
          <mat-select formControlName="timezone">
            @for (tz of timezones; track tz) {
              <mat-option [value]="tz">{{ tz }}</mat-option>
            }
          </mat-select>
        </mat-form-field>
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button mat-flat-button (click)="save()" [disabled]="form.invalid || saving">
        {{ saving ? 'Saving...' : 'Save' }}
      </button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .dialog-form {
        display: flex;
        flex-direction: column;
        min-width: 380px;
        gap: 4px;
      }
      .name-row {
        display: flex;
        gap: 12px;
      }
      .name-row mat-form-field {
        flex: 1;
      }
      mat-form-field {
        width: 100%;
      }
    `,
  ],
})
export class UserDialogComponent implements OnInit {
  readonly data = inject<DialogData>(MAT_DIALOG_DATA);
  private readonly dialogRef = inject(MatDialogRef<UserDialogComponent>);
  private readonly api = inject(ApiService);
  private readonly authService = inject(AuthService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly fb = inject(FormBuilder);

  availableRoles = AVAILABLE_ROLES;
  timezones = TIMEZONES;
  saving = false;

  form = this.fb.group({
    first_name: [this.data.user?.first_name || ''],
    last_name: [this.data.user?.last_name || ''],
    email: [this.data.user?.email || '', [Validators.required, Validators.email]],
    password: [''],
    confirmPassword: [''],
    roles: [this.data.user?.roles || [], Validators.required],
    timezone: [this.data.user?.timezone || 'UTC'],
  });

  constructor() {
    if (this.data.mode === 'create') {
      this.form.get('password')!.setValidators([Validators.required, passwordValidator()]);
      this.form
        .get('confirmPassword')!
        .setValidators([Validators.required, matchPasswordValidator('password')]);
    }
  }

  ngOnInit(): void {
    if (this.data.mode === 'create') {
      this.authService.checkHealth().subscribe({
        next: (health) => {
          if (health.password_policy) {
            const ctrl = this.form.get('password')!;
            ctrl.setValidators([Validators.required, passwordValidator(health.password_policy)]);
            ctrl.updateValueAndValidity();
          }
        },
      });
    }
  }

  save(): void {
    if (this.form.invalid) return;
    this.saving = true;

    const { first_name, last_name, email, password, roles, timezone } = this.form.getRawValue();

    if (this.data.mode === 'create') {
      this.api
        .post('/users', {
          email,
          password,
          first_name: first_name || undefined,
          last_name: last_name || undefined,
          roles,
          timezone,
        })
        .subscribe({
          next: () => {
            this.snackBar.open('User created', 'OK', { duration: 3000 });
            this.dialogRef.close(true);
          },
          error: (err) => {
            this.saving = false;
            this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
          },
        });
    } else {
      this.api
        .put(`/users/${this.data.user!.id}`, {
          email,
          first_name: first_name || undefined,
          last_name: last_name || undefined,
          roles,
          timezone,
        })
        .subscribe({
        next: () => {
          this.snackBar.open('User updated', 'OK', { duration: 3000 });
          this.dialogRef.close(true);
        },
        error: (err) => {
          this.saving = false;
          this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
        },
      });
    }
  }
}
