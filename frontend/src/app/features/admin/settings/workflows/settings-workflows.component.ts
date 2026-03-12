import { Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { SettingsService } from '../settings.service';
import { SystemSettings } from '../../../../core/models/admin.model';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';

@Component({
  selector: 'app-settings-workflows',
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
    MatProgressBarModule,
  ],
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    } @else {
      <form [formGroup]="form" class="tab-form">
        <mat-card>
          <mat-card-header>
            <mat-card-title>Workflow Execution</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <mat-form-field appearance="outline">
              <mat-label>Max Concurrent Workflows</mat-label>
              <input matInput type="number" formControlName="max_concurrent_workflows" />
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Default Timeout (seconds)</mat-label>
              <input matInput type="number" formControlName="workflow_default_timeout" />
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
  styles: [],
})
export class SettingsWorkflowsComponent implements OnInit {
  private readonly settingsService = inject(SettingsService);
  private readonly fb = inject(FormBuilder);
  private readonly snackBar = inject(MatSnackBar);

  loading = signal(true);
  saving = signal(false);

  form = this.fb.group({
    max_concurrent_workflows: [10],
    workflow_default_timeout: [300],
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
      max_concurrent_workflows: s.max_concurrent_workflows,
      workflow_default_timeout: s.workflow_default_timeout,
    });
  }

  save(): void {
    this.saving.set(true);
    this.settingsService.save(this.form.getRawValue()).subscribe({
      next: () => {
        this.saving.set(false);
        this.snackBar.open('Workflow settings saved', 'OK', { duration: 3000 });
      },
      error: (err) => {
        this.saving.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }
}
