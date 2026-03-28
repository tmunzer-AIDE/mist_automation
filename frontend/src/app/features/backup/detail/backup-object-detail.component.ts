import { Component, DestroyRef, inject, OnInit, signal, computed } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NgClass, SlicePipe } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatMenuModule } from '@angular/material/menu';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ApiService } from '../../../core/services/api.service';
import { LlmService } from '../../../core/services/llm.service';
import { GlobalChatService } from '../../../core/services/global-chat.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { ObjectDependencyResponse } from '../../../core/models/backup.model';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { AiIconComponent } from '../../../shared/components/ai-icon/ai-icon.component';
import { AiSummaryPanelComponent } from '../../../shared/components/ai-summary-panel/ai-summary-panel.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { extractErrorMessage } from '../../../shared/utils/error.utils';
import { JsonViewDialogComponent } from './json-view-dialog.component';
import { CascadeRestoreDialogComponent } from './cascade-restore-dialog.component';

interface ObjectVersion {
  id: string;
  object_id: string;
  object_type: string;
  object_name: string | null;
  org_id: string;
  site_id: string | null;
  version: number;
  event_type: string;
  changed_fields: string[];
  backed_up_at: string;
  backed_up_by: string | null;
  is_deleted: boolean;
  configuration: Record<string, unknown>;
}

interface DiffEntry {
  path: string;
  type: string;
  oldValue?: unknown;
  newValue?: unknown;
}

interface DiffGroup {
  key: string;
  entries: DiffEntry[];
  typeCounts: Record<string, number>;
  isGroup: boolean;
}

