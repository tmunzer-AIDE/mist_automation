import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { LlmService } from '../../../../core/services/llm.service';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';

@Component({
  selector: 'app-add-repo-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressBarModule,
  ],
  template: `
    <h2 mat-dialog-title>Add Git Repository</h2>
    @if (saving()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    }
    <mat-dialog-content>
      <p class="hint">
        Provide a git repo URL. The system will clone it and auto-discover all
        <code>SKILL.md</code> files. Clone runs in the background.
      </p>
      <form [formGroup]="form" class="form-grid">
        <mat-form-field appearance="outline" class="full-width">
          <mat-label>Repository URL</mat-label>
          <input matInput formControlName="url" placeholder="https://github.com/user/skills-repo.git" />
          @if (form.get('url')?.hasError('required')) {
            <mat-error>URL is required</mat-error>
          }
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Branch</mat-label>
          <input matInput formControlName="branch" />
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Access Token (optional)</mat-label>
          <input matInput formControlName="token" type="password" placeholder="ghp_... (for private repos)" />
        </mat-form-field>
      </form>
      @if (error()) {
        <p class="api-error">{{ error() }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close [disabled]="saving()">Cancel</button>
      <button mat-flat-button (click)="save()" [disabled]="saving() || form.invalid">Add Repository</button>
    </mat-dialog-actions>
  `,
  styles: [`
    .full-width { width: 100%; }
    .form-grid { display: flex; flex-direction: column; gap: 4px; }
    .hint { font-size: 13px; color: var(--mat-sys-on-surface-variant); margin-bottom: 12px; }
    .api-error { color: var(--app-error, #f44336); font-size: 13px; margin-top: 8px; }
    mat-dialog-content { min-width: 480px; }
  `],
})
export class AddRepoDialogComponent {
  private readonly llmService = inject(LlmService);
  private readonly dialogRef = inject(MatDialogRef<AddRepoDialogComponent>);
  private readonly fb = inject(FormBuilder);

  form = this.fb.group({
    url: ['', [Validators.required, Validators.minLength(5)]],
    branch: ['main', Validators.required],
    token: [''],
  });

  saving = signal(false);
  error = signal<string | null>(null);

  save(): void {
    if (this.form.invalid) return;
    const { url, branch, token } = this.form.value;
    this.saving.set(true);
    this.error.set(null);
    this.llmService.addSkillRepo(url!, branch!, token || null).subscribe({
      next: (repo) => this.dialogRef.close(repo),
      error: (err) => {
        this.error.set(extractErrorMessage(err));
        this.saving.set(false);
      },
    });
  }
}
