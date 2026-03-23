import { Component, inject } from '@angular/core';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatSelectModule } from '@angular/material/select';

@Component({
  selector: 'app-description-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatSelectModule,
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
        <mat-select formControlName="sharing">
          <mat-option value="private">Private</mat-option>
          <mat-option value="read-only">Read-Only</mat-option>
          <mat-option value="read-write">Read-Write</mat-option>
        </mat-select>
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

  form = this.fb.group({
    description: [this.data?.description || ''],
    sharing: [this.data?.sharing || 'private'],
  });
}
