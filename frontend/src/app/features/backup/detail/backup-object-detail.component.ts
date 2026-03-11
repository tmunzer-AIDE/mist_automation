import { Component, inject, OnInit, OnDestroy, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { Subscription } from 'rxjs';
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
import { TopbarService } from '../../../core/services/topbar.service';
import { ObjectDependencyResponse } from '../../../core/models/backup.model';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
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

@Component({
  selector: 'app-backup-object-detail',
  standalone: true,
  imports: [
    CommonModule,
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
    DateTimePipe,
  ],
  templateUrl: './backup-object-detail.component.html',
  styleUrl: './backup-object-detail.component.scss',
})
export class BackupObjectDetailComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly topbarService = inject(TopbarService);
  private routeSub!: Subscription;

  objectId = '';
  versions = signal<ObjectVersion[]>([]);
  loading = signal(true);
  selectedVersionId: string | null = null;
  dependencies = signal<ObjectDependencyResponse | null>(null);
  depsLoading = signal(true);

  // Compare mode
  compareMode = false;
  compareVersions: [ObjectVersion | null, ObjectVersion | null] = [null, null];
  diffEntries: { path: string; type: string; oldValue?: unknown; newValue?: unknown }[] = [];

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
    this.routeSub = this.route.paramMap.subscribe((params) => {
      const id = params.get('objectId') || '';
      if (id !== this.objectId) {
        this.objectId = id;
        this.resetState();
        this.loadVersions();
        this.loadDependencies();
      }
    });
  }

  ngOnDestroy(): void {
    this.routeSub.unsubscribe();
  }

  private resetState(): void {
    this.versions.set([]);
    this.loading.set(true);
    this.selectedVersionId = null;
    this.dependencies.set(null);
    this.depsLoading.set(true);
    this.compareMode = false;
    this.compareVersions = [null, null];
    this.diffEntries = [];
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
    if (this.compareMode) {
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
    this.compareMode = !this.compareMode;
    if (!this.compareMode) {
      this.compareVersions = [null, null];
      this.diffEntries = [];
    }
  }

  toggleCompareVersion(v: ObjectVersion): void {
    if (!this.compareMode) return;

    // If already selected, deselect
    if (this.compareVersions[0]?.id === v.id) {
      this.compareVersions = [this.compareVersions[1], null];
      this.diffEntries = [];
      return;
    }
    if (this.compareVersions[1]?.id === v.id) {
      this.compareVersions = [this.compareVersions[0], null];
      this.diffEntries = [];
      return;
    }

    // Add to selection
    if (!this.compareVersions[0]) {
      this.compareVersions = [v, null];
    } else {
      this.compareVersions = [this.compareVersions[0], v];
      this.computeDiff();
    }
  }

  isCompareSelected(v: ObjectVersion): boolean {
    return this.compareVersions[0]?.id === v.id || this.compareVersions[1]?.id === v.id;
  }

  compareLabel(v: ObjectVersion): string | null {
    if (this.compareVersions[0]?.id === v.id) return 'A';
    if (this.compareVersions[1]?.id === v.id) return 'B';
    return null;
  }

  private computeDiff(): void {
    const [a, b] = this.compareVersions;
    if (!a || !b) return;
    // Order so that older version is on the left
    const older = a.version < b.version ? a : b;
    const newer = a.version < b.version ? b : a;
    this.compareVersions = [older, newer];
    this.diffEntries = this.deepDiff(older.configuration, newer.configuration);
  }

  private deepDiff(
    a: Record<string, unknown>,
    b: Record<string, unknown>,
    path = '',
  ): { path: string; type: string; oldValue?: unknown; newValue?: unknown }[] {
    const result: { path: string; type: string; oldValue?: unknown; newValue?: unknown }[] = [];
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
        },
        error: () => {
          this.loading.set(false);
        },
      });
  }
}
