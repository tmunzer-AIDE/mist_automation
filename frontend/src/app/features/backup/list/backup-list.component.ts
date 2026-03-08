import { Component, ChangeDetectorRef, inject, OnInit } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MatTableModule } from '@angular/material/table';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatSortModule, Sort } from '@angular/material/sort';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatMenuModule } from '@angular/material/menu';
import { MatCardModule } from '@angular/material/card';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { ApiService } from '../../../core/services/api.service';
import {
  BackupJobResponse,
  BackupJobListResponse,
  BackupObjectSummary,
  BackupObjectListResponse,
  BackupChangeEvent,
  BackupChangeListResponse,
  MistObjectTypeOption,
  MistSiteOption,
} from '../../../core/models/backup.model';
import { PageHeaderComponent } from '../../../shared/components/page-header/page-header.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { BackupCreateDialogComponent } from './backup-create-dialog.component';

@Component({
  selector: 'app-backup-list',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    ReactiveFormsModule,
    MatTableModule,
    MatPaginatorModule,
    MatSortModule,
    MatButtonModule,
    MatIconModule,
    MatDialogModule,
    MatProgressBarModule,
    MatSnackBarModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatChipsModule,
    MatTooltipModule,
    MatMenuModule,
    MatCardModule,
    MatButtonToggleModule,
    PageHeaderComponent,
    EmptyStateComponent,
    StatusBadgeComponent,
    DatePipe,
  ],
  templateUrl: './backup-list.component.html',
  styleUrl: './backup-list.component.scss',
})
export class BackupListComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);
  private readonly cdr = inject(ChangeDetectorRef);
  private readonly fb = inject(FormBuilder);

  // ── Backup jobs ─────────────────────────────────────────────────────
  jobs: BackupJobResponse[] = [];
  jobsTotal = 0;
  loadingJobs = true;

  // ── Object table ─────────────────────────────────────────────────────
  objects: BackupObjectSummary[] = [];
  objectsTotal = 0;
  objectsPageSize = 25;
  objectsPageIndex = 0;
  loadingObjects = true;

  // ── Sort ──────────────────────────────────────────────────────────────
  sortField = 'last_backed_up_at';
  sortDirection: 'asc' | 'desc' | '' = 'desc';

  displayedColumns = [
    'scope',
    'object_type',
    'object_name',
    'version_count',
    'first_backed_up_at',
    'last_backed_up_at',
    'last_modified_at',
    'status',
    'actions',
  ];

  // ── Timeline ─────────────────────────────────────────────────────────
  changes: BackupChangeEvent[] = [];
  changesTotal = 0;
  loadingChanges = true;
  timelineLimit = 50;

  // ── Filters ──────────────────────────────────────────────────────────
  searchQuery = '';
  objectTypeOptions: MistObjectTypeOption[] = [];
  siteOptions: MistSiteOption[] = [];

  filterForm = this.fb.group({
    object_type: [''],
    scope: [''],
    status: [''],
    site_id: [''],
  });

  // Quick filter presets
  activeQuickFilter: string | null = null;

  ngOnInit(): void {
    this.loadObjectTypes();
    this.loadSites();
    this.loadObjects();
    this.loadChanges();
    this.loadJobs();
  }

  // ── Data loading ─────────────────────────────────────────────────────

  loadObjects(): void {
    this.loadingObjects = true;
    const params: Record<string, string | number> = {
      skip: this.objectsPageIndex * this.objectsPageSize,
      limit: this.objectsPageSize,
    };

    if (this.searchQuery) params['search'] = this.searchQuery;
    if (this.sortField) params['sort'] = this.sortField;
    if (this.sortDirection) params['order'] = this.sortDirection;

    const f = this.filterForm.value;
    if (f.object_type) params['object_type'] = f.object_type;
    if (f.scope) params['scope'] = f.scope;
    if (f.status) params['status'] = f.status;
    if (f.site_id) params['site_id'] = f.site_id;

    this.api.get<BackupObjectListResponse>('/backups/objects', params).subscribe({
      next: (res) => {
        this.objects = res.objects;
        this.objectsTotal = res.total;
        this.loadingObjects = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.loadingObjects = false;
        this.cdr.detectChanges();
      },
    });
  }

  loadChanges(): void {
    this.loadingChanges = true;
    const params: Record<string, string | number> = {
      limit: this.timelineLimit,
    };

    const f = this.filterForm.value;
    if (f.object_type) params['object_type'] = f.object_type;
    if (f.scope) params['scope'] = f.scope;
    if (f.site_id) params['site_id'] = f.site_id;

    this.api.get<BackupChangeListResponse>('/backups/changes', params).subscribe({
      next: (res) => {
        this.changes = res.changes;
        this.changesTotal = res.total;
        this.loadingChanges = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.loadingChanges = false;
        this.cdr.detectChanges();
      },
    });
  }

  loadJobs(): void {
    this.loadingJobs = true;
    this.api.get<BackupJobListResponse>('/backups', { limit: 10 }).subscribe({
      next: (res) => {
        this.jobs = res.backups;
        this.jobsTotal = res.total;
        this.loadingJobs = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.loadingJobs = false;
        this.cdr.detectChanges();
      },
    });
  }

  viewJobDetail(job: BackupJobResponse): void {
    this.router.navigate(['/backup', job.id]);
  }

  private loadObjectTypes(): void {
    this.api
      .get<{ object_types: MistObjectTypeOption[] }>('/admin/mist/object-types')
      .subscribe({
        next: (res) => {
          this.objectTypeOptions = res.object_types;
          this.cdr.detectChanges();
        },
      });
  }

  private loadSites(): void {
    this.api.get<{ sites: MistSiteOption[] }>('/admin/mist/sites').subscribe({
      next: (res) => {
        this.siteOptions = res.sites;
        this.cdr.detectChanges();
      },
    });
  }

  // ── Sort ──────────────────────────────────────────────────────────────

  onSort(sort: Sort): void {
    this.sortField = sort.active;
    this.sortDirection = sort.direction;
    this.objectsPageIndex = 0;
    this.loadObjects();
  }

  // ── Filter actions ───────────────────────────────────────────────────

  applySearch(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.searchQuery = input.value.trim();
    this.objectsPageIndex = 0;
    this.loadObjects();
  }

  applyFilters(): void {
    this.activeQuickFilter = null;
    this.objectsPageIndex = 0;
    this.loadObjects();
    this.loadChanges();
  }

  clearFilters(): void {
    this.filterForm.reset({ object_type: '', scope: '', status: '', site_id: '' });
    this.searchQuery = '';
    this.activeQuickFilter = null;
    this.objectsPageIndex = 0;
    this.loadObjects();
    this.loadChanges();
  }

  quickFilter(preset: string): void {
    this.filterForm.reset({ object_type: '', scope: '', status: '', site_id: '' });
    this.searchQuery = '';
    this.activeQuickFilter = preset;
    this.objectsPageIndex = 0;

    if (preset === 'active') {
      this.filterForm.patchValue({ status: 'active' });
    } else if (preset === 'deleted') {
      this.filterForm.patchValue({ status: 'deleted' });
    }
    // 'recent' is handled by default sort (most recently updated first)

    this.loadObjects();
    this.loadChanges();
  }

  get hasActiveFilters(): boolean {
    const f = this.filterForm.value;
    return !!(this.searchQuery || f.object_type || f.scope || f.status || f.site_id);
  }

  // ── Pagination ───────────────────────────────────────────────────────

  onPage(event: PageEvent): void {
    this.objectsPageIndex = event.pageIndex;
    this.objectsPageSize = event.pageSize;
    this.loadObjects();
  }

  // ── Actions ──────────────────────────────────────────────────────────

  viewObjectDetail(obj: BackupObjectSummary): void {
    this.router.navigate(['/backup', 'object', obj.object_id]);
  }

  openCreateDialog(): void {
    const ref = this.dialog.open(BackupCreateDialogComponent, { width: '500px' });
    ref.afterClosed().subscribe((result) => {
      if (result) {
        this.snackBar.open('Backup job created', 'OK', { duration: 3000 });
        // Reload after a short delay to let the backup run
        setTimeout(() => {
          this.loadObjects();
          this.loadChanges();
          this.loadJobs();
        }, 2000);
      }
    });
  }

  // ── Timeline helpers ─────────────────────────────────────────────────

  eventTypeLabel(eventType: string): string {
    const labels: Record<string, string> = {
      full_backup: 'Backed up',
      incremental: 'Incremental',
      created: 'Created',
      updated: 'Updated',
      deleted: 'Deleted',
      restored: 'Restored',
    };
    return labels[eventType] || eventType;
  }

  eventDotClass(eventType: string): string {
    const classes: Record<string, string> = {
      updated: 'dot-updated',
      deleted: 'dot-deleted',
      created: 'dot-created',
      restored: 'dot-restored',
      full_backup: 'dot-backup',
      incremental: 'dot-backup',
    };
    return classes[eventType] || 'dot-backup';
  }

  tooltipText(change: BackupChangeEvent): string {
    const name = change.object_name || change.object_id;
    const event = this.eventTypeLabel(change.event_type);
    const type = change.object_type;
    const fields = change.changed_fields.length > 0
      ? '\nChanged: ' + change.changed_fields.slice(0, 5).join(', ') +
        (change.changed_fields.length > 5 ? ` (+${change.changed_fields.length - 5})` : '')
      : '';
    return `${event}: ${name}\nType: ${type}${fields}`;
  }

  filterByTimelineEvent(change: BackupChangeEvent): void {
    this.filterForm.patchValue({ object_type: change.object_type });
    this.searchQuery = change.object_name || '';
    this.objectsPageIndex = 0;
    this.activeQuickFilter = null;
    this.loadObjects();
  }
}
