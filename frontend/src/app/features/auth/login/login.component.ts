import { Component, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
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
import {
  selectAuthLoading,
  selectAuthError,
} from '../../../core/state/auth/auth.selectors';
import { AuthService } from '../../../core/services/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [
    CommonModule,
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

  loading$ = this.store.select(selectAuthLoading);
  error$ = this.store.select(selectAuthError);
  showOnboardLink = false;
  hidePassword = true;

  loginForm = this.fb.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(8)]],
    remember_me: [false],
  });

  ngOnInit(): void {
    this.authService.checkHealth().subscribe({
      next: (health) => {
        this.showOnboardLink = !health.is_initialized;
      },
      error: () => {},
    });
  }

  onSubmit(): void {
    if (this.loginForm.invalid) return;
    const { email, password, remember_me } = this.loginForm.getRawValue();
    this.store.dispatch(
      AuthActions.login({
        request: { email: email!, password: password!, remember_me: remember_me! },
      })
    );
  }
}
