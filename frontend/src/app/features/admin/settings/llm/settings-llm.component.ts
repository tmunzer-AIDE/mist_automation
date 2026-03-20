import { Component, inject, OnInit, signal } from '@angular/core';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSliderModule } from '@angular/material/slider';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { SettingsService } from '../settings.service';
import { LlmService } from '../../../../core/services/llm.service';
import { SystemSettings } from '../../../../core/models/admin.model';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';

const PROVIDER_OPTIONS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'ollama', label: 'Ollama (Local)' },
  { value: 'lm_studio', label: 'LM Studio (Local)' },
  { value: 'azure_openai', label: 'Azure OpenAI' },
  { value: 'bedrock', label: 'AWS Bedrock' },
];

const MODEL_HINTS: Record<string, string> = {
  openai: 'gpt-4o, gpt-4o-mini, gpt-4-turbo',
  anthropic: 'claude-sonnet-4-20250514, claude-haiku-4-5-20251001',
  ollama: 'llama3.1, mistral, codellama',
  lm_studio: 'Use the model name loaded in LM Studio',
  azure_openai: 'gpt-4o (deployment name)',
  bedrock: 'anthropic.claude-sonnet-4-20250514-v1:0',
};

@Component({
  selector: 'app-settings-llm',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatSlideToggleModule,
    MatSliderModule,
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
            <mat-card-title>LLM Configuration</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <div class="toggle-row">
              <mat-slide-toggle formControlName="llm_enabled">Enable LLM Integration</mat-slide-toggle>
            </div>

            <mat-form-field appearance="outline">
              <mat-label>Provider</mat-label>
              <mat-select formControlName="llm_provider">
                @for (opt of providers; track opt.value) {
                  <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                }
              </mat-select>
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>API Key</mat-label>
              <input
                matInput
                type="password"
                formControlName="llm_api_key"
                [placeholder]="apiKeySet() ? 'Leave empty to keep current' : 'Enter API key'"
              />
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Model</mat-label>
              <input matInput formControlName="llm_model" [placeholder]="modelHint()" />
              @if (modelHint()) {
                <mat-hint>e.g., {{ modelHint() }}</mat-hint>
              }
            </mat-form-field>

            @if (showBaseUrl()) {
              <mat-form-field appearance="outline">
                <mat-label>Base URL</mat-label>
                <input
                  matInput
                  formControlName="llm_base_url"
                  placeholder="http://localhost:11434"
                />
                <mat-hint>Required for Ollama or custom API endpoints</mat-hint>
              </mat-form-field>
            }
          </mat-card-content>
        </mat-card>

        <mat-card>
          <mat-card-header>
            <mat-card-title>Parameters</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <div class="slider-row">
              <label>Temperature: {{ form.get('llm_temperature')?.value }}</label>
              <mat-slider min="0" max="2" step="0.1" discrete>
                <input matSliderThumb formControlName="llm_temperature" />
              </mat-slider>
            </div>

            <mat-form-field appearance="outline">
              <mat-label>Max Tokens per Request</mat-label>
              <input
                matInput
                type="number"
                formControlName="llm_max_tokens_per_request"
              />
              <mat-hint>100 - 32000</mat-hint>
            </mat-form-field>
          </mat-card-content>
          <mat-card-actions align="end">
            <button
              mat-stroked-button
              (click)="testConnection()"
              [disabled]="testing() || !form.get('llm_enabled')?.value"
            >
              <mat-icon>wifi_tethering</mat-icon>
              {{ testing() ? 'Testing...' : 'Test Connection' }}
            </button>
            <button mat-flat-button (click)="save()" [disabled]="saving()">
              <mat-icon>save</mat-icon> {{ saving() ? 'Saving...' : 'Save' }}
            </button>
          </mat-card-actions>
        </mat-card>
      </form>
    }
  `,
  styles: [
    `
      .toggle-row {
        margin-bottom: 16px;
      }
      .slider-row {
        display: flex;
        flex-direction: column;
        margin-bottom: 8px;
      }
      .slider-row label {
        font-size: 14px;
        color: var(--app-neutral);
        margin-bottom: 4px;
      }
    `,
  ],
})
export class SettingsLlmComponent implements OnInit {
  private readonly settingsService = inject(SettingsService);
  private readonly llmService = inject(LlmService);
  private readonly fb = inject(FormBuilder);
  private readonly snackBar = inject(MatSnackBar);

  loading = signal(true);
  saving = signal(false);
  testing = signal(false);
  apiKeySet = signal(false);

  readonly providers = PROVIDER_OPTIONS;

  form = this.fb.group({
    llm_enabled: [false],
    llm_provider: [''],
    llm_api_key: [''],
    llm_model: [''],
    llm_base_url: [''],
    llm_temperature: [0.3, [Validators.min(0), Validators.max(2)]],
    llm_max_tokens_per_request: [4096, [Validators.min(100), Validators.max(32000)]],
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
        error: () => this.loading.set(false),
      });
    }
  }

  modelHint(): string {
    const provider = this.form.get('llm_provider')?.value;
    return provider ? MODEL_HINTS[provider] || '' : '';
  }

  showBaseUrl(): boolean {
    const provider = this.form.get('llm_provider')?.value;
    return ['ollama', 'lm_studio', 'azure_openai', 'bedrock'].includes(provider || '');
  }

  testConnection(): void {
    this.testing.set(true);
    this.llmService.testConnection().subscribe({
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

  save(): void {
    this.saving.set(true);
    const values = this.form.getRawValue();
    const updates: Record<string, unknown> = {};

    // Always send toggle and non-sensitive fields
    if (values.llm_enabled !== null) updates['llm_enabled'] = values.llm_enabled;
    if (values.llm_provider) updates['llm_provider'] = values.llm_provider;
    if (values.llm_model) updates['llm_model'] = values.llm_model;
    if (values.llm_temperature !== null) updates['llm_temperature'] = values.llm_temperature;
    if (values.llm_max_tokens_per_request !== null)
      updates['llm_max_tokens_per_request'] = values.llm_max_tokens_per_request;

    // Only send sensitive/optional fields if non-empty
    if (values.llm_api_key) updates['llm_api_key'] = values.llm_api_key;
    if (values.llm_base_url) updates['llm_base_url'] = values.llm_base_url;

    this.settingsService.save(updates).subscribe({
      next: () => {
        this.saving.set(false);
        this.snackBar.open('LLM settings saved', 'OK', { duration: 3000 });
        // Reload to get fresh state (api_key_set, etc.)
        this.settingsService.load().subscribe((s) => this.populateForm(s));
      },
      error: (err) => {
        this.saving.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  private populateForm(s: SystemSettings): void {
    this.apiKeySet.set(s.llm_api_key_set);
    this.form.patchValue({
      llm_enabled: s.llm_enabled,
      llm_provider: s.llm_provider || '',
      llm_model: s.llm_model || '',
      llm_base_url: s.llm_base_url || '',
      llm_temperature: s.llm_temperature,
      llm_max_tokens_per_request: s.llm_max_tokens_per_request,
    });
  }
}
