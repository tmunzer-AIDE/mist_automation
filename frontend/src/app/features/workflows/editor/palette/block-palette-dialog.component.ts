import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  MatDialogModule,
  MatDialogRef,
} from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';

export interface BlockOption {
  kind: 'filter' | 'secondary_filter' | 'action';
  actionType?: string;
  label: string;
  icon: string;
  color: string;
  description: string;
}

interface BlockCategory {
  name: string;
  options: BlockOption[];
}

@Component({
  selector: 'app-block-palette-dialog',
  standalone: true,
  imports: [CommonModule, MatDialogModule, MatIconModule, MatButtonModule],
  templateUrl: './block-palette-dialog.component.html',
  styleUrl: './block-palette-dialog.component.scss',
})
export class BlockPaletteDialogComponent {
  private readonly dialogRef = inject(MatDialogRef<BlockPaletteDialogComponent>);

  categories: BlockCategory[] = [
    {
      name: 'Filters',
      options: [
        {
          kind: 'filter',
          label: 'Field Filter',
          icon: 'filter_list',
          color: '#00838f',
          description: 'Filter events by field values',
        },
        {
          kind: 'secondary_filter',
          label: 'Secondary Filter',
          icon: 'filter_alt',
          color: '#00695c',
          description: 'Filter using API lookups',
        },
      ],
    },
    {
      name: 'API Actions',
      options: [
        {
          kind: 'action',
          actionType: 'mist_api_get',
          label: 'Mist API GET',
          icon: 'cloud_download',
          color: '#1976d2',
          description: 'Fetch data from Mist API',
        },
        {
          kind: 'action',
          actionType: 'mist_api_post',
          label: 'Mist API POST',
          icon: 'cloud_upload',
          color: '#1976d2',
          description: 'Create resource via Mist API',
        },
        {
          kind: 'action',
          actionType: 'mist_api_put',
          label: 'Mist API PUT',
          icon: 'edit',
          color: '#1976d2',
          description: 'Update resource via Mist API',
        },
        {
          kind: 'action',
          actionType: 'mist_api_delete',
          label: 'Mist API DELETE',
          icon: 'delete',
          color: '#d32f2f',
          description: 'Delete resource via Mist API',
        },
      ],
    },
    {
      name: 'Notifications',
      options: [
        {
          kind: 'action',
          actionType: 'webhook',
          label: 'Webhook',
          icon: 'send',
          color: '#7b1fa2',
          description: 'Send HTTP request to external URL',
        },
        {
          kind: 'action',
          actionType: 'slack',
          label: 'Slack',
          icon: 'chat',
          color: '#e91e63',
          description: 'Send Slack notification',
        },
        {
          kind: 'action',
          actionType: 'servicenow',
          label: 'ServiceNow',
          icon: 'confirmation_number',
          color: '#388e3c',
          description: 'Create or update ServiceNow record',
        },
        {
          kind: 'action',
          actionType: 'pagerduty',
          label: 'PagerDuty',
          icon: 'notifications_active',
          color: '#f57c00',
          description: 'Trigger PagerDuty incident',
        },
      ],
    },
    {
      name: 'Flow Control',
      options: [
        {
          kind: 'action',
          actionType: 'delay',
          label: 'Delay',
          icon: 'schedule',
          color: '#616161',
          description: 'Wait for a specified duration',
        },
        {
          kind: 'action',
          actionType: 'condition',
          label: 'Condition',
          icon: 'call_split',
          color: '#0097a7',
          description: 'Branch based on a condition',
        },
      ],
    },
  ];

  selectOption(option: BlockOption): void {
    this.dialogRef.close(option);
  }
}
