# Backup Object Time Travel View — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework `backup-object-detail` to a three-zone time-travel layout: compact object header, time-proportional sparkline timeline, and a persistent split view (version list with A/B pins + rollback actions on the left; always-visible diff panel on the right).

**Architecture:** Replace the current mat-table + compare-mode toggle with signal-based A/B pin state. A `timelineBubbles` computed derives per-bubble positions (time-proportional, min-spacing guarantee) and sizes (change count). `computeDiff()` fires whenever both pins are set. Default on load: B = latest, A = previous.

**Tech Stack:** Angular 21 signals/computed, standalone components, CSS custom properties, existing `deepDiff()` / `CascadeRestoreDialogComponent` / `JsonViewDialogComponent` reused as-is.

> **Implementation note:** The Simulate action was shipped as a dedicated `SimulateRestoreDialogComponent` (not `CascadeRestoreDialogComponent`). It calls `POST /backups/objects/versions/{id}/restore?simulate=true` and shows the `RestoreSimulationResponse` in a step-machine dialog (`confirm → loading → result | error`). The plan tasks below predated this decision.

---

## Files

| File | Change |
|---|---|
| `frontend/src/app/features/backup/detail/backup-object-detail.component.ts` | Full rework: remove compare mode, add pin signals + timeline computed + pin interaction |
| `frontend/src/app/features/backup/detail/backup-object-detail.component.html` | Full rework: three-zone layout |
| `frontend/src/app/features/backup/detail/backup-object-detail.component.scss` | Full rework: timeline, split layout, version rows; keep diff-entry styles |

No backend changes. All API endpoints already exist.

---

## Task 1: Rework component TypeScript

**Files:**
- Modify: `frontend/src/app/features/backup/detail/backup-object-detail.component.ts`

- [ ] **Step 1: Replace the entire component TypeScript with the new version**

Replace the full file with:

```typescript
import { Component, DestroyRef, HostListener, inject, OnInit, signal, computed } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NgClass, SlicePipe } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
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
import { AiInlineAnalysisComponent } from '../../../shared/components/ai-inline-analysis/ai-inline-analysis.component';
import { AiAnalysisResultComponent } from '../../../shared/components/ai-inline-analysis/ai-analysis-result.component';
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

interface TimelineBubble {
  version: ObjectVersion;
  left: number;     // 0–100 (%)
  diameter: number; // 8–28 (px)
  color: 'green' | 'yellow' | 'red' | 'blue';
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
    MatTooltipModule,
    MatExpansionModule,
    MatDialogModule,
    MatSnackBarModule,
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
  private readonly snackBar = inject(MatSnackBar);
  private readonly topbarService = inject(TopbarService);
  private readonly destroyRef = inject(DestroyRef);

  objectId = '';
  versions = signal<ObjectVersion[]>([]);
  loading = signal(true);

  // A/B pins for comparison
  pinA = signal<ObjectVersion | null>(null);
  pinB = signal<ObjectVersion | null>(null);

  /** Tracked timeline container width (px). Used to convert 20px min-gap to %. */
  timelineContainerWidth = signal(800);

  @HostListener('window:resize', ['$event.target.innerWidth'])
  onResize(width: number): void {
    this.timelineContainerWidth.set(width);
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

  maxChanges = computed(() => {
    const counts = this.versions().map((v) => v.changed_fields.length);
    return Math.max(1, ...counts);
  });

  daysBetweenPins = computed<number | null>(() => {
    const a = this.pinA();
    const b = this.pinB();
    if (!a || !b) return null;
    const ms = Math.abs(
      new Date(b.backed_up_at).getTime() - new Date(a.backed_up_at).getTime(),
    );
    return Math.round(ms / (1000 * 60 * 60 * 24));
  });

  /**
   * Per-bubble position + size for the sparkline timeline.
   * Positions are time-proportional with a minimum 2.5% gap between adjacent bubbles.
   */
  timelineBubbles = computed<TimelineBubble[]>(() => {
    const versions = this.versions();
    const pinA = this.pinA();
    const pinB = this.pinB();
    if (versions.length === 0) return [];

    // Timeline goes oldest → newest (left → right)
    const sorted = [...versions].reverse();

    const earliest = new Date(sorted[0].backed_up_at).getTime();
    const latest = new Date(sorted[sorted.length - 1].backed_up_at).getTime();
    const range = latest - earliest;

    // Raw proportional positions
    const positions: number[] = sorted.map((v) =>
      range === 0 ? 50 : ((new Date(v.backed_up_at).getTime() - earliest) / range) * 100,
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
    }

    return sorted.map((v, i) => ({
      version: v,
      left: positions[i],
      diameter: Math.min(28, Math.max(8, 8 + v.changed_fields.length * 2)),
      color:
        pinB?.id === v.id
          ? 'blue'
          : v.changed_fields.length <= 2
            ? 'green'
            : v.changed_fields.length <= 6
              ? 'yellow'
              : 'red',
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

  // ── Lifecycle ─────────────────────────────────────────────────────────────

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
   * - Click A → clear A
   * - Click B → clear B
   * - No A set → set A
   * - A set, no B → set B, compute diff
   * - Both set → replace A, compute diff
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
  }

  /** Returns true for the 3 newest versions and for any pinned version. */
  isFullRow(v: ObjectVersion, index: number): boolean {
    return index < 3 || this.pinA()?.id === v.id || this.pinB()?.id === v.id;
  }

  // ── Actions ───────────────────────────────────────────────────────────────

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

  /** Simulate rollback: open CascadeRestoreDialogComponent in dry-run mode. */
  simulateRestore(v: ObjectVersion): void {
    this.dialog.open(CascadeRestoreDialogComponent, {
      width: '600px',
      maxHeight: '80vh',
      data: {
        versionId: v.id,
        objectName: v.object_name || v.object_id,
        objectType: v.object_type,
        isDeleted: v.is_deleted,
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
      .subscribe({
        next: (res) => { this.dependencies.set(res); this.depsLoading.set(false); },
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
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors. If you see errors about removed properties (`compareMode`, `versionColumns`, etc.) being referenced from the template, that's expected — the template is updated in Task 2.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/features/backup/detail/backup-object-detail.component.ts
git commit -m "feat(backup): replace compare-mode with A/B pin state + timeline computation"
```

