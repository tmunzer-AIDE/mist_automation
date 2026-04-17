import { DatePipe, SlicePipe } from '@angular/common';
import { Component, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { interval, Subscription } from 'rxjs';
import { take, takeWhile } from 'rxjs/operators';
import { ConfirmDialogComponent } from '../../../../shared/components/confirm-dialog/confirm-dialog.component';
import { LlmService } from '../../../../core/services/llm.service';
import { McpConfig, Skill, SkillGitRepo } from '../../../../core/models/llm.model';
import { extractErrorMessage } from '../../../../shared/utils/error.utils';
import { AddSkillDialogComponent } from './add-skill-dialog.component';
import { AddRepoDialogComponent } from './add-repo-dialog.component';
import { SkillMcpBindingDialogComponent } from './skill-mcp-binding-dialog.component';

@Component({
  selector: 'app-skills-admin',
  standalone: true,
  imports: [
    DatePipe,
    SlicePipe,
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
      <!-- Git repos card -->
      <mat-card>
        <mat-card-header>
          <mat-card-title>Skills — Git Repositories</mat-card-title>
          <button mat-flat-button (click)="addRepo()">
            <mat-icon>add</mat-icon> Add Git Repo
          </button>
        </mat-card-header>
        <mat-card-content>
          @if (repos().length === 0) {
            <p class="empty-hint">No git repos configured. Add one to auto-discover skills.</p>
          } @else {
            <table mat-table [dataSource]="repos()" class="repo-table">
              <ng-container matColumnDef="url">
                <th mat-header-cell *matHeaderCellDef>Repository</th>
                <td mat-cell *matCellDef="let r">
                  <span class="repo-url">{{ r.url }}</span>
                  <span class="branch-badge">{{ r.branch }}</span>
                </td>
              </ng-container>
              <ng-container matColumnDef="status">
                <th mat-header-cell *matHeaderCellDef>Last Synced</th>
                <td mat-cell *matCellDef="let r">
                  @if (syncingRepos().has(r.id)) {
                    <span class="syncing">Syncing…</span>
                  } @else if (r.error) {
                    <span class="error-text" [matTooltip]="r.error">
                      <mat-icon class="error-icon">error_outline</mat-icon> Error
                    </span>
                  } @else if (r.last_refreshed_at) {
                    {{ r.last_refreshed_at | date: 'short' }}
                  } @else {
                    <span class="pending">Pending…</span>
                  }
                </td>
              </ng-container>
              <ng-container matColumnDef="binding">
                <th mat-header-cell *matHeaderCellDef>MCP Binding</th>
                <td mat-cell *matCellDef="let r">
                  @if (r.mcp_config_id) {
                    <span class="badge badge-bound" [matTooltip]="r.mcp_config_id">{{ mcpLabel(r.mcp_config_id) }}</span>
                  } @else {
                    <span class="badge badge-unbound">unbound</span>
                  }
                </td>
              </ng-container>
              <ng-container matColumnDef="actions">
                <th mat-header-cell *matHeaderCellDef></th>
                <td mat-cell *matCellDef="let r">
                  <div class="inline-actions">
                    <button mat-icon-button matTooltip="Set MCP binding" (click)="editRepoBinding(r)">
                      <mat-icon>link</mat-icon>
                    </button>
                    <button
                      mat-icon-button
                      matTooltip="Refresh"
                      [disabled]="syncingRepos().has(r.id)"
                      (click)="refreshRepo(r)"
                    >
                      <mat-icon>sync</mat-icon>
                    </button>
                    <button mat-icon-button matTooltip="Delete" (click)="deleteRepo(r)">
                      <mat-icon>delete</mat-icon>
                    </button>
                  </div>
                </td>
              </ng-container>
              <tr mat-header-row *matHeaderRowDef="repoColumns"></tr>
              <tr mat-row *matRowDef="let row; columns: repoColumns"></tr>
            </table>
          }
        </mat-card-content>
      </mat-card>

      <!-- Skills table card -->
      <mat-card>
        <mat-card-header>
          <mat-card-title>Skills</mat-card-title>
          <button mat-flat-button (click)="addSkill()">
            <mat-icon>add</mat-icon> Add Skill
          </button>
        </mat-card-header>
        <mat-card-content>
          @if (skills().length === 0) {
            <p class="empty-hint">No skills loaded yet. Add a SKILL.md directly or via a git repo.</p>
          } @else {
            <table mat-table [dataSource]="skills()" class="skills-table">
              <ng-container matColumnDef="name">
                <th mat-header-cell *matHeaderCellDef>Name</th>
                <td mat-cell *matCellDef="let s" [class.disabled-row]="!s.enabled">
                  {{ s.name }}
                  @if (s.error) {
                    <mat-icon class="error-icon" [matTooltip]="s.error">error_outline</mat-icon>
                  }
                </td>
              </ng-container>
              <ng-container matColumnDef="description">
                <th mat-header-cell *matHeaderCellDef>Description</th>
                <td mat-cell *matCellDef="let s" [class.disabled-row]="!s.enabled">
                  {{ s.description | slice: 0 : 100 }}{{ (s.description?.length ?? 0) > 100 ? '…' : '' }}
                </td>
              </ng-container>
              <ng-container matColumnDef="source">
                <th mat-header-cell *matHeaderCellDef>Source</th>
                <td mat-cell *matCellDef="let s">
                  @if (s.source === 'direct') {
                    <span class="badge badge-direct">direct</span>
                  } @else {
                    <span class="badge badge-git" [matTooltip]="s.git_repo_url || ''">git</span>
                  }
                </td>
              </ng-container>
              <ng-container matColumnDef="binding">
                <th mat-header-cell *matHeaderCellDef>MCP Binding</th>
                <td mat-cell *matCellDef="let s">
                  @if (s.effective_mcp_config_id) {
                    <span class="badge badge-bound" [matTooltip]="s.effective_mcp_config_id">
                      {{ mcpLabel(s.effective_mcp_config_id) }}
                    </span>
                    @if (s.source === 'git' && !s.mcp_config_id) {
                      <span class="binding-origin" matTooltip="Inherited from repo binding">repo</span>
                    }
                  } @else {
                    <span class="badge badge-unbound">unbound</span>
                  }
                </td>
              </ng-container>
              <ng-container matColumnDef="enabled">
                <th mat-header-cell *matHeaderCellDef>Enabled</th>
                <td mat-cell *matCellDef="let s">
                  <mat-slide-toggle [checked]="s.enabled" (change)="toggleSkill(s)"></mat-slide-toggle>
                </td>
              </ng-container>
              <ng-container matColumnDef="synced">
                <th mat-header-cell *matHeaderCellDef>Last Synced</th>
                <td mat-cell *matCellDef="let s">
                  {{ s.last_synced_at ? (s.last_synced_at | date: 'short') : '—' }}
                </td>
              </ng-container>
              <ng-container matColumnDef="actions">
                <th mat-header-cell *matHeaderCellDef></th>
                <td mat-cell *matCellDef="let s">
                  <button mat-icon-button [matTooltip]="bindingActionTooltip(s)" (click)="editSkillBinding(s)">
                    <mat-icon>link</mat-icon>
                  </button>
                  @if (s.source === 'direct') {
                    <button mat-icon-button matTooltip="Delete" (click)="deleteSkill(s)">
                      <mat-icon>delete</mat-icon>
                    </button>
                  }
                </td>
              </ng-container>
              <tr mat-header-row *matHeaderRowDef="skillColumns"></tr>
              <tr mat-row *matRowDef="let row; columns: skillColumns"></tr>
            </table>
          }
        </mat-card-content>
      </mat-card>
    }
  `,
  styles: [`
    mat-card { margin-bottom: 16px; }
    mat-card-header { display: flex; justify-content: space-between; align-items: center; }
    .empty-hint { color: var(--mat-sys-on-surface-variant); font-size: 13px; padding: 16px; text-align: center; }
    .repo-table, .skills-table { width: 100%; background: transparent; }
    .repo-url { font-family: monospace; font-size: 12px; }
    .branch-badge {
      font-size: 11px; padding: 2px 6px; border-radius: 8px; margin-left: 8px;
      background: var(--mat-sys-surface-variant); color: var(--mat-sys-on-surface-variant);
    }
    .syncing, .pending { color: var(--app-neutral, #888); font-size: 12px; }
    .error-text { color: var(--app-error, #f44336); font-size: 12px; display: flex; align-items: center; gap: 4px; }
    .error-icon { font-size: 16px; width: 16px; height: 16px; color: var(--app-error, #f44336); }
    .disabled-row { opacity: 0.5; }
    .badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 10px; }
    .badge-direct { background: var(--mat-sys-secondary-container); color: var(--mat-sys-on-secondary-container); }
    .badge-git { background: var(--mat-sys-tertiary-container); color: var(--mat-sys-on-tertiary-container); }
    .badge-bound { background: var(--mat-sys-primary-container); color: var(--mat-sys-on-primary-container); }
    .badge-unbound { background: var(--mat-sys-surface-variant); color: var(--mat-sys-on-surface-variant); }
    .binding-origin {
      margin-left: 6px;
      font-size: 11px;
      color: var(--mat-sys-on-surface-variant);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .inline-actions { display: flex; justify-content: flex-end; }
  `],
})
export class SkillsAdminComponent implements OnInit, OnDestroy {
  private readonly llmService = inject(LlmService);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);

  loading = signal(true);
  skills = signal<Skill[]>([]);
  repos = signal<SkillGitRepo[]>([]);
  mcpConfigs = signal<McpConfig[]>([]);
  syncingRepos = signal<Set<string>>(new Set());

  skillColumns = ['name', 'description', 'source', 'binding', 'enabled', 'synced', 'actions'];
  repoColumns = ['url', 'binding', 'status', 'actions'];

  private pollSubs = new Map<string, Subscription>();

  ngOnDestroy(): void {
    this.pollSubs.forEach((sub) => sub.unsubscribe());
    this.pollSubs.clear();
  }

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);

    this.llmService.listMcpConfigs().subscribe({
      next: (configs) => this.mcpConfigs.set(configs),
      error: () => this.mcpConfigs.set([]),
    });

    this.llmService.listSkillRepos().subscribe({
      next: (repos) => {
        this.repos.set(repos);
        this.llmService.listSkills().subscribe({
          next: (skills) => {
            this.skills.set(skills);
            this.loading.set(false);
          },
          error: () => this.loading.set(false),
        });
      },
      error: () => this.loading.set(false),
    });
  }

  addSkill(): void {
    const ref = this.dialog.open(AddSkillDialogComponent, { width: '560px' });
    ref.afterClosed().subscribe((result) => {
      if (result) {
        this.load();
        this.snackBar.open('Skill added', 'OK', { duration: 3000 });
      }
    });
  }

  toggleSkill(skill: Skill): void {
    this.llmService.toggleSkill(skill.id).subscribe({
      next: (updated) => {
        this.skills.update((list) => list.map((s) => (s.id === updated.id ? updated : s)));
      },
      error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
    });
  }

  deleteSkill(skill: Skill): void {
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: { title: 'Delete Skill', message: `Delete skill '${skill.name}'? This cannot be undone.` },
    });
    ref.afterClosed().subscribe((confirmed) => {
      if (!confirmed) return;
      this.llmService.deleteSkill(skill.id).subscribe({
        next: () => {
          this.skills.update((list) => list.filter((s) => s.id !== skill.id));
          this.snackBar.open(`'${skill.name}' deleted`, 'OK', { duration: 3000 });
        },
        error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
      });
    });
  }

  addRepo(): void {
    const ref = this.dialog.open(AddRepoDialogComponent, { width: '560px' });
    ref.afterClosed().subscribe((repo: SkillGitRepo | undefined) => {
      if (repo) {
        this.repos.update((list) => [...list, repo]);
        this._startPolling(repo.id);
        this.snackBar.open('Repository added — cloning in background…', 'OK', { duration: 4000 });
      }
    });
  }

  refreshRepo(repo: SkillGitRepo): void {
    this.llmService.refreshSkillRepo(repo.id).subscribe({
      next: () => {
        this._startPolling(repo.id);
        this.snackBar.open('Refresh started…', 'OK', { duration: 3000 });
      },
      error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
    });
  }

  editRepoBinding(repo: SkillGitRepo): void {
    this._editRepoBindingById(repo.id, repo.url, repo.mcp_config_id);
  }

  editSkillBinding(skill: Skill): void {
    if (skill.source === 'git') {
      if (!skill.git_repo_id) {
        this.snackBar.open('Git skill is missing its repository reference', 'OK', { duration: 5000 });
        return;
      }

      const repo = this.repos().find((r) => r.id === skill.git_repo_id);
      this._editRepoBindingById(skill.git_repo_id, repo?.url ?? skill.name, repo?.mcp_config_id ?? null);
      return;
    }

    const ref = this.dialog.open(SkillMcpBindingDialogComponent, {
      width: '520px',
      data: {
        title: 'Set MCP Binding for Skill',
        subtitle: skill.name,
        currentMcpConfigId: skill.mcp_config_id,
      },
    });

    ref.afterClosed().subscribe((mcpConfigId: string | null | undefined) => {
      if (mcpConfigId === undefined || mcpConfigId === skill.mcp_config_id) {
        return;
      }

      this.llmService.setSkillMcpServer(skill.id, mcpConfigId).subscribe({
        next: (updatedSkill) => {
          this.skills.update((list) => list.map((s) => (s.id === updatedSkill.id ? updatedSkill : s)));
          this.snackBar.open(mcpConfigId ? 'Skill bound to MCP server' : 'Skill MCP binding cleared', 'OK', {
            duration: 3000,
          });
        },
        error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
      });
    });
  }

  bindingActionTooltip(skill: Skill): string {
    return skill.source === 'git' ? 'Set MCP binding (repo-level)' : 'Set MCP binding';
  }

  mcpLabel(mcpConfigId: string | null): string {
    if (!mcpConfigId) {
      return 'unbound';
    }
    const match = this.mcpConfigs().find((cfg) => cfg.id === mcpConfigId);
    if (match) {
      return match.name;
    }
    if (mcpConfigId.length <= 12) {
      return mcpConfigId;
    }
    return `${mcpConfigId.slice(0, 8)}...`;
  }

  deleteRepo(repo: SkillGitRepo): void {
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: 'Delete Repository',
        message: `Delete '${repo.url}'? All skills from this repo will also be removed.`,
      },
    });
    ref.afterClosed().subscribe((confirmed) => {
      if (!confirmed) return;
      this.llmService.deleteSkillRepo(repo.id).subscribe({
        next: () => {
          this.repos.update((list) => list.filter((r) => r.id !== repo.id));
          this.skills.update((list) => list.filter((s) => s.git_repo_id !== repo.id));
          this.snackBar.open('Repository deleted', 'OK', { duration: 3000 });
        },
        error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
      });
    });
  }

  private _startPolling(repoId: string): void {
    this.syncingRepos.update((s) => new Set([...s, repoId]));
    this.pollSubs.get(repoId)?.unsubscribe();

    let attempts = 0;
    const MAX_ATTEMPTS = 20; // 20 × 3s = 60s max

    const sub = interval(3000)
      .pipe(
        take(MAX_ATTEMPTS),
        takeWhile(() => this.syncingRepos().has(repoId)),
      )
      .subscribe(() => {
        attempts++;
        this.llmService.getSkillRepo(repoId).subscribe({
          next: (updated) => {
            this.repos.update((list) => list.map((r) => (r.id === repoId ? updated : r)));
            if (updated.last_refreshed_at || updated.error || attempts >= MAX_ATTEMPTS) {
              this._stopPolling(repoId);
              if (updated.error) {
                this.snackBar.open(`Sync error: ${updated.error}`, 'OK', { duration: 8000 });
              } else if (updated.last_refreshed_at) {
                this.load();
                this.snackBar.open('Repository synced', 'OK', { duration: 3000 });
              }
            }
          },
          error: () => {
            this._stopPolling(repoId);
            this.snackBar.open('Failed to check sync status', 'OK', { duration: 5000 });
          },
        });
      });

    this.pollSubs.set(repoId, sub);
  }

  private _stopPolling(repoId: string): void {
    this.syncingRepos.update((s) => {
      const next = new Set(s);
      next.delete(repoId);
      return next;
    });
    this.pollSubs.get(repoId)?.unsubscribe();
    this.pollSubs.delete(repoId);
  }

  private _editRepoBindingById(repoId: string, repoLabel: string, currentMcpConfigId: string | null): void {
    const ref = this.dialog.open(SkillMcpBindingDialogComponent, {
      width: '520px',
      data: {
        title: 'Set MCP Binding for Repository',
        subtitle: repoLabel,
        currentMcpConfigId,
      },
    });

    ref.afterClosed().subscribe((mcpConfigId: string | null | undefined) => {
      if (mcpConfigId === undefined || mcpConfigId === currentMcpConfigId) {
        return;
      }

      this.llmService.setSkillRepoMcpServer(repoId, mcpConfigId).subscribe({
        next: () => {
          this.load();
          this.snackBar.open(mcpConfigId ? 'Repository bound to MCP server' : 'Repository MCP binding cleared', 'OK', {
            duration: 3000,
          });
        },
        error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
      });
    });
  }
}
