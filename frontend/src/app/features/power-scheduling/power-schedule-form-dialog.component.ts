import { Component, inject, OnInit, signal, computed } from '@angular/core';
import { FormArray, FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../core/services/api.service';
import { DAY_SHORTS, PowerSchedule, PowerSchedulingService, ScheduleWindow } from './power-scheduling.service';
import { extractErrorMessage } from '../../shared/utils/error.utils';

export interface FormDialogData {
  mode: 'create' | 'edit';
  schedule?: PowerSchedule;
}

interface SiteOption {
  id: string;
  name: string;
}

@Component({
  selector: 'app-power-schedule-form-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatSlideToggleModule,
    MatIconModule,
    MatProgressBarModule,
    MatAutocompleteModule,
    MatSnackBarModule,
    MatTooltipModule,
  ],
  template: `
    <h2 mat-dialog-title>{{ data.mode === 'create' ? 'Add Site Schedule' : 'Edit Schedule' }}</h2>

    @if (saving()) {
      <mat-progress-bar mode="indeterminate"></mat-progress-bar>
    }

    <mat-dialog-content>
      <form [formGroup]="form" class="dialog-form">

        @if (data.mode === 'create') {
          <mat-form-field appearance="outline" class="field-full">
            <mat-label>Site</mat-label>
            <input
              matInput
              [matAutocomplete]="siteAuto"
              (input)="siteSearch.set($any($event.target).value)"
              placeholder="Search sites..."
            />
            <mat-icon matSuffix>search</mat-icon>
            <mat-autocomplete
              #siteAuto
              [displayWith]="siteDisplayFn"
              (optionSelected)="onSiteSelected($event.option.value)"
            >
              @if (loadingSites()) {
                <mat-option disabled>Loading sites...</mat-option>
              }
              @for (site of filteredSites(); track site.id) {
                <mat-option [value]="site.id">{{ site.name }}</mat-option>
              }
            </mat-autocomplete>
          </mat-form-field>
        }

        <!-- Schedule section -->
        <div class="section-divider">
          <span class="section-title">Schedule</span>
          <span class="divider-line"></span>
          <mat-slide-toggle formControlName="enabled" class="enabled-toggle"></mat-slide-toggle>
        </div>

        <!-- Off-hours windows -->
        @for (w of windows.controls; track $index; let wi = $index) {
          <div class="window-block" [formGroup]="windowGroup(wi)">
            <div class="window-top-row">
              <div class="days-row">
                @for (label of dayLabels; track $index; let di = $index) {
                  <button
                    type="button"
                    class="day-btn"
                    [class.active]="windowGroup(wi).get('days_' + di)?.value"
                    (click)="toggleDay(wi, di)"
                  >{{ label }}</button>
                }
              </div>
              <button
                mat-icon-button
                type="button"
                class="remove-btn"
                (click)="removeWindow(wi)"
                [disabled]="windows.length <= 1"
                matTooltip="Remove window"
              >
                <mat-icon>close</mat-icon>
              </button>
            </div>
            <div class="time-row">
              <mat-form-field appearance="outline" class="time-field">
                <mat-label>From</mat-label>
                <input matInput type="time" formControlName="start" />
              </mat-form-field>
              <div class="time-connector">
                <span class="time-line"></span>
                <mat-icon class="time-arrow-icon">arrow_forward</mat-icon>
                <span class="time-line"></span>
              </div>
              <mat-form-field appearance="outline" class="time-field">
                <mat-label>Until</mat-label>
                <input matInput type="time" formControlName="end" />
              </mat-form-field>
            </div>
          </div>
        }

        <button mat-stroked-button type="button" (click)="addWindow()" class="add-window-btn">
          <mat-icon>add</mat-icon> Add Window
        </button>

        <!-- Thresholds section -->
        <div class="section-divider">
          <span class="section-title">Thresholds</span>
          <span class="divider-line"></span>
        </div>

        <div class="threshold-grid">
          <mat-form-field appearance="outline">
            <mat-label>Grace Period</mat-label>
            <input matInput type="number" formControlName="grace_period_minutes" />
            <span matTextSuffix>min</span>
            <mat-hint>Wait before disabling empty AP</mat-hint>
            <mat-error>Enter a value between 1 and 60</mat-error>
          </mat-form-field>

          <mat-form-field appearance="outline">
            <mat-label>Neighbor RSSI</mat-label>
            <input matInput type="number" formControlName="neighbor_rssi_threshold_dbm" />
            <span matTextSuffix>dBm</span>
            <mat-hint>Min RSSI to count as neighbor</mat-hint>
            <mat-error>Enter a value between -100 and 0</mat-error>
          </mat-form-field>

          <mat-form-field appearance="outline">
            <mat-label>Roam RSSI</mat-label>
            <input matInput type="number" formControlName="roam_rssi_threshold_dbm" />
            <span matTextSuffix>dBm</span>
            <mat-hint>Client threshold to pre-enable</mat-hint>
            <mat-error>Enter a value between -100 and 0</mat-error>
          </mat-form-field>
        </div>

        <!-- Critical APs section -->
        <div class="section-divider">
          <span class="section-title">Critical APs</span>
          <span class="divider-line"></span>
        </div>

        <mat-form-field appearance="outline" class="field-full">
          <mat-label>MAC addresses</mat-label>
          <textarea matInput formControlName="critical_ap_macs_text" rows="2" placeholder="aa:bb:cc:dd:ee:ff, ..."></textarea>
          <mat-hint>Comma-separated — these APs are never disabled</mat-hint>
        </mat-form-field>

      </form>
    </mat-dialog-content>

    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button mat-flat-button (click)="save()" [disabled]="!canSave()">
        {{ saving() ? 'Saving…' : (data.mode === 'create' ? 'Add Site' : 'Save Changes') }}
      </button>
    </mat-dialog-actions>
  `,
  styleUrl: './power-schedule-form-dialog.component.scss',
})
export class PowerScheduleFormDialogComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(ApiService);
  private readonly service = inject(PowerSchedulingService);
  private readonly dialogRef = inject(MatDialogRef<PowerScheduleFormDialogComponent>);
  private readonly snackBar = inject(MatSnackBar);
  readonly data = inject<FormDialogData>(MAT_DIALOG_DATA);

  readonly dayLabels = DAY_SHORTS;

  sites = signal<SiteOption[]>([]);
  loadingSites = signal(false);
  saving = signal(false);
  selectedSite = signal<SiteOption | null>(null);
  siteSearch = signal('');

  filteredSites = computed(() => {
    const q = this.siteSearch().toLowerCase();
    return q ? this.sites().filter((s) => s.name.toLowerCase().includes(q)) : this.sites();
  });

  siteDisplayFn = (value: string | null): string =>
    this.sites().find((s) => s.id === value)?.name ?? (value ?? '');

  form = this.fb.group({
    enabled: [true],
    grace_period_minutes: [5, [Validators.required, Validators.min(1), Validators.max(60)]],
    neighbor_rssi_threshold_dbm: [-65, [Validators.required, Validators.min(-100), Validators.max(0)]],
    roam_rssi_threshold_dbm: [-75, [Validators.required, Validators.min(-100), Validators.max(0)]],
    critical_ap_macs_text: [''],
    windows: this.fb.array([]),
  });

  get windows(): FormArray {
    return this.form.get('windows') as FormArray;
  }

  windowGroup(index: number): FormGroup {
    return this.windows.at(index) as FormGroup;
  }

  ngOnInit(): void {
    if (this.data.mode === 'create') {
      this.loadSites();
      this.addWindow();
    } else if (this.data.schedule) {
      const s = this.data.schedule;
      this.form.patchValue({
        enabled: s.enabled,
        grace_period_minutes: s.grace_period_minutes,
        neighbor_rssi_threshold_dbm: s.neighbor_rssi_threshold_dbm,
        roam_rssi_threshold_dbm: s.roam_rssi_threshold_dbm,
        critical_ap_macs_text: s.critical_ap_macs.join(', '),
      });
      for (const w of s.windows.length ? s.windows : [undefined]) {
        this.addWindow(w);
      }
    }
  }

  addWindow(window?: ScheduleWindow): void {
    const days = window?.days ?? [];
    this.windows.push(
      this.fb.group({
        days_0: [days.includes(0)],
        days_1: [days.includes(1)],
        days_2: [days.includes(2)],
        days_3: [days.includes(3)],
        days_4: [days.includes(4)],
        days_5: [days.includes(5)],
        days_6: [days.includes(6)],
        start: [window?.start ?? '22:00', Validators.required],
        end: [window?.end ?? '06:00', Validators.required],
      }),
    );
  }

  removeWindow(index: number): void {
    this.windows.removeAt(index);
  }

  toggleDay(wi: number, di: number): void {
    const ctrl = this.windowGroup(wi).get(`days_${di}`);
    ctrl?.setValue(!ctrl.value);
  }

  onSiteSelected(siteId: string): void {
    const site = this.sites().find((s) => s.id === siteId);
    this.selectedSite.set(site ?? null);
  }

  readonly canSave = computed(() => {
    if (this.saving()) return false;
    if (this.data.mode === 'create' && !this.selectedSite()) return false;
    if (this.windows.length === 0) return false;
    if (!this.form.valid) return false;
    return this.windows.controls.every((wg) => [0, 1, 2, 3, 4, 5, 6].some((d) => wg.get(`days_${d}`)?.value));
  });

  save(): void {
    if (!this.canSave()) return;
    this.saving.set(true);

    const macs = (this.form.value.critical_ap_macs_text ?? '')
      .split(',')
      .map((m) => m.trim())
      .filter(Boolean);

    const windows = this.windows.controls.map((wg) => ({
      days: [0, 1, 2, 3, 4, 5, 6].filter((d) => wg.get(`days_${d}`)?.value),
      start: wg.get('start')!.value as string,
      end: wg.get('end')!.value as string,
    }));

    const body = {
      site_name: this.data.mode === 'create' ? this.selectedSite()!.name : this.data.schedule!.site_name,
      windows,
      grace_period_minutes: this.form.value.grace_period_minutes!,
      neighbor_rssi_threshold_dbm: this.form.value.neighbor_rssi_threshold_dbm!,
      roam_rssi_threshold_dbm: this.form.value.roam_rssi_threshold_dbm!,
      critical_ap_macs: macs,
      enabled: this.form.value.enabled!,
    };

    const siteId = this.data.mode === 'create' ? this.selectedSite()!.id : this.data.schedule!.site_id;
    const obs =
      this.data.mode === 'create'
        ? this.service.createSchedule(siteId, body)
        : this.service.updateSchedule(siteId, body);

    obs.subscribe({
      next: (result) => this.dialogRef.close(result),
      error: (err) => {
        this.saving.set(false);
        this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 });
      },
    });
  }

  private loadSites(): void {
    this.loadingSites.set(true);
    this.api.get<{ sites: SiteOption[] }>('/admin/mist/sites').subscribe({
      next: (res) => {
        this.sites.set(res.sites.slice().sort((a, b) => a.name.localeCompare(b.name)));
        this.loadingSites.set(false);
      },
      error: () => {
        this.loadingSites.set(false);
        this.snackBar.open('Failed to load sites from Mist', 'OK', { duration: 5000 });
      },
    });
  }
}
