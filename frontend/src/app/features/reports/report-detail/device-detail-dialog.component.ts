import { Component, inject } from '@angular/core';
import { UpperCasePipe } from '@angular/common';
import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatTableModule } from '@angular/material/table';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';

@Component({
  selector: 'app-device-detail-dialog',
  standalone: true,
  imports: [
    UpperCasePipe,
    MatDialogModule,
    MatTableModule,
    MatIconModule,
    MatButtonModule,
    MatChipsModule,
    StatusBadgeComponent,
  ],
  template: `
    <h2 mat-dialog-title>
      <mat-icon [class]="'status-icon ' + overallStatus()">{{ statusIcon(overallStatus()) }}</mat-icon>
      {{ data.device.name }} — {{ data.device.model }}
    </h2>

    <mat-dialog-content>
      <!-- Device checks -->
      <div class="checks-grid">
        @for (check of data.device.checks; track check.check) {
          <div class="check-item">
            <mat-icon [class]="'status-icon small ' + check.status">{{ statusIcon(check.status) }}</mat-icon>
            <span class="check-label">{{ formatCheckName(check.check) }}</span>
            <span class="check-value">{{ check.value }}</span>
          </div>
        }
      </div>

      <!-- Switch: VC Members -->
      @if (data.type === 'switch' && data.device.virtual_chassis?.members?.length) {
        <h3>Virtual Chassis Members</h3>
        <div class="table-card">
          <table mat-table [dataSource]="data.device.virtual_chassis!.members">
            <ng-container matColumnDef="member_id">
              <th mat-header-cell *matHeaderCellDef>Member</th>
              <td mat-cell *matCellDef="let m">{{ m.member_id }}</td>
            </ng-container>
            <ng-container matColumnDef="model">
              <th mat-header-cell *matHeaderCellDef>Model</th>
              <td mat-cell *matCellDef="let m">{{ m.model }}</td>
            </ng-container>
            <ng-container matColumnDef="firmware">
              <th mat-header-cell *matHeaderCellDef>Firmware</th>
              <td mat-cell *matCellDef="let m">{{ m.firmware }}</td>
            </ng-container>
            <ng-container matColumnDef="vc_ports_up">
              <th mat-header-cell *matHeaderCellDef>VC Ports UP</th>
              <td mat-cell *matCellDef="let m">
                <span [class]="m.vc_ports_up >= 2 ? 'status-text pass' : 'status-text fail'">{{ m.vc_ports_up }}</span>
              </td>
            </ng-container>
            <ng-container matColumnDef="status">
              <th mat-header-cell *matHeaderCellDef>Status</th>
              <td mat-cell *matCellDef="let m"><app-status-badge [status]="m.status"></app-status-badge></td>
            </ng-container>
            <tr mat-header-row *matHeaderRowDef="['member_id', 'model', 'firmware', 'vc_ports_up', 'status']"></tr>
            <tr mat-row *matRowDef="let m; columns: ['member_id', 'model', 'firmware', 'vc_ports_up', 'status']"></tr>
          </table>
        </div>
      }

      <!-- Switch: Cable Tests -->
      @if (data.type === 'switch' && data.device.cable_tests?.length) {
        <h3>Cable Tests ({{ data.device.cable_tests.length }} ports)</h3>
        <div class="table-card">
          <table mat-table [dataSource]="data.device.cable_tests">
            <ng-container matColumnDef="port">
              <th mat-header-cell *matHeaderCellDef>Port</th>
              <td mat-cell *matCellDef="let ct">{{ ct.port }}</td>
            </ng-container>
            <ng-container matColumnDef="result">
              <th mat-header-cell *matHeaderCellDef>Result</th>
              <td mat-cell *matCellDef="let ct">
                <mat-icon [class]="'status-icon ' + ct.status">{{ statusIcon(ct.status) }}</mat-icon>
                {{ ct.status | uppercase }}
              </td>
            </ng-container>
            <ng-container matColumnDef="pairs">
              <th mat-header-cell *matHeaderCellDef>Pairs</th>
              <td mat-cell *matCellDef="let ct">
                <div class="pairs-vertical">
                  @for (p of ct.pairs; track p.pair) {
                    <span class="pair-chip" [class.pass]="isCableOk(p.status)" [class.fail]="!isCableOk(p.status)">
                      {{ p.pair }}: {{ p.status }}{{ p.length ? ' (' + p.length + ')' : '' }}
                    </span>
                  }
                </div>
              </td>
            </ng-container>
            <ng-container matColumnDef="neighbor">
              <th mat-header-cell *matHeaderCellDef>LLDP Neighbor</th>
              <td mat-cell *matCellDef="let ct">
                {{ ct.neighbor_system_name }}{{ ct.neighbor_port_desc ? ' (' + ct.neighbor_port_desc + ')' : '' }}
              </td>
            </ng-container>
            <tr mat-header-row *matHeaderRowDef="['port', 'neighbor', 'result', 'pairs']"></tr>
            <tr mat-row *matRowDef="let ct; columns: ['port', 'neighbor', 'result', 'pairs']"></tr>
          </table>
        </div>
      }

      <!-- Gateway: WAN Ports -->
      @if (data.type === 'gateway' && data.device.wan_ports?.length) {
        <h3>WAN Ports</h3>
        <div class="table-card">
          <table mat-table [dataSource]="flatWanPorts">
            <ng-container matColumnDef="interface">
              <th mat-header-cell *matHeaderCellDef>Interface</th>
              <td mat-cell *matCellDef="let p" [class.member-row]="p._isMember" [style.paddingLeft]="p._isMember ? '28px' : null">
                {{ p.interface }}
              </td>
            </ng-container>
            <ng-container matColumnDef="name">
              <th mat-header-cell *matHeaderCellDef>Name</th>
              <td mat-cell *matCellDef="let p">{{ p._isMember ? '(member)' : p.name }}</td>
            </ng-container>
            <ng-container matColumnDef="status">
              <th mat-header-cell *matHeaderCellDef>Status</th>
              <td mat-cell *matCellDef="let p">
                <mat-icon [class]="'status-icon ' + (p.up ? 'pass' : 'fail')">
                  {{ p.up ? 'check_circle' : 'cancel' }}
                </mat-icon>
                {{ p.up ? 'UP' : 'DOWN' }}
              </td>
            </ng-container>
            <ng-container matColumnDef="wan_type">
              <th mat-header-cell *matHeaderCellDef>WAN Type</th>
              <td mat-cell *matCellDef="let p">{{ p._isMember ? '' : p.wan_type }}</td>
            </ng-container>
            <ng-container matColumnDef="wan_neighbor">
              <th mat-header-cell *matHeaderCellDef>LLDP Neighbor</th>
              <td mat-cell *matCellDef="let p">
                {{ p.neighbor_system_name }}{{ p.neighbor_port_desc ? ' (' + p.neighbor_port_desc + ')' : '' }}
              </td>
            </ng-container>
            <tr mat-header-row *matHeaderRowDef="['interface', 'name', 'status', 'wan_type', 'wan_neighbor']"></tr>
            <tr mat-row *matRowDef="let p; columns: ['interface', 'name', 'status', 'wan_type', 'wan_neighbor']"
                [class.member-row]="p._isMember"></tr>
          </table>
        </div>
      }

      <!-- Gateway: LAN Ports -->
      @if (data.type === 'gateway' && data.device.lan_ports?.length) {
        <h3>LAN Ports</h3>
        <div class="table-card">
          <table mat-table [dataSource]="flatLanPorts">
            <ng-container matColumnDef="interface">
              <th mat-header-cell *matHeaderCellDef>Interface</th>
              <td mat-cell *matCellDef="let p" [class.member-row]="p._isMember" [style.paddingLeft]="p._isMember ? '28px' : null">
                {{ p.interface }}
              </td>
            </ng-container>
            <ng-container matColumnDef="network">
              <th mat-header-cell *matHeaderCellDef>Network</th>
              <td mat-cell *matCellDef="let p">{{ p._isMember ? '' : p.network }}</td>
            </ng-container>
            <ng-container matColumnDef="status">
              <th mat-header-cell *matHeaderCellDef>Status</th>
              <td mat-cell *matCellDef="let p">
                <mat-icon [class]="'status-icon ' + (p.up ? 'pass' : 'fail')">
                  {{ p.up ? 'check_circle' : 'cancel' }}
                </mat-icon>
                {{ p.up ? 'UP' : 'DOWN' }}
              </td>
            </ng-container>
            <ng-container matColumnDef="lan_neighbor">
              <th mat-header-cell *matHeaderCellDef>LLDP Neighbor</th>
              <td mat-cell *matCellDef="let p">
                {{ p.neighbor_system_name }}{{ p.neighbor_port_desc ? ' (' + p.neighbor_port_desc + ')' : '' }}
              </td>
            </ng-container>
            <tr mat-header-row *matHeaderRowDef="['interface', 'network', 'status', 'lan_neighbor']"></tr>
            <tr mat-row *matRowDef="let p; columns: ['interface', 'network', 'status', 'lan_neighbor']"
                [class.member-row]="p._isMember"></tr>
          </table>
        </div>
      }

      <!-- Gateway: Networks -->
      @if (data.type === 'gateway' && data.device.networks?.length) {
        <h3>Networks</h3>
        <div class="table-card">
          <table mat-table [dataSource]="data.device.networks">
            <ng-container matColumnDef="name">
              <th mat-header-cell *matHeaderCellDef>Network</th>
              <td mat-cell *matCellDef="let n">{{ n.name }}</td>
            </ng-container>
            <ng-container matColumnDef="gateway_ip">
              <th mat-header-cell *matHeaderCellDef>Gateway IP</th>
              <td mat-cell *matCellDef="let n">{{ n.gateway_ip }}</td>
            </ng-container>
            <ng-container matColumnDef="dhcp_status">
              <th mat-header-cell *matHeaderCellDef>DHCP</th>
              <td mat-cell *matCellDef="let n">{{ n.dhcp_status }}</td>
            </ng-container>
            <ng-container matColumnDef="dhcp_detail">
              <th mat-header-cell *matHeaderCellDef>DHCP Detail</th>
              <td mat-cell *matCellDef="let n">
                @if (n.dhcp_status === 'Server' && n.dhcp_pool) {
                  Pool: {{ n.dhcp_pool }}
                } @else if (n.dhcp_status === 'Relay' && n.dhcp_relay_servers?.length) {
                  Servers: {{ n.dhcp_relay_servers.join(', ') }}
                }
              </td>
            </ng-container>
            <tr mat-header-row *matHeaderRowDef="['name', 'gateway_ip', 'dhcp_status', 'dhcp_detail']"></tr>
            <tr mat-row *matRowDef="let n; columns: ['name', 'gateway_ip', 'dhcp_status', 'dhcp_detail']"></tr>
          </table>
        </div>
      }
      <!-- Device Events -->
      @if (data.device.events?.length) {
        <h3>Device Events (24h)</h3>
        <div class="table-card">
          <table mat-table [dataSource]="data.device.events">
            <ng-container matColumnDef="display">
              <th mat-header-cell *matHeaderCellDef>Event</th>
              <td mat-cell *matCellDef="let ev">{{ ev.display }}</td>
            </ng-container>
            <ng-container matColumnDef="sub_id">
              <th mat-header-cell *matHeaderCellDef>Detail</th>
              <td mat-cell *matCellDef="let ev">{{ ev.sub_id || '' }}</td>
            </ng-container>
            <ng-container matColumnDef="event_status">
              <th mat-header-cell *matHeaderCellDef>Status</th>
              <td mat-cell *matCellDef="let ev">
                <span [class]="'event-status ' + ev.status">{{ ev.status }}</span>
              </td>
            </ng-container>
            <ng-container matColumnDef="counts">
              <th mat-header-cell *matHeaderCellDef>Trigger / Clear</th>
              <td mat-cell *matCellDef="let ev">{{ ev.trigger_count }} / {{ ev.clear_count }}</td>
            </ng-container>
            <tr mat-header-row *matHeaderRowDef="['display', 'sub_id', 'event_status', 'counts']"></tr>
            <tr mat-row *matRowDef="let ev; columns: ['display', 'sub_id', 'event_status', 'counts']"></tr>
          </table>
        </div>
      }
    </mat-dialog-content>

    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Close</button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      h2[mat-dialog-title] {
        display: flex;
        align-items: center;
        gap: 8px;
      }

      h3 {
        margin: 16px 0 8px;
        font-size: 14px;
        font-weight: 600;
        text-transform: uppercase;
        color: var(--app-neutral);
      }

      .checks-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 12px 24px;
        margin-bottom: 16px;
      }

      .check-item {
        display: flex;
        align-items: center;
        gap: 4px;
        font-size: 13px;
      }

      .check-label {
        color: var(--app-neutral);
      }

      .status-icon {
        font-size: 18px;
        width: 18px;
        height: 18px;
        vertical-align: middle;
        &.pass { color: var(--app-success); }
        &.fail { color: var(--app-error); }
        &.warn { color: var(--app-warning); }
        &.info { color: var(--app-info); }
        &.small { font-size: 14px; width: 14px; height: 14px; }
      }

      .status-text {
        &.pass { color: var(--app-success); }
        &.fail { color: var(--app-error); }
      }

      .mat-column-port {
        width: 140px;
        white-space: nowrap;
      }

      .pairs-vertical {
        display: flex;
        flex-direction: column;
        gap: 3px;
        padding: 4px 0;
      }

      .pair-chip {
        display: inline-block;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 11px;
        font-family: monospace;
        &.pass {
          background: rgba(76, 175, 80, 0.15);
          color: var(--app-success);
        }
        &.fail {
          background: rgba(244, 67, 54, 0.15);
          color: var(--app-error);
        }
      }

      .member-row {
        opacity: 0.7;
        font-size: 12px;
      }

      .event-status {
        text-transform: capitalize;
        font-weight: 500;
        &.triggered {
          color: var(--app-error);
        }
        &.cleared {
          color: var(--app-success);
        }
      }
    `,
  ],
})
export class DeviceDetailDialogComponent {
  readonly data: { type: 'ap' | 'switch' | 'gateway'; device: any } = inject(MAT_DIALOG_DATA);

