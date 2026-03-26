import { Component, computed, inject, signal } from '@angular/core';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatAutocompleteModule } from '@angular/material/autocomplete';

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
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button mat-flat-button (click)="dialogRef.close(form.getRawValue())">Save</button>
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
  private readonly data: { description: string; sharing: string } = inject(MAT_DIALOG_DATA);
  private readonly fb = inject(FormBuilder);

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
