import { Component, ChangeDetectorRef, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { AuthService } from '../../../core/services/auth.service';
import {
  passwordValidator,
  matchPasswordValidator,
} from '../../../shared/validators/password.validator';

@Component({
  selector: 'app-password-change',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatSnackBarModule,
  ],
  template: `
    <mat-card>
      <mat-card-header>
        <mat-card-title>Change Password</mat-card-title>
      </mat-card-header>
      <mat-card-content>
        <form [formGroup]="form" (ngSubmit)="onSubmit()" class="password-form">
          <mat-form-field appearance="outline">
            <mat-label>Current Password</mat-label>
            <input matInput type="password" formControlName="current_password" />
          </mat-form-field>

          <mat-form-field appearance="outline">
            <mat-label>New Password</mat-label>
            <input matInput type="password" formControlName="new_password" />
            @if (form.get('new_password')?.errors; as errors) {
              <mat-error>
                {{ errors['minLength'] || errors['uppercase'] || errors['lowercase'] || errors['digit'] || errors['special'] || 'Invalid' }}
              </mat-error>
            }
          </mat-form-field>

          <mat-form-field appearance="outline">
            <mat-label>Confirm New Password</mat-label>
            <input matInput type="password" formControlName="confirm_password" />
            @if (form.get('confirm_password')?.hasError('passwordMismatch')) {
              <mat-error>Passwords do not match</mat-error>
            }
          </mat-form-field>

          <button mat-flat-button type="submit"
                  [disabled]="form.invalid || saving">
            {{ saving ? 'Changing...' : 'Change Password' }}
          </button>
        </form>
      </mat-card-content>
    </mat-card>
  `,
  styles: [`
    mat-card { max-width: 500px; }
    .password-form {
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding-top: 16px;
    }
    mat-form-field { width: 100%; }
  `],
})
export class PasswordChangeComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly cdr = inject(ChangeDetectorRef);

  saving = false;

  form = this.fb.group({
    current_password: ['', Validators.required],
    new_password: ['', [Validators.required, passwordValidator()]],
    confirm_password: ['', [Validators.required, matchPasswordValidator('new_password')]],
  });

  ngOnInit(): void {
    this.authService.checkHealth().subscribe({
      next: (health) => {
        if (health.password_policy) {
          const ctrl = this.form.get('new_password')!;
          ctrl.setValidators([Validators.required, passwordValidator(health.password_policy)]);
          ctrl.updateValueAndValidity();
        }
      },
    });
  }

  onSubmit(): void {
    if (this.form.invalid) return;
    this.saving = true;

    const { current_password, new_password } = this.form.getRawValue();
    this.authService
      .changePassword({
        current_password: current_password!,
        new_password: new_password!,
      })
      .subscribe({
        next: () => {
          this.saving = false;
          this.form.reset();
          this.snackBar.open('Password changed successfully', 'OK', { duration: 3000 });
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
