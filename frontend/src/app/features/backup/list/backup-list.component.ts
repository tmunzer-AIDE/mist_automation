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
import { MatTabsModule } from '@angular/material/tabs';
import { MatMenuModule } from '@angular/material/menu';
import { ApiService } from '../../../core/services/api.service';
import {
  BackupJobResponse,
  BackupJobListResponse,
  BackupObjectSummary,
  BackupObjectListResponse,
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
    MatTabsModule,
    MatMenuModule,
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

  // ── Tabs ──────────────────────────────────────────────────────────────
  activeTabIndex = 1; // Default to Objects tab

  // ── Backup jobs ─────────────────────────────────────────────────────
  jobs: BackupJobResponse[] = [];
  jobsTotal = 0;
  jobsPageSize = 10;
  jobsPageIndex = 0;
  loadingJobs = true;
  jobColumns = ['status', 'backup_type', 'object_count', 'size', 'created_at'];

  // ── Object table ─────────────────────────────────────────────────────
  objects: BackupObjectSummary[] = [];
  objectsTotal = 0;
  objectsPageSize = 25;
  objectsPageIndex = 0;
  loadingObjects = true;
  objectColumns = ['object_name', 'object_type', 'scope', 'version_count', 'last_backed_up_at', 'status'];

  // ── Sort ──────────────────────────────────────────────────────────────
  sortField = 'last_backed_up_at';
  sortDirection: 'asc' | 'desc' | '' = 'desc';

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

  ngOnInit(): void {
    this.loadObjectTypes();
    this.loadSites();
    this.loadObjects();
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

  loadJobs(): void {
    this.loadingJobs = true;
    const params: Record<string, string | number> = {
      skip: this.jobsPageIndex * this.jobsPageSize,
      limit: this.jobsPageSize,
    };
    this.api.get<BackupJobListResponse>('/backups', params).subscribe({
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
    this.objectsPageIndex = 0;
    this.loadObjects();
  }

  clearFilters(): void {
    this.filterForm.reset({ object_type: '', scope: '', status: '', site_id: '' });
    this.searchQuery = '';
    this.objectsPageIndex = 0;
    this.loadObjects();
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

  onJobsPage(event: PageEvent): void {
    this.jobsPageIndex = event.pageIndex;
    this.jobsPageSize = event.pageSize;
    this.loadJobs();
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
        setTimeout(() => {
          this.loadObjects();
          this.loadJobs();
        }, 2000);
      }
    });
  }
}