---

## Task 2: Rework component template

**Files:**
- Modify: `frontend/src/app/features/backup/detail/backup-object-detail.component.html`

- [ ] **Step 1: Replace the entire template with the new three-zone layout**

```html
<div class="page-actions">
  <a mat-stroked-button routerLink="/backup">
    <mat-icon>arrow_back</mat-icon> Back
  </a>
</div>

@if (loading()) {
  <mat-progress-bar mode="indeterminate"></mat-progress-bar>
}

@if (!loading() && latestVersion(); as latest) {

  <!-- ── Zone 1: Object header ── -->
  <div class="object-header">
    <code class="object-type-badge">{{ latest.object_type }}</code>
    <span class="object-name">{{ latest.object_name || latest.object_id }}</span>
    @if (latest.is_deleted) {
      <app-status-badge status="deleted"></app-status-badge>
    }
    <span class="object-meta">{{ latest.site_id ? 'Site' : 'Org' }}</span>
    <code class="object-meta object-uuid">{{ objectId }}</code>
    <span class="object-meta object-version-count">
      {{ versions().length }} version{{ versions().length === 1 ? '' : 's' }}
      · first seen {{ oldestVersion()?.backed_up_at | dateTime }}
    </span>
  </div>

  <!-- ── Zone 2: Sparkline timeline ── -->
  <div class="timeline-wrapper">
    <div class="timeline-hint">
      Bubble size = # of changes · click any bubble or row to pin
      <span class="pin-label pin-label-a">A</span> /
      <span class="pin-label pin-label-b">B</span>
    </div>
    <div class="timeline-track-area">
      <!-- Base track -->
      <div class="timeline-track"></div>
      <!-- A→B gradient connector -->
      @if (timelineConnector(); as connector) {
        <div
          class="timeline-connector"
          [style.left.%]="connector.left"
          [style.right.%]="connector.right"
        ></div>
      }
      <!-- Bubbles -->
      @for (bubble of timelineBubbles(); track bubble.version.id) {
        <div
          class="timeline-bubble-wrapper"
          [style.left.%]="bubble.left"
          [matTooltip]="
            'v' +
            bubble.version.version +
            ' · ' +
            (bubble.version.backed_up_at | dateTime) +
            ' · ' +
            bubble.version.changed_fields.length +
            ' change' +
            (bubble.version.changed_fields.length === 1 ? '' : 's')
          "
          (click)="pinVersion(bubble.version)"
        >
          <div
            class="timeline-bubble"
            [class.bubble-green]="bubble.color === 'green'"
            [class.bubble-yellow]="bubble.color === 'yellow'"
            [class.bubble-red]="bubble.color === 'red'"
            [class.bubble-blue]="bubble.color === 'blue'"
            [class.bubble-pin-a]="pinA()?.id === bubble.version.id"
            [class.bubble-pin-b]="pinB()?.id === bubble.version.id"
            [style.width.px]="bubble.diameter"
            [style.height.px]="bubble.diameter"
            [style.margin-top.px]="-bubble.diameter / 2"
          ></div>
          @if (pinA()?.id === bubble.version.id) {
            <span class="bubble-pin-label pin-label-a">A</span>
          } @else if (pinB()?.id === bubble.version.id) {
            <span class="bubble-pin-label pin-label-b">B</span>
          }
        </div>
      }
    </div>
    <!-- Date axis: just show first and last dates -->
    <div class="timeline-dates">
      <span>{{ oldestVersion()?.backed_up_at | dateTime }}</span>
      <span>{{ latestVersion()?.backed_up_at | dateTime }}</span>
    </div>
  </div>

  <!-- ── Zone 3: Split layout ── -->
  <div class="split-layout">

    <!-- Left pane: version list -->
    <div class="version-list">
      <div class="version-list-header">All versions — newest first</div>

      @for (v of versions(); track v.id; let i = $index) {
        <div
          class="version-row"
          [class.pin-a-row]="pinA()?.id === v.id"
          [class.pin-b-row]="pinB()?.id === v.id"
          (click)="pinVersion(v)"
        >
          <!-- Pin indicator circle -->
          <div
            class="pin-indicator"
            [class.pin-indicator-a]="pinA()?.id === v.id"
            [class.pin-indicator-b]="pinB()?.id === v.id"
          >
            @if (pinA()?.id === v.id) { A }
            @else if (pinB()?.id === v.id) { B }
          </div>

          @if (isFullRow(v, i)) {
            <!-- Full row (3 newest + any pinned version) -->
            <div class="row-content">
              <div class="row-title">
                <span class="version-number">v{{ v.version }}</span>
                @if (i === 0) {
                  <span class="latest-badge">latest</span>
                }
                @if (v.is_deleted) {
                  <span class="deleted-badge">deleted</span>
                }
              </div>
              <div class="row-meta">
                {{ v.backed_up_at | dateTime }}
                @if (v.backed_up_by) { · {{ v.backed_up_by }} }
                @else { · {{ eventLabel(v.event_type) }} }
              </div>
              <div class="change-bar-row">
                <div class="change-bar-track">
                  <div
                    class="change-bar-fill"
                    [style.width.%]="(v.changed_fields.length / maxChanges()) * 100"
                  ></div>
                </div>
                <span class="change-count">
                  {{ v.changed_fields.length }}
                  change{{ v.changed_fields.length === 1 ? '' : 's' }}
                </span>
              </div>
              @if (v.changed_fields.length > 0) {
                <div class="field-tags">
                  @for (f of v.changed_fields | slice: 0 : 2; track f) {
                    <span class="field-tag">{{ f }}</span>
                  }
                  @if (v.changed_fields.length > 2) {
                    <span class="field-tag field-tag-more">+{{ v.changed_fields.length - 2 }}</span>
                  }
                </div>
              }
              <div class="row-actions" (click)="$event.stopPropagation()">
                <button mat-stroked-button (click)="viewJson(v)">
                  <mat-icon>code</mat-icon> View
                </button>
                <button mat-stroked-button class="action-rollback" (click)="restoreVersion(v)">
                  <mat-icon>restore</mat-icon> Rollback
                </button>
                <button mat-stroked-button class="action-simulate" (click)="simulateRestore(v)">
                  <mat-icon>science</mat-icon> Simulate
                </button>
              </div>
            </div>
          } @else {
            <!-- Compact row (older versions not pinned) -->
            <div class="row-content row-content-compact">
              <span class="version-number">v{{ v.version }}</span>
              <span class="compact-meta">
                {{ v.backed_up_at | dateTime }} ·
                {{ v.changed_fields.length }} change{{ v.changed_fields.length === 1 ? '' : 's' }}
              </span>
              <div class="compact-actions" (click)="$event.stopPropagation()">
                <button
                  mat-icon-button
                  [matTooltip]="'Rollback to v' + v.version"
                  (click)="restoreVersion(v)"
                >
                  <mat-icon>restore</mat-icon>
                </button>
                <button
                  mat-icon-button
                  [matTooltip]="'Simulate rollback to v' + v.version"
                  (click)="simulateRestore(v)"
                >
                  <mat-icon>science</mat-icon>
                </button>
              </div>
            </div>
          }
        </div>
      }
    </div>

    <!-- Right pane: diff panel -->
    <div class="diff-panel">
      @if (!pinA() || !pinB()) {
        <div class="diff-placeholder">
          <mat-icon>compare_arrows</mat-icon>
          <p>Select two versions to compare</p>
          <p class="diff-placeholder-hint">
            Click any row to set <span class="pin-label pin-label-a">A</span>, then another for
            <span class="pin-label pin-label-b">B</span>
          </p>
        </div>
      } @else {
        <!-- Diff header -->
        <div class="diff-panel-header">
          <span class="pin-chip pin-chip-a">A v{{ pinA()!.version }}</span>
          <mat-icon class="diff-arrow">arrow_forward</mat-icon>
          <span class="pin-chip pin-chip-b">B v{{ pinB()!.version }}</span>
          <span class="diff-panel-meta">
            · {{ diffEntries().length }} change{{ diffEntries().length === 1 ? '' : 's' }}
            @if (daysBetweenPins(); as days) {
              · {{ days }} day{{ days === 1 ? '' : 's' }} apart
            }
          </span>
          <div class="diff-panel-counts">
            <span class="diff-count-badge badge-added">+{{ diffTypeCounts()['added'] || 0 }}</span>
            <span class="diff-count-badge badge-removed">−{{ diffTypeCounts()['removed'] || 0 }}</span>
            <span class="diff-count-badge badge-modified">~{{ diffTypeCounts()['modified'] || 0 }}</span>
          </div>
        </div>

        @if (diffEntries().length === 0) {
          <p class="no-diff">No differences found between these versions.</p>
        } @else {
          <!-- Toolbar -->
          <div class="diff-toolbar">
            <div class="diff-filter-chips">
              @for (type of ['added', 'removed', 'modified']; track type) {
                @if (diffTypeCounts()[type]) {
                  <button
                    class="filter-chip"
                    [class.filter-active]="activeFilters().has(type)"
                    [ngClass]="'filter-' + type"
                    (click)="toggleFilter(type)"
                  >
                    <span class="filter-label">{{ type }}</span>
                    <span class="filter-count">{{ diffTypeCounts()[type] }}</span>
                  </button>
                }
              }
            </div>
            <app-ai-inline-analysis
              class="diff-ai-chip"
              [llmAvailable]="llmAvailable()"
              [summary]="aiSummary()"
              [error]="aiError()"
              [loading]="aiLoading()"
              [threadId]="aiThreadId()"
              loadingLabel="Summarizing changes..."
              [buttonOnly]="true"
              [(expanded)]="aiExpanded"
              (analyzeRequested)="summarizeChanges()"
            />
            <button
              mat-icon-button
              class="expand-all-btn"
              (click)="toggleExpandAll()"
              [matTooltip]="allExpanded() ? 'Collapse all' : 'Expand all'"
            >
              <mat-icon>{{ allExpanded() ? 'unfold_less' : 'unfold_more' }}</mat-icon>
            </button>
          </div>

          @if (aiHasContent() && aiExpanded()) {
            <app-ai-analysis-result
              [threadId]="aiThreadId()"
              [summary]="aiSummary()"
              [error]="aiError()"
              [loading]="aiLoading()"
              loadingLabel="Summarizing changes..."
            />
          }

          <!-- Grouped diff list -->
          <div class="diff-list">
            @for (group of filteredGroups(); track group.key) {
              @if (group.isGroup) {
                <div class="diff-group">
                  <div class="diff-group-header" (click)="toggleGroup(group.key)">
                    <mat-icon class="group-chevron">
                      {{ isGroupExpanded(group.key) ? 'expand_more' : 'chevron_right' }}
                    </mat-icon>
                    <code class="diff-group-key">{{ group.key }}</code>
                    <span class="diff-group-count">{{ group.entries.length }}</span>
                    <span class="diff-group-badges">
                      @for (t of ['added', 'removed', 'modified']; track t) {
                        @if (group.typeCounts[t]) {
                          <span class="diff-type-badge mini" [ngClass]="'badge-' + t">
                            {{ group.typeCounts[t] }} {{ t }}
                          </span>
                        }
                      }
                    </span>
                  </div>
                  @if (isGroupExpanded(group.key)) {
                    <div class="diff-group-body">
                      @for (d of group.entries; track d.path) {
                        <div class="diff-entry" [ngClass]="'diff-' + d.type">
                          <div class="diff-header" (click)="toggleEntry(d.path)">
                            <div class="diff-header-left">
                              <mat-icon class="entry-chevron">
                                {{ isEntryExpanded(d.path) ? 'expand_more' : 'chevron_right' }}
                              </mat-icon>
                              <code class="diff-path">{{ stripGroupPrefix(d.path, group.key) }}</code>
                            </div>
                            <span class="diff-type-badge">{{ d.type }}</span>
                          </div>
                          @if (isEntryExpanded(d.path)) {
                            <div class="diff-values">
                              @if (d.type === 'removed' || d.type === 'modified') {
                                <pre class="diff-old">{{ formatValue(d.oldValue) }}</pre>
                              }
                              @if (d.type === 'added' || d.type === 'modified') {
                                <pre class="diff-new">{{ formatValue(d.newValue) }}</pre>
                              }
                            </div>
                          }
                        </div>
                      }
                    </div>
                  }
                </div>
              } @else {
                <div class="diff-entry standalone" [ngClass]="'diff-' + group.entries[0].type">
                  <div class="diff-header" (click)="toggleEntry(group.entries[0].path)">
                    <div class="diff-header-left">
                      <mat-icon class="entry-chevron">
                        {{ isEntryExpanded(group.entries[0].path) ? 'expand_more' : 'chevron_right' }}
                      </mat-icon>
                      <code class="diff-path">{{ group.entries[0].path }}</code>
                    </div>
                    <span class="diff-type-badge">{{ group.entries[0].type }}</span>
                  </div>
                  @if (isEntryExpanded(group.entries[0].path)) {
                    <div class="diff-values">
                      @if (group.entries[0].type === 'removed' || group.entries[0].type === 'modified') {
                        <pre class="diff-old">{{ formatValue(group.entries[0].oldValue) }}</pre>
                      }
                      @if (group.entries[0].type === 'added' || group.entries[0].type === 'modified') {
                        <pre class="diff-new">{{ formatValue(group.entries[0].newValue) }}</pre>
                      }
                    </div>
                  }
                </div>
              }
            }
          </div>
        }
      }
    </div>
  </div>

  <!-- ── Status bar ── -->
  <div class="status-bar">
    <span>
      1st click → set <span class="pin-label pin-label-a">A</span> ·
      2nd click → set <span class="pin-label pin-label-b">B</span> ·
      click A or B again to clear
    </span>
    <span>⚡ Simulate runs the Digital Twin dry-run pre-check</span>
  </div>

  <!-- ── References ── -->
  @if (dependencies(); as deps) {
    @if (deps.parents.length > 0 || deps.children.length > 0) {
      <mat-accordion class="ref-accordion" multi>
        @if (deps.parents.length > 0) {
          <mat-expansion-panel>
            <mat-expansion-panel-header>
              <mat-panel-title>
                <mat-icon class="ref-icon">arrow_upward</mat-icon>
                References
                <span class="ref-count">{{ deps.parents.length }}</span>
              </mat-panel-title>
              <mat-panel-description>Objects this {{ latest.object_type }} depends on</mat-panel-description>
            </mat-expansion-panel-header>
            <div class="ref-list">
              @for (p of deps.parents; track p.target_id + p.field_path) {
                <div class="ref-row">
                  <span class="ref-type-badge">{{ p.target_type }}</span>
                  @if (p.exists_in_backup) {
                    <a
                      class="ref-name ref-link"
                      [class.ref-deleted]="p.is_deleted"
                      [routerLink]="'/backup/object/' + p.target_id"
                    >{{ p.target_name || p.target_id.slice(0, 8) }}</a>
                  } @else {
                    <span class="ref-name ref-missing">{{ p.target_name || p.target_id.slice(0, 8) }}</span>
                  }
                  <code class="ref-field">{{ p.field_path }}</code>
                  <app-status-badge
                    [status]="p.is_deleted ? 'deleted' : p.exists_in_backup ? 'active' : 'missing'"
                  ></app-status-badge>
                </div>
              }
            </div>
          </mat-expansion-panel>
        }
        @if (deps.children.length > 0) {
          <mat-expansion-panel>
            <mat-expansion-panel-header>
              <mat-panel-title>
                <mat-icon class="ref-icon">arrow_downward</mat-icon>
                Referenced by
                <span class="ref-count">{{ deps.children.length }}</span>
              </mat-panel-title>
              <mat-panel-description>Objects that depend on this {{ latest.object_type }}</mat-panel-description>
            </mat-expansion-panel-header>
            <div class="ref-list">
              @for (c of deps.children; track c.source_id + c.field_path) {
                <div class="ref-row">
                  <span class="ref-type-badge">{{ c.source_type }}</span>
                  <a
                    class="ref-name ref-link"
                    [class.ref-deleted]="c.is_deleted"
                    [routerLink]="'/backup/object/' + c.source_id"
                  >{{ c.source_name || c.source_id.slice(0, 8) }}</a>
                  <code class="ref-field">{{ c.field_path }}</code>
                  @if (c.is_deleted) { <app-status-badge status="deleted"></app-status-badge> }
                </div>
              }
            </div>
          </mat-expansion-panel>
        }
      </mat-accordion>
    }
  }
}

@if (!loading() && versions().length === 0) {
  <app-empty-state
    icon="history"
    title="No versions found"
    message="This object has no backup versions."
  ></app-empty-state>
}
```

