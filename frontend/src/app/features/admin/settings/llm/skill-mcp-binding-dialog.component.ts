import { Component, OnInit, inject, signal } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { McpConfig } from '../../../../core/models/llm.model';
import { LlmService } from '../../../../core/services/llm.service';

export interface SkillMcpBindingDialogData {
  title: string;
  subtitle?: string;
  currentMcpConfigId: string | null;
}

@Component({
  selector: 'app-skill-mcp-binding-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatProgressBarModule,
    MatSelectModule,
  ],
  template: `
    <h2 mat-dialog-title>{{ data.title }}</h2>
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    }
    <mat-dialog-content>
      @if (data.subtitle) {
        <p class="hint">{{ data.subtitle }}</p>
      }
      <mat-form-field appearance="outline" class="full-width">
        <mat-label>MCP Server</mat-label>
        <mat-select [formControl]="mcpConfigCtrl">
          <mat-option [value]="null">No binding</mat-option>
          @if (showMissingCurrentOption()) {
            <mat-option [value]="data.currentMcpConfigId">
              Missing config ({{ data.currentMcpConfigId }})
            </mat-option>
          }
          @for (cfg of mcpConfigs(); track cfg.id) {
            <mat-option [value]="cfg.id">{{ cfg.name }}</mat-option>
          }
        </mat-select>
      </mat-form-field>
      @if (mcpConfigs().length === 0) {
        <p class="hint">No MCP servers are configured. Save to clear binding or keep unbound.</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button mat-flat-button (click)="save()" [disabled]="loading()">Save</button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .full-width { width: 100%; }
      .hint { font-size: 13px; color: var(--mat-sys-on-surface-variant); margin-bottom: 12px; }
      mat-dialog-content { min-width: 420px; }
    `,
  ],
})
export class SkillMcpBindingDialogComponent implements OnInit {
  private readonly llmService = inject(LlmService);
  private readonly dialogRef = inject(MatDialogRef<SkillMcpBindingDialogComponent>);

  readonly data = inject<SkillMcpBindingDialogData>(MAT_DIALOG_DATA);

  mcpConfigCtrl = new FormControl<string | null>(null);
  mcpConfigs = signal<McpConfig[]>([]);
  loading = signal(true);

  ngOnInit(): void {
    this.mcpConfigCtrl.setValue(this.data.currentMcpConfigId ?? null);
    this.llmService.listMcpConfigs().subscribe({
      next: (configs) => {
        this.mcpConfigs.set(configs);
        this.loading.set(false);
      },
      error: () => {
        this.mcpConfigs.set([]);
        this.loading.set(false);
      },
    });
  }

  showMissingCurrentOption(): boolean {
    if (!this.data.currentMcpConfigId) {
      return false;
    }
    return !this.mcpConfigs().some((cfg) => cfg.id === this.data.currentMcpConfigId);
  }

  save(): void {
    this.dialogRef.close(this.mcpConfigCtrl.value ?? null);
  }
}
