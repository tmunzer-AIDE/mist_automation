import { Component, inject, OnInit, signal } from '@angular/core';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatDividerModule } from '@angular/material/divider';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSliderModule } from '@angular/material/slider';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { LlmService } from '../../../../core/services/llm.service';
import { LlmConfig, LlmModel } from '../../../../core/models/llm.model';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';

const PROVIDER_OPTIONS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'ollama', label: 'Ollama (Local)' },
  { value: 'lm_studio', label: 'LM Studio (Local)' },
  { value: 'azure_openai', label: 'Azure OpenAI' },
  { value: 'bedrock', label: 'AWS Bedrock' },
  { value: 'vertex', label: 'Google Vertex AI' },
];

@Component({
  selector: 'app-llm-config-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatDividerModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatSelectModule,
    MatSlideToggleModule,
    MatSliderModule,
    MatSnackBarModule,
  ],
  template: `
    <h2 mat-dialog-title>{{ isEdit ? 'Edit' : 'Add' }} LLM Configuration</h2>
    <mat-dialog-content>
      <form [formGroup]="form" class="config-form">
        <!-- Step 1: Connection -->
        <div class="section-title">Connection</div>

        <mat-form-field appearance="outline">
          <mat-label>Name</mat-label>
          <input matInput formControlName="name" placeholder="e.g., GPT-4o Cloud" />
        </mat-form-field>

        <mat-form-field appearance="outline">
          <mat-label>Provider</mat-label>
          <mat-select formControlName="provider">
            @for (opt of providers; track opt.value) {
              <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
            }
          </mat-select>
        </mat-form-field>

        @if (showBaseUrl()) {
          <mat-form-field appearance="outline">
            <mat-label>Base URL</mat-label>
            <input matInput formControlName="base_url" placeholder="http://localhost:11434" />
          </mat-form-field>
        }

        <mat-form-field appearance="outline">
          <mat-label>API Key</mat-label>
          <input
            matInput
            type="password"
            formControlName="api_key"
            [placeholder]="isEdit && data.config?.api_key_set ? 'Leave empty to keep current' : 'Enter API key'"
          />
        </mat-form-field>

        <button
          mat-stroked-button
          type="button"
          (click)="testConnection()"
          [disabled]="testing()"
          class="action-button"
        >
          <mat-icon>wifi_tethering</mat-icon>
          {{ testing() ? 'Testing...' : 'Test Connection' }}
        </button>

        <mat-divider></mat-divider>

        <!-- Step 2: Model Configuration -->
        <div class="section-title">Model</div>

        <div class="model-row">
          <mat-form-field appearance="outline" class="model-field">
            <mat-label>Model</mat-label>
            @if (availableModels().length > 0) {
              <mat-select formControlName="model">
                @for (m of availableModels(); track m.id) {
                  <mat-option [value]="m.id">{{ m.name }}</mat-option>
                }
              </mat-select>
            } @else {
              <input matInput formControlName="model" placeholder="Model name" />
            }
          </mat-form-field>
          <button
            mat-stroked-button
            type="button"
            (click)="fetchModels()"
            [disabled]="fetchingModels()"
            class="fetch-button"
          >
            <mat-icon>refresh</mat-icon>
            {{ fetchingModels() ? 'Loading...' : 'Fetch Models' }}
          </button>
        </div>

        <div class="slider-row">
          <label>Temperature: {{ form.get('temperature')?.value }}</label>
          <mat-slider min="0" max="2" step="0.1" discrete>
            <input matSliderThumb formControlName="temperature" />
          </mat-slider>
        </div>

        <mat-form-field appearance="outline">
          <mat-label>Max Tokens per Request</mat-label>
          <input matInput type="number" formControlName="max_tokens_per_request" />
        </mat-form-field>

        <mat-divider></mat-divider>

        <div class="toggle-row">
          <mat-slide-toggle formControlName="is_default">Set as Default</mat-slide-toggle>
          <mat-slide-toggle formControlName="enabled">Enabled</mat-slide-toggle>
        </div>
      </form>

      @if (saving()) {
        <mat-progress-bar mode="indeterminate"></mat-progress-bar>
      }
    </mat-dialog-content>

    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close [disabled]="saving()">Cancel</button>
      <button mat-flat-button (click)="save()" [disabled]="saving() || form.invalid">
        {{ saving() ? 'Saving...' : 'Save' }}
      </button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .config-form { display: flex; flex-direction: column; gap: 4px; min-width: 400px; }
      .section-title { font-size: 13px; font-weight: 600; color: var(--mat-sys-on-surface-variant); margin: 8px 0 4px; }
      .model-row { display: flex; align-items: flex-start; gap: 8px; }
      .model-field { flex: 1; }
      .fetch-button { margin-top: 8px; }
      .action-button { align-self: flex-start; margin-bottom: 8px; }
      .slider-row { display: flex; flex-direction: column; margin-bottom: 8px; }
      .slider-row label { font-size: 14px; color: var(--app-neutral); margin-bottom: 4px; }
      .toggle-row { display: flex; gap: 24px; margin: 8px 0; }
      mat-divider { margin: 8px 0; }
    `,
  ],
})
export class LlmConfigDialogComponent implements OnInit {
  readonly data: { config: LlmConfig | null } = inject(MAT_DIALOG_DATA);
  private readonly llmService = inject(LlmService);
  private readonly dialogRef = inject(MatDialogRef<LlmConfigDialogComponent>);
  private readonly fb = inject(FormBuilder);
  private readonly snackBar = inject(MatSnackBar);