- [ ] **Step 2: Verify TypeScript compiles (template strict mode)**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/features/backup/detail/backup-object-detail.component.html
git commit -m "feat(backup): rework object detail template to three-zone time-travel layout"
```

---

## Task 3: Rework component SCSS

**Files:**
- Modify: `frontend/src/app/features/backup/detail/backup-object-detail.component.scss`

- [ ] **Step 1: Replace the entire SCSS file**

```scss
// ── Object header ─────────────────────────────────────────────────────────

.object-header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 10px 0 16px;
}

.object-type-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 4px;
  background: var(--mat-sys-primary-container);
  color: var(--mat-sys-on-primary-container);
  font-family: var(--app-font-mono);
  white-space: nowrap;
}

.object-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--mat-sys-on-surface);
}

.object-meta {
  font-size: 12px;
  color: var(--mat-sys-on-surface-variant);
  &.object-uuid { font-family: var(--app-font-mono); font-size: 11px; }
  &.object-version-count { margin-left: auto; }
}

// ── Timeline ──────────────────────────────────────────────────────────────

.timeline-wrapper {
  background: var(--mat-sys-surface-container-low);
  border: 1px solid var(--mat-sys-outline-variant);
  border-radius: 12px;
  padding: 12px 24px 8px;
  margin-bottom: 20px;
}

