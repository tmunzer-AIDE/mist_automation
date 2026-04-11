import { Component, DestroyRef, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription, debounceTime, forkJoin } from 'rxjs';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatTableModule } from '@angular/material/table';
import { SkeletonLoaderComponent } from '../../../shared/components/skeleton-loader/skeleton-loader.component';
import { TelemetryService } from '../telemetry.service';
import { TelemetryNavService } from '../telemetry-nav.service';
import { ScopeSummary, ScopeDevices, DeviceSummaryRecord, APScopeSummary, SwitchScopeSummary, GatewayScopeSummary } from '../models';

@Component({
  selector: 'app-telemetry-site-devices',
  standalone: true,
  imports: [
    DecimalPipe,
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatTableModule,
    SkeletonLoaderComponent,
  ],
  templateUrl: './telemetry-site-devices.component.html',
  styleUrl: './telemetry-site-devices.component.scss',
})
export class TelemetrySiteDevicesComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly telemetryService = inject(TelemetryService);
  readonly nav = inject(TelemetryNavService);

  readonly siteId = signal('');
  readonly loading = signal(false);
  readonly summary = signal<ScopeSummary | null>(null);
  readonly devices = signal<ScopeDevices | null>(null);
  readonly activeType = signal<'' | 'ap' | 'switch' | 'gateway'>('');

  readonly searchCtrl = new FormControl('');
  private readonly searchTerm = signal('');

  private wsSub?: Subscription;

  // ── KPI getters ──────────────────────────────────────────────────────────

  get ap(): APScopeSummary | null { return this.summary()?.ap ?? null; }
  get sw(): SwitchScopeSummary | null { return this.summary()?.switch ?? null; }
  get gw(): GatewayScopeSummary | null { return this.summary()?.gateway ?? null; }

  readonly deviceCounts = computed(() => {
    const devs = this.devices()?.devices ?? [];
    return {
      ap: devs.filter((d) => d.device_type === 'ap').length,
      switch: devs.filter((d) => d.device_type === 'switch').length,
      gateway: devs.filter((d) => d.device_type === 'gateway').length,
    };
  });

  // ── Filtered device list ─────────────────────────────────────────────────

  readonly filteredDevices = computed(() => {
    const term = this.searchTerm().toLowerCase();
    const type = this.activeType();
    let devs = this.devices()?.devices ?? [];
    if (type) devs = devs.filter((d) => d.device_type === type);
    if (!term) return devs;
    return devs.filter(
      (d) =>
        d.name.toLowerCase().includes(term) ||
        d.mac.includes(term) ||
        d.model.toLowerCase().includes(term),
    );
  });

  // ── Table columns ────────────────────────────────────────────────────────

  readonly allColumns = ['name', 'device_type', 'model', 'cpu_util', 'num_clients', 'last_seen'];
  readonly apColumns = ['name', 'model', 'cpu_util', 'num_clients', 'last_seen'];
  readonly swColumns = ['name', 'model', 'cpu_util', 'num_clients', 'last_seen'];
  readonly gwColumns = ['name', 'model', 'cpu_util', 'last_seen'];

  readonly displayedColumns = computed(() => {
    switch (this.activeType()) {
      case 'ap': return this.apColumns;
      case 'switch': return this.swColumns;
      case 'gateway': return this.gwColumns;
      default: return this.allColumns;
    }
  });

  // ── Lifecycle ────────────────────────────────────────────────────────────

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id') ?? '';
      this.siteId.set(id);
      if (id) {
        this.loadData();
        this.nav.loadSiteDevices(id);
        this._subscribeWs(id);
      }
    });

    this.searchCtrl.valueChanges
      .pipe(debounceTime(200), takeUntilDestroyed(this.destroyRef))
      .subscribe((v) => this.searchTerm.set(v ?? ''));
  }

  ngOnDestroy(): void {
    this.wsSub?.unsubscribe();
  }

  // ── Data loading ─────────────────────────────────────────────────────────

  loadData(): void {
    const siteId = this.siteId();
    if (!siteId) return;
    this.loading.set(true);

    forkJoin({
      summary: this.telemetryService.getScopeSummary(siteId),
      devices: this.telemetryService.getScopeDevices(siteId),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ summary, devices }) => {
          this.summary.set(summary);
          this.devices.set(devices);
          this.loading.set(false);
          // Update nav device list too
          this.nav.loadSiteDevices(siteId);
        },
        error: () => this.loading.set(false),
      });
  }

  private _subscribeWs(siteId: string): void {
    this.wsSub?.unsubscribe();
    this.wsSub = this.telemetryService
      .subscribeToSite(siteId)
      .pipe(debounceTime(5000))
      .subscribe(() => {
        forkJoin({
          summary: this.telemetryService.getScopeSummary(siteId),
          devices: this.telemetryService.getScopeDevices(siteId),
        }).subscribe({
          next: ({ summary, devices }) => {
            this.summary.set(summary);
            this.devices.set(devices);
          },
        });
      });
  }

  // ── User actions ─────────────────────────────────────────────────────────

  setType(type: '' | 'ap' | 'switch' | 'gateway'): void {
    this.activeType.set(this.activeType() === type ? '' : type);
  }

  navigateToDevice(device: DeviceSummaryRecord): void {
    this.router.navigate(['/telemetry/device', device.mac]);
  }

  formatLastSeen(ts: number | null): string {
    if (!ts) return '—';
    const diff = Math.floor(Date.now() / 1000 - ts);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return `${Math.floor(diff / 3600)}h ago`;
  }
}