  readonly providers = PROVIDER_OPTIONS;
  readonly isEdit = !!this.data.config;

  saving = signal(false);
  testing = signal(false);
  fetchingModels = signal(false);
  availableModels = signal<LlmModel[]>([]);

  form = this.fb.group({
    name: ['', Validators.required],
    provider: ['openai', Validators.required],
    api_key: [''],
    model: [''],
    base_url: [''],
    temperature: [0.3, [Validators.min(0), Validators.max(2)]],
    max_tokens_per_request: [4096, [Validators.min(100), Validators.max(32000)]],
    is_default: [false],
    enabled: [true],
  });

  ngOnInit(): void {
    if (this.data.config) {
      const c = this.data.config;
      this.form.patchValue({
        name: c.name,
        provider: c.provider,
        model: c.model || '',
        base_url: c.base_url || '',
        temperature: c.temperature,
        max_tokens_per_request: c.max_tokens_per_request,
        is_default: c.is_default,
        enabled: c.enabled,
      });
    }
  }

  showBaseUrl(): boolean {
    const p = this.form.get('provider')?.value;
    return ['ollama', 'lm_studio', 'azure_openai', 'bedrock'].includes(p || '');
  }

  private buildConnectionPayload(): Record<string, string | undefined> {
    const v = this.form.getRawValue();
    return {
      provider: v.provider || 'openai',
      api_key: v.api_key || undefined,
      base_url: v.base_url || undefined,
      config_id: !v.api_key && this.data.config ? this.data.config.id : undefined,
    };
  }

  testConnection(): void {
    this.testing.set(true);
    this.llmService.testConnectionAnonymous(this.buildConnectionPayload()).subscribe({
      next: (result) => {
        this.testing.set(false);
        if (result.status === 'connected') {
          this.snackBar.open(`Connected to ${result.model}`, 'OK', { duration: 3000 });
        } else {
          this.snackBar.open(result.error || 'Connection failed', 'OK', { duration: 5000 });
        }
      },
      error: (err) => {
        this.testing.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  fetchModels(): void {
    this.fetchingModels.set(true);
    this.llmService.discoverModels(this.buildConnectionPayload()).subscribe({
      next: (res) => {
        this.availableModels.set(res.models);
        this.fetchingModels.set(false);
        if (res.models.length === 0) {
          this.snackBar.open('No models found — enter model name manually', 'OK', { duration: 3000 });
        }
      },
      error: (err) => {
        this.fetchingModels.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  save(): void {
    this.saving.set(true);
    const values = this.form.getRawValue();
    const payload: Record<string, unknown> = {};

    for (const [k, v] of Object.entries(values)) {
      if (k === 'api_key' && !v) continue;
      if (v !== null && v !== undefined) payload[k] = v;
    }

    const obs = this.isEdit
      ? this.llmService.updateConfig(this.data.config!.id, payload)
      : this.llmService.createConfig(payload);

    obs.subscribe({
      next: () => {
        this.saving.set(false);
        this.snackBar.open(this.isEdit ? 'Configuration updated' : 'Configuration created', 'OK', {
          duration: 3000,
        });
        this.dialogRef.close(true);
      },
      error: (err) => {
        this.saving.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }
}