.timeline-hint {
  font-size: 10px;
  color: var(--mat-sys-on-surface-variant);
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.timeline-track-area {
  position: relative;
  height: 56px;
  overflow: visible;
}

.timeline-track {
  position: absolute;
  top: 50%;
  left: 0;
  right: 0;
  height: 1px;
  background: var(--mat-sys-outline-variant);
  transform: translateY(-50%);
}

.timeline-connector {
  position: absolute;
  top: 50%;
  height: 3px;
  transform: translateY(-50%);
  background: linear-gradient(90deg, var(--app-error-badge), var(--mat-sys-primary));
  border-radius: 2px;
  z-index: 1;
  opacity: 0.7;
}

.timeline-bubble-wrapper {
  position: absolute;
  top: 50%;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  z-index: 2;

  &:hover .timeline-bubble { filter: brightness(1.15); }
}

.timeline-bubble {
  border-radius: 50%;
  flex-shrink: 0;
  transition: filter 0.15s;

  &.bubble-green { background: var(--app-success-badge); }
  &.bubble-yellow { background: var(--app-warning-badge, #e3b341); }
  &.bubble-red { background: var(--app-error-badge); }
  &.bubble-blue {
    background: var(--mat-sys-primary);
    box-shadow: 0 0 6px color-mix(in srgb, var(--mat-sys-primary) 50%, transparent);
  }
}

.bubble-pin-label {
  font-size: 8px;
  font-weight: 700;
  padding: 0 4px;
  border-radius: 8px;
  margin-top: 3px;
  line-height: 14px;
  white-space: nowrap;
}

.timeline-dates {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--mat-sys-on-surface-variant);
  margin-top: 6px;
  padding: 0 2px;
}

// ── Pin labels (shared between timeline hint and status bar) ──────────────

.pin-label {
  font-size: 10px;
  font-weight: 700;
  padding: 0 5px;
  border-radius: 4px;
  line-height: 16px;

  &.pin-label-a { background: var(--app-error-badge-bg); color: var(--app-error-badge); }
  &.pin-label-b { background: var(--mat-sys-primary-container); color: var(--mat-sys-on-primary-container); }
}

.bubble-pin-label {
  &.pin-label-a { background: var(--app-error-badge); color: white; }
  &.pin-label-b { background: var(--mat-sys-primary); color: var(--mat-sys-on-primary); }
}

// ── Split layout ──────────────────────────────────────────────────────────

.split-layout {
  display: flex;
  border: 1px solid var(--mat-sys-outline-variant);
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 4px;
  min-height: 420px;
}

// ── Version list (left pane) ──────────────────────────────────────────────

.version-list {
  width: 280px;
  flex-shrink: 0;
  border-right: 1px solid var(--mat-sys-outline-variant);
  overflow-y: auto;
  scrollbar-width: thin;
}

.version-list-header {
  padding: 8px 12px;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--mat-sys-on-surface-variant);
  background: var(--mat-sys-surface-container);
  border-bottom: 1px solid var(--mat-sys-outline-variant);
  position: sticky;
  top: 0;
  z-index: 1;
}

.version-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 9px 12px;
  border-bottom: 1px solid var(--mat-sys-outline-variant);
  border-left: 3px solid transparent;
  cursor: pointer;
  transition: background 0.1s;

  &:last-child { border-bottom: none; }

  &:hover:not(.pin-a-row):not(.pin-b-row) {
    background: var(--mat-sys-surface-container-low);
  }

  &.pin-a-row {
    border-left-color: var(--app-error-badge);
    background: color-mix(in srgb, var(--app-error-badge) 8%, transparent);
  }

  &.pin-b-row {
    border-left-color: var(--mat-sys-primary);
    background: color-mix(in srgb, var(--mat-sys-primary) 8%, transparent);
  }
}

