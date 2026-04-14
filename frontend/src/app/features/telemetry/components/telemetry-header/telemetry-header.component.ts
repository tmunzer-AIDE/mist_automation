import { Component, DestroyRef, OnInit, computed, effect, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { ScopeSite, TimeRange } from '../../models';
import { TelemetryNavService } from '../../telemetry-nav.service';

@Component({
    selector: 'app-telemetry-header',
    standalone: true,
    imports: [
        ReactiveFormsModule,
        MatAutocompleteModule,
        MatButtonModule,
        MatFormFieldModule,
        MatIconModule,
        MatInputModule,
    ],
    templateUrl: './telemetry-header.component.html',
    styleUrl: './telemetry-header.component.scss',
})
export class TelemetryHeaderComponent implements OnInit {
    private readonly router = inject(Router);
    private readonly destroyRef = inject(DestroyRef);
    readonly nav = inject(TelemetryNavService);

    readonly timeRanges: TimeRange[] = ['1h', '6h', '24h'];
    readonly siteCtrl = new FormControl<string | ScopeSite>('');
    private readonly siteSearchTerm = signal('');

    readonly isDetailView = computed(() => {
        const view = this.nav.activeView();
        return view === 'client-detail' || view === 'device-detail';
    });

    readonly currentSiteId = computed(() => this.nav.activeSiteId() ?? this.nav.detailSiteId());

    readonly currentSite = computed(() => {
        const siteId = this.currentSiteId();
        if (!siteId) return null;
        return this.nav.sites().find((site) => site.site_id === siteId) ?? null;
    });

    readonly currentSiteName = computed(() => {
        return this.currentSite()?.site_name || this.nav.detailSiteName() || this.currentSiteId() || '';
    });

    readonly isSiteView = computed(() => !this.isDetailView() && !!this.currentSiteId());
    readonly showTabs = computed(() => this.isSiteView());
    readonly detailTitle = computed(() => this.nav.detailTitle() || 'Detail');
    readonly detailTypeChip = computed(() => {
        const kind = this.nav.detailKind();
        if (kind === 'ap') return 'AP';
        if (kind === 'switch') return 'SW';
        if (kind === 'gateway') return 'GW';
        if (kind === 'client') return 'CLIENT';
        return '';
    });

    readonly orgSiteCount = computed(() => this.nav.sites().length);

    readonly filteredSites = computed(() => {
        const term = this.siteSearchTerm().toLowerCase();
        const all = this.nav.sites();
        if (!term) return all;
        return all.filter((site) => site.site_name.toLowerCase().includes(term));
    });

    readonly summaryTabActive = computed(() => this.nav.activeView() === 'summary');
    readonly clientsTabActive = computed(() => {
        const view = this.nav.activeView();
        return view === 'clients' || view === 'client-detail';
    });
    readonly devicesTabActive = computed(() => {
        const view = this.nav.activeView();
        return view === 'devices' || view === 'device-detail';
    });

    constructor() {
        effect(() => {
            if (this.isDetailView()) return;
            const site = this.currentSite();
            this.siteCtrl.setValue(site?.site_name || '', { emitEvent: false });
            this.siteSearchTerm.set('');
        });
    }

    ngOnInit(): void {
        this.nav.loadSites();

        this.siteCtrl.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((value) => {
            this.siteSearchTerm.set(typeof value === 'string' ? value : '');
        });
    }

    setTimeRange(range: TimeRange): void {
        this.nav.timeRange.set(range);
    }

    isTimeRangeActive(range: TimeRange): boolean {
        return this.nav.timeRange() === range;
    }

    displaySiteName(value: ScopeSite | string): string {
        if (!value) return '';
        if (typeof value === 'string') return value;
        return value.site_name;
    }

    selectAllSites(): void {
        this.siteCtrl.setValue('', { emitEvent: false });
        this.siteSearchTerm.set('');
        this.nav.invalidateDevices();
        this.router.navigate(['/telemetry']);
    }

    selectSite(site: ScopeSite | string): void {
        if (typeof site === 'string') {
            this.selectAllSites()
        } else if (typeof site === 'object') {
            this.siteCtrl.setValue(site.site_name, { emitEvent: false });
            this.siteSearchTerm.set('');
            this.nav.invalidateDevices();
            this.router.navigate(['/telemetry/site', site.site_id]);
        }
    }

    goToTelemetryRoot(): void {
        this.router.navigate(['/telemetry']);
    }

    goToSiteSummary(): void {
        const siteId = this.currentSiteId();
        if (!siteId) return;
        this.router.navigate(['/telemetry/site', siteId]);
    }

    goToClients(): void {
        const siteId = this.currentSiteId();
        if (!siteId) return;
        this.router.navigate(['/telemetry/site', siteId, 'clients']);
    }

    goToDevices(): void {
        const siteId = this.currentSiteId();
        if (!siteId) return;
        this.nav.loadSiteDevices(siteId);
        this.router.navigate(['/telemetry/site', siteId, 'devices']);
    }
}