@Component({
  selector: 'app-backup-object-detail',
  standalone: true,
  imports: [
    NgClass,
    SlicePipe,
    RouterModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatTableModule,
    MatChipsModule,
    MatTooltipModule,
    MatMenuModule,
    MatExpansionModule,
    MatDialogModule,
    MatSnackBarModule,
    EmptyStateComponent,
    StatusBadgeComponent,
    AiIconComponent,
    AiSummaryPanelComponent,
    DateTimePipe,
  ],
  templateUrl: './backup-object-detail.component.html',
  styleUrl: './backup-object-detail.component.scss',
})
export class BackupObjectDetailComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly llmService = inject(LlmService);
  private readonly globalChatService = inject(GlobalChatService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly topbarService = inject(TopbarService);
  private readonly destroyRef = inject(DestroyRef);

  objectId = '';
  versions = signal<ObjectVersion[]>([]);
  loading = signal(true);

  // AI Summary
  llmAvailable = signal(false);
  aiThreadId = signal<string | null>(null);
  aiSummary = signal<string | null>(null);
  aiError = signal<string | null>(null);
  aiPanelOpen = signal(false);
  aiLoading = signal(false);
  selectedVersionId = signal<string | null>(null);
  dependencies = signal<ObjectDependencyResponse | null>(null);
  depsLoading = signal(true);

  // Compare mode
  compareMode = signal(false);
  compareVersions = signal<[ObjectVersion | null, ObjectVersion | null]>([null, null]);
  diffEntries = signal<DiffEntry[]>([]);
  activeFilters = signal<Set<string>>(new Set());
  expandedGroups = signal<Set<string>>(new Set());
  expandedEntries = signal<Set<string>>(new Set());

  diffTypeCounts = computed<Record<string, number>>(() => {
    const counts: Record<string, number> = { added: 0, removed: 0, modified: 0 };
    for (const entry of this.diffEntries()) {
      counts[entry.type] = (counts[entry.type] ?? 0) + 1;
    }
    return counts;
  });

  diffGroups = computed<DiffGroup[]>(() => {
    const entries = this.diffEntries();
    if (entries.length === 0) return [];

    const groupMap = new Map<string, DiffEntry[]>();
    for (const entry of entries) {
      const dotIndex = entry.path.indexOf('.');
      const key = dotIndex === -1 ? entry.path : entry.path.substring(0, dotIndex);
      const list = groupMap.get(key) ?? [];
      list.push(entry);
      groupMap.set(key, list);
    }

    const result: DiffGroup[] = [];
    const seen = new Set<string>();
    for (const entry of entries) {
      const dotIndex = entry.path.indexOf('.');
      const key = dotIndex === -1 ? entry.path : entry.path.substring(0, dotIndex);
      if (seen.has(key)) continue;
      seen.add(key);
      const groupEntries = groupMap.get(key)!;
      const typeCounts: Record<string, number> = {};
      for (const e of groupEntries) {
        typeCounts[e.type] = (typeCounts[e.type] ?? 0) + 1;
      }
      result.push({
        key,
        entries: groupEntries,
        typeCounts,
        isGroup: groupEntries.length > 1 || (groupEntries.length === 1 && groupEntries[0].path.includes('.')),
      });
    }
    return result;
  });

  filteredGroups = computed<DiffGroup[]>(() => {
    const filters = this.activeFilters();
    const groups = this.diffGroups();
    if (filters.size === 0) return groups;

    return groups
      .map((group) => {
        const filtered = group.entries.filter((e) => filters.has(e.type));
        if (filtered.length === 0) return null;
        const typeCounts: Record<string, number> = {};
        for (const e of filtered) {
          typeCounts[e.type] = (typeCounts[e.type] ?? 0) + 1;
        }
        return { ...group, entries: filtered, typeCounts };
      })
      .filter((g): g is DiffGroup => g !== null);
  });

  filteredCount = computed(() =>
    this.filteredGroups().reduce((sum, g) => sum + g.entries.length, 0),
  );

  allExpanded = computed(() => {
    const groups = this.filteredGroups();
    if (groups.length === 0) return false;
    const expandedG = this.expandedGroups();
    const expandedE = this.expandedEntries();
    return groups.every((g) => {
      if (g.isGroup) {
        if (!expandedG.has(g.key)) return false;
        return g.entries.every((e) => expandedE.has(e.path));
      }
      return expandedE.has(g.entries[0].path);
    });
  });

  versionColumns = ['version', 'date', 'admin', 'event_type', 'changed_fields', 'actions'];

  latestVersion = computed(() => {
    const v = this.versions();
    return v.length > 0 ? v[0] : null;
  });

  oldestVersion = computed(() => {
    const v = this.versions();
    return v.length > 0 ? v[v.length - 1] : null;
  });

  ngOnInit(): void {
    this.topbarService.setTitle('Object Detail');
    this.llmService.getStatus().subscribe({
      next: (s) => this.llmAvailable.set(s.enabled),
      error: () => this.llmAvailable.set(false),
    });
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('objectId') || '';
      if (id !== this.objectId) {
        this.objectId = id;
        this.resetState();
        this.loadVersions();
        this.loadDependencies();
      }
    });
  }

  private resetState(): void {
    this.versions.set([]);
    this.loading.set(true);
    this.selectedVersionId.set(null);
    this.dependencies.set(null);
    this.depsLoading.set(true);
    this.compareMode.set(false);
    this.compareVersions.set([null, null]);
    this.aiThreadId.set(null);
    this.aiPanelOpen.set(false);
    this.diffEntries.set([]);
    this.activeFilters.set(new Set());
    this.expandedGroups.set(new Set());
    this.expandedEntries.set(new Set());
  }

  eventLabel(eventType: string): string {
    const labels: Record<string, string> = {
      full_backup: 'Full Backup',
      incremental: 'Incremental',
      created: 'Created',
      updated: 'Updated',
      deleted: 'Deleted',
      restored: 'Restored',
    };
    return labels[eventType] || eventType;
  }

  onRowClick(v: ObjectVersion): void {
    if (this.compareMode()) {
      this.toggleCompareVersion(v);
    }
  }

  viewJson(v: ObjectVersion): void {
    this.dialog.open(JsonViewDialogComponent, {
      width: '700px',
      maxHeight: '80vh',
      data: {
        title: `${v.object_name || v.object_id} — v${v.version}`,
        json: v.configuration,
      },
    });
  }

  restoreVersion(v: ObjectVersion): void {
    const ref = this.dialog.open(CascadeRestoreDialogComponent, {
      width: '600px',
      maxHeight: '80vh',
      data: {
        versionId: v.id,
        objectName: v.object_name || v.object_id,
        objectType: v.object_type,
        isDeleted: v.is_deleted,
      },
    });
    ref.afterClosed().subscribe((result) => {
      if (result?.restored) {
        if (result.newObjectId && result.newObjectId !== this.objectId) {
          this.router.navigate(['/backup/object', result.newObjectId]);
        } else {
          this.loadVersions();
          this.loadDependencies();
        }
      }
    });
  }

  toggleCompareMode(): void {
    this.compareMode.set(!this.compareMode());
    if (!this.compareMode()) {
      this.compareVersions.set([null, null]);
      this.diffEntries.set([]);
      this.activeFilters.set(new Set());
      this.expandedGroups.set(new Set());
      this.expandedEntries.set(new Set());
    }
  }

  toggleCompareVersion(v: ObjectVersion): void {
    if (!this.compareMode()) return;
    const cv = this.compareVersions();

    // If already selected, deselect
    if (cv[0]?.id === v.id) {
      this.compareVersions.set([cv[1], null]);
      this.diffEntries.set([]);
      return;
    }
    if (cv[1]?.id === v.id) {
      this.compareVersions.set([cv[0], null]);
      this.diffEntries.set([]);
      return;
    }

    // Add to selection
    if (!cv[0]) {
      this.compareVersions.set([v, null]);
    } else {
      this.compareVersions.set([cv[0], v]);
      this.computeDiff();
    }
  }

  isCompareSelected(v: ObjectVersion): boolean {
    const cv = this.compareVersions();
    return cv[0]?.id === v.id || cv[1]?.id === v.id;
  }

  compareLabel(v: ObjectVersion): string | null {
    const cv = this.compareVersions();
    if (cv[0]?.id === v.id) return 'A';
    if (cv[1]?.id === v.id) return 'B';
    return null;
  }

  private computeDiff(): void {
    const [a, b] = this.compareVersions();
    if (!a || !b) return;
    // Order so that older version is on the left
    const older = a.version < b.version ? a : b;
    const newer = a.version < b.version ? b : a;
    this.compareVersions.set([older, newer]);
    this.diffEntries.set(this.deepDiff(older.configuration, newer.configuration));
    this.activeFilters.set(new Set());
    this.expandedGroups.set(new Set());
    this.expandedEntries.set(new Set());
  }

  private deepDiff(
    a: Record<string, unknown>,
    b: Record<string, unknown>,
    path = '',
  ): DiffEntry[] {
    const result: DiffEntry[] = [];
    const allKeys = new Set([...Object.keys(a), ...Object.keys(b)]);

    for (const key of allKeys) {
      const p = path ? `${path}.${key}` : key;
      if (!(key in a)) {
        result.push({ path: p, type: 'added', newValue: b[key] });
      } else if (!(key in b)) {
        result.push({ path: p, type: 'removed', oldValue: a[key] });
      } else if (
        typeof a[key] === 'object' &&
        a[key] !== null &&
        !Array.isArray(a[key]) &&
        typeof b[key] === 'object' &&
        b[key] !== null &&
        !Array.isArray(b[key])
      ) {
        result.push(
          ...this.deepDiff(a[key] as Record<string, unknown>, b[key] as Record<string, unknown>, p),
        );
      } else if (JSON.stringify(a[key]) !== JSON.stringify(b[key])) {
        result.push({ path: p, type: 'modified', oldValue: a[key], newValue: b[key] });
      }
    }
    return result;
  }

  toggleFilter(type: string): void {
    const current = new Set(this.activeFilters());
    if (current.has(type)) {
      current.delete(type);
    } else {
      current.add(type);
    }
    this.activeFilters.set(current);
  }

  toggleGroup(key: string): void {
    const current = new Set(this.expandedGroups());
    if (current.has(key)) {
      current.delete(key);
    } else {
      current.add(key);
    }
    this.expandedGroups.set(current);
  }

  toggleEntry(path: string): void {
    const current = new Set(this.expandedEntries());
    if (current.has(path)) {
      current.delete(path);
    } else {
      current.add(path);
    }
    this.expandedEntries.set(current);
  }

  toggleExpandAll(): void {
    if (this.allExpanded()) {
      this.expandedGroups.set(new Set());
      this.expandedEntries.set(new Set());
    } else {
      const groups = new Set(this.filteredGroups().map((g) => g.key));
      const entries = new Set(this.filteredGroups().flatMap((g) => g.entries.map((e) => e.path)));
      this.expandedGroups.set(groups);
      this.expandedEntries.set(entries);
    }
  }

  isGroupExpanded(key: string): boolean {
    return this.expandedGroups().has(key);
  }

  isEntryExpanded(path: string): boolean {
    return this.expandedEntries().has(path);
  }

  stripGroupPrefix(path: string, groupKey: string): string {
    return path.startsWith(groupKey + '.') ? path.substring(groupKey.length + 1) : path;
  }

  formatValue(val: unknown): string {
    if (val === undefined || val === null) return '—';
    if (typeof val === 'string') return val;
    return JSON.stringify(val, null, 2);
  }

  private loadDependencies(): void {
    this.depsLoading.set(true);
    this.api
      .get<ObjectDependencyResponse>(`/backups/objects/${this.objectId}/dependencies`)
      .subscribe({
        next: (res) => {
          this.dependencies.set(res);
          this.depsLoading.set(false);
        },
        error: () => {
          this.depsLoading.set(false);
        },
      });
  }

  private loadVersions(): void {
    this.loading.set(true);
    this.api
      .get<{
        versions: ObjectVersion[];
        total: number;
      }>(`/backups/objects/${this.objectId}/versions`)
      .subscribe({
        next: (res) => {
          this.versions.set(res.versions);
          this.loading.set(false);
          const latest = res.versions[0];
          if (latest) {
            this.globalChatService.setContext({
              page: 'Backup Object Detail',
              details: {
                object_type: latest.object_type,
                object_name: latest.object_name,
                object_id: latest.object_id,
                versions: res.total,
                scope: latest.site_id ? 'site' : 'org',
              },
            });
          }
        },
        error: () => {
          this.loading.set(false);
        },
      });
  }

  // ── AI Summary ──────────────────────────────────────────────────────────

  summarizeChanges(): void {
    const v0 = this.compareVersions()[0];
    const v1 = this.compareVersions()[1];
    if (!v0 || !v1) return;

    this.aiPanelOpen.set(true);
    this.aiLoading.set(true);
    this.aiSummary.set(null);
    this.aiError.set(null);

    this.llmService.summarizeDiff(v0.id, v1.id).subscribe({
      next: (res) => {
        this.aiThreadId.set(res.thread_id);
        this.aiSummary.set(res.summary);
        this.aiLoading.set(false);
      },
      error: (err) => {
        this.aiError.set(extractErrorMessage(err));
        this.aiLoading.set(false);
      },
    });
  }
}
