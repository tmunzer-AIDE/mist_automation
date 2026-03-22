import { Component, computed, input, output, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

export interface RestoreDiffData {
  object_type: string;
  object_name: string | null;
  object_id: string;
  target_version: number;
  target_version_id: string;
  current_version: number | null;
  current_version_id: string | null;
  is_deleted: boolean;
  changes: DiffChange[];
  summary: { added: number; removed: number; modified: number; total: number };
  warnings: string[];
  deleted_dependencies: Array<{ object_type: string; object_id: string; object_name?: string }>;
  deleted_children: Array<{ object_type: string; object_id: string; object_name?: string }>;
}

interface DiffChange {
  path: string;
  type: 'added' | 'removed' | 'modified';
  old?: unknown;
  new?: unknown;
  value?: unknown;
}

interface DiffGroup {
  key: string;
  entries: DiffChange[];
  typeCounts: Record<string, number>;
}

@Component({
  selector: 'app-restore-diff-card',
  standalone: true,
  imports: [MatIconModule, MatButtonModule],
  template: `
    <div class="restore-card">
      <!-- Header -->
      <div class="restore-header">
        <div class="restore-icon">
          <mat-icon>settings_backup_restore</mat-icon>
        </div>
        <div class="restore-title">
          <div class="restore-label">Restore confirmation</div>
          <div class="restore-object">
            {{ data().object_name || data().object_id }}
            <span class="restore-type">{{ data().object_type }}</span>
          </div>
        </div>
      </div>

      <!-- Version info -->
      <div class="version-info">
        @if (data().is_deleted) {
          <mat-icon class="version-icon">add_circle_outline</mat-icon>
          <span>Recreate deleted object from v{{ data().target_version }}</span>
        } @else if (data().summary.total === 0) {
          <mat-icon class="version-icon">check_circle_outline</mat-icon>
          <span>Version {{ data().target_version }} is identical to current</span>
        } @else {
          <mat-icon class="version-icon">compare_arrows</mat-icon>
          <span>v{{ data().current_version }} → v{{ data().target_version }}</span>
        }
      </div>

      <!-- Warnings -->
      @if (allWarnings().length > 0) {
        <div class="warnings-section">
          @for (w of allWarnings(); track $index) {
            <div class="warning-item">
              <mat-icon>warning</mat-icon>
              <span>{{ w }}</span>
            </div>
          }
        </div>
      }

      <!-- Summary badges -->
      @if (data().summary.total > 0) {
        <div class="diff-summary">
          @if (data().summary.added > 0) {
            <span class="badge badge-added">+{{ data().summary.added }} added</span>
          }
          @if (data().summary.removed > 0) {
            <span class="badge badge-removed">-{{ data().summary.removed }} removed</span>
          }
          @if (data().summary.modified > 0) {
            <span class="badge badge-modified">~{{ data().summary.modified }} modified</span>
          }
          @if (data().summary.total > data().changes.length) {
            <span class="badge badge-truncated">{{ data().summary.total - data().changes.length }} more</span>
          }
        </div>
      }

      <!-- Diff groups -->
      @if (groups().length > 0) {
        <div class="diff-list">
          @for (group of groups(); track group.key) {
            <div class="diff-group">
              <div class="diff-group-header" (click)="toggleGroup(group.key)">
                <mat-icon class="chevron">{{ isGroupExpanded(group.key) ? 'expand_more' : 'chevron_right' }}</mat-icon>
                <span class="group-key">{{ group.key }}</span>
                <span class="group-count">{{ group.entries.length }}</span>
              </div>
              @if (isGroupExpanded(group.key)) {
                <div class="diff-group-body">
                  @for (entry of group.entries; track entry.path) {
                    <div class="diff-entry">
                      <div class="diff-entry-header">
                        <span class="entry-path">{{ entrySubPath(group.key, entry.path) }}</span>
                        <span class="entry-badge" [class]="'entry-badge-' + entry.type">{{ entry.type }}</span>
                      </div>
                      <div class="diff-values">
                        @if (entry.type === 'modified') {
                          <pre class="diff-old">{{ formatValue(entry.old) }}</pre>
                          <pre class="diff-new">{{ formatValue(entry.new) }}</pre>
                        } @else {
                          <pre [class]="entry.type === 'added' ? 'diff-new' : 'diff-old'">{{ formatValue(entry.value) }}</pre>
                        }
                      </div>
                    </div>
                  }
                </div>
              }
            </div>
          }
        </div>
      }

      <!-- Actions -->
      <div class="restore-actions">
        <button mat-flat-button color="primary" (click)="accepted.emit()">
          <mat-icon>settings_backup_restore</mat-icon>
          Restore
        </button>
        <button mat-stroked-button (click)="declined.emit()">Cancel</button>
      </div>
    </div>
  `,
  styles: [
    `
      .restore-card {
        margin: 0 4px;
        border-radius: 12px;
        border: 1px solid var(--app-info-bg, #e3f2fd);
        background: var(--mat-sys-surface-container, #f5f5f5);
        overflow: hidden;
        animation: restore-in 200ms ease-out;
      }

      @keyframes restore-in {
        from {
          opacity: 0;
          transform: translateY(8px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }

      .restore-header {
        display: flex;
        gap: 10px;
        padding: 12px 14px;
        align-items: flex-start;
      }

      .restore-icon {
        flex-shrink: 0;
        width: 32px;
        height: 32px;
        border-radius: 50%;
        background: var(--app-info-bg, #e3f2fd);
        color: var(--app-info, #1976d2);
        display: flex;
        align-items: center;
        justify-content: center;
        mat-icon {
          font-size: 18px;
          width: 18px;
          height: 18px;
        }
      }

      .restore-title {
        flex: 1;
        min-width: 0;
      }

      .restore-label {
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--app-info, #1976d2);
      }

      .restore-object {
        font-size: 14px;
        font-weight: 500;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .restore-type {
        font-size: 11px;
        font-weight: 400;
        color: var(--app-neutral);
        margin-left: 6px;
      }

      .version-info {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 0 14px 8px;
        font-size: 13px;
        color: var(--app-neutral);

        .version-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
        }
      }

      .warnings-section {
        padding: 0 14px 8px;
      }

      .warning-item {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        color: var(--app-warning, #e65100);
        padding: 4px 8px;
        border-radius: 6px;
        background: var(--app-warning-bg, #fff3cd);
        margin-bottom: 4px;

        mat-icon {
          font-size: 14px;
          width: 14px;
          height: 14px;
          flex-shrink: 0;
        }

        span {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
      }

      .diff-summary {
        display: flex;
        gap: 6px;
        padding: 0 14px 8px;
        flex-wrap: wrap;
      }

      .badge {
        font-size: 11px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 10px;
      }

      .badge-added {
        background: var(--app-success-bg, #e8f5e9);
        color: var(--app-success, #2e7d32);
      }
      .badge-removed {
        background: var(--app-error-bg, #fbe9e7);
        color: var(--app-error, #c62828);
      }
      .badge-modified {
        background: var(--app-info-bg, #e3f2fd);
        color: var(--app-info, #1976d2);
      }
      .badge-truncated {
        background: rgba(128, 128, 128, 0.12);
        color: var(--app-neutral);
      }

      .diff-list {
        max-height: 250px;
        overflow-y: auto;
        border-top: 1px solid rgba(128, 128, 128, 0.15);
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.3) transparent;
      }

      .diff-group-header {
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 6px 14px;
        cursor: pointer;
        font-size: 13px;
        font-weight: 500;
        border-bottom: 1px solid rgba(128, 128, 128, 0.1);

        &:hover {
          background: rgba(128, 128, 128, 0.06);
        }

        .chevron {
          font-size: 18px;
          width: 18px;
          height: 18px;
          color: var(--app-neutral);
        }

        .group-key {
          flex: 1;
          font-family: monospace;
        }

        .group-count {
          font-size: 11px;
          color: var(--app-neutral);
          background: rgba(128, 128, 128, 0.12);
          padding: 1px 6px;
          border-radius: 8px;
        }
      }

      .diff-group-body {
        padding-left: 10px;
      }

      .diff-entry-header {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 4px 14px 0;
        font-size: 12px;

        .entry-path {
          flex: 1;
          font-family: monospace;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .entry-badge {
          font-size: 10px;
          font-weight: 600;
          padding: 1px 5px;
          border-radius: 4px;
          flex-shrink: 0;
        }

        .entry-badge-added {
          background: var(--app-success-bg, #e8f5e9);
          color: var(--app-success, #2e7d32);
        }
        .entry-badge-removed {
          background: var(--app-error-bg, #fbe9e7);
          color: var(--app-error, #c62828);
        }
        .entry-badge-modified {
          background: var(--app-info-bg, #e3f2fd);
          color: var(--app-info, #1976d2);
        }
      }

      .diff-values {
        padding: 4px 14px 4px 28px;

        pre {
          font-size: 11px;
          margin: 2px 0;
          padding: 4px 8px;
          border-radius: 4px;
          white-space: pre-wrap;
          word-break: break-all;
          max-height: 80px;
          overflow-y: auto;
        }
      }

      .diff-old {
        background: var(--app-error-bg, #fbe9e7);
        color: var(--app-error, #c62828);
      }

      .diff-new {
        background: var(--app-success-bg, #e8f5e9);
        color: var(--app-success, #2e7d32);
      }

      .restore-actions {
        display: flex;
        gap: 8px;
        padding: 10px 14px;
        border-top: 1px solid rgba(128, 128, 128, 0.15);

        button {
          font-size: 13px;
          height: 32px;
        }

        mat-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
          margin-right: 4px;
        }
      }
    `,
  ],
})
export class RestoreDiffCardComponent {
  data = input.required<RestoreDiffData>();
  description = input('');

  accepted = output<void>();
  declined = output<void>();

  expandedGroups = signal<Set<string>>(new Set());

  groups = computed<DiffGroup[]>(() => {
    const changes = this.data().changes;
    const groupMap = new Map<string, DiffChange[]>();
    for (const entry of changes) {
      const key = entry.path.includes('.') ? entry.path.split('.')[0] : entry.path;
      const list = groupMap.get(key) ?? [];
      list.push(entry);
      groupMap.set(key, list);
    }
    return Array.from(groupMap.entries()).map(([key, entries]) => {
      const typeCounts: Record<string, number> = {};
      for (const e of entries) {
        typeCounts[e.type] = (typeCounts[e.type] ?? 0) + 1;
      }
      return { key, entries, typeCounts };
    });
  });

  allWarnings = computed<string[]>(() => {
    const d = this.data();
    const warnings = [...d.warnings];
    for (const dep of d.deleted_dependencies) {
      warnings.push(`Dependency deleted: ${dep.object_type} '${dep.object_name || dep.object_id}'`);
    }
    for (const child of d.deleted_children) {
      warnings.push(`Child deleted: ${child.object_type} '${child.object_name || child.object_id}'`);
    }
    return warnings;
  });

  toggleGroup(key: string): void {
    this.expandedGroups.update((set) => {
      const next = new Set(set);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  isGroupExpanded(key: string): boolean {
    return this.expandedGroups().has(key);
  }

  entrySubPath(groupKey: string, fullPath: string): string {
    return fullPath.startsWith(groupKey + '.') ? fullPath.slice(groupKey.length + 1) : fullPath;
  }

  formatValue(value: unknown): string {
    if (value === null || value === undefined) return 'null';
    if (typeof value === 'string') return value;
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }
}
