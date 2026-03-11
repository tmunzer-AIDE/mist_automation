import { Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTableModule } from '@angular/material/table';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatChipsModule } from '@angular/material/chips';
import { ApiService } from '../../../core/services/api.service';
import { TopbarService } from '../../../core/services/topbar.service';
import { BackupDiffResponse } from '../../../core/models/backup.model';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';

@Component({
  selector: 'app-backup-compare',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatTableModule,
    MatProgressBarModule,
    MatChipsModule,
    EmptyStateComponent,
  ],
  templateUrl: './backup-compare.component.html',
  styleUrl: './backup-compare.component.scss',
})
export class BackupCompareComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly fb = inject(FormBuilder);
  private readonly route = inject(ActivatedRoute);
  private readonly topbarService = inject(TopbarService);

  loading = signal(false);
  diff = signal<BackupDiffResponse | null>(null);
  displayedColumns = ['path', 'change_type', 'old_value', 'new_value'];

  form = this.fb.group({
    backup_id_1: ['', Validators.required],
    backup_id_2: ['', Validators.required],
  });

  ngOnInit(): void {
    this.topbarService.setTitle('Compare Backups');
    const id1 = this.route.snapshot.queryParamMap.get('id1');
    if (id1) {
      this.form.patchValue({ backup_id_1: id1 });
    }
  }

  compare(): void {
    if (this.form.invalid) return;
    this.loading.set(true);
    this.diff.set(null);

    const { backup_id_1, backup_id_2 } = this.form.getRawValue();
    this.api
      .get<BackupDiffResponse>('/backups/compare', {
        backup_id_1: backup_id_1!,
        backup_id_2: backup_id_2!,
      })
      .subscribe({
        next: (d) => {
          this.diff.set(d);
          this.loading.set(false);
        },
        error: () => {
          this.loading.set(false);
        },
      });
  }
}
