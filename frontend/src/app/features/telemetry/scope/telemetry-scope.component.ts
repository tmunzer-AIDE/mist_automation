import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin } from 'rxjs';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { TelemetryService } from '../telemetry.service';
import {
  TimeRange,
  ScopeSummary,
  ScopeDevices,
  BandSummary,
  APScopeSummary,
  SwitchScopeSummary,
  GatewayScopeSummary,
} from '../models';
import { ScopeDeviceTableComponent } from './components/scope-device-table/scope-device-table.component';

@Component({
  selector: 'app-telemetry-scope',
  standalone: true,
  imports: [
    DecimalPipe,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    ScopeDeviceTableComponent,
  ],
  templateUrl: './telemetry-scope.component.html',
  styleUrl: './telemetry-scope.component.scss',
})
export class TelemetryScopeComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly telemetryService = inject(TelemetryService);

  readonly siteId = signal<string | null>(null);
  readonly timeRange = signal<TimeRange>('1h');
  readonly loading = signal(false);
  readonly summary = signal<ScopeSummary | null>(null);
  readonly devices = signal<ScopeDevices | null>(null);

  readonly isOrgScope = computed(() => !this.siteId());
  readonly hasAP = computed(() => !!this.summary()?.ap);
  readonly hasSwitch = computed(() => !!this.summary()?.switch);
  readonly hasGateway = computed(() => !!this.summary()?.gateway);

  readonly timeRanges: TimeRange[] = ['1h', '6h', '24h'];

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id');
      this.siteId.set(id);
      this.loadScopeData();
    });
  }

  loadScopeData(): void {
    this.loading.set(true);
    const sid = this.siteId() ?? undefined;
    forkJoin({
      summary: this.telemetryService.getScopeSummary(sid),
      devices: this.telemetryService.getScopeDevices(sid),
    }).subscribe({
      next: ({ summary, devices }) => {
        this.summary.set(summary);
        this.devices.set(devices);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  setTimeRange(tr: TimeRange): void {
    this.timeRange.set(tr);
  }

  navigateToDevice(mac: string): void {
    this.router.navigate(['/telemetry/device', mac]);
  }

  bandEntries(
    bands: Record<string, BandSummary>,
  ): Array<{ band: string; label: string; avg_util_all: number }> {
    const labels: Record<string, string> = { band_24: '2.4G', band_5: '5G', band_6: '6G' };
    return Object.entries(bands).map(([band, v]) => ({
      band,
      label: labels[band] ?? band,
      avg_util_all: v.avg_util_all,
    }));
  }

  reportingOk(active: number, total: number): boolean {
    return total > 0 && active === total;
  }

  get ap(): APScopeSummary | null {
    return this.summary()?.ap ?? null;
  }

  get sw(): SwitchScopeSummary | null {
    return this.summary()?.switch ?? null;
  }

  get gw(): GatewayScopeSummary | null {
    return this.summary()?.gateway ?? null;
  }
}
