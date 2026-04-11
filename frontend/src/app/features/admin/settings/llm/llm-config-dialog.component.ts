import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { DecimalPipe } from '@angular/common';
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
  { value: 'mistral', label: 'Mistral' },
  { value: 'azure_openai', label: 'Azure OpenAI' },
  { value: 'bedrock', label: 'AWS Bedrock' },
  { value: 'vertex', label: 'Google Vertex AI' },
  { value: 'openai_compatible', label: 'OpenAI Compatible (Local)' },
];

@Component({
  selector: 'app-llm-config-dialog',
  standalone: true,
  imports: [
    DecimalPipe,
    ReactiveFormsModule,
    MatAutocompleteModule,
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
          <input matInput [matAutocomplete]="providerAuto"
                 (input)="providerSearch.set($any($event.target).value)">
          <mat-autocomplete #providerAuto (optionSelected)="form.get('provider')!.setValue($event.option.value)">
            @for (opt of filteredProviders(); track opt.value) {
              <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
            }
          </mat-autocomplete>
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
              <input matInput [matAutocomplete]="modelAuto"
                     (input)="modelSearch.set($any($event.target).value)">
              <mat-autocomplete #modelAuto (optionSelected)="onModelSelected($event.option.value)">
                @for (m of filteredModels(); track m.id) {
                  <mat-option [value]="m.id">{{ m.name }}</mat-option>
                }
              </mat-autocomplete>
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

        <mat-form-field appearance="outline">
          <mat-label>Context Window (tokens)</mat-label>
          <input matInput type="number" formControlName="context_window_tokens"
                 placeholder="Auto-detected" min="1000" max="2000000">
          <mat-hint>
            @if (data.config?.context_window_effective; as effective) {
              Effective: {{ effective | number }} tokens
            } @else {
              Leave empty for auto-detection (default: 20,000)
            }
          </mat-hint>
        </mat-form-field>

        @if (data.config && !data.config.context_window_tokens && data.config.context_window_effective === 20000) {
          <div class="context-window-warning">
            Context window could not be auto-detected for this model. Using default (20,000 tokens).
            Set a manual value if your model supports a larger context.
          </div>
        }

        <mat-divider></mat-divider>

        <div class="toggle-row">
          <mat-slide-toggle formControlName="is_default">Set as Default</mat-slide-toggle>
          <mat-slide-toggle formControlName="enabled">Enabled</mat-slide-toggle>
        </div>

        <mat-form-field appearance="outline" class="full-width">
          <mat-label>Canvas Prompt Tier</mat-label>
          <mat-select formControlName="canvas_prompt_tier">
            <mat-option [value]="null">Auto-detect</mat-option>
            <mat-option value="full">Full (large models)</mat-option>
            <mat-option value="explicit">Explicit (small models)</mat-option>
            <mat-option value="none">Disabled</mat-option>
          </mat-select>
          <mat-hint>Controls canvas artifact instructions in system prompts</mat-hint>
        </mat-form-field>
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
      .context-window-warning { color: var(--app-warning-text); font-size: 12px; margin: -8px 0 8px 0; padding: 4px 8px; }
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

  providerSearch = signal('');
  modelSearch = signal('');

  filteredProviders = computed(() => {
    const term = this.providerSearch().toLowerCase();
    return term
      ? this.providers.filter((p) => p.label.toLowerCase().includes(term))
      : this.providers;
  });

  filteredModels = computed(() => {
    const term = this.modelSearch().toLowerCase();
    return term
      ? this.availableModels().filter(
          (m) => m.name.toLowerCase().includes(term) || m.id.toLowerCase().includes(term)
        )
      : this.availableModels();
  });

  form = this.fb.group({
    name: ['', Validators.required],
    provider: ['openai', Validators.required],
    api_key: [''],
    model: [''],
    base_url: [''],
    temperature: [0.3, [Validators.min(0), Validators.max(2)]],
    max_tokens_per_request: [4096, [Validators.min(100), Validators.max(32000)]],
    context_window_tokens: [this.data.config?.context_window_tokens || null],
    is_default: [false],
    enabled: [true],
    canvas_prompt_tier: [null as string | null],
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
        context_window_tokens: c.context_window_tokens ?? null,
        is_default: c.is_default,
        enabled: c.enabled,
        canvas_prompt_tier: c.canvas_prompt_tier ?? null,
      });
    }
  }

  onModelSelected(modelId: string): void {
    this.form.get('model')!.setValue(modelId);
    const selected = this.availableModels().find((m) => m.id === modelId);
    if (selected?.context_window && !this.form.value.context_window_tokens) {
      this.form.patchValue({ context_window_tokens: selected.context_window });
    }
  }

  showBaseUrl(): boolean {
    const p = this.form.get('provider')?.value;
    return [
      'openai_compatible',
      'azure_openai',
      'bedrock',
      'mistral',
      'ollama',
      'lm_studio',
      'llama_cpp',
      'vllm',
    ].includes(
      p || '',
    );
  }

  private normalizeBaseUrl(value: unknown): string | undefined {
    if (typeof value !== 'string') return undefined;
    const trimmed = value.trim();
    return trimmed ? trimmed : undefined;
  }

  private buildConnectionPayload(): Record<string, string | undefined> {
    const v = this.form.getRawValue();
    const baseUrl = this.showBaseUrl() ? this.normalizeBaseUrl(v.base_url) : undefined;
    return {
      provider: v.provider || 'openai',
      api_key: v.api_key || undefined,
      base_url: baseUrl,
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
    const allowBaseUrl = this.showBaseUrl();
    const payload: Record<string, unknown> = {};

    for (const [k, v] of Object.entries(values)) {
      if (k === 'api_key' && !v) continue;
      if (k === 'base_url' && !allowBaseUrl) {
        payload[k] = null;
        continue;
      }
      if (k === 'base_url') {
        payload[k] = this.normalizeBaseUrl(v) ?? null;
        continue;
      }
      // canvas_prompt_tier: null means "auto-detect" and must be sent explicitly
      if (k === 'canvas_prompt_tier') { payload[k] = v; continue; }
      // context_window_tokens: null means "auto-detect" and must be sent explicitly (to clear override)
      if (k === 'context_window_tokens') { payload[k] = v ? Number(v) : null; continue; }
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
