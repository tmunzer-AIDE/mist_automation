import {
  Component,
  Input,
  Output,
  EventEmitter,
  ViewChild,
  input,
  output,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule, MatTableDataSource } from '@angular/material/table';
import { MatPaginatorModule, MatPaginator, PageEvent } from '@angular/material/paginator';
import { MatSortModule, MatSort, Sort } from '@angular/material/sort';
import { MatProgressBarModule } from '@angular/material/progress-bar';

export interface TableColumn {
  key: string;
  label: string;
  sortable?: boolean;
}

@Component({
  selector: 'app-data-table',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatPaginatorModule,
    MatSortModule,
    MatProgressBarModule,
  ],
  template: `
    @if (loading) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    }
    <div class="table-container">
      <table mat-table [dataSource]="dataSource" matSort (matSortChange)="onSort($event)">
        @for (col of columns; track col.key) {
          <ng-container [matColumnDef]="col.key">
            <th mat-header-cell *matHeaderCellDef [mat-sort-header]="col.sortable !== false ? col.key : ''">
              {{ col.label }}
            </th>
            <td mat-cell *matCellDef="let row">
              <ng-content *ngTemplateOutlet="null"></ng-content>
              {{ row[col.key] }}
            </td>
          </ng-container>
        }

        @if (showActions) {
          <ng-container matColumnDef="actions">
            <th mat-header-cell *matHeaderCellDef>Actions</th>
            <td mat-cell *matCellDef="let row">
              <ng-content select="[actions]"></ng-content>
            </td>
          </ng-container>
        }

        <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
        <tr mat-row *matRowDef="let row; columns: displayedColumns"
            [class.clickable]="rowClickable"
            (click)="rowClick.emit(row)"></tr>
      </table>
    </div>
    <mat-paginator
      [length]="total"
      [pageSize]="pageSize"
      [pageSizeOptions]="[10, 25, 50, 100]"
      (page)="pageChange.emit($event)"
      showFirstLastButtons>
    </mat-paginator>
  `,
  styles: [`
    .table-container {
      overflow-x: auto;
    }
    table { width: 100%; }
    tr.clickable { cursor: pointer; }
    tr.clickable:hover { background: var(--mat-sys-surface-variant); }
  `],
})
export class DataTableComponent {
  @Input() columns: TableColumn[] = [];
  @Input() data: unknown[] = [];
  @Input() total = 0;
  @Input() pageSize = 25;
  @Input() loading = false;
  @Input() showActions = false;
  @Input() rowClickable = false;
  @Output() pageChange = new EventEmitter<PageEvent>();
  @Output() sortChange = new EventEmitter<Sort>();
  @Output() rowClick = new EventEmitter<unknown>();

  @ViewChild(MatPaginator) paginator!: MatPaginator;
  @ViewChild(MatSort) sort!: MatSort;

  dataSource = new MatTableDataSource<unknown>();

  get displayedColumns(): string[] {
    const cols = this.columns.map((c) => c.key);
    if (this.showActions) cols.push('actions');
    return cols;
  }

  ngOnChanges(): void {
    this.dataSource.data = this.data;
  }

  onSort(sort: Sort): void {
    this.sortChange.emit(sort);
  }
}
