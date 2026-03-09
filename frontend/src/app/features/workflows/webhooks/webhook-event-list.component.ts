import { Component, ChangeDetectorRef, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatTableModule } from '@angular/material/table';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSelectModule } from '@angular/material/select';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatChipsModule } from '@angular/material/chips';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { FormsModule } from '@angular/forms';
import { PageHeaderComponent } from '../../../shared/components/page-header/page-header.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { RelativeTimePipe } from '../../../shared/pipes/relative-time.pipe';
import { WebhookEventService } from '../../../core/services/webhook-event.service';
import { WebhookEventSummary } from '../../../core/models/webhook-event.model';
import { WebhookEventDetailDialogComponent } from './webhook-event-detail-dialog.component';

@Component({
  selector: 'app-webhook-event-list',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    FormsModule,
    MatTableModule,
    MatPaginatorModule,
    MatButtonModule,
    MatIconModule,
    MatSelectModule,
    MatFormFieldModule,
    MatChipsModule,
    MatDialogModule,
    PageHeaderComponent,
    EmptyStateComponent,
    StatusBadgeComponent,
    RelativeTimePipe,
  ],
  templateUrl: './webhook-event-list.component.html',
  styleUrl: './webhook-event-list.component.scss',
})
export class WebhookEventListComponent implements OnInit {
  private readonly webhookEventService = inject(WebhookEventService);
  private readonly dialog = inject(MatDialog);
  private readonly cdr = inject(ChangeDetectorRef);

  events: WebhookEventSummary[] = [];
  total = 0;
  pageSize = 25;
  pageIndex = 0;
  loading = true;

  // Filters
  webhookTypeFilter: string | undefined;
  processedFilter: boolean | undefined;

  displayedColumns = [
    'received_at',
    'webhook_type',
    'routed_to',
    'response_status',
    'processed',
    'matched_workflows',
  ];

  ngOnInit(): void {
    this.loadEvents();
  }

  loadEvents(): void {
    this.loading = true;
    this.webhookEventService
      .listEvents(
        this.pageIndex * this.pageSize,
        this.pageSize,
        this.webhookTypeFilter,
        this.processedFilter
      )
      .subscribe({
        next: (res) => {
          this.events = res.events;
          this.total = res.total;
          this.loading = false;
          this.cdr.detectChanges();
        },
        error: () => {
          this.loading = false;
          this.cdr.detectChanges();
        },
      });
  }

  onPage(event: PageEvent): void {
    this.pageIndex = event.pageIndex;
    this.pageSize = event.pageSize;
    this.loadEvents();
  }

  onFilterChange(): void {
    this.pageIndex = 0;
    this.loadEvents();
  }

  openEventDetail(event: WebhookEventSummary): void {
    this.dialog.open(WebhookEventDetailDialogComponent, {
      width: '800px',
      maxHeight: '90vh',
      data: { eventId: event.id },
    });
  }

  getStatusClass(code: number): string {
    if (code >= 200 && code < 300) return 'status-ok';
    if (code >= 400 && code < 500) return 'status-client-error';
    if (code >= 500) return 'status-server-error';
    return '';
  }
}
