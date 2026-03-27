import { Component, computed, inject, signal } from '@angular/core';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-description-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatAutocompleteModule,
    MatChipsModule,
    MatIconModule,
  ],
  template: `
    <h2 mat-dialog-title>Edit Description</h2>
    <mat-dialog-content [formGroup]="form">
      <mat-form-field class="full-width">
        <mat-label>Description</mat-label>
        <textarea
          matInput
          formControlName="description"
          rows="5"
          placeholder="Describe what this workflow does..."
        ></textarea>
      </mat-form-field>

      <mat-form-field class="full-width">
        <mat-label>Sharing</mat-label>
        <input
          matInput
          [matAutocomplete]="sharingAuto"
          [value]="sharingDisplayValue()"
          (input)="sharingSearch.set($any($event.target).value)"
        />
        <mat-autocomplete
          #sharingAuto
          (optionSelected)="form.get('sharing')!.setValue($event.option.value)"
        >
          @for (opt of filteredSharingOptions(); track opt.value) {
            <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
          }
        </mat-autocomplete>
      </mat-form-field>

      <mat-form-field class="full-width">
        <mat-label>Tags</mat-label>
        <mat-chip-grid #tagChipGrid>
          @for (tag of tags(); track tag) {
            <mat-chip-row (removed)="removeTag(tag)">
              {{ tag }}
              <button matChipRemove><mat-icon>cancel</mat-icon></button>
            </mat-chip-row>
          }
        </mat-chip-grid>
        <input
          [matChipInputFor]="tagChipGrid"
          [value]="tagInput()"
          (input)="tagInput.set($any($event.target).value)"
          (keydown)="onTagKeydown($event)"
          (blur)="addTag()"
          placeholder="Type a tag and press Enter..."
        />
      </mat-form-field>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button mat-flat-button (click)="dialogRef.close({ ...form.getRawValue(), tags: tags() })">Save</button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .full-width {
        width: 100%;
      }
    `,
  ],
})
export class DescriptionDialogComponent {
  readonly dialogRef = inject(MatDialogRef<DescriptionDialogComponent>);
  private readonly data: { description: string; sharing: string; tags: string[] } = inject(MAT_DIALOG_DATA);
  private readonly fb = inject(FormBuilder);

  tags = signal<string[]>(this.data?.tags || []);
  tagInput = signal('');

  addTag(): void {
    const value = this.tagInput().trim();
    if (value && !this.tags().includes(value)) {
      this.tags.update((t) => [...t, value]);
    }
    this.tagInput.set('');
  }

  removeTag(tag: string): void {
    this.tags.update((t) => t.filter((v) => v !== tag));
  }

  onTagKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault();
      this.addTag();
    }
  }

  readonly sharingOptions = [
    { value: 'private', label: 'Private' },
    { value: 'read-only', label: 'Read-Only' },
    { value: 'read-write', label: 'Read-Write' },
  ];
  sharingSearch = signal('');
  filteredSharingOptions = computed(() => {
    const term = this.sharingSearch().toLowerCase();
    return term
      ? this.sharingOptions.filter((o) => o.label.toLowerCase().includes(term))
      : this.sharingOptions;
  });
  sharingDisplayValue = computed(() => {
    const val = this.form.get('sharing')?.value || 'private';
    return this.sharingOptions.find((o) => o.value === val)?.label ?? val;
  });

  form = this.fb.group({
    description: [this.data?.description || ''],
    sharing: [this.data?.sharing || 'private'],
  });
}
