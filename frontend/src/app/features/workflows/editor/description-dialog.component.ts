import { Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';

@Component({
  selector: 'app-description-dialog',
  standalone: true,
  imports: [FormsModule, MatDialogModule, MatFormFieldModule, MatInputModule, MatButtonModule],
  template: `
    <h2 mat-dialog-title>Edit Description</h2>
    <mat-dialog-content>
      <mat-form-field class="full-width">
        <mat-label>Description</mat-label>
        <textarea
          matInput
          [(ngModel)]="description"
          rows="5"
          placeholder="Describe what this workflow does..."
        ></textarea>
      </mat-form-field>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button mat-flat-button (click)="dialogRef.close(description)">Save</button>
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
  private readonly data: string = inject(MAT_DIALOG_DATA);

  description = this.data || '';
}
