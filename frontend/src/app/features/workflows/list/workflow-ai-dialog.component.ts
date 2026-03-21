import { Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { TextFieldModule } from '@angular/cdk/text-field';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { switchMap, tap } from 'rxjs';
import { AiIconComponent } from '../../../shared/components/ai-icon/ai-icon.component';
import { LlmService, WorkflowAssistResponse } from '../../../core/services/llm.service';
import { WorkflowService } from '../../../core/services/workflow.service';
import { extractErrorMessage } from '../../../shared/utils/error.utils';

type Step = 'input' | 'categories' | 'generating' | 'done';

@Component({
  selector: 'app-workflow-ai-dialog',
  standalone: true,
  imports: [
    FormsModule,
    TextFieldModule,
    MatButtonModule,
    MatChipsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatSnackBarModule,
    AiIconComponent,
  ],
  template: `
    <h2 mat-dialog-title>Create Workflow with AI</h2>
    <mat-dialog-content>
      @if (step() === 'categories' || step() === 'generating') {
        <mat-progress-bar mode="indeterminate"></mat-progress-bar>
      }

      <!-- Step: Input -->
      @if (step() === 'input') {
        <p class="hint">Describe the workflow you want to create in plain language.</p>
        <mat-form-field appearance="outline" class="full-width">
          <mat-label>Workflow description</mat-label>
          <textarea
            matInput
            cdkTextareaAutosize
            [cdkAutosizeMinRows]="3"
            [cdkAutosizeMaxRows]="8"
            [(ngModel)]="descriptionText"
            placeholder="e.g., When an AP goes offline, wait 5 minutes, check if it's still offline, then send a Slack alert..."
          ></textarea>
        </mat-form-field>
      }

      <!-- Step: Selecting categories -->
      @if (step() === 'categories') {
        <div class="step-status">
          <mat-icon class="spin">sync</mat-icon>
          <span>Identifying relevant Mist APIs...</span>
        </div>
      }

      <!-- Step: Generating workflow -->
      @if (step() === 'generating') {
        <div class="step-progress">
          <div class="step-done">
            <mat-icon>check_circle</mat-icon>
            <span>Selected APIs: </span>
            <span class="category-chips">
              @for (cat of selectedCategories(); track cat) {
                <span class="category-chip">{{ cat }}</span>
              }
            </span>
          </div>
          <div class="step-status">
            <mat-icon class="spin">sync</mat-icon>
            <span>Generating workflow...</span>
          </div>
        </div>
      }

      <!-- Step: Done -->
      @if (step() === 'done' && result()) {
        <div class="step-progress">
          <div class="step-done">
            <mat-icon>check_circle</mat-icon>
            <span>Selected APIs: </span>
            <span class="category-chips">
              @for (cat of selectedCategories(); track cat) {
                <span class="category-chip">{{ cat }}</span>
              }
            </span>
          </div>
        </div>

        <div class="result-section">
          <div class="result-header">
            <mat-icon class="result-icon">check_circle</mat-icon>
            <div>
              <div class="result-name">{{ result()!.name || 'Generated Workflow' }}</div>
              <div class="result-desc">{{ result()!.description }}</div>
            </div>
          </div>
          <div class="result-stats">
            <span>{{ result()!.nodes.length }} nodes</span>
            <span>{{ result()!.edges.length }} edges</span>
          </div>
          @if (result()!.validation_errors.length > 0) {
            <div class="validation-errors">
              @for (err of result()!.validation_errors; track err) {
                <div class="validation-error">{{ err }}</div>
              }
            </div>
          }

          <mat-form-field appearance="outline" class="full-width refine-input">
            <mat-label>Refine (optional)</mat-label>
            <textarea
              matInput
              cdkTextareaAutosize
              [cdkAutosizeMinRows]="2"
              [cdkAutosizeMaxRows]="4"
              [(ngModel)]="refineText"
              placeholder="e.g., Add a PagerDuty alert as well..."
            ></textarea>
          </mat-form-field>
        </div>
      }

      @if (error()) {
        <div class="error-msg">{{ error() }}</div>
      }
    </mat-dialog-content>

    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close [disabled]="step() === 'categories' || step() === 'generating'">
        Cancel
      </button>
      @if (step() === 'input') {
        <button
          mat-flat-button
          (click)="generate()"
          [disabled]="!descriptionText.trim()"
        >
          <app-ai-icon [size]="18" [animated]="false"></app-ai-icon> Generate
        </button>
      }
      @if (step() === 'done' && result()) {
        <button
          mat-stroked-button
          (click)="refine()"
          [disabled]="!refineText.trim()"
        >
          <mat-icon>refresh</mat-icon> Refine
        </button>
        <button
          mat-flat-button
          (click)="createWorkflow()"
          [disabled]="creating() || result()!.validation_errors.length > 0"
        >
          <mat-icon>add</mat-icon> {{ creating() ? 'Creating...' : 'Create Workflow' }}
        </button>
      }
    </mat-dialog-actions>
  `,
  styles: [
    `
      .hint { color: var(--mat-sys-on-surface-variant); font-size: 13px; margin-bottom: 12px; }
      .full-width { width: 100%; }

      .step-progress { display: flex; flex-direction: column; gap: 10px; margin: 8px 0; }
      .step-done {
        display: flex; align-items: center; gap: 6px; font-size: 13px;
        color: var(--app-success, #4caf50);
        mat-icon { font-size: 18px; width: 18px; height: 18px; }
      }
      .step-status {
        display: flex; align-items: center; gap: 8px; font-size: 13px;
        color: var(--mat-sys-on-surface-variant);
        padding: 12px 0;
        mat-icon { font-size: 18px; width: 18px; height: 18px; }
      }
      .category-chips { display: inline-flex; flex-wrap: wrap; gap: 4px; }
      .category-chip {
        font-size: 11px; font-weight: 500; padding: 2px 8px; border-radius: 10px;
        background: var(--mat-sys-primary-container); color: var(--mat-sys-on-primary-container);
      }

      .spin { animation: spin 1.2s linear infinite; }
      @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

      .result-section { display: flex; flex-direction: column; gap: 12px; margin-top: 8px; }
      .result-header { display: flex; align-items: flex-start; gap: 12px; }
      .result-icon { color: var(--app-success, #4caf50); font-size: 28px; width: 28px; height: 28px; margin-top: 2px; }
      .result-name { font-size: 16px; font-weight: 600; }
      .result-desc { font-size: 13px; color: var(--mat-sys-on-surface-variant); margin-top: 2px; }
      .result-stats { display: flex; gap: 16px; font-size: 13px; color: var(--mat-sys-on-surface-variant); }
      .validation-errors { background: rgba(244, 67, 54, 0.08); border-radius: 8px; padding: 8px 12px; }
      .validation-error { color: var(--app-error, #f44336); font-size: 13px; padding: 2px 0; }
      .refine-input { margin-top: 4px; }
      .error-msg { color: var(--app-error, #f44336); font-size: 13px; margin-top: 8px; }
    `,
  ],
})
export class WorkflowAiDialogComponent {
  private readonly llmService = inject(LlmService);
  private readonly workflowService = inject(WorkflowService);
  private readonly dialogRef = inject(MatDialogRef<WorkflowAiDialogComponent>);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);

  descriptionText = '';
  refineText = '';
  step = signal<Step>('input');
  creating = signal(false);
  error = signal<string | null>(null);
  result = signal<WorkflowAssistResponse | null>(null);
  selectedCategories = signal<string[]>([]);
  private threadId: string | null = null;

  generate(): void {
    const desc = this.descriptionText.trim();
    if (!desc) return;

    this.error.set(null);
    this.step.set('categories');

    this.llmService
      .selectCategories(desc)
      .pipe(
        tap((catRes) => {
          this.selectedCategories.set(catRes.categories);
          this.step.set('generating');
        }),
        switchMap((catRes) => this.llmService.workflowAssist(desc, catRes.categories)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (res) => {
          this.result.set(res);
          this.threadId = res.thread_id;
          this.step.set('done');
        },
        error: (err) => {
          this.error.set(extractErrorMessage(err));
          this.step.set('input');
        },
      });
  }

  refine(): void {
    const text = this.refineText.trim();
    if (!text || !this.threadId) return;

    this.step.set('generating');
    this.error.set(null);

    this.llmService.workflowAssist(text, undefined, this.threadId).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (res) => {
        this.result.set(res);
        this.threadId = res.thread_id;
        this.refineText = '';
        this.step.set('done');
      },
      error: (err) => {
        this.error.set(extractErrorMessage(err));
        this.step.set('done');
      },
    });
  }

  createWorkflow(): void {
    const res = this.result();
    if (!res) return;

    this.creating.set(true);
    this.workflowService
      .create({
        name: res.name || 'AI-Generated Workflow',
        description: res.description,
        workflow_type: 'standard',
        nodes: res.nodes,
        edges: res.edges,
      })
      .subscribe({
        next: (wf) => {
          this.creating.set(false);
          this.snackBar.open('Workflow created', 'OK', { duration: 3000 });
          this.dialogRef.close();
          this.router.navigate(['/workflows', wf.id]);
        },
        error: (err) => {
          this.creating.set(false);
          this.error.set(extractErrorMessage(err));
        },
      });
  }
}
