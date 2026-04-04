import { Component, inject, OnInit } from '@angular/core';
import { AsyncPipe } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { Store } from '@ngrx/store';
import { AuthActions } from '../../../core/state/auth/auth.actions';
import { selectAuthLoading, selectAuthError } from '../../../core/state/auth/auth.selectors';
import { AuthService } from '../../../core/services/auth.service';
import { PasskeyService } from '../../../core/services/passkey.service';
import { TokenService } from '../../../core/services/token.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [
    AsyncPipe,
    ReactiveFormsModule,
    RouterModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatCheckboxModule,
    MatIconModule,
    MatProgressBarModule,
  ],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss',
})
export class LoginComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly store = inject(Store);
  private readonly authService = inject(AuthService);
  private readonly passkeyService = inject(PasskeyService);
  private readonly tokenService = inject(TokenService);

  loading$ = this.store.select(selectAuthLoading);
  error$ = this.store.select(selectAuthError);
  showOnboardLink = false;
  hidePassword = true;

  passkeySupported = false;
  passkeyLoading = false;
  passkeyError: string | null = null;

  loginForm = this.fb.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(8)]],
    remember_me: [false],
  });

  ngOnInit(): void {
    this.passkeySupported = this.passkeyService.isSupported();
    this.authService.checkHealth().subscribe({
      next: (health) => {
        this.showOnboardLink = !health.is_initialized;
        if (!health.passkey_support) {
          this.passkeySupported = false;
        }
      },
      error: () => {},
    });
  }

  onPasskeyLogin(): void {
    this.passkeyLoading = true;
    this.passkeyError = null;
    this.passkeyService.login().subscribe({
      next: (response) => {
        this.tokenService.setToken(response.access_token, response.expires_in);
        this.store.dispatch(AuthActions.loginSuccess({ expiresIn: response.expires_in }));
        this.passkeyLoading = false;
      },
      error: (err) => {
        this.passkeyLoading = false;
        if (err?.name === 'NotAllowedError') return;
        this.passkeyError = err?.error?.detail || 'Passkey authentication failed';
      },
    });
  }

  onSubmit(): void {
    if (this.loginForm.invalid) return;
    const { email, password, remember_me } = this.loginForm.getRawValue();
    this.store.dispatch(
      AuthActions.login({
        request: { email: email!, password: password!, remember_me: remember_me! },
      }),
    );
  }
}
