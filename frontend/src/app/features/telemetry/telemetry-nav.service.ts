import { Injectable, computed, inject, signal } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { filter } from 'rxjs';
import { TelemetryService } from './telemetry.service';
import { ScopeSite, ScopeDevices, TimeRange } from './models';

export type TelemetryView = 'summary' | 'clients' | 'devices' | 'client-detail' | 'device-detail' | null;
export type TelemetryDetailKind = 'client' | 'ap' | 'switch' | 'gateway' | null;

@Injectable({ providedIn: 'root' })
export class TelemetryNavService {
  private readonly telemetryService = inject(TelemetryService);
  private readonly router = inject(Router);

  readonly timeRange = signal<TimeRange>('6h');
  readonly sites = signal<ScopeSite[]>([]);
  readonly sitesLoaded = signal(false);
  readonly activeSiteId = signal<string | null>(null);
  readonly activeView = signal<TelemetryView>(null);
  readonly siteDevices = signal<ScopeDevices | null>(null);
  readonly devicesLoaded = signal(false);
  readonly detailTitle = signal('');
  readonly detailKind = signal<TelemetryDetailKind>(null);
  readonly detailStale = signal<boolean | null>(null);
  readonly detailSiteId = signal<string | null>(null);
  readonly detailSiteName = signal('');

  readonly selectedSite = computed(() => {
    const id = this.activeSiteId();
    return id ? (this.sites().find((s) => s.site_id === id) ?? null) : null;
  });

  constructor() {
    this.router.events.pipe(filter((e) => e instanceof NavigationEnd)).subscribe(() => {
      this._syncFromUrl(this.router.url);
    });
    this._syncFromUrl(this.router.url);
  }

  loadSites(): void {
    if (this.sitesLoaded()) return;
    this.telemetryService.getScopeSites().subscribe({
      next: (result) => {
        this.sites.set(result.sites);
        this.sitesLoaded.set(true);
      },
    });
  }

  loadSiteDevices(siteId: string): void {
    if (this.devicesLoaded() && this.activeSiteId() === siteId) return;
    this.siteDevices.set(null);
    this.devicesLoaded.set(false);
    this.telemetryService.getScopeDevices(siteId).subscribe({
      next: (result) => {
        this.siteDevices.set(result);
        this.devicesLoaded.set(true);
      },
    });
  }

  invalidateDevices(): void {
    this.devicesLoaded.set(false);
    this.siteDevices.set(null);
  }

  setDetailContext(context: {
    title: string;
    kind: TelemetryDetailKind;
    stale?: boolean | null;
    siteId?: string | null;
    siteName?: string;
  }): void {
    this.detailTitle.set(context.title || '');
    this.detailKind.set(context.kind ?? null);
    this.detailStale.set(context.stale ?? null);
    this.detailSiteId.set(context.siteId ?? null);
    this.detailSiteName.set(context.siteName ?? '');
  }

  clearDetailContext(): void {
    this.detailTitle.set('');
    this.detailKind.set(null);
    this.detailStale.set(null);
    this.detailSiteId.set(null);
    this.detailSiteName.set('');
  }

  private _syncFromUrl(url: string): void {
    // Strip query params and fragment
    const path = url.split('?')[0].split('#')[0];
    const segments = path.replace(/^\/telemetry\/?/, '').split('/').filter(Boolean);

    if (segments.length === 0) {
      this.activeSiteId.set(null);
      this.activeView.set(null);
      this.clearDetailContext();
      return;
    }

    if (segments[0] === 'site' && segments[1]) {
      const siteId = segments[1];
      this.activeSiteId.set(siteId);
      if (segments[2] === 'clients') {
        this.activeView.set(segments[3] ? 'client-detail' : 'clients');
      } else if (segments[2] === 'devices') {
        this.activeView.set('devices');
      } else if (segments[2] === 'client') {
        this.activeView.set('client-detail');
      } else if (segments[2] === 'device') {
        this.activeView.set('device-detail');
      } else {
        this.activeView.set('summary');
      }
    } else if (segments[0] === 'device' && segments[1]) {
      this.activeSiteId.set(null);
      this.activeView.set('device-detail');
    } else {
      this.activeSiteId.set(null);
      this.activeView.set(null);
      this.clearDetailContext();
    }

    if (this.activeView() !== 'client-detail' && this.activeView() !== 'device-detail') {
      this.clearDetailContext();
    }
  }
}
