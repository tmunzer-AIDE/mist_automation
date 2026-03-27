import { Component, computed, inject, OnInit, signal, ViewChild } from '@angular/core';
import { NgClass } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { ReactiveFormsModule, FormBuilder, FormControl } from '@angular/forms';
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
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { BaseChartDirective } from 'ng2-charts';
import { ChartConfiguration } from 'chart.js/auto';
import { ApiService } from '../../../core/services/api.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { GlobalChatService } from '../../../core/services/global-chat.service';
import {
  BackupObjectSummary,
  BackupObjectListResponse,
  BackupObjectStatsResponse,
  BackupJobStatsResponse,
  MistObjectTypeOption,
  MistSiteOption,
} from '../../../core/models/backup.model';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { BackupCreateDialogComponent } from './backup-create-dialog.component';
import { BackupChartCardComponent } from '../shared/backup-chart-card.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import {
  getChartColor,
  baseChartOptions,
  barDataset,
  lineDataset,
} from '../../../shared/utils/chart-defaults';

@Component({
  selector: 'app-backup-object-list',
  standalone: true,
  imports: [
    NgClass,
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
    MatAutocompleteModule,
    BaseChartDirective,
    EmptyStateComponent,
    StatusBadgeComponent,
    BackupChartCardComponent,
    DateTimePipe,
  ],
  templateUrl: './backup-object-list.component.html',
  styleUrl: './backup-object-list.component.scss',
})
export class BackupObjectListComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);
  private readonly fb = inject(FormBuilder);
  private readonly topbarService = inject(TopbarService);
  private readonly globalChatService = inject(GlobalChatService);

  // ── Object table ─────────────────────────────────────────────────────
  objects = signal<BackupObjectSummary[]>([]);
  objectsTotal = signal(0);
  objectsPageSize = 25;
  objectsPageIndex = 0;
  loadingObjects = signal(true);
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
  searchControl = new FormControl('');
  searchQuery = '';
  objectTypeOptions = signal<MistObjectTypeOption[]>([]);
  objectType = signal<MistObjectTypeOption[]>([]);

  siteOptions = signal<MistSiteOption[]>([]);

  // ── Select search ──────────────────────────────────────────────────
  scopeSearch = signal('');
  typeSearch = signal('');
  siteSearch = signal('');
  statusSearch = signal('');

  private readonly scopeOptions = [
    { value: '', label: 'All' },
    { value: 'org', label: 'Org' },
    { value: 'site', label: 'Site' },
  ];
  filteredScopeOptions = computed(() => {
    const q = this.scopeSearch().toLowerCase();
    return q ? this.scopeOptions.filter((o) => o.label.toLowerCase().includes(q)) : this.scopeOptions;
  });

  filteredTypeOptions = computed(() => {
    const q = this.typeSearch().toLowerCase();
    const all = this.objectTypeOptions();
    return q ? all.filter((o) => o.label.toLowerCase().includes(q)) : all;
  });

  filteredSiteOptions = computed(() => {
    const q = this.siteSearch().toLowerCase();
    const all = this.siteOptions();
    return q ? all.filter((s) => s.name.toLowerCase().includes(q)) : all;
  });

  private readonly statusOptions = [
    { value: '', label: 'All' },
    { value: 'active', label: 'Active' },
    { value: 'deleted', label: 'Deleted' },
  ];
  filteredStatusOptions = computed(() => {
    const q = this.statusSearch().toLowerCase();
    return q
      ? this.statusOptions.filter((o) => o.label.toLowerCase().includes(q))
      : this.statusOptions;
  });

  // ── Display values for autocomplete inputs ─────────────────────────
  scopeDisplayValue = computed(() => {
    const val = this.filterForm.get('scope')?.value;
    return this.scopeOptions.find((o) => o.value === val)?.label ?? '';
  });

  typeDisplayValue = computed(() => {
    const val = this.filterForm.get('object_type')?.value;
    if (!val) return 'All';
    return this.objectTypeOptions().find((o) => o.value.split(':')[1] === val)?.label ?? '';
  });

  siteDisplayValue = computed(() => {
    const val = this.filterForm.get('site_id')?.value;
    if (!val) return 'All';
    return this.siteOptions().find((s) => s.id === val)?.name ?? '';
  });

  statusDisplayValue = computed(() => {
    const val = this.filterForm.get('status')?.value;
    return this.statusOptions.find((o) => o.value === val)?.label ?? '';
  });

  filterForm = this.fb.group({
    object_type: [''],
    scope: [''],
    status: [''],
    site_id: [''],
  });

  // ── Chart ────────────────────────────────────────────────────────────
  @ViewChild(BaseChartDirective) private chartDirective?: BaseChartDirective;
  chartConfig = signal<ChartConfiguration<'bar'> | null>(null);

  ngOnInit(): void {
    this.topbarService.setTitle('Backups');
    this.globalChatService.setContext({ page: 'Backups' });
    this.loadObjectTypes();
    this.loadSites();
    this.loadObjects();
    this.loadCharts();
  }

  // ── Data loading ─────────────────────────────────────────────────────

  loadObjects(): void {
    this.loadingObjects.set(true);
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
        this.objects.set(res.objects);
        this.objectsTotal.set(res.total);
        this.loadingObjects.set(false);
      },
      error: () => {
        this.loadingObjects.set(false);
      },
    });
  }

  private loadCharts(animate = true): void {
    forkJoin({
      objects: this.api.get<BackupObjectStatsResponse>('/backups/stats/objects'),
      jobs: this.api.get<BackupJobStatsResponse>('/backups/stats/jobs'),
    }).subscribe({
      next: ({ objects, jobs }) => {
        const labels = objects.days.map((d) => d.date.slice(5));
        const options = baseChartOptions('Jobs', 'Objects');
        const data = {
          labels,
          datasets: [
            barDataset(
              'Jobs completed',
              jobs.days.map((d) => d.completed),
              getChartColor('completed'),
            ),
            barDataset(
              'Jobs failed',
              jobs.days.map((d) => d.failed),
              getChartColor('failed'),
            ),
            lineDataset(
              'Objects backed up',
              objects.days.map((d) => d.object_count),
              getChartColor('objects'),
            ),
          ],
        };

        if (!animate && this.chartDirective?.chart) {
          const chart = this.chartDirective.chart;
          chart.data = data;
          chart.options = options as any;
          chart.update('none');
        } else {
          this.chartConfig.set({ type: 'bar', data, options });
        }
      },
    });
  }

  private loadObjectTypes(): void {
    this.api.get<{ object_types: MistObjectTypeOption[] }>('/admin/mist/object-types').subscribe({
      next: (res) => {
        this.objectType.set(res.object_types);
        this.filterScopeObjects();
      },
    });
  }

  private loadSites(): void {
    this.api.get<{ sites: MistSiteOption[] }>('/admin/mist/sites').subscribe({
      next: (res) => {
        this.siteOptions.set(res.sites);
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

  applySearch(): void {
    this.searchQuery = (this.searchControl.value || '').trim();
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
    let scope = this.filterForm.get('scope')?.value;

    this.objectTypeOptions.set(
      this.objectType()
        .filter((t) => t.scope === scope || scope === '')
        .sort((a, b) => a.label.localeCompare(b.label)),
    );
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
        setTimeout(() => {
          this.loadObjects();
          this.loadCharts(false);
        }, 2000);
      }
    });
  }
}
