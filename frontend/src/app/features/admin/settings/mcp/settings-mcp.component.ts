import { Component, inject, OnInit, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { LlmService } from '../../../../core/services/llm.service';
import { McpConfig } from '../../../../core/models/llm.model';
import { McpConfigDialogComponent } from './mcp-config-dialog.component';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';

@Component({
  selector: 'app-settings-mcp',
  standalone: true,
  imports: [
    MatButtonModule,
    MatCardModule,
    MatDialogModule,
    MatIconModule,
    MatProgressBarModule,
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
            <mat-card-title>MCP Servers</mat-card-title>
            <button mat-flat-button (click)="addConfig()">
              <mat-icon>add</mat-icon> Add Server
            </button>
          </mat-card-header>
          <mat-card-content>
            @if (configs().length === 0) {
              <p class="empty-hint">No MCP servers configured. Add one to enable AI Agent tool access.</p>
            } @else {
              <table mat-table [dataSource]="configs()" class="config-table">
                <ng-container matColumnDef="name">
                  <th mat-header-cell *matHeaderCellDef>Name</th>
                  <td mat-cell *matCellDef="let c">{{ c.name }}</td>
                </ng-container>
                <ng-container matColumnDef="url">
                  <th mat-header-cell *matHeaderCellDef>URL</th>
                  <td mat-cell *matCellDef="let c" class="url-cell">{{ c.url }}</td>
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
                      <button mat-icon-button matTooltip="Test Connection" (click)="testConfig(c)">
                        <mat-icon>wifi_tethering</mat-icon>
                      </button>
                      <button mat-icon-button matTooltip="Edit" (click)="editConfig(c)">
                        <mat-icon>edit</mat-icon>
                      </button>
                      <button mat-icon-button matTooltip="Delete" (click)="deleteConfig(c)">
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
      </div>
    }
  `,
  styles: [
    `
      .empty-hint { color: var(--mat-sys-on-surface-variant); font-size: 13px; padding: 16px; text-align: center; }
      .config-table { width: 100%; }
      .url-cell { font-family: var(--app-font-mono); font-size: 12px; max-width: 300px; overflow: hidden; text-overflow: ellipsis; }
      .status-dot {
        font-size: 12px; font-weight: 500;
        &.active { color: var(--app-success); }
        &.disabled { color: var(--app-neutral); }
      }
      .inline-actions { display: flex; gap: 0; justify-content: flex-end; }
      mat-card-header { display: flex; justify-content: space-between; align-items: center; }
    `,
  ],
})
export class SettingsMcpComponent implements OnInit {
  private readonly llmService = inject(LlmService);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);

  loading = signal(true);
  configs = signal<McpConfig[]>([]);
  displayedColumns = ['name', 'url', 'status', 'actions'];

  ngOnInit(): void {
    this.loadConfigs();
  }

  private loadConfigs(): void {
    this.llmService.listMcpConfigs().subscribe({
      next: (configs) => { this.configs.set(configs); this.loading.set(false); },
      error: () => this.loading.set(false),
    });
  }

  addConfig(): void {
    const ref = this.dialog.open(McpConfigDialogComponent, { width: '600px', data: { config: null } });
    ref.afterClosed().subscribe((r) => { if (r) this.loadConfigs(); });
  }

  editConfig(c: McpConfig): void {
    const ref = this.dialog.open(McpConfigDialogComponent, { width: '600px', data: { config: c } });
    ref.afterClosed().subscribe((r) => { if (r) this.loadConfigs(); });
  }

  testConfig(c: McpConfig): void {
    this.llmService.testMcpConfig(c.id).subscribe({
      next: (res) => {
        if (res.status === 'connected') {
          this.snackBar.open(`Connected - ${res.tools} tools`, 'OK', { duration: 3000 });
        } else {
          this.snackBar.open(res.error || 'Connection failed', 'OK', { duration: 5000 });
        }
      },
      error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
    });
  }

  deleteConfig(c: McpConfig): void {
    this.llmService.deleteMcpConfig(c.id).subscribe({
      next: () => { this.loadConfigs(); this.snackBar.open(`'${c.name}' deleted`, 'OK', { duration: 3000 }); },
      error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
    });
  }
}
