import { Component, computed, EventEmitter, Input, Output } from '@angular/core';
import { DecimalPipe, DatePipe, TitleCasePipe } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { DeviceSummaryRecord } from '../../../models';

@Component({
  selector: 'app-scope-device-table',
  standalone: true,
  imports: [DecimalPipe, DatePipe, TitleCasePipe, MatTableModule],
  templateUrl: './scope-device-table.component.html',
})
export class ScopeDeviceTableComponent {
  @Input() devices: DeviceSummaryRecord[] = [];
  @Input() isOrgScope = false;
  @Output() deviceSelected = new EventEmitter<string>();

  readonly displayedColumns = computed(() =>
    this.isOrgScope
      ? ['name', 'device_type', 'cpu_util', 'num_clients', 'last_seen']
      : ['name', 'device_type', 'cpu_util', 'num_clients', 'last_seen'],
  );
}