  readonly flatWanPorts = this._flattenWithMembers(this.data.device.wan_ports ?? []);
  readonly flatLanPorts = this._flattenWithMembers(this.data.device.lan_ports ?? []);

  overallStatus(): string {
    const dev = this.data.device;
    if (dev.checks?.some((c: any) => c.status === 'fail')) return 'fail';
    if (this.data.type === 'switch') {
      if (dev.cable_tests?.some((ct: any) => ct.status === 'fail')) return 'fail';
      if (dev.virtual_chassis?.members?.some((m: any) => m.checks?.some((c: any) => c.status === 'fail')))
        return 'fail';
    }
    if (dev.checks?.some((c: any) => c.status === 'warn')) return 'warn';
    return dev.checks?.find((c: any) => c.check === 'connection_status')?.status ?? 'info';
  }

  statusIcon(status: string): string {
    switch (status) {
      case 'pass': return 'check_circle';
      case 'fail': return 'cancel';
      case 'warn': return 'warning';
      case 'error': return 'error';
      default: return 'info';
    }
  }

  isCableOk(status: string): boolean {
    const s = status.toLowerCase();
    return s === 'normal' || s === 'ok' || s === 'pass' || s === 'passed';
  }

  formatCheckName(check: string): string {
    return check.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) + ':';
  }

  private _flattenWithMembers(ports: any[]): any[] {
    const rows: any[] = [];
    for (const p of ports) {
      rows.push(p);
      for (const m of p.members ?? []) {
        rows.push({ ...m, _isMember: true });
      }
    }
    return rows;
  }
}
