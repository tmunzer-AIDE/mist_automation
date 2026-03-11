import { Component, inject, OnInit, signal } from '@angular/core';
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
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { PageHeaderComponent } from '../../../shared/components/page-header/page-header.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { WebhookEventService } from '../../../core/services/webhook-event.service';
import { WebhookEventSummary } from '../../../core/models/webhook-event.model';
import { TopbarService } from '../../../core/services/topbar.service';
import { WebhookEventDetailDialogComponent } from './webhook-event-detail-dialog.component';

@Component({
  selector: 'app-webhook-event-list',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    ReactiveFormsModule,
    MatTableModule,
    MatPaginatorModule,
    MatButtonModule,
    MatIconModule,
    MatSelectModule,
    MatFormFieldModule,
    MatChipsModule,
    MatDialogModule,
    MatProgressBarModule,
    PageHeaderComponent,
    EmptyStateComponent,
    StatusBadgeComponent,
    DateTimePipe,
  ],
  templateUrl: './webhook-event-list.component.html',
  styleUrl: './webhook-event-list.component.scss',
})
export class WebhookEventListComponent implements OnInit {
  private readonly webhookEventService = inject(WebhookEventService);
  private readonly dialog = inject(MatDialog);
  private readonly fb = inject(FormBuilder);
  private readonly topbarService = inject(TopbarService);

  events = signal<WebhookEventSummary[]>([]);
  total = signal(0);
  pageSize = signal(25);
  pageIndex = signal(0);
  loading = signal(true);

  // Filters
  filterForm = this.fb.group({
    webhookType: [undefined as string | undefined],
    processed: [undefined as boolean | undefined],
  });

  displayedColumns = [
    'received_at',
    'webhook_type',
    'routed_to',
    'response_status',
    'processed',
    'matched_workflows',
  ];

  ngOnInit(): void {
    this.topbarService.setTitle('Webhook Monitor');
    this.loadEvents();
  }

  loadEvents(): void {
    this.loading.set(true);
    const filters = this.filterForm.getRawValue();
    this.webhookEventService
      .listEvents(
        this.pageIndex() * this.pageSize(),
        this.pageSize(),
        filters.webhookType || undefined,
        filters.processed ?? undefined,
      )
      .subscribe({
        next: (res) => {
          this.events.set(res.events);
          this.total.set(res.total);
          this.loading.set(false);
        },
        error: () => {
          this.loading.set(false);
        },
      });
  }

  onPage(event: PageEvent): void {
    this.pageIndex.set(event.pageIndex);
    this.pageSize.set(event.pageSize);
    this.loadEvents();
  }

  onFilterChange(): void {
    this.pageIndex.set(0);
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