.pin-indicator {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 1px solid var(--mat-sys-outline-variant);
  background: var(--mat-sys-surface-container);
  color: var(--mat-sys-on-surface-variant);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 9px;
  font-weight: 700;
  margin-top: 1px;

  &.pin-indicator-a {
    background: var(--app-error-badge);
    color: white;
    border-color: var(--app-error-badge);
  }
  &.pin-indicator-b {
    background: var(--mat-sys-primary);
    color: var(--mat-sys-on-primary);
    border-color: var(--mat-sys-primary);
  }
}

.row-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.row-title {
  display: flex;
  align-items: center;
  gap: 6px;
}

.version-number {
  font-size: 13px;
  font-weight: 600;
  color: var(--mat-sys-on-surface);
}

.latest-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 8px;
  background: var(--mat-sys-primary-container);
  color: var(--mat-sys-on-primary-container);
}

.deleted-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 8px;
  background: var(--app-error-badge-bg);
  color: var(--app-error-badge);
}

.row-meta {
  font-size: 11px;
  color: var(--mat-sys-on-surface-variant);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.change-bar-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.change-bar-track {
  flex: 1;
  height: 4px;
  background: var(--mat-sys-surface-container);
  border-radius: 2px;
  overflow: hidden;
}

.change-bar-fill {
  height: 100%;
  background: var(--mat-sys-primary);
  border-radius: 2px;
  min-width: 4px;
}

.change-count {
  font-size: 10px;
  color: var(--mat-sys-on-surface-variant);
  white-space: nowrap;
  flex-shrink: 0;
}

.field-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
}

