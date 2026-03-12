import { Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatListModule, MatSelectionListChange } from '@angular/material/list';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ApiService } from '../../../core/services/api.service';
import {
  MistSiteOption,
  MistObjectOption,
  MistObjectTypeOption,
} from '../../../core/models/backup.model';
import { extractErrorMessage } from '../../../shared/utils/error.utils';

const BACKUP_TYPES = [
  { value: 'full', label: 'Full Backup', description: 'Backup the entire organization' },
  { value: 'manual', label: 'Manual Backup', description: 'Select specific objects to backup' },
];

@Component({
  selector: 'app-backup-create-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatCheckboxModule,
    MatProgressBarModule,
    MatListModule,
    MatIconModule,
    MatSnackBarModule,
  ],
  template: `
    <h2 mat-dialog-title>Create Backup</h2>
    <mat-dialog-content>
      <form [formGroup]="form" class="dialog-form">
        <!-- Backup Type -->
        <mat-form-field appearance="outline">
          <mat-label>Backup Type</mat-label>
          <mat-select formControlName="backup_type" (selectionChange)="onTypeChange()">
            @for (type of backupTypes; track type.value) {
              <mat-option [value]="type.value">{{ type.label }}</mat-option>
            }
          </mat-select>
          @if (selectedTypeDescription) {
            <mat-hint>{{ selectedTypeDescription }}</mat-hint>
          }
        </mat-form-field>

        <!-- Manual backup options -->
        @if (form.value.backup_type === 'manual') {
          <!-- Object type selection (grouped by scope) -->
          <mat-form-field appearance="outline">
            <mat-label>Object Type</mat-label>
            <mat-select formControlName="object_type" (selectionChange)="onObjectTypeChange()">
              @if (loadingObjectTypes()) {
                <mat-option disabled>Loading...</mat-option>
              }
              <mat-optgroup label="Organization">
                @for (otype of orgObjectTypes(); track otype.value) {
                  <mat-option [value]="otype.value">{{ otype.label }}</mat-option>
                }
              </mat-optgroup>
              <mat-optgroup label="Site">
                @for (otype of siteObjectTypes(); track otype.value) {
                  <mat-option [value]="otype.value">{{ otype.label }}</mat-option>
                }
              </mat-optgroup>
            </mat-select>
          </mat-form-field>

          <!-- Site selection (only for site-scoped types) -->
          @if (selectedObjectTypeDef?.scope === 'site') {
            <mat-form-field appearance="outline">
              <mat-label>Site</mat-label>
              <mat-select formControlName="site_id" (selectionChange)="onSiteChange()">
                @for (site of sites(); track site.id) {
                  <mat-option [value]="site.id">{{ site.name }}</mat-option>
                }
              </mat-select>
              @if (loadingSites()) {
                <mat-hint>Loading sites...</mat-hint>
              }
            </mat-form-field>
          }

          <!-- Object selection (only for list types) -->
          @if (shouldShowObjectList) {
            @if (loadingObjects()) {
              <mat-progress-bar mode="indeterminate"></mat-progress-bar>
            }

            @if (!loadingObjects() && objects().length === 0) {
              <p class="no-objects">No objects found for this type.</p>
            }

            @if (!loadingObjects() && objects().length > 0) {
              <div class="object-list-header">
                <span class="object-count"
                  >{{ selectedObjectIds().length }} of {{ objects().length }} selected</span
                >
                <button mat-button type="button" (click)="toggleSelectAll()">
                  {{ selectedObjectIds().length === objects().length ? 'Deselect All' : 'Select All' }}
                </button>
              </div>
              <mat-selection-list (selectionChange)="onObjectSelectionChange($event)">
                @for (obj of objects(); track obj.id) {
                  <mat-list-option [value]="obj.id" [selected]="selectedObjectIds().includes(obj.id)">
                    {{ obj.name || obj.id }}
                    @if (obj.type) {
                      <span class="object-type-badge">{{ obj.type }}</span>
                    }
                  </mat-list-option>
                }
              </mat-selection-list>
            }
          }
        }
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button mat-flat-button (click)="create()" [disabled]="!canCreate() || creating()">
        {{ creating() ? 'Creating...' : 'Create Backup' }}
      </button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .dialog-form {
        display: flex;
        flex-direction: column;
        min-width: 420px;
        gap: 4px;
      }
      mat-form-field {
        width: 100%;
      }
      .object-list-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 4px;
      }
      .object-count {
        font-size: 13px;
        color: var(--mat-sys-on-surface-variant);
      }
      mat-selection-list {
        max-height: 280px;
        overflow-y: auto;
        border: 1px solid var(--mat-sys-outline-variant);
        border-radius: 8px;
      }
      .no-objects {
        text-align: center;
        color: var(--mat-sys-on-surface-variant);
        padding: 16px;
      }
      .object-type-badge {
        font-size: 11px;
        background: var(--mat-sys-surface-variant);
        padding: 2px 6px;
        border-radius: 4px;
        margin-left: 8px;
      }
    `,
  ],
})
export class BackupCreateDialogComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(ApiService);
  private readonly dialogRef = inject(MatDialogRef<BackupCreateDialogComponent>);
  private readonly snackBar = inject(MatSnackBar);

  backupTypes = BACKUP_TYPES;
  creating = signal(false);
  loadingSites = signal(false);
  loadingObjects = signal(false);
  loadingObjectTypes = signal(false);

  sites = signal<MistSiteOption[]>([]);
  objects = signal<MistObjectOption[]>([]);
  selectedObjectIds = signal<string[]>([]);

  allObjectTypes = signal<MistObjectTypeOption[]>([]);
  orgObjectTypes = signal<MistObjectTypeOption[]>([]);
  siteObjectTypes = signal<MistObjectTypeOption[]>([]);

  form = this.fb.group({
    backup_type: ['full', Validators.required],
    site_id: [''],
    object_type: [''],
  });

  get selectedTypeDescription(): string {
    const type = this.backupTypes.find((t) => t.value === this.form.value.backup_type);
    return type?.description ?? '';
  }

  get selectedObjectTypeDef(): MistObjectTypeOption | undefined {
    return this.allObjectTypes().find((t) => t.value === this.form.value.object_type);
  }

  get shouldShowObjectList(): boolean {
    const def = this.selectedObjectTypeDef;
    if (!def || !def.is_list) return false;
    if (def.scope === 'site') return !!this.form.value.site_id;
    return true;
  }

  ngOnInit(): void {
    this.loadSites();
    this.loadObjectTypes();
  }

  onTypeChange(): void {
    if (this.form.value.backup_type === 'full') {
      this.form.patchValue({ site_id: '', object_type: '' });
      this.objects.set([]);
      this.selectedObjectIds.set([]);
    }
  }

  onSiteChange(): void {
    this.objects.set([]);
    this.selectedObjectIds.set([]);
    if (this.selectedObjectTypeDef?.is_list) {
      this.loadObjects();
    }
  }

  onObjectTypeChange(): void {
    this.form.patchValue({ site_id: '' });
    this.objects.set([]);
    this.selectedObjectIds.set([]);

    const def = this.selectedObjectTypeDef;
    if (def?.is_list && def.scope === 'org') {
      this.loadObjects();
    }
  }

  onObjectSelectionChange(event: MatSelectionListChange): void {
    this.selectedObjectIds.update((ids) => {
      let updated = [...ids];
      for (const option of event.options) {
        if (option.selected) {
          if (!updated.includes(option.value)) {
            updated.push(option.value);
          }
        } else {
          updated = updated.filter((id) => id !== option.value);
        }
      }
      return updated;
    });
  }

  toggleSelectAll(): void {
    if (this.selectedObjectIds().length === this.objects().length) {
      this.selectedObjectIds.set([]);
    } else {
      this.selectedObjectIds.set(this.objects().map((o) => o.id));
    }
  }

  canCreate(): boolean {
    if (this.form.value.backup_type === 'full') {
      return true;
    }

    const def = this.selectedObjectTypeDef;
    if (!def) return false;

    // Site-scoped types require a site
    if (def.scope === 'site' && !this.form.value.site_id) return false;

    // List types require at least one selected object
    if (def.is_list && this.selectedObjectIds().length === 0) return false;

    return true;
  }

  create(): void {
    if (!this.canCreate()) return;
    this.creating.set(true);

    const body: Record<string, unknown> = {
      backup_type: this.form.value.backup_type,
    };

    if (this.form.value.backup_type === 'manual') {
      body['object_type'] = this.form.value.object_type;
      if (this.form.value.site_id) {
        body['site_id'] = this.form.value.site_id;
      }
      if (this.selectedObjectTypeDef?.is_list) {
        body['object_ids'] = this.selectedObjectIds();
      }
    }

    this.api.post('/backups', body).subscribe({
      next: () => this.dialogRef.close(true),
      error: (err) => {
        this.creating.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  private loadSites(): void {
    this.loadingSites.set(true);
    this.api.get<{ sites: MistSiteOption[] }>('/admin/mist/sites').subscribe({
      next: (res) => {
        this.sites.set(res.sites);
        this.loadingSites.set(false);
      },
      error: () => {
        this.loadingSites.set(false);
        this.snackBar.open('Failed to load sites from Mist', 'OK', { duration: 5000 });
      },
    });
  }

  private loadObjectTypes(): void {
    this.loadingObjectTypes.set(true);
    this.api.get<{ object_types: MistObjectTypeOption[] }>('/admin/mist/object-types').subscribe({
      next: (res) => {
        this.allObjectTypes.set(res.object_types);
        this.orgObjectTypes.set(res.object_types.filter((t) => t.scope === 'org'));
        this.siteObjectTypes.set(res.object_types.filter((t) => t.scope === 'site'));
        this.loadingObjectTypes.set(false);
      },
      error: () => {
        this.loadingObjectTypes.set(false);
        this.snackBar.open('Failed to load object types', 'OK', { duration: 5000 });
      },
    });
  }

  private loadObjects(): void {
    const objectType = this.form.value.object_type;
    if (!objectType) return;

    const params: Record<string, string> = { object_type: objectType };
    if (this.form.value.site_id) {
      params['site_id'] = this.form.value.site_id;
    }

    this.loadingObjects.set(true);
    this.api.get<{ objects: MistObjectOption[] }>('/admin/mist/objects', params).subscribe({
      next: (res) => {
        this.objects.set(res.objects);
        this.loadingObjects.set(false);
      },
      error: () => {
        this.loadingObjects.set(false);
        this.snackBar.open('Failed to load objects from Mist', 'OK', { duration: 5000 });
      },
    });
  }
}
