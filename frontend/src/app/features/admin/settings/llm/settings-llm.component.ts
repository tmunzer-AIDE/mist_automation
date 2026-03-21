import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { LlmService } from '../../../../core/services/llm.service';
import { LlmConfig } from '../../../../core/models/llm.model';
import { SettingsService } from '../settings.service';
import { LlmConfigDialogComponent } from './llm-config-dialog.component';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';

@Component({
  selector: 'app-settings-llm',
  standalone: true,
  imports: [
    FormsModule,
    MatButtonModule,
    MatCardModule,
    MatDialogModule,
    MatIconModule,
    MatProgressBarModule,
    MatSlideToggleModule,
    MatSnackBarModule,
    MatTableModule,
    MatTooltipModule,
  ],
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    } @else {
      <div class="tab-form">
        <mat-card>
          <mat-card-header>
            <mat-card-title>LLM Integration</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <div class="toggle-row">
              <mat-slide-toggle
                [ngModel]="llmEnabled()"
                (ngModelChange)="toggleGlobalLlm($event)"
              >
                Enable LLM Features
              </mat-slide-toggle>
            </div>
          </mat-card-content>
        </mat-card>

        @if (llmEnabled()) {
          <mat-card>
            <mat-card-header>
              <mat-card-title>LLM Configurations</mat-card-title>
              <button mat-flat-button (click)="addConfig()">
                <mat-icon>add</mat-icon> Add Configuration
              </button>
            </mat-card-header>
            <mat-card-content>
              @if (configs().length === 0) {
                <p class="empty-hint">No LLM configurations yet. Add one to get started.</p>
              } @else {
                <table mat-table [dataSource]="configs()" class="config-table">
                  <ng-container matColumnDef="name">
                    <th mat-header-cell *matHeaderCellDef>Name</th>
                    <td mat-cell *matCellDef="let c">
                      {{ c.name }}
                      @if (c.is_default) {
                        <span class="default-badge">Default</span>
                      }
                    </td>
                  </ng-container>
                  <ng-container matColumnDef="provider">
                    <th mat-header-cell *matHeaderCellDef>Provider</th>
                    <td mat-cell *matCellDef="let c">{{ c.provider }}</td>
                  </ng-container>
                  <ng-container matColumnDef="model">
                    <th mat-header-cell *matHeaderCellDef>Model</th>
                    <td mat-cell *matCellDef="let c">{{ c.model || '—' }}</td>
                  </ng-container>
                  <ng-container matColumnDef="status">
                    <th mat-header-cell *matHeaderCellDef>Status</th>
                    <td mat-cell *matCellDef="let c">
                      <span class="status-dot" [class.active]="c.enabled" [class.disabled]="!c.enabled">
                        {{ c.enabled ? 'Active' : 'Disabled' }}
                      </span>
                    </td>
                  </ng-container>
                  <ng-container matColumnDef="actions">
                    <th mat-header-cell *matHeaderCellDef></th>
                    <td mat-cell *matCellDef="let c">
                      <div class="inline-actions">
                        @if (!c.is_default) {
                          <button mat-icon-button matTooltip="Set as Default" (click)="setDefault(c)">
                            <mat-icon>star_outline</mat-icon>
                          </button>
                        }
                        <button mat-icon-button matTooltip="Test Connection" (click)="testConfig(c)">
                          <mat-icon>wifi_tethering</mat-icon>
                        </button>
                        <button mat-icon-button matTooltip="Edit" (click)="editConfig(c)">
                          <mat-icon>edit</mat-icon>
                        </button>
                        <button
                          mat-icon-button
                          matTooltip="Delete"
                          [disabled]="c.is_default"
                          (click)="deleteConfig(c)"
                        >
                          <mat-icon>delete</mat-icon>
                        </button>
                      </div>
                    </td>
                  </ng-container>
                  <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
                  <tr mat-row *matRowDef="let row; columns: displayedColumns"></tr>
                </table>
              }
            </mat-card-content>
          </mat-card>
        }
      </div>
    }
  `,
  styles: [
    `
      .toggle-row { margin-bottom: 8px; }
      .empty-hint { color: var(--mat-sys-on-surface-variant); font-size: 13px; padding: 16px; text-align: center; }
      .config-table { width: 100%; }
      .default-badge {
        font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 10px;
        background: var(--mat-sys-primary-container); color: var(--mat-sys-on-primary-container);
        margin-left: 8px;
      }
      .status-dot {
        font-size: 12px; font-weight: 500;
        &.active { color: var(--app-success, #4caf50); }
        &.disabled { color: var(--app-neutral, #888); }
      }
      .inline-actions { display: flex; gap: 0; justify-content: flex-end; }
      mat-card-header { display: flex; justify-content: space-between; align-items: center; }
    `,
  ],
})
export class SettingsLlmComponent implements OnInit {
  private readonly llmService = inject(LlmService);
  private readonly settingsService = inject(SettingsService);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);

  loading = signal(true);
  llmEnabled = signal(false);
  configs = signal<LlmConfig[]>([]);
  displayedColumns = ['name', 'provider', 'model', 'status', 'actions'];

  ngOnInit(): void {
    this.settingsService.load().subscribe({
      next: (s) => {
        this.llmEnabled.set(s.llm_enabled);
        if (s.llm_enabled) {
          this.loadConfigs();
        } else {
          this.loading.set(false);
        }
      },
      error: () => this.loading.set(false),
    });
  }

  private loadConfigs(): void {
    this.llmService.listConfigs().subscribe({
      next: (configs) => {
        this.configs.set(configs);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  toggleGlobalLlm(enabled: boolean): void {
    this.settingsService.save({ llm_enabled: enabled }).subscribe({
      next: () => {
        this.llmEnabled.set(enabled);
        if (enabled) this.loadConfigs();
        this.snackBar.open(enabled ? 'LLM enabled' : 'LLM disabled', 'OK', { duration: 3000 });
      },
      error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
    });
  }

  addConfig(): void {
    const ref = this.dialog.open(LlmConfigDialogComponent, {
      width: '600px',
      maxHeight: '80vh',
      data: { config: null },
    });
    ref.afterClosed().subscribe((result) => {
      if (result) this.loadConfigs();
    });
  }

  editConfig(config: LlmConfig): void {
    const ref = this.dialog.open(LlmConfigDialogComponent, {
      width: '600px',
      maxHeight: '80vh',
      data: { config },
    });
    ref.afterClosed().subscribe((result) => {
      if (result) this.loadConfigs();
    });
  }

  setDefault(config: LlmConfig): void {
    this.llmService.setDefaultConfig(config.id).subscribe({
      next: () => {
        this.loadConfigs();
        this.snackBar.open(`'${config.name}' set as default`, 'OK', { duration: 3000 });
      },
      error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
    });
  }

  testConfig(config: LlmConfig): void {
    this.llmService.testConfig(config.id).subscribe({
      next: (result) => {
        if (result.status === 'connected') {
          this.snackBar.open(`Connected to ${result.model}`, 'OK', { duration: 3000 });
        } else {
          this.snackBar.open(result.error || 'Connection failed', 'OK', { duration: 5000 });
        }
      },
      error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
    });
  }

  deleteConfig(config: LlmConfig): void {
    if (config.is_default) return;
    this.llmService.deleteConfig(config.id).subscribe({
      next: () => {
        this.loadConfigs();
        this.snackBar.open(`'${config.name}' deleted`, 'OK', { duration: 3000 });
      },
      error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
    });
  }
}