.field-tag {
  font-size: 10px;
  font-family: var(--app-font-mono);
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--mat-sys-surface-container);
  color: var(--mat-sys-on-surface-variant);

  &.field-tag-more {
    font-weight: 700;
    background: var(--mat-sys-primary-container);
    color: var(--mat-sys-on-primary-container);
    font-family: inherit;
  }
}

.row-actions {
  display: flex;
  gap: 4px;
  margin-top: 4px;
  flex-wrap: wrap;

  button { font-size: 11px; height: 28px; line-height: 28px; padding: 0 8px; }
  mat-icon { font-size: 14px; width: 14px; height: 14px; margin-right: 3px; }

  &.action-rollback { color: var(--app-error-badge); border-color: var(--app-error-border); }
  &.action-simulate { color: var(--app-warning-badge, #e3b341); }
}

// Compact row content
.row-content-compact {
  flex-direction: row;
  align-items: center;
  gap: 8px;

  .version-number { color: var(--mat-sys-on-surface-variant); font-weight: 500; }
}

.compact-meta {
  flex: 1;
  font-size: 11px;
  color: var(--mat-sys-on-surface-variant);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.compact-actions {
  display: flex;
  gap: 0;
  flex-shrink: 0;
}

// ── Diff panel (right pane) ───────────────────────────────────────────────

.diff-panel {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
  min-width: 0;
  scrollbar-width: thin;
}

.diff-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 200px;
  color: var(--mat-sys-on-surface-variant);
  gap: 8px;
  text-align: center;

  mat-icon { font-size: 40px; width: 40px; height: 40px; opacity: 0.3; }
  p { margin: 0; font-size: 14px; }
}

.diff-placeholder-hint {
  font-size: 12px;
  opacity: 0.7;
  display: flex;
  align-items: center;
  gap: 4px;
}

.diff-panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--mat-sys-outline-variant);
  flex-wrap: wrap;
}

