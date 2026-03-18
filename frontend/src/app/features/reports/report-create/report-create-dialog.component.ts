import { Component, inject, OnInit, signal } from '@angular/core';
import { ReactiveFormsModule, FormControl, Validators } from '@angular/forms';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ApiService } from '../../../core/services/api.service';

interface SiteOption {
  id: string;
  name: string;
}

interface ReportTypeOption {
  value: string;
  label: string;
  description: string;
  endpoint: string;
}

const REPORT_TYPES: ReportTypeOption[] = [
  {
    value: 'post_deployment_validation',
    label: 'Post-Deployment Validation',
    description: 'Validates template variables, device names, firmware, connectivity, and cable tests.',
    endpoint: '/reports/validation',
  },
];

@Component({
  selector: 'app-report-create-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatSelectModule,
    MatButtonModule,
    MatProgressBarModule,
    MatSnackBarModule,
  ],
  template: `
    <h2 mat-dialog-title>New Report</h2>

    <mat-dialog-content>
      @if (loadingSites()) {
        <mat-progress-bar mode="indeterminate"></mat-progress-bar>
      }

      <mat-form-field appearance="outline" class="full-width">
        <mat-label>Report Type</mat-label>
        <mat-select [formControl]="reportTypeControl">
          @for (rt of reportTypes; track rt.value) {
            <mat-option [value]="rt.value">{{ rt.label }}</mat-option>
          }
        </mat-select>
      </mat-form-field>

      @if (selectedType()) {
        <p class="type-description">{{ selectedType()!.description }}</p>
      }

      <mat-form-field appearance="outline" class="full-width">
        <mat-label>Site</mat-label>
        <mat-select [formControl]="siteControl">
          @for (site of sites(); track site.id) {
            <mat-option [value]="site.id">{{ site.name }}</mat-option>
          }
        </mat-select>
      </mat-form-field>
    </mat-dialog-content>

    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button
        mat-flat-button
        color="primary"
        [disabled]="!siteControl.valid || !reportTypeControl.valid || submitting()"
        (click)="submit()"
      >
        Generate Report
      </button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .full-width {
        width: 100%;
        margin-top: 8px;
      }

      .type-description {
        font-size: 13px;
        color: var(--app-neutral);
        margin: -8px 0 8px;
      }
    `,
  ],
})
export class ReportCreateDialogComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly dialogRef = inject(MatDialogRef<ReportCreateDialogComponent>);
  private readonly snackBar = inject(MatSnackBar);

  readonly reportTypes = REPORT_TYPES;

  sites = signal<SiteOption[]>([]);
  loadingSites = signal(true);
  submitting = signal(false);
  selectedType = signal<ReportTypeOption | null>(REPORT_TYPES[0]);

  reportTypeControl = new FormControl<string>(REPORT_TYPES[0].value, {
    nonNullable: true,
    validators: [Validators.required],
  });
  siteControl = new FormControl<string>('', {
    nonNullable: true,
    validators: [Validators.required],
  });

  ngOnInit(): void {
    this.reportTypeControl.valueChanges.subscribe((value) => {
      this.selectedType.set(REPORT_TYPES.find((rt) => rt.value === value) ?? null);
    });

    this.api.get<{ sites: SiteOption[] }>('/reports/sites').subscribe({
      next: (res) => {
        this.sites.set(res.sites.sort((a, b) => a.name.localeCompare(b.name)));
        this.loadingSites.set(false);
      },
      error: () => {
        this.loadingSites.set(false);
        this.snackBar.open('Failed to load sites', 'OK', { duration: 3000 });
      },
    });
  }

  submit(): void {
    if (!this.siteControl.valid || !this.reportTypeControl.valid) return;

    const reportType = this.selectedType();
    if (!reportType) return;

    this.submitting.set(true);
    this.api
      .post<{ id: string }>(reportType.endpoint, { site_id: this.siteControl.value })
      .subscribe({
        next: (res) => {
          this.submitting.set(false);
          this.dialogRef.close(res.id);
        },
        error: () => {
          this.submitting.set(false);
          this.snackBar.open('Failed to create report', 'OK', { duration: 3000 });
        },
      });
  }
}
