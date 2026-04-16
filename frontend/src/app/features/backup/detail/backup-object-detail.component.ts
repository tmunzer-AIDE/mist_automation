import { Component, DestroyRef, ElementRef, inject, OnInit, ViewChild, signal, computed } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NgClass, SlicePipe } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { ApiService } from '../../../core/services/api.service';
import { LlmService } from '../../../core/services/llm.service';
import { GlobalChatService } from '../../../core/services/global-chat.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { ObjectDependencyResponse } from '../../../core/models/backup.model';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { AiInlineAnalysisComponent } from '../../../shared/components/ai-inline-analysis/ai-inline-analysis.component';
import { AiAnalysisResultComponent } from '../../../shared/components/ai-inline-analysis/ai-analysis-result.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { extractErrorMessage } from '../../../shared/utils/error.utils';
import { JsonViewDialogComponent } from './json-view-dialog.component';
import { CascadeRestoreDialogComponent } from './cascade-restore-dialog.component';
import { SimulateRestoreDialogComponent } from './simulate-restore-dialog.component';

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

interface TimelineBubble {
  version: ObjectVersion;
  left: number;     // 0–100 (%)
  diameter: number; // 8–28 (px)
}

@Component({
  selector: 'app-backup-object-detail',
  standalone: true,
  imports: [
    NgClass,
    SlicePipe,
    RouterModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatTooltipModule,
    MatExpansionModule,
    MatDialogModule,
    EmptyStateComponent,
    StatusBadgeComponent,
    AiInlineAnalysisComponent,
    AiAnalysisResultComponent,
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
  private readonly topbarService = inject(TopbarService);
  private readonly destroyRef = inject(DestroyRef);

  objectId = '';
  versions = signal<ObjectVersion[]>([]);
  loading = signal(true);

  // A/B pins for comparison
  pinA = signal<ObjectVersion | null>(null);
  pinB = signal<ObjectVersion | null>(null);

  /** Tracks the actual timeline track element width via ResizeObserver. Defaults to 800 until mounted. */
  timelineContainerWidth = signal(800);
  private timelineResizeObserver: ResizeObserver | null = null;

  /**
   * Setter-based ViewChild: fires whenever the conditional #timelineTrackArea element
   * enters or leaves the DOM, so the ResizeObserver is always attached to the live element.
   */
  @ViewChild('timelineTrackArea')
  private set timelineTrackEl(el: ElementRef<HTMLElement> | undefined) {
    this.timelineResizeObserver?.disconnect();
    if (el) {
      this.timelineResizeObserver = new ResizeObserver((entries) => {
        const width = entries[0]?.contentRect.width;
        if (width) this.timelineContainerWidth.set(width);
      });
      this.timelineResizeObserver.observe(el.nativeElement);
    }
  }

  // AI Summary
  llmAvailable = signal(false);
  aiThreadId = signal<string | null>(null);
  aiSummary = signal<string | null>(null);
  aiError = signal<string | null>(null);
  aiLoading = signal(false);
  aiExpanded = signal(true);
  aiHasContent = computed(() => !!this.aiSummary() || !!this.aiError() || this.aiLoading());

  dependencies = signal<ObjectDependencyResponse | null>(null);
  depsLoading = signal(true);

  // Diff state
  diffEntries = signal<DiffEntry[]>([]);
  activeFilters = signal<Set<string>>(new Set());
  expandedGroups = signal<Set<string>>(new Set());
  expandedEntries = signal<Set<string>>(new Set());

  // ── Computed ──────────────────────────────────────────────────────────────

  latestVersion = computed(() => {
    const v = this.versions();
    return v.length > 0 ? v[0] : null;
  });

  oldestVersion = computed(() => {
    const v = this.versions();
    return v.length > 0 ? v[v.length - 1] : null;
  });

  firstSeenAt = computed<string | null>(() => {
    const versions = this.versions();
    if (versions.length === 0) return null;

    let earliest = this.toUtcMs(versions[0].backed_up_at);
    let earliestRaw = versions[0].backed_up_at;

    for (let i = 1; i < versions.length; i++) {
      const currentRaw = versions[i].backed_up_at;
      const current = this.toUtcMs(currentRaw);
      if (current < earliest) {
        earliest = current;
        earliestRaw = currentRaw;
      }
    }

    return earliestRaw;
  });

  maxChanges = computed(() => {
    const counts = this.versions().map((v) => v.changed_fields.length);
    return Math.max(1, ...counts);
  });

  daysBetweenPins = computed<number | null>(() => {
    const a = this.pinA();
    const b = this.pinB();
    if (!a || !b) return null;
    const ms = Math.abs(
      this.toUtcMs(b.backed_up_at) - this.toUtcMs(a.backed_up_at),
    );
    return Math.round(ms / (1000 * 60 * 60 * 24));
  });

  /**
   * Per-bubble position + size for the sparkline timeline.
   * Positions are time-proportional with a minimum 20px gap between adjacent bubbles.
   */
  timelineBubbles = computed<TimelineBubble[]>(() => {
    const versions = this.versions();
    if (versions.length === 0) return [];

    // Timeline goes oldest -> newest (left -> right) using backup timestamp, not version number.
    const sorted = [...versions].sort((a, b) => {
      const delta = this.toUtcMs(a.backed_up_at) - this.toUtcMs(b.backed_up_at);
      return delta !== 0 ? delta : a.version - b.version;
    });

    const earliest = this.toUtcMs(sorted[0].backed_up_at);
    const latest = this.toUtcMs(sorted[sorted.length - 1].backed_up_at);
    const range = latest - earliest;

    // Raw proportional positions
    const positions: number[] = sorted.map((v) =>
      range === 0 ? 50 : ((this.toUtcMs(v.backed_up_at) - earliest) / range) * 100,
    );

    // Enforce minimum 20px gap between adjacent bubbles.
    // We work in % space: use the component's tracked container width (pixels) to convert.
    // containerWidth defaults to 800px (a safe lower bound) until a resize is observed.
    const minGapPct = (20 / this.timelineContainerWidth()) * 100;
    for (let i = 1; i < positions.length; i++) {
      if (positions[i] - positions[i - 1] < minGapPct) {
        positions[i] = positions[i - 1] + minGapPct;
      }
    }

    // Scale back if the last position overflowed past 100%
    const maxLeft = positions[positions.length - 1];
    if (maxLeft > 100) {
      const scale = 100 / maxLeft;
      for (let i = 0; i < positions.length; i++) positions[i] *= scale;
      // Re-enforce min gap after scaling: scaling shrinks all gaps proportionally,
      // which can violate the constraint again. Clamp at 100% instead of overflowing.
      for (let i = 1; i < positions.length; i++) {
        if (positions[i] - positions[i - 1] < minGapPct) {
          positions[i] = Math.min(positions[i - 1] + minGapPct, 100);
        }
      }
    }

    return sorted.map((v, i) => ({
      version: v,
      left: positions[i],
      diameter: Math.min(28, Math.max(8, 8 + v.changed_fields.length * 2)),
    }));
  });

  /**
   * Left/right % positions of the gradient connector between A and B pins.
   * Returns null when fewer than 2 pins are set.
   */
  timelineConnector = computed<{ left: number; right: number } | null>(() => {
    const a = this.pinA();
    const b = this.pinB();
    const bubbles = this.timelineBubbles();
    if (!a || !b) return null;
    const bA = bubbles.find((bub) => bub.version.id === a.id);
    const bB = bubbles.find((bub) => bub.version.id === b.id);
    if (!bA || !bB) return null;
    return {
      left: Math.min(bA.left, bB.left),
      right: 100 - Math.max(bA.left, bB.left),
    };
  });

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
        isGroup:
          groupEntries.length > 1 ||
          (groupEntries.length === 1 && groupEntries[0].path.includes('.')),
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
        for (const e of filtered) typeCounts[e.type] = (typeCounts[e.type] ?? 0) + 1;
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

  /** Versions that should render the full row: the 3 newest + any pinned. */
  fullRowIds = computed<Set<string>>(() => {
    const ids = new Set<string>();
    this.versions()
      .slice(0, 3)
      .forEach((v) => ids.add(v.id));
    const a = this.pinA();
    const b = this.pinB();
    if (a) ids.add(a.id);
    if (b) ids.add(b.id);
    return ids;
  });

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  ngOnInit(): void {
    this.destroyRef.onDestroy(() => this.timelineResizeObserver?.disconnect());
    this.topbarService.setTitle('Object Detail');
    this.llmService
      .getStatus()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
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
    this.pinA.set(null);
    this.pinB.set(null);
    this.dependencies.set(null);
    this.depsLoading.set(true);
    this.aiThreadId.set(null);
    this.aiSummary.set(null);
    this.aiError.set(null);
    this.diffEntries.set([]);
    this.activeFilters.set(new Set());
    this.expandedGroups.set(new Set());
    this.expandedEntries.set(new Set());
  }

  // ── Pin interaction ───────────────────────────────────────────────────────

  /**
   * Pin cycle:
   * - Click A → clear A (and diff)
   * - Click B → clear B (and diff)
   * - No A set → set A; if B already pinned, compute diff immediately
   * - A set, no B → set B, compute diff
   * - Both set → replace A, compute diff (pins reorder to oldest→newest)
   */
  pinVersion(v: ObjectVersion): void {
    const a = this.pinA();
    const b = this.pinB();

    if (a?.id === v.id) {
      this.pinA.set(null);
      this.diffEntries.set([]);
      return;
    }
    if (b?.id === v.id) {
      this.pinB.set(null);
      this.diffEntries.set([]);
      return;
    }
    if (!a) {
      this.pinA.set(v);
      if (b) this.computeDiff(); // B already pinned — compute diff right away
      return;
    }
    if (!b) {
      this.pinB.set(v);
      this.computeDiff();
      return;
    }
    // Both set: replace A
    this.pinA.set(v);
    this.computeDiff();
  }

  private computeDiff(): void {
    const a = this.pinA();
    const b = this.pinB();
    if (!a || !b) {
      this.diffEntries.set([]);
      return;
    }
    // Always diff older → newer
    const older = a.version < b.version ? a : b;
    const newer = a.version < b.version ? b : a;
    this.pinA.set(older);
    this.pinB.set(newer);
    this.diffEntries.set(this.deepDiff(older.configuration, newer.configuration));
    this.activeFilters.set(new Set());
    this.expandedGroups.set(new Set());
    this.expandedEntries.set(new Set());
    // Clear stale AI summary from the previous pin pair
    this.aiThreadId.set(null);
    this.aiSummary.set(null);
    this.aiError.set(null);
    this.aiLoading.set(false);
  }

  // ── Actions ───────────────────────────────────────────────────────────────

  goBack(): void {
    this.router.navigate(['/backup']);
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
    ref.afterClosed().pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
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

  /** Simulate rollback: runs the Digital Twin pre-check and shows the result. */
  simulateRestore(v: ObjectVersion): void {
    this.dialog.open(SimulateRestoreDialogComponent, {
      width: '520px',
      maxHeight: '80vh',
      data: {
        versionId: v.id,
        objectName: v.object_name || v.object_id,
        objectType: v.object_type,
      },
    });
  }

  // ── Diff helpers ─────────────────────────────────────────────────────────

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
          ...this.deepDiff(
            a[key] as Record<string, unknown>,
            b[key] as Record<string, unknown>,
            p,
          ),
        );
      } else if (JSON.stringify(a[key]) !== JSON.stringify(b[key])) {
        result.push({ path: p, type: 'modified', oldValue: a[key], newValue: b[key] });
      }
    }
    return result;
  }

  /** Parse a backend datetime string as UTC millis. Appends 'Z' if no timezone indicator is present. */
  private toUtcMs(value: string): number {
    const utc = /[Zz]$/.test(value) || /[+-]\d{2}:\d{2}$/.test(value) ? value : value + 'Z';
    return new Date(utc).getTime();
  }

  toggleFilter(type: string): void {
    const current = new Set(this.activeFilters());
    if (current.has(type)) current.delete(type);
    else current.add(type);
    this.activeFilters.set(current);
  }

  toggleGroup(key: string): void {
    const current = new Set(this.expandedGroups());
    if (current.has(key)) current.delete(key);
    else current.add(key);
    this.expandedGroups.set(current);
  }

  toggleEntry(path: string): void {
    const current = new Set(this.expandedEntries());
    if (current.has(path)) current.delete(path);
    else current.add(path);
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

  isGroupExpanded(key: string): boolean { return this.expandedGroups().has(key); }
  isEntryExpanded(path: string): boolean { return this.expandedEntries().has(path); }

  stripGroupPrefix(path: string, groupKey: string): string {
    return path.startsWith(groupKey + '.') ? path.substring(groupKey.length + 1) : path;
  }

  formatValue(val: unknown): string {
    if (val === undefined || val === null) return '—';
    if (typeof val === 'string') return val;
    return JSON.stringify(val, null, 2);
  }

  // ── Data loading ──────────────────────────────────────────────────────────

  private loadVersions(): void {
    this.loading.set(true);
    this.api
      .get<{ versions: ObjectVersion[]; total: number }>(
        `/backups/objects/${this.objectId}/versions`,
      )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.versions.set(res.versions);
          this.loading.set(false);
          // Default: B = latest, A = previous
          if (res.versions.length >= 2) {
            this.pinB.set(res.versions[0]);
            this.pinA.set(res.versions[1]);
            this.computeDiff();
          } else if (res.versions.length === 1) {
            this.pinB.set(res.versions[0]);
          }
          const latest = res.versions[0];
          if (latest) {
            this.topbarService.setTitle(
              `${latest.object_type}: ${latest.object_name || latest.object_id}`,
            );
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
        error: () => this.loading.set(false),
      });
  }

  private loadDependencies(): void {
    this.depsLoading.set(true);
    this.api
      .get<ObjectDependencyResponse>(`/backups/objects/${this.objectId}/dependencies`)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.dependencies.set(res);
          this.depsLoading.set(false);
        },
        error: () => this.depsLoading.set(false),
      });
  }

  // ── AI Summary ────────────────────────────────────────────────────────────

  summarizeChanges(): void {
    const v0 = this.pinA();
    const v1 = this.pinB();
    if (!v0 || !v1) return;

    this.aiLoading.set(true);
    this.aiSummary.set(null);
    this.aiError.set(null);

    this.llmService.summarizeDiff(v0.id, v1.id).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
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
