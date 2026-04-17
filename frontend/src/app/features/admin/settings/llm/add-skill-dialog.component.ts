import { Component, OnInit, inject, signal } from '@angular/core';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { McpConfig } from '../../../../core/models/llm.model';
import { LlmService } from '../../../../core/services/llm.service';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';

@Component({
  selector: 'app-add-skill-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressBarModule,
    MatSelectModule,
  ],
  template: `
    <h2 mat-dialog-title>Add Skill</h2>
    @if (saving()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    }
    <mat-dialog-content>
      <p class="hint">Paste the full contents of a <code>SKILL.md</code> file below.</p>
      <mat-form-field appearance="outline" class="full-width">
        <mat-label>SKILL.md content</mat-label>
        <textarea
          matInput
          [formControl]="contentCtrl"
          rows="14"
          placeholder="---&#10;name: my-skill&#10;description: Does useful things.&#10;---&#10;&#10;# My Skill&#10;Instructions here."
        ></textarea>
        @if (contentCtrl.hasError('required')) {
          <mat-error>Content is required</mat-error>
        }
      </mat-form-field>

      <mat-form-field appearance="outline" class="full-width">
        <mat-label>MCP Server Binding (optional)</mat-label>
        <mat-select [formControl]="mcpConfigCtrl">
          <mat-option [value]="null">No binding</mat-option>
          @for (cfg of mcpConfigs(); track cfg.id) {
            <mat-option [value]="cfg.id">{{ cfg.name }}</mat-option>
          }
        </mat-select>
      </mat-form-field>

      @if (mcpConfigs().length === 0) {
        <p class="hint">No MCP servers configured yet. You can still add the skill unbound.</p>
      }

      @if (error()) {
        <p class="api-error">{{ error() }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close [disabled]="saving()">Cancel</button>
      <button mat-flat-button (click)="save()" [disabled]="saving() || contentCtrl.invalid">Add Skill</button>
    </mat-dialog-actions>
  `,
  styles: [`
    .full-width { width: 100%; }
    .hint { font-size: 13px; color: var(--mat-sys-on-surface-variant); margin-bottom: 12px; }
    .api-error { color: var(--app-error, #f44336); font-size: 13px; margin-top: 8px; }
    mat-dialog-content { min-width: 480px; }
  `],
})
export class AddSkillDialogComponent implements OnInit {
  private readonly llmService = inject(LlmService);
  private readonly dialogRef = inject(MatDialogRef<AddSkillDialogComponent>);

  contentCtrl = new FormControl('', [Validators.required, Validators.minLength(10)]);
  mcpConfigCtrl = new FormControl<string | null>(null);
  saving = signal(false);
  error = signal<string | null>(null);
  mcpConfigs = signal<McpConfig[]>([]);

  ngOnInit(): void {
    this.llmService.listMcpConfigs().subscribe({
      next: (configs) => this.mcpConfigs.set(configs),
      error: () => this.mcpConfigs.set([]),
    });
  }

  save(): void {
    if (this.contentCtrl.invalid || !this.contentCtrl.value) return;
    this.saving.set(true);
    this.error.set(null);
    this.llmService.addDirectSkill(this.contentCtrl.value, this.mcpConfigCtrl.value).subscribe({
      next: () => this.dialogRef.close(true),
      error: (err) => {
        this.error.set(extractErrorMessage(err));
        this.saving.set(false);
      },
    });
  }
}