.pin-chip {
  font-size: 12px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 4px;

  &.pin-chip-a { background: var(--app-error-badge-bg); color: var(--app-error-badge); }
  &.pin-chip-b { background: var(--mat-sys-primary-container); color: var(--mat-sys-on-primary-container); }
}

.diff-arrow { color: var(--mat-sys-on-surface-variant); font-size: 18px; width: 18px; height: 18px; }

.diff-panel-meta { font-size: 12px; color: var(--mat-sys-on-surface-variant); }

.diff-panel-counts { display: flex; gap: 4px; margin-left: auto; }

.diff-count-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 8px;

  &.badge-added { background: var(--app-success-badge-bg); color: var(--app-success-badge); }
  &.badge-removed { background: var(--app-error-badge-bg); color: var(--app-error-badge); }
  &.badge-modified { background: var(--app-info-badge-bg); color: var(--app-info-badge); }
}

.no-diff { text-align: center; color: var(--mat-sys-on-surface-variant); padding: 32px; }

// Diff toolbar — identical to original
.diff-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 8px;
}

.diff-filter-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.diff-ai-chip { margin-left: auto; }

.filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 16px;
  border: 1px solid var(--mat-sys-outline-variant);
  background: var(--mat-sys-surface-container-low);
  color: var(--mat-sys-on-surface-variant);
  font: 500 12px/1 inherit;
  cursor: pointer;

  &:hover { background: var(--mat-sys-surface-container); }

  &.filter-active {
    &.filter-added { background: var(--app-success-badge-bg); color: var(--app-success-badge); border-color: var(--app-success-border); }
    &.filter-removed { background: var(--app-error-badge-bg); color: var(--app-error-badge); border-color: var(--app-error-border); }
    &.filter-modified { background: var(--app-info-badge-bg); color: var(--app-info-badge); border-color: var(--app-info-border); }
  }
}

.filter-count {
  font-weight: 700;
  font-size: 11px;
  padding: 0 5px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.06);
  line-height: 18px;
}

// Diff list — identical to original
.diff-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow-y: auto;
  scrollbar-width: thin;
}

.diff-group {
  border: 1px solid var(--mat-sys-outline-variant);
  border-radius: 8px;
  overflow: hidden;
}

.diff-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--mat-sys-surface-container);
  cursor: pointer;
}

.group-chevron, .entry-chevron { color: var(--mat-sys-on-surface-variant); }
.group-chevron { font-size: 18px; width: 18px; height: 18px; }

.diff-group-key { font-size: 13px; font-weight: 600; font-family: var(--app-font-mono); }
.diff-group-count { font-size: 11px; font-weight: 700; padding: 0 7px; border-radius: 10px; background: var(--mat-sys-primary-container); color: var(--mat-sys-on-primary-container); line-height: 20px; }
.diff-group-badges { display: flex; gap: 4px; margin-left: auto; }
.diff-group-body { display: flex; flex-direction: column; border-top: 1px solid var(--mat-sys-outline-variant); }

.diff-entry {
  border-bottom: 1px solid var(--mat-sys-outline-variant);
  &:last-child { border-bottom: none; }
  &.standalone {
    border: 1px solid var(--mat-sys-outline-variant);
    border-radius: 8px;
    overflow: hidden;
    &.diff-added { border-color: var(--app-success-border); }
    &.diff-removed { border-color: var(--app-error-border); }
    &.diff-modified { border-color: var(--app-info-border); }
  }
}

