import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { MatTabsModule } from '@angular/material/tabs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { TopbarService } from '../../core/services/topbar.service';

interface LicenseEntry {
  name: string;
  version: string;
  license: string;
  url: string;
  author: string;
}

interface LicensesData {
  generated_at: string;
  backend: LicenseEntry[];
  frontend: LicenseEntry[];
}

@Component({
  selector: 'app-about',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatPaginatorModule,
    MatProgressBarModule,
    MatTableModule,
    MatTabsModule,
  ],
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate" />
    }

    <div class="about-container">
      <div class="about-header">
        <h2>Third-Party Licenses</h2>
        @if (generatedAt()) {
          <span class="generated-at">Last updated: {{ generatedAt() }}</span>
        }
      </div>

      <mat-tab-group>
        <mat-tab [label]="'Python / Backend (' + allBackend().length + ')'">
          <div class="tab-content">
            <mat-form-field class="search-field" appearance="outline">
              <mat-label>Search packages</mat-label>
              <input matInput [formControl]="backendSearch" placeholder="Name or license..." />
              <mat-icon matSuffix>search</mat-icon>
            </mat-form-field>

            <div class="table-card">
              <table mat-table [dataSource]="pagedBackend()">
                <ng-container matColumnDef="name">
                  <th mat-header-cell *matHeaderCellDef>Package</th>
                  <td mat-cell *matCellDef="let row">{{ row.name }}</td>
                </ng-container>
                <ng-container matColumnDef="version">
                  <th mat-header-cell *matHeaderCellDef>Version</th>
                  <td mat-cell *matCellDef="let row" class="version-cell">{{ row.version }}</td>
                </ng-container>
                <ng-container matColumnDef="license">
                  <th mat-header-cell *matHeaderCellDef>License</th>
                  <td mat-cell *matCellDef="let row">{{ row.license }}</td>
                </ng-container>
                <ng-container matColumnDef="link">
                  <th mat-header-cell *matHeaderCellDef></th>
                  <td mat-cell *matCellDef="let row" class="link-cell">
                    @if (row.url) {
                      <a mat-icon-button [href]="row.url" target="_blank" rel="noopener noreferrer">
                        <mat-icon>open_in_new</mat-icon>
                      </a>
                    }
                  </td>
                </ng-container>
                <tr mat-header-row *matHeaderRowDef="columns"></tr>
                <tr mat-row *matRowDef="let row; columns: columns"></tr>
                @if (filteredBackend().length === 0) {
                  <tr class="mat-mdc-row">
                    <td [attr.colspan]="columns.length" class="empty-cell">No packages match your search.</td>
                  </tr>
                }
              </table>
            </div>

            <mat-paginator
              [length]="backendTotal()"
              [pageSize]="backendPageSize()"
              [pageSizeOptions]="pageSizes"
              [pageIndex]="backendPage()"
              (page)="onBackendPage($event)"
            />
          </div>
        </mat-tab>

        <mat-tab [label]="'npm / Frontend (' + allFrontend().length + ')'">
          <div class="tab-content">
            <mat-form-field class="search-field" appearance="outline">
              <mat-label>Search packages</mat-label>
              <input matInput [formControl]="frontendSearch" placeholder="Name or license..." />
              <mat-icon matSuffix>search</mat-icon>
            </mat-form-field>

            <div class="table-card">
              <table mat-table [dataSource]="pagedFrontend()">
                <ng-container matColumnDef="name">
                  <th mat-header-cell *matHeaderCellDef>Package</th>
                  <td mat-cell *matCellDef="let row">{{ row.name }}</td>
                </ng-container>
                <ng-container matColumnDef="version">
                  <th mat-header-cell *matHeaderCellDef>Version</th>
                  <td mat-cell *matCellDef="let row" class="version-cell">{{ row.version }}</td>
                </ng-container>
                <ng-container matColumnDef="license">
                  <th mat-header-cell *matHeaderCellDef>License</th>
                  <td mat-cell *matCellDef="let row">{{ row.license }}</td>
                </ng-container>
                <ng-container matColumnDef="link">
                  <th mat-header-cell *matHeaderCellDef></th>
                  <td mat-cell *matCellDef="let row" class="link-cell">
                    @if (row.url) {
                      <a mat-icon-button [href]="row.url" target="_blank" rel="noopener noreferrer">
                        <mat-icon>open_in_new</mat-icon>
                      </a>
                    }
                  </td>
                </ng-container>
                <tr mat-header-row *matHeaderRowDef="columns"></tr>
                <tr mat-row *matRowDef="let row; columns: columns"></tr>
                @if (filteredFrontend().length === 0) {
                  <tr class="mat-mdc-row">
                    <td [attr.colspan]="columns.length" class="empty-cell">No packages match your search.</td>
                  </tr>
                }
              </table>
            </div>

            <mat-paginator
              [length]="frontendTotal()"
              [pageSize]="frontendPageSize()"
              [pageSizeOptions]="pageSizes"
              [pageIndex]="frontendPage()"
              (page)="onFrontendPage($event)"
            />
          </div>
        </mat-tab>
      </mat-tab-group>
    </div>
  `,
  styles: [
    `
      .about-container {
        padding: 24px;
        max-width: 1100px;
      }

      .about-header {
        display: flex;
        align-items: baseline;
        gap: 16px;
        margin-bottom: 24px;

        h2 {
          margin: 0;
          font-size: 1.5rem;
          font-weight: 500;
        }

        .generated-at {
          font-size: 0.8rem;
          color: var(--mat-sys-on-surface-variant);
        }
      }

      .tab-content {
        padding-top: 20px;
      }

      .search-field {
        width: 100%;
        max-width: 400px;
        margin-bottom: 16px;
      }

      .table-card {
        overflow-x: auto;
      }

      table {
        width: 100%;
      }

      .version-cell {
        color: var(--mat-sys-on-surface-variant);
        font-size: 0.85rem;
        white-space: nowrap;
        width: 120px;
      }

      .link-cell {
        width: 48px;
        text-align: center;
      }

      .empty-cell {
        padding: 24px;
        text-align: center;
        color: var(--mat-sys-on-surface-variant);
      }
    `,
  ],
})
export class AboutComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly topbarService = inject(TopbarService);
  private readonly destroyRef = inject(DestroyRef);

  readonly pageSizes = [25, 50, 100];
  readonly columns = ['name', 'version', 'license', 'link'];

  loading = signal(true);
  generatedAt = signal('');
  allBackend = signal<LicenseEntry[]>([]);
  allFrontend = signal<LicenseEntry[]>([]);

  backendFilter = signal('');
  frontendFilter = signal('');
  backendPage = signal(0);
  frontendPage = signal(0);
  backendPageSize = signal(25);
  frontendPageSize = signal(25);

  filteredBackend = computed(() => {
    const f = this.backendFilter().toLowerCase();
    return this.allBackend().filter(
      (l) => !f || l.name.toLowerCase().includes(f) || l.license.toLowerCase().includes(f),
    );
  });

  filteredFrontend = computed(() => {
    const f = this.frontendFilter().toLowerCase();
    return this.allFrontend().filter(
      (l) => !f || l.name.toLowerCase().includes(f) || l.license.toLowerCase().includes(f),
    );
  });

  pagedBackend = computed(() => {
    const page = this.backendPage();
    const size = this.backendPageSize();
    return this.filteredBackend().slice(page * size, (page + 1) * size);
  });

  pagedFrontend = computed(() => {
    const page = this.frontendPage();
    const size = this.frontendPageSize();
    return this.filteredFrontend().slice(page * size, (page + 1) * size);
  });

  backendTotal = computed(() => this.filteredBackend().length);
  frontendTotal = computed(() => this.filteredFrontend().length);

  backendSearch = new FormControl('');
  frontendSearch = new FormControl('');

  ngOnInit(): void {
    this.topbarService.setTitle('About');

    this.http.get<LicensesData>('assets/licenses.json').subscribe({
      next: (data) => {
        this.generatedAt.set(data.generated_at);
        this.allBackend.set(data.backend);
        this.allFrontend.set(data.frontend);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });

    this.backendSearch.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((v) => {
      this.backendFilter.set((v ?? '').trim().toLowerCase());
      this.backendPage.set(0);
    });

    this.frontendSearch.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((v) => {
      this.frontendFilter.set((v ?? '').trim().toLowerCase());
      this.frontendPage.set(0);
    });
  }

  onBackendPage(event: PageEvent): void {
    this.backendPage.set(event.pageIndex);
    this.backendPageSize.set(event.pageSize);
  }

  onFrontendPage(event: PageEvent): void {
    this.frontendPage.set(event.pageIndex);
    this.frontendPageSize.set(event.pageSize);
  }
}
