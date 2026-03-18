import { Component, inject, OnInit } from '@angular/core';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { AuthService } from '../../../core/services/auth.service';
import { TokenService } from '../../../core/services/token.service';
import { Store } from '@ngrx/store';
import { AuthActions } from '../../../core/state/auth/auth.actions';
import {
  passwordValidator,
  matchPasswordValidator,
} from '../../../shared/validators/password.validator';

@Component({
  selector: 'app-onboard',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
  ],
  templateUrl: './onboard.component.html',
  styleUrl: './onboard.component.scss',
})
export class OnboardComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  private readonly tokenService = inject(TokenService);
  private readonly store = inject(Store);
  private readonly router = inject(Router);

  loading = false;
  error: string | null = null;
  hidePassword = true;
  hideConfirm = true;

  form = this.fb.group({
    firstName: [''],
    lastName: [''],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, passwordValidator()]],
    confirmPassword: ['', [Validators.required, matchPasswordValidator('password')]],
  });

  ngOnInit(): void {
    // Fetch password policy from backend and update validator
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

  onSubmit(): void {
    if (this.form.invalid) return;
    this.loading = true;
    this.error = null;

    const { firstName, lastName, email, password } = this.form.getRawValue();
    this.authService
      .onboard({
        email: email!,
        password: password!,
        first_name: firstName || undefined,
        last_name: lastName || undefined,
      })
      .subscribe({
      next: (response) => {
        this.loading = false;
        this.tokenService.setToken(response.access_token, response.expires_in);
        this.store.dispatch(
          AuthActions.loginSuccess({
            expiresIn: response.expires_in,
          }),
        );
      },
      error: (err) => {
        this.loading = false;
        this.error = err.message || 'Onboarding failed';
      },
    });
  }
}
