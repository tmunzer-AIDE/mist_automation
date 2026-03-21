import { JsonPipe, SlicePipe } from '@angular/common';
import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ReactiveFormsModule, FormControl } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { LlmService } from '../../../../core/services/llm.service';
import { McpTool } from '../../../../core/models/llm.model';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';

interface ToolState {
  tool: McpTool;
  argsCtrl: FormControl<string>;
  result: string | null;
  running: boolean;
  error: string | null;
}

@Component({
  selector: 'app-mcp-tools-dialog',
  standalone: true,
  imports: [
    JsonPipe,
    SlicePipe,
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatExpansionModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatSnackBarModule,
  ],
  template: `
    <h2 mat-dialog-title>{{ data.name }} - Tools</h2>
    <mat-dialog-content>
      @if (loading()) {
        <mat-progress-bar mode="indeterminate"></mat-progress-bar>
      } @else if (loadError()) {
        <div class="error-text">{{ loadError() }}</div>
      } @else if (toolStates().length === 0) {
        <p class="empty-hint">No tools found on this server.</p>
      } @else {
        <mat-accordion multi>
          @for (ts of toolStates(); track ts.tool.name) {
            <mat-expansion-panel>
              <mat-expansion-panel-header>
                <mat-panel-title>{{ ts.tool.name }}</mat-panel-title>
                <mat-panel-description>{{ ts.tool.description | slice:0:60 }}</mat-panel-description>
              </mat-expansion-panel-header>

              <div class="tool-detail">
                <p class="tool-desc">{{ ts.tool.description }}</p>

                @if (getSchemaProperties(ts.tool)) {
                  <div class="schema-block">
                    <span class="schema-label">Parameters:</span>
                    <pre>{{ getSchemaProperties(ts.tool) | json }}</pre>
                  </div>
                }

                <mat-form-field appearance="outline" class="args-field">
                  <mat-label>Arguments (JSON)</mat-label>
                  <textarea matInput [formControl]="ts.argsCtrl" rows="3" placeholder="{}"></textarea>
                </mat-form-field>

                <div class="tool-actions">
                  @if (ts.running) {
                    <button mat-flat-button color="primary" disabled>Running...</button>
                  } @else {
                    <button mat-flat-button color="primary" (click)="callTool(ts)">
                      <mat-icon>play_arrow</mat-icon> Try It
                    </button>
                  }
                </div>

                @if (ts.result !== null) {
                  <div class="result-block">
                    <span class="result-label">Result:</span>
                    <pre class="result-text">{{ ts.result }}</pre>
                  </div>
                }

                @if (ts.error) {
                  <div class="result-block error">
                    <span class="result-label">Error:</span>
                    <pre class="result-text">{{ ts.error }}</pre>
                  </div>
                }
              </div>
            </mat-expansion-panel>
          }
        </mat-accordion>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Close</button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      mat-dialog-content { min-width: 500px; max-height: 70vh; }
      .empty-hint { color: var(--mat-sys-on-surface-variant); font-size: 13px; text-align: center; padding: 24px; }
      .error-text { color: var(--app-error); padding: 16px; }
      .tool-desc { font-size: 13px; color: var(--mat-sys-on-surface-variant); margin: 0 0 12px; }
      .schema-block { margin-bottom: 12px; }
      .schema-label, .result-label { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
      .schema-block pre, .result-text {
        font-size: 12px; background: var(--mat-sys-surface-container); border-radius: 6px;
        padding: 8px 12px; overflow-x: auto; max-height: 200px; margin: 4px 0 0;
      }
      .args-field { width: 100%; }
      .tool-actions { margin-bottom: 8px; }
      .tool-actions button mat-icon { font-size: 18px; width: 18px; height: 18px; margin-right: 4px; }
      .result-block { margin-top: 8px; }
      .result-block.error .result-text { color: var(--app-error); }
    `,
  ],
})
export class McpToolsDialogComponent implements OnInit {
  private readonly llmService = inject(LlmService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);
  readonly data = inject<{ configId: string | null; name: string }>(MAT_DIALOG_DATA);

  loading = signal(true);
  loadError = signal<string | null>(null);
  toolStates = signal<ToolState[]>([]);

  ngOnInit(): void {
    const obs = this.data.configId
      ? this.llmService.listMcpTools(this.data.configId)
      : this.llmService.listLocalMcpTools();

    obs.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (tools) => {
        this.toolStates.set(
          tools.map((t) => ({
            tool: t,
            argsCtrl: new FormControl('{}', { nonNullable: true }),
            result: null,
            running: false,
            error: null,
          })),
        );
        this.loading.set(false);
      },
      error: (err) => {
        this.loadError.set(extractErrorMessage(err));
        this.loading.set(false);
      },
    });
  }

  getSchemaProperties(tool: McpTool): Record<string, unknown> | null {
    const props = tool.input_schema?.['properties'];
    return props && typeof props === 'object' ? (props as Record<string, unknown>) : null;
  }

  callTool(ts: ToolState): void {
    let args: Record<string, unknown>;
    try {
      args = JSON.parse(ts.argsCtrl.value || '{}');
    } catch {
      this.snackBar.open('Invalid JSON arguments', 'OK', { duration: 3000 });
      return;
    }

    ts.running = true;
    ts.result = null;
    ts.error = null;
    // Trigger signal update
    this.toolStates.update((s) => [...s]);

    const obs = this.data.configId
      ? this.llmService.callMcpTool(this.data.configId, ts.tool.name, args)
      : this.llmService.callLocalMcpTool(ts.tool.name, args);

    obs.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (res) => {
        ts.running = false;
        ts.result = res.result;
        this.toolStates.update((s) => [...s]);
      },
      error: (err) => {
        ts.running = false;
        ts.error = extractErrorMessage(err);
        this.toolStates.update((s) => [...s]);
      },
    });
  }
}
