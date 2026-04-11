import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { RouterModule } from '@angular/router';
import { Router } from '@angular/router';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { TelemetryNavService } from './telemetry-nav.service';
import { TopbarService } from '../../core/services/topbar.service';
import { ScopeSite, DeviceSummaryRecord, TimeRange } from './models';

@Component({
  selector: 'app-telemetry-shell',
  standalone: true,
  imports: [
    RouterModule,
    ReactiveFormsModule,
    MatAutocompleteModule,
    MatFormFieldModule,
    MatInputModule,
    MatIconModule,
    MatButtonModule,
  ],
  templateUrl: './telemetry-shell.component.html',
  styleUrl: './telemetry-shell.component.scss',
})
export class TelemetryShellComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly topbarService = inject(TopbarService);
  readonly nav = inject(TelemetryNavService);

  readonly timeRanges: TimeRange[] = ['1h', '6h', '24h'];

  readonly siteCtrl = new FormControl<string | ScopeSite>('');
  private readonly siteSearchTerm = signal('');

  readonly filteredSites = computed(() => {
    const term = this.siteSearchTerm().toLowerCase();
    const all = this.nav.sites();
    if (!term) return all;
    return all.filter((s) => s.site_name.toLowerCase().includes(term));
  });

  readonly filteredDevices = computed(() => {
    const devs = this.nav.siteDevices()?.devices ?? [];
    const term = this.deviceSearchTerm().toLowerCase();
    if (!term) return devs;
    return devs.filter(
      (d) =>
        d.name.toLowerCase().includes(term) ||
        d.mac.includes(term) ||
        d.model.toLowerCase().includes(term),
    );
  });

  readonly deviceSearchCtrl = new FormControl<string | DeviceSummaryRecord>('');
  private readonly deviceSearchTerm = signal('');

  readonly showViewPicker = computed(() => !!this.nav.activeSiteId());
  readonly showDevicePicker = computed(() => this.nav.activeView() === 'devices');

  ngOnInit(): void {
    this.topbarService.setTitle('Telemetry');
    this.nav.loadSites();

    this.siteCtrl.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((v) => {
      this.siteSearchTerm.set(typeof v === 'string' ? v : '');
    });

    this.deviceSearchCtrl.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((v) => {
      this.deviceSearchTerm.set(typeof v === 'string' ? v : '');
    });
  }

  setTimeRange(tr: TimeRange): void {
    this.nav.timeRange.set(tr);
  }

  selectSite(site: ScopeSite): void {
    this.siteCtrl.setValue(site.site_name, { emitEvent: false });
    this.siteSearchTerm.set('');
    this.nav.invalidateDevices();
    this.router.navigate(['/telemetry/site', site.site_id]);
  }

  selectAllSites(): void {
    this.siteCtrl.setValue('', { emitEvent: false });
    this.siteSearchTerm.set('');
    this.router.navigate(['/telemetry']);
  }

  selectDevice(device: DeviceSummaryRecord): void {
    this.deviceSearchCtrl.setValue('', { emitEvent: false });
    this.deviceSearchTerm.set('');
    this.router.navigate(['/telemetry/device', device.mac]);
  }

  displaySiteName(val: ScopeSite | string): string {
    if (!val) return '';
    if (typeof val === 'string') return val;
    return val.site_name;
  }

  displayDeviceName(val: DeviceSummaryRecord | string): string {
    if (!val) return '';
    if (typeof val === 'string') return val;
    return val.name || val.mac;
  }

  navigateView(view: string): void {
    const siteId = this.nav.activeSiteId();
    if (!siteId) return;
    if (view === 'summary') {
      this.router.navigate(['/telemetry/site', siteId]);
    } else {
      this.router.navigate(['/telemetry/site', siteId, view]);
    }
    if (view === 'devices') {
      this.nav.loadSiteDevices(siteId);
    }
  }

  isViewActive(view: string): boolean {
    const v = this.nav.activeView();
    if (view === 'summary') return v === 'summary';
    if (view === 'clients') return v === 'clients' || v === 'client-detail';
    if (view === 'devices') return v === 'devices' || v === 'device-detail';
    return false;
  }
}
