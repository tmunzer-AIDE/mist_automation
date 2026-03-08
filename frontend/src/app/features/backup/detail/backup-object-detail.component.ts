import { Component, ChangeDetectorRef, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatMenuModule } from '@angular/material/menu';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ApiService } from '../../../core/services/api.service';
import { PageHeaderComponent } from '../../../shared/components/page-header/page-header.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { RelativeTimePipe } from '../../../shared/pipes/relative-time.pipe';
import { JsonViewDialogComponent } from './json-view-dialog.component';

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
    MatDialogModule,
    MatSnackBarModule,
    PageHeaderComponent,
    EmptyStateComponent,
    StatusBadgeComponent,
    RelativeTimePipe,
  ],
  templateUrl: './backup-object-detail.component.html',
  styleUrl: './backup-object-detail.component.scss',
})
export class BackupObjectDetailComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly cdr = inject(ChangeDetectorRef);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);

  objectId = '';
  versions: ObjectVersion[] = [];
  loading = true;
  selectedVersionId: string | null = null;

  versionColumns = ['version', 'date', 'admin', 'event_type', 'changed_fields', 'actions'];

  get latestVersion(): ObjectVersion | null {
    return this.versions.length > 0 ? this.versions[0] : null;
  }

  get oldestVersion(): ObjectVersion | null {
    return this.versions.length > 0 ? this.versions[this.versions.length - 1] : null;
  }

  ngOnInit(): void {
    this.objectId = this.route.snapshot.paramMap.get('objectId') || '';
    this.loadVersions();
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

  dotClass(eventType: string): string {
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

  versionTooltip(v: ObjectVersion): string {
    const event = this.eventLabel(v.event_type);
    const admin = v.backed_up_by ? `\nBy: ${v.backed_up_by}` : '';
    const fields = v.changed_fields.length > 0
      ? '\nChanged: ' + v.changed_fields.slice(0, 5).join(', ')
      : '';
    return `v${v.version} — ${event}${admin}${fields}`;
  }

  selectVersion(v: ObjectVersion): void {
    this.selectedVersionId = this.selectedVersionId === v.id ? null : v.id;
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
    this.snackBar.open(
      `Restore v${v.version}? This feature is coming soon.`,
      'OK',
      { duration: 4000 }
    );
  }

  private loadVersions(): void {
    this.loading = true;
    this.api
      .get<{ versions: ObjectVersion[]; total: number }>(
        `/backups/objects/${this.objectId}/versions`
      )
      .subscribe({
        next: (res) => {
          this.versions = res.versions;
          this.loading = false;
          this.cdr.detectChanges();
        },
        error: () => {
          this.loading = false;
          this.cdr.detectChanges();
        },
      });
  }
}