.diff-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 12px;
  background: var(--mat-sys-surface-container);
  cursor: pointer;
}

.diff-header-left { display: flex; align-items: center; gap: 4px; min-width: 0; }
.entry-chevron { font-size: 16px; width: 16px; height: 16px; flex-shrink: 0; }
.diff-path { font-size: 12px; font-weight: 500; font-family: var(--app-font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.diff-type-badge {
  font: 700 11px/1 inherit;
  padding: 1px 8px;
  border-radius: 10px;
  text-transform: uppercase;
  flex-shrink: 0;
  &.mini { padding: 1px 6px; }
  &.badge-added, .diff-added & { background: var(--app-success-badge-bg); color: var(--app-success-badge); }
  &.badge-removed, .diff-removed & { background: var(--app-error-badge-bg); color: var(--app-error-badge); }
  &.badge-modified, .diff-modified & { background: var(--app-info-badge-bg); color: var(--app-info-badge); }
}

.diff-values { display: flex; }

.diff-old, .diff-new {
  flex: 1;
  margin: 0;
  padding: 8px 12px;
  font: 12px/1.5 var(--app-font-mono);
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  scrollbar-width: thin;
}

.diff-old { background: var(--app-diff-old-bg); border-right: 1px solid var(--mat-sys-outline-variant); }
.diff-new { background: var(--app-diff-new-bg); }

// ── Status bar ────────────────────────────────────────────────────────────

.status-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  color: var(--mat-sys-on-surface-variant);
  padding: 6px 12px;
  margin-bottom: 20px;
  background: var(--mat-sys-surface-container-low);
  border: 1px solid var(--mat-sys-outline-variant);
  border-top: none;
  border-radius: 0 0 12px 12px;
}

// ── References accordion — identical to original ──────────────────────────

.ref-accordion {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 24px;

  .ref-icon { font-size: 18px; width: 18px; height: 18px; margin-right: 6px; color: var(--mat-sys-on-surface-variant); }
  .ref-count { margin-left: 6px; font-size: 11px; font-weight: 700; padding: 0 7px; border-radius: 10px; background: var(--mat-sys-primary-container); color: var(--mat-sys-on-primary-container); line-height: 20px; }
}

.ref-list { display: flex; flex-direction: column; gap: 2px; max-height: 280px; overflow-y: auto; scrollbar-width: thin; }

.ref-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 5px 8px;
  border-radius: 6px;
  &:hover { background: var(--mat-sys-surface-container-low); }
}

.ref-type-badge { flex-shrink: 0; font-size: 11px; font-weight: 600; padding: 1px 8px; border-radius: 8px; background: var(--mat-sys-surface-container); color: var(--mat-sys-on-surface-variant); white-space: nowrap; }

.ref-name {
  font: 500 13px/1 inherit;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  &.ref-link { color: var(--mat-sys-primary); text-decoration: none; cursor: pointer; &:hover { text-decoration: underline; } }
  &.ref-missing { color: var(--mat-sys-on-surface-variant); font-style: italic; }
  &.ref-deleted { color: var(--mat-sys-error); text-decoration: line-through; }
}

.ref-field { flex-shrink: 0; font-size: 11px; font-family: var(--app-font-mono); color: var(--mat-sys-on-surface-variant); margin-left: auto; }
```

- [ ] **Step 2: Start the dev server and verify the page renders**

```bash
cd frontend && ng serve
```

Navigate to any backup object detail page (e.g., via `/backup` → click an object). Verify:

1. Object header bar renders with type badge, name, and version count on the right
2. Timeline renders with bubbles centered on the track line, correctly spaced
3. On load, B = latest version (blue bubble), A = previous version, diff panel is populated
4. Clicking a version row cycles the A/B pin as described in the status bar hint
5. Clicking a bubble in the timeline has the same effect as clicking the list row
6. Rollback button opens `CascadeRestoreDialogComponent` (same as before)
7. Simulate button opens `SimulateRestoreDialogComponent` — starts in `confirm` step, runs `POST .../restore?simulate=true` on user click, shows result with severity chip + warnings list, offers "Open Digital Twin" when `twin_session_id` is returned
8. Compact rows show for versions older than the 3rd newest (when >3 versions exist)
9. References accordion still works below the split layout

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/features/backup/detail/backup-object-detail.component.scss
git commit -m "feat(backup): add time-travel SCSS — timeline, split layout, A/B pin styles"
```

---

## Edge Case Checklist (verify in browser before done)

| Scenario | Expected |
|---|---|
| Object with 1 version | B = that version, no A, diff panel shows placeholder |
| Object with exactly 2 versions | Both pinned by default, diff shown immediately |
| Two versions within seconds of each other | Bubbles do not overlap — min-gap applied |
| 10+ versions | Older rows use compact format; scrollbar appears in version list |
| Deleted object (latest `is_deleted: true`) | "deleted" badge on v_latest's row title |
| Very long `object_name` | Truncates in header with text-overflow |
