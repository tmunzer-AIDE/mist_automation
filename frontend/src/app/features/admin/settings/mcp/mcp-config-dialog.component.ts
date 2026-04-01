import { Component, inject, OnInit, signal } from '@angular/core';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { LlmService } from '../../../../core/services/llm.service';
import { McpConfig } from '../../../../core/models/llm.model';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';

@Component({
  selector: 'app-mcp-config-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatSlideToggleModule,
    MatSnackBarModule,
  ],
  template: `
    <h2 mat-dialog-title>{{ isEdit ? 'Edit' : 'Add' }} MCP Server</h2>
    <mat-dialog-content>
      <form [formGroup]="form" class="config-form">
        <mat-form-field appearance="outline">
          <mat-label>Name</mat-label>
          <input matInput formControlName="name" placeholder="e.g., Mist MCP" />
        </mat-form-field>

        <mat-form-field appearance="outline">
          <mat-label>URL</mat-label>
          <input matInput formControlName="url" placeholder="https://mcp.example.com/mcp" />
        </mat-form-field>

        <mat-form-field appearance="outline">
          <mat-label>Headers (JSON)</mat-label>
          <textarea
            matInput
            formControlName="headers"
            rows="3"
            [placeholder]="isEdit && data.config?.headers_set ? 'Leave empty to keep current' : '{&quot;Authorization&quot;: &quot;Bearer ...&quot;}'"
          ></textarea>
          <mat-hint>JSON object with HTTP headers (e.g., auth tokens)</mat-hint>
        </mat-form-field>

        <div class="toggle-row">
          <mat-slide-toggle formControlName="ssl_verify">SSL Verify</mat-slide-toggle>
          <mat-slide-toggle formControlName="enabled">Enabled</mat-slide-toggle>
        </div>

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
      .toggle-row { display: flex; gap: 24px; margin: 8px 0; }
      .action-button { align-self: flex-start; margin-bottom: 8px; }
    `,
  ],
})
export class McpConfigDialogComponent implements OnInit {
  readonly data: { config: McpConfig | null } = inject(MAT_DIALOG_DATA);
  private readonly llmService = inject(LlmService);
  private readonly dialogRef = inject(MatDialogRef<McpConfigDialogComponent>);
  private readonly fb = inject(FormBuilder);
  private readonly snackBar = inject(MatSnackBar);

  readonly isEdit = !!this.data.config;
  saving = signal(false);
  testing = signal(false);

  form = this.fb.group({
    name: ['', Validators.required],
    url: ['', Validators.required],
    headers: [''],
    ssl_verify: [true],
    enabled: [true],
  });

  ngOnInit(): void {
    if (this.data.config) {
      const c = this.data.config;
      this.form.patchValue({
        name: c.name,
        url: c.url,
        headers: c.headers ? JSON.stringify(c.headers, null, 2) : '',
        ssl_verify: c.ssl_verify,
        enabled: c.enabled,
      });
    }
  }

  testConnection(): void {
    this.testing.set(true);
    const v = this.form.getRawValue();
    const payload: Record<string, unknown> = {
      url: v.url,
      ssl_verify: v.ssl_verify,
    };
    if (v.headers?.trim()) {
      try {
        payload['headers'] = JSON.parse(v.headers);
      } catch {
        this.snackBar.open('Invalid JSON in headers', 'OK', { duration: 3000 });
        this.testing.set(false);
        return;
      }
    } else if (this.isEdit) {
      payload['config_id'] = this.data.config!.id;
    }
    this.llmService.testMcpConnectionAnonymous(payload).subscribe({
      next: (res) => {
        this.testing.set(false);
        if (res.status === 'connected') {
          this.snackBar.open(`Connected - ${res.tools} tools available`, 'OK', { duration: 3000 });
        } else {
          this.snackBar.open(res.error || 'Connection failed', 'OK', { duration: 5000 });
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
    const v = this.form.getRawValue();
    const payload: Record<string, unknown> = {
      name: v.name,
      url: v.url,
      ssl_verify: v.ssl_verify,
      enabled: v.enabled,
    };
    if (v.headers?.trim()) {
      try {
        payload['headers'] = JSON.parse(v.headers);
      } catch {
        this.snackBar.open('Invalid JSON in headers', 'OK', { duration: 3000 });
        this.saving.set(false);
        return;
      }
    }
    const obs = this.isEdit
      ? this.llmService.updateMcpConfig(this.data.config!.id, payload)
      : this.llmService.createMcpConfig(payload);

    obs.subscribe({
      next: () => {
        this.saving.set(false);
        this.snackBar.open(this.isEdit ? 'MCP config updated' : 'MCP config created', 'OK', { duration: 3000 });
        this.dialogRef.close(true);
      },
      error: (err) => {
        this.saving.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }
}
