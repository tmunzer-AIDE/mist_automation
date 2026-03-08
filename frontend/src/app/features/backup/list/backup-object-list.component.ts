import { Component, ChangeDetectorRef, inject, OnInit } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { forkJoin } from 'rxjs';
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
import { BaseChartDirective } from 'ng2-charts';
import { ChartConfiguration } from 'chart.js/auto';
import { ApiService } from '../../../core/services/api.service';
import {
  BackupObjectSummary,
  BackupObjectListResponse,
  BackupObjectStatsResponse,
  BackupJobStatsResponse,
  MistObjectTypeOption,
  MistSiteOption,
} from '../../../core/models/backup.model';
import { PageHeaderComponent } from '../../../shared/components/page-header/page-header.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { BackupCreateDialogComponent } from './backup-create-dialog.component';
import { BackupChartCardComponent } from '../shared/backup-chart-card.component';

@Component({
  selector: 'app-backup-object-list',
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
    BaseChartDirective,
    PageHeaderComponent,
    EmptyStateComponent,
    StatusBadgeComponent,
    BackupChartCardComponent,
    DatePipe,
  ],
  templateUrl: './backup-object-list.component.html',
  styleUrl: './backup-object-list.component.scss',
})
export class BackupObjectListComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);
  private readonly cdr = inject(ChangeDetectorRef);
  private readonly fb = inject(FormBuilder);

  // ── Object table ─────────────────────────────────────────────────────
  objects: BackupObjectSummary[] = [];
  objectsTotal = 0;
  objectsPageSize = 25;
  objectsPageIndex = 0;
  loadingObjects = true;
  objectColumns = [
    'object_name',
    'object_type',
    'scope',
    'version_count',
    'last_backed_up_at',
    'status',
  ];

  // ── Sort ──────────────────────────────────────────────────────────────
  sortField = 'last_backed_up_at';
  sortDirection: 'asc' | 'desc' | '' = 'desc';

  // ── Filters ──────────────────────────────────────────────────────────
  searchQuery = '';
  objectTypeOptions: MistObjectTypeOption[] = [];
  objectType: MistObjectTypeOption[] = [];

  siteOptions: MistSiteOption[] = [];

  filterForm = this.fb.group({
    object_type: [''],
    scope: [''],
    status: [''],
    site_id: [''],
  });

  // ── Chart ────────────────────────────────────────────────────────────
  chartConfig: ChartConfiguration<'bar'> | null = null;

  ngOnInit(): void {
    this.loadObjectTypes();
    this.loadSites();
    this.loadObjects();
    this.loadCharts();
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

  private loadCharts(): void {
    const completed = '#2563eb';   // vivid blue
    const failed = '#ef4444';      // vivid red
    const objectsLine = '#10b981'; // vivid emerald
    const gridColor = '#e2e8f0';

    forkJoin({
      objects: this.api.get<BackupObjectStatsResponse>('/backups/stats/objects'),
      jobs: this.api.get<BackupJobStatsResponse>('/backups/stats/jobs'),
    }).subscribe({
      next: ({ objects, jobs }) => {
        const labels = objects.days.map((d) => d.date.slice(5));
        this.chartConfig = {
          type: 'bar',
          data: {
            labels,
            datasets: [
              {
                label: 'Jobs completed',
                data: jobs.days.map((d) => d.completed),
                backgroundColor: completed,
                borderRadius: 2,
                stack: 'jobs',
                order: 1,
                yAxisID: 'y',
              },
              {
                label: 'Jobs failed',
                data: jobs.days.map((d) => d.failed),
                backgroundColor: failed,
                borderRadius: 2,
                stack: 'jobs',
                order: 1,
                yAxisID: 'y',
              },
              {
                label: 'Objects backed up',
                data: objects.days.map((d) => d.object_count),
                type: 'line' as const,
                borderColor: objectsLine,
                backgroundColor: 'transparent',
                fill: false,
                pointRadius: 2,
                tension: 0.3,
                borderWidth: 2,
                order: 0,
                yAxisID: 'y1',
              } as any,
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: true } },
            scales: {
              x: {
                grid: { display: false },
                ticks: { maxTicksLimit: 15, font: { size: 10 } },
              },
              y: {
                position: 'left',
                stacked: true,
                beginAtZero: true,
                grid: { color: gridColor },
                ticks: { precision: 0, font: { size: 10 } },
                title: { display: true, text: 'Jobs', font: { size: 11 } },
              },
              y1: {
                position: 'right',
                beginAtZero: true,
                grid: { drawOnChartArea: false },
                ticks: { precision: 0, font: { size: 10 } },
                title: { display: true, text: 'Objects', font: { size: 11 } },
              },
            },
          },
        };
        this.cdr.detectChanges();
      },
    });
  }

  private loadObjectTypes(): void {
    this.api
      .get<{ object_types: MistObjectTypeOption[] }>('/admin/mist/object-types')
      .subscribe({
        next: (res) => {
          this.objectType = res.object_types;
          this.filterScopeObjects();
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
    this.filterScopeObjects();
    this.loadObjects();
  }

  clearFilters(): void {
    this.filterForm.reset({ object_type: '', scope: '', status: '', site_id: '' });
    this.searchQuery = '';
    this.objectsPageIndex = 0;
    this.filterScopeObjects();
    this.loadObjects();
  }

  get hasActiveFilters(): boolean {
    const f = this.filterForm.value;
    return !!(this.searchQuery || f.object_type || f.scope || f.status || f.site_id);
  }

  filterScopeObjects(): void {
    let scope = this.filterForm.get("scope")?.value;

    this.objectTypeOptions = this.objectType
        .filter(t => t.scope === scope || scope === '')
        .sort((a, b) => a.label.localeCompare(b.label));
      
    this.cdr.detectChanges();
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

  navigateToJobs(): void {
    this.router.navigate(['/backup', 'jobs']);
  }

  openCreateDialog(): void {
    const ref = this.dialog.open(BackupCreateDialogComponent, { width: '500px' });
    ref.afterClosed().subscribe((result) => {
      if (result) {
        this.snackBar.open('Backup job created', 'OK', { duration: 3000 });
        setTimeout(() => this.loadObjects(), 2000);
      }
    });
  }
}
